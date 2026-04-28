"""End-to-end R5 Monte Carlo backtester (Python).

Note: traders that use the standard competition Logger pattern call print()
each tick with the entire compressed state. We redirect the trader's stdout
to /dev/null during run() to avoid swamping the simulator output.

Wires R5Scenario v2 (FV + pulses calibrated from history) into a per-tick
simulation loop with order book, trader.run() invocation, fill matching,
position tracking, and PnL accounting.

Per spec (CLAUDE.md):
  - Bot takers act BEFORE the strategy sees the book each tick.
  - Strategy orders cancel ALL if worst-case position would breach limits.
  - Trade price = best_bid (sell pulse) / best_ask (buy pulse), 100% of trades.
  - Half-spread h is product-specific; book has L1+L2.

Validation entry: run hold-1 trader (results/round1/.../trader_hold1 or
traders/trader_hold1.py) on day-4 1000 ticks against this sim. Should
produce ~-2160 PnL matching portal sub 545243.

Outputs:
  per-asset position+PnL trajectory, total PnL per session.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


@contextlib.contextmanager
def silence_stdout():
    """Suppress noisy trader.run() prints (Logger pattern) during simulation."""
    saved = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = saved

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "traders"))

from datamodel import (  # noqa: E402
    Listing, Observation, Order, OrderDepth, Trade, TradingState,
)

DATA_DIR = REPO_ROOT / "data" / "prosperity4" / "round5"
CAL_PATH = REPO_ROOT / "analysis" / "round5" / "calibration_r5.json"


CATEGORIES = {
    "galaxy_sounds": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "sleep_pods": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                   "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "microchips": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                   "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "pebbles": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "robots": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
               "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "uv_visors": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                  "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "translators": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                    "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                    "TRANSLATOR_VOID_BLUE"],
    "panels": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "oxygen_shakes": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                      "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                      "OXYGEN_SHAKE_GARLIC"],
    "snackpacks": ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                   "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
}
ALL_PRODUCTS = [p for ps in CATEGORIES.values() for p in ps]
CATEGORY_OF = {p: c for c, ps in CATEGORIES.items() for p in ps}
POSITION_LIMIT = 10
DAYS = (2, 3, 4)
PEBBLE_FREE = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L"]
PEBBLE_DERIVED = "PEBBLES_XL"


# ---------------------------------------------------------------------------
# Re-use Scenario from r5_scenario_v2
# ---------------------------------------------------------------------------

# Inline import to avoid module path collisions
_v2 = REPO_ROOT / "analysis" / "round5" / "r5_scenario_v2.py"
spec = importlib.util.spec_from_file_location("r5_scenario_v2", _v2)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
R5Scenario = _mod.R5Scenario
load_calibration_bundle = _mod.load_calibration_bundle


# ---------------------------------------------------------------------------
# Sim infra
# ---------------------------------------------------------------------------

@dataclass
class AssetState:
    symbol: str
    h: float
    depth_l1: int
    depth_l2: int
    l2_lift: int
    position: int = 0
    cash: float = 0.0
    realised_pnl: float = 0.0
    fills: int = 0


@dataclass
class SimBook:
    """Tracks both bot-owned and strategy-owned levels."""
    bid_levels: List[Tuple[int, int, str]]  # (price, qty, owner) sorted high→low
    ask_levels: List[Tuple[int, int, str]]  # (price, qty, owner) sorted low→high

    def to_order_depth(self) -> OrderDepth:
        od = OrderDepth()
        for price, qty, _owner in self.bid_levels:
            if qty > 0:
                od.buy_orders[price] = od.buy_orders.get(price, 0) + qty
        for price, qty, _owner in self.ask_levels:
            if qty > 0:
                od.sell_orders[price] = od.sell_orders.get(price, 0) - qty
        return od


def make_bot_book(fv: float, h: float, depth_l1: int, depth_l2: int,
                  l2_lift: int) -> SimBook:
    """Per spec: bid_1 = floor(fv - h + 0.5), ask_1 = ceil(fv + h - 0.5)."""
    bid_1 = int(np.floor(fv - h + 0.5))
    ask_1 = int(np.ceil(fv + h - 0.5))
    bid_2 = bid_1 - l2_lift
    ask_2 = ask_1 + l2_lift
    return SimBook(
        bid_levels=[(bid_1, depth_l1, "bot"), (bid_2, depth_l2, "bot")],
        ask_levels=[(ask_1, depth_l1, "bot"), (ask_2, depth_l2, "bot")],
    )


def take_from_book(book: SimBook, side: str, qty: int,
                   buyer_id: str, seller_id: str, asset_state: AssetState,
                   timestamp: int) -> List[Trade]:
    """Take qty units from the book on `side` ∈ {'bid','ask'}.
    side='bid' means we're SELLING (taker hits bids).
    side='ask' means we're BUYING  (taker lifts asks).
    Returns Trade list. Updates book in place."""
    fills: List[Trade] = []
    levels = book.bid_levels if side == "bid" else book.ask_levels
    remaining = qty
    while remaining > 0 and levels:
        price, available, owner = levels[0]
        take = min(available, remaining)
        if take <= 0:
            break
        # If owner is "strategy", this is OUR resting order being filled
        if owner == "strategy":
            if side == "bid":
                # Our bid was hit by a seller → we BUY take units at price
                asset_state.position += take
                asset_state.cash -= take * price
                fills.append(Trade(asset_state.symbol, price, take,
                                   buyer="SELF", seller=seller_id, timestamp=timestamp))
            else:
                # Our ask was lifted by a buyer → we SELL take units at price
                asset_state.position -= take
                asset_state.cash += take * price
                fills.append(Trade(asset_state.symbol, price, take,
                                   buyer=buyer_id, seller="SELF", timestamp=timestamp))
        else:
            # Trade fired into bot liquidity (not our concern for PnL but record it)
            if side == "bid":
                fills.append(Trade(asset_state.symbol, price, take,
                                   buyer="", seller=seller_id, timestamp=timestamp))
            else:
                fills.append(Trade(asset_state.symbol, price, take,
                                   buyer=buyer_id, seller="", timestamp=timestamp))
        remaining -= take
        if take == available:
            levels.pop(0)
        else:
            levels[0] = (price, available - take, owner)
    return fills


def add_strategy_orders(book: SimBook, orders: List[Order]) -> None:
    """Add strategy orders into the book at appropriate prices.
    Orders cross the spread → take immediately (handled separately).
    Orders inside the spread → improve top-of-book.
    Orders at/behind bot levels → join queue (treated as if they arrive
    AFTER bot in queue order; bot fills first if same level)."""
    for o in orders:
        if o.quantity > 0:  # buy order
            # If price >= best_ask: cross — handled by take routine
            # Otherwise: insert into bid stack
            inserted = False
            for i, (p, q, owner) in enumerate(book.bid_levels):
                if o.price > p:
                    book.bid_levels.insert(i, (o.price, o.quantity, "strategy"))
                    inserted = True
                    break
                elif o.price == p:
                    # Append to same level — strategy goes BEHIND bot in queue
                    # Simplest: just merge the volume but mark mixed; we model
                    # as separate "strategy" entry at end of same level
                    book.bid_levels.insert(i + 1, (o.price, o.quantity, "strategy"))
                    inserted = True
                    break
            if not inserted:
                book.bid_levels.append((o.price, o.quantity, "strategy"))
        elif o.quantity < 0:  # sell order
            qty = -o.quantity
            inserted = False
            for i, (p, q, owner) in enumerate(book.ask_levels):
                if o.price < p:
                    book.ask_levels.insert(i, (o.price, qty, "strategy"))
                    inserted = True
                    break
                elif o.price == p:
                    book.ask_levels.insert(i + 1, (o.price, qty, "strategy"))
                    inserted = True
                    break
            if not inserted:
                book.ask_levels.append((o.price, qty, "strategy"))


def cross_strategy_orders(book: SimBook, orders: List[Order],
                          state: AssetState, timestamp: int) -> List[Trade]:
    """For orders that cross the spread, immediately fill them against the book."""
    fills: List[Trade] = []
    crossing_orders = []
    passive_orders = []
    for o in orders:
        if o.quantity > 0:
            best_ask = book.ask_levels[0][0] if book.ask_levels else None
            if best_ask is not None and o.price >= best_ask:
                crossing_orders.append(o)
            else:
                passive_orders.append(o)
        elif o.quantity < 0:
            best_bid = book.bid_levels[0][0] if book.bid_levels else None
            if best_bid is not None and o.price <= best_bid:
                crossing_orders.append(o)
            else:
                passive_orders.append(o)
    # Process crossing first: each crossing order fills against the opposite side
    for o in crossing_orders:
        if o.quantity > 0:  # we're buying
            remaining = o.quantity
            while remaining > 0 and book.ask_levels and book.ask_levels[0][0] <= o.price:
                price, available, owner = book.ask_levels[0]
                take = min(available, remaining)
                state.position += take
                state.cash -= take * price
                fills.append(Trade(state.symbol, price, take,
                                   buyer="SELF", seller="bot", timestamp=timestamp))
                state.fills += 1
                remaining -= take
                if take == available:
                    book.ask_levels.pop(0)
                else:
                    book.ask_levels[0] = (price, available - take, owner)
        else:  # we're selling
            qty = -o.quantity
            remaining = qty
            while remaining > 0 and book.bid_levels and book.bid_levels[0][0] >= o.price:
                price, available, owner = book.bid_levels[0]
                take = min(available, remaining)
                state.position -= take
                state.cash += take * price
                fills.append(Trade(state.symbol, price, take,
                                   buyer="bot", seller="SELF", timestamp=timestamp))
                state.fills += 1
                remaining -= take
                if take == available:
                    book.bid_levels.pop(0)
                else:
                    book.bid_levels[0] = (price, available - take, owner)
    # Add passive orders to book for bots to potentially fire against
    add_strategy_orders(book, passive_orders)
    return fills


def check_position_safety(orders: List[Order], current_pos: int,
                          limit: int = POSITION_LIMIT) -> bool:
    """Per spec: if worst-case fill puts |position| > limit, ALL orders cancelled."""
    buy_qty = sum(o.quantity for o in orders if o.quantity > 0)
    sell_qty = sum(-o.quantity for o in orders if o.quantity < 0)
    worst_long = current_pos + buy_qty
    worst_short = current_pos - sell_qty
    return worst_long <= limit and worst_short >= -limit


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def load_trader(trader_path: Path):
    spec = importlib.util.spec_from_file_location("user_trader", trader_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["user_trader"] = mod
    spec.loader.exec_module(mod)
    return mod.Trader()


def simulate_session(scenario: R5Scenario, trader, day: int, n_ticks: int,
                     rng: np.random.Generator, verbose: bool = False) -> Dict:
    """Generate one synthetic day, run trader through it, return per-asset PnL."""
    # 1. Generate the FV+pulse session
    sess = scenario.generate_day(day, n_ticks, rng)
    fv_paths = sess["fv_paths"]
    pulses = sess["pulses"]
    pulses_by_tick: Dict[int, List[Dict]] = {}
    for p in pulses:
        pulses_by_tick.setdefault(p["tick"], []).append(p)

    # 2. Init asset states
    asset_cfg = scenario.cal["book_cfg"]
    states: Dict[str, AssetState] = {}
    for sym in ALL_PRODUCTS:
        c = asset_cfg[sym]
        states[sym] = AssetState(
            symbol=sym, h=c["h"], depth_l1=c["depth_l1"],
            depth_l2=c["depth_l2"], l2_lift=c["l2_lift"],
        )

    listings = {sym: Listing(symbol=sym, product=sym, denomination=1) for sym in ALL_PRODUCTS}
    trader_data = ""
    own_trades_by_sym: Dict[str, List[Trade]] = {sym: [] for sym in ALL_PRODUCTS}

    # 3. Per-tick loop
    for tick in range(n_ticks):
        timestamp = tick * 100
        own_trades_this_tick: Dict[str, List[Trade]] = {sym: [] for sym in ALL_PRODUCTS}
        market_trades_this_tick: Dict[str, List[Trade]] = {sym: [] for sym in ALL_PRODUCTS}

        # 3a. Build per-asset books (bot-only)
        books: Dict[str, SimBook] = {}
        for sym in ALL_PRODUCTS:
            fv = float(fv_paths[sym][tick])
            books[sym] = make_bot_book(fv, states[sym].h, states[sym].depth_l1,
                                        states[sym].depth_l2, states[sym].l2_lift)

        # 3b. Bot pulses BEFORE strategy sees book (per CLAUDE.md spec)
        for pulse in pulses_by_tick.get(tick, []):
            for member in pulse["members"]:
                book = books[member]
                state = states[member]
                if pulse["direction"] == "BUY":
                    # Taker BUYs (lifts asks)
                    fills = take_from_book(book, "ask", pulse["qty"],
                                          buyer_id="bot", seller_id="",
                                          asset_state=state, timestamp=timestamp)
                else:
                    # Taker SELLs (hits bids)
                    fills = take_from_book(book, "bid", pulse["qty"],
                                          buyer_id="", seller_id="bot",
                                          asset_state=state, timestamp=timestamp)
                # Pulse fills before strategy = market trades, not own trades.
                # (Strategy book contributions get hit only AFTER strategy posts orders.)
                for f in fills:
                    market_trades_this_tick[member].append(f)

        # 3c. Build TradingState for trader.run()
        order_depths = {sym: books[sym].to_order_depth() for sym in ALL_PRODUCTS
                        if books[sym].bid_levels or books[sym].ask_levels}
        position = {sym: states[sym].position for sym in ALL_PRODUCTS if states[sym].position != 0}
        ts = TradingState(
            traderData=trader_data,
            timestamp=timestamp,
            listings=listings,
            order_depths=order_depths,
            own_trades=own_trades_by_sym,  # cumulative own trades from prior ticks
            market_trades=market_trades_this_tick,
            position=position,
            observations=Observation({}, {}),
        )

        try:
            with silence_stdout():
                result = trader.run(ts)
            if isinstance(result, tuple) and len(result) == 3:
                orders_dict, _conversions, trader_data = result
            else:
                orders_dict = {}
        except Exception as e:
            if verbose:
                print(f"  trader.run() error at tick={tick}: {e}")
            orders_dict = {}

        # 3d. Validate worst-case + execute strategy orders
        for sym, orders in orders_dict.items():
            if sym not in states:
                continue
            if not orders:
                continue
            if not check_position_safety(orders, states[sym].position):
                # All orders cancelled per spec
                continue
            fills = cross_strategy_orders(books[sym], orders, states[sym], timestamp)
            for f in fills:
                own_trades_by_sym[sym].append(f)

        # 3e. After strategy posts: bots may fire against strategy book.
        # In the per-spec ordering, takers fire BEFORE strategy. So additional
        # taker action AFTER strategy is technically not present. (Per CLAUDE.md
        # step 5: "Remaining bots may trade on your quotes" — but the calibrated
        # pulse process is single-shot per tick, already fired.)
        # We could simulate elastic takers here later; skipping for now.

        # 3f. End-of-tick PnL mark-to-market for reporting
        # (We'll do the final mark at end of session.)

    # 4. End-of-session: mark-to-market positions at last mid
    final_results: Dict[str, Dict] = {}
    total_pnl = 0.0
    for sym, st in states.items():
        last_mid = float(fv_paths[sym][-1])  # ish; better use sim mid from last book
        unrealised = st.position * last_mid
        pnl = st.cash + unrealised
        final_results[sym] = {
            "position": st.position,
            "cash": st.cash,
            "unrealised": unrealised,
            "fills": st.fills,
            "pnl": pnl,
        }
        total_pnl += pnl
    final_results["__total__"] = {"pnl": total_pnl}
    return final_results


# ---------------------------------------------------------------------------

def main():
    print("Loading calibration…")
    cal, k_cal, qty_dist = load_calibration_bundle()
    scenario = R5Scenario(cal, k_cal, qty_dist)

    # Validate against hold-1 portal sub 545243 (-2160 PnL on day 4 1K ticks).
    # Local equivalent kept at traders/round5/hold1.py if portal extract was cleaned.
    hold1_path = REPO_ROOT / "tmp" / "portal_545243" / "545243.py"
    if not hold1_path.exists():
        hold1_path = REPO_ROOT / "traders" / "round5" / "hold1.py"
    print(f"\nLoading hold-1 trader: {hold1_path}")
    trader = load_trader(hold1_path)

    n_seeds = 50
    print(f"\nRunning hold-1 against synthetic day 4, 1000 ticks, {n_seeds} seeds…")
    pnls = []
    per_asset_pnls = {sym: [] for sym in ALL_PRODUCTS}
    for seed in range(n_seeds):
        rng = np.random.default_rng(seed)
        # Reset trader state by re-instantiating
        trader = load_trader(hold1_path)
        result = simulate_session(scenario, trader, day=4, n_ticks=1000, rng=rng)
        total = result["__total__"]["pnl"]
        pnls.append(total)
        for sym in ALL_PRODUCTS:
            per_asset_pnls[sym].append(result[sym]["pnl"])

    portal_pnl = -2159.50
    pnls = np.array(pnls)
    print(f"\nSynthetic PnL distribution ({n_seeds} seeds):")
    print(f"  mean={pnls.mean():.2f}  std={pnls.std():.2f}")
    print(f"  p05={np.percentile(pnls, 5):.2f}  p25={np.percentile(pnls, 25):.2f}  "
          f"p50={np.percentile(pnls, 50):.2f}  p75={np.percentile(pnls, 75):.2f}  "
          f"p95={np.percentile(pnls, 95):.2f}")
    print(f"\nPortal hold-1 actual (day-4 1K ticks): {portal_pnl}")
    portal_percentile = (pnls < portal_pnl).mean() * 100
    print(f"Portal value is at p{portal_percentile:.0f} of the synthetic distribution")
    if 5 <= portal_percentile <= 95:
        print("  ✓ within sim distribution")
    else:
        print("  ⚠ outside sim 90% interval — possible model bias")

    # Per-asset comparison: synthetic mean PnL vs historical day-4 hold-1
    print("\n=== Per-asset hold-1 PnL: synthetic mean vs historical-implied ===")
    # Compute historical day-4 1K-tick hold-1 PnL per asset
    import pandas as pd
    p4 = pd.read_csv(DATA_DIR / "prices_round_5_day_4.csv", sep=";")
    p4_1k = p4[p4["timestamp"] <= 99900]
    hist_pnls = {}
    for sym in ALL_PRODUCTS:
        sub = p4_1k[p4_1k["product"] == sym].sort_values("timestamp")
        if len(sub) == 0:
            continue
        ask0 = sub.iloc[0]["ask_price_1"]
        mid_T = sub.iloc[-1]["mid_price"]
        hist_pnls[sym] = float(mid_T - ask0)

    # Sort by historical PnL and show top-5 worst, top-5 best
    sorted_sym = sorted(hist_pnls.items(), key=lambda r: r[1])
    print(f"{'product':35s} {'hist_pnl':>10s} {'syn_mean':>10s} {'syn_std':>10s} {'within_band':>12s}")
    print("-- worst 5 in history:")
    for sym, hp in sorted_sym[:5]:
        sp = np.array(per_asset_pnls[sym])
        in_band = "yes" if abs(hp - sp.mean()) <= 2 * sp.std() else "no"
        print(f"{sym:35s} {hp:>10.2f} {sp.mean():>10.2f} {sp.std():>10.2f} {in_band:>12s}")
    print("-- best 5 in history:")
    for sym, hp in sorted_sym[-5:]:
        sp = np.array(per_asset_pnls[sym])
        in_band = "yes" if abs(hp - sp.mean()) <= 2 * sp.std() else "no"
        print(f"{sym:35s} {hp:>10.2f} {sp.mean():>10.2f} {sp.std():>10.2f} {in_band:>12s}")

    in_band_total = sum(1 for sym in ALL_PRODUCTS
                        if abs(hist_pnls.get(sym, 0) - np.mean(per_asset_pnls[sym])) <= 2 * np.std(per_asset_pnls[sym]))
    print(f"\nProducts where historical hold-1 PnL within ±2σ of synthetic: {in_band_total}/50")


if __name__ == "__main__":
    main()
