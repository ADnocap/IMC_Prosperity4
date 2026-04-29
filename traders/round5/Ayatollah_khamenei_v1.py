"""R5 trader Ayatollah_khamenei_v1 — mm_v2 + microprice FV + OBI skew + post-trade adverse list.

Built on top of mm_v2 (penny-jump MM + inventory skew + 2 basket-FV constraints).
Three additions, all motivated by `analysis/round5/mm_features.py` results:

  1) Microprice as fair value (replaces (best_bid+best_ask)/2 for the 48 plain
     assets — Pebbles_XL and Snackpack_Vanilla still use their basket-implied
     FVs because those are exact constraints).
       microprice = (ask*bid_vol + bid*ask_vol) / (bid_vol + ask_vol)
     r(OBI, Δmid_next) is positive on every one of the 40 plain-MM assets
     (range +0.003 .. +0.065, noise floor 0.006 → many at ~10σ); microprice
     and OBI are r²≈1 collinear so we use microprice for a tidier formulation.

  2) OBI-driven quote shift. On top of the existing inventory skew, we shift
     both quotes by round(OBI_GAIN * obi_norm) where
       obi_norm = (bid_vol1 - ask_vol1) / (bid_vol1 + ask_vol1)  ∈ [-1, +1]
     OBI_GAIN = 1.0 → only shifts at moderate-to-extreme imbalance (|obi|>0.5),
     deliberately conservative because the predictive r is only ~0.05.

  3) HIGH_ADVERSE_ASSETS replaces mm_v2's σ-proxy HIGH_SIGMA_ASSETS list with
     the post-trade-flow ranking from `mm_post_trade.csv` (h=5):
        + ADD: UV_VISOR_RED/YELLOW/MAGENTA/ORANGE/AMBER, ROBOT_MOPPING/DISHES,
               PANEL_1X2, MICROCHIP_RECTANGLE, TRANSLATOR_VOID_BLUE/GRAPHITE_MIST,
               OXYGEN_SHAKE_GARLIC
        − REMOVE: MICROCHIP_SQUARE/OVAL/TRIANGLE, ROBOT_VACUUMING/LAUNDRY/IRONING,
                  PEBBLES_XS/S
     Notable: MICROCHIP_SQUARE was the single biggest reverter in the data
     (-3.33 ticks signed Δmid @ h=5) yet was flagged adverse by σ. Switching
     the list lets us penny-jump SQUARE aggressively.
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


# --- 50 product universe (declarations needed for Rust MC sim auto-detection) ---
GALAXY_SOUNDS_DARK_MATTER = "GALAXY_SOUNDS_DARK_MATTER"
GALAXY_SOUNDS_BLACK_HOLES = "GALAXY_SOUNDS_BLACK_HOLES"
GALAXY_SOUNDS_PLANETARY_RINGS = "GALAXY_SOUNDS_PLANETARY_RINGS"
GALAXY_SOUNDS_SOLAR_WINDS = "GALAXY_SOUNDS_SOLAR_WINDS"
GALAXY_SOUNDS_SOLAR_FLAMES = "GALAXY_SOUNDS_SOLAR_FLAMES"
SLEEP_POD_SUEDE = "SLEEP_POD_SUEDE"
SLEEP_POD_LAMB_WOOL = "SLEEP_POD_LAMB_WOOL"
SLEEP_POD_POLYESTER = "SLEEP_POD_POLYESTER"
SLEEP_POD_NYLON = "SLEEP_POD_NYLON"
SLEEP_POD_COTTON = "SLEEP_POD_COTTON"
MICROCHIP_CIRCLE = "MICROCHIP_CIRCLE"
MICROCHIP_OVAL = "MICROCHIP_OVAL"
MICROCHIP_SQUARE = "MICROCHIP_SQUARE"
MICROCHIP_RECTANGLE = "MICROCHIP_RECTANGLE"
MICROCHIP_TRIANGLE = "MICROCHIP_TRIANGLE"
PEBBLES_XS = "PEBBLES_XS"
PEBBLES_S = "PEBBLES_S"
PEBBLES_M = "PEBBLES_M"
PEBBLES_L = "PEBBLES_L"
PEBBLES_XL = "PEBBLES_XL"
ROBOT_VACUUMING = "ROBOT_VACUUMING"
ROBOT_MOPPING = "ROBOT_MOPPING"
ROBOT_DISHES = "ROBOT_DISHES"
ROBOT_LAUNDRY = "ROBOT_LAUNDRY"
ROBOT_IRONING = "ROBOT_IRONING"
UV_VISOR_YELLOW = "UV_VISOR_YELLOW"
UV_VISOR_AMBER = "UV_VISOR_AMBER"
UV_VISOR_ORANGE = "UV_VISOR_ORANGE"
UV_VISOR_RED = "UV_VISOR_RED"
UV_VISOR_MAGENTA = "UV_VISOR_MAGENTA"
TRANSLATOR_SPACE_GRAY = "TRANSLATOR_SPACE_GRAY"
TRANSLATOR_ASTRO_BLACK = "TRANSLATOR_ASTRO_BLACK"
TRANSLATOR_ECLIPSE_CHARCOAL = "TRANSLATOR_ECLIPSE_CHARCOAL"
TRANSLATOR_GRAPHITE_MIST = "TRANSLATOR_GRAPHITE_MIST"
TRANSLATOR_VOID_BLUE = "TRANSLATOR_VOID_BLUE"
PANEL_1X2 = "PANEL_1X2"
PANEL_2X2 = "PANEL_2X2"
PANEL_1X4 = "PANEL_1X4"
PANEL_2X4 = "PANEL_2X4"
PANEL_4X4 = "PANEL_4X4"
OXYGEN_SHAKE_MORNING_BREATH = "OXYGEN_SHAKE_MORNING_BREATH"
OXYGEN_SHAKE_EVENING_BREATH = "OXYGEN_SHAKE_EVENING_BREATH"
OXYGEN_SHAKE_MINT = "OXYGEN_SHAKE_MINT"
OXYGEN_SHAKE_CHOCOLATE = "OXYGEN_SHAKE_CHOCOLATE"
OXYGEN_SHAKE_GARLIC = "OXYGEN_SHAKE_GARLIC"
SNACKPACK_CHOCOLATE = "SNACKPACK_CHOCOLATE"
SNACKPACK_VANILLA = "SNACKPACK_VANILLA"
SNACKPACK_PISTACHIO = "SNACKPACK_PISTACHIO"
SNACKPACK_STRAWBERRY = "SNACKPACK_STRAWBERRY"
SNACKPACK_RASPBERRY = "SNACKPACK_RASPBERRY"

POSITION_LIMIT = 10
PEBBLES_FREE = (PEBBLES_XS, PEBBLES_S, PEBBLES_M, PEBBLES_L)
PEBBLE_CONSTANT = 50000.0

# Inventory skew (carry-over from mm_v2): -ticks per unit inventory.
SKEW_TICKS = 0.3

# OBI-driven quote shift toward heavy side. round(1.0 * obi_norm) → 1 tick at
# |obi|>0.5, 0 otherwise. Conservative because predictive r is only ~0.05.
OBI_GAIN = 1.0

# Snackpack K_day EMA alpha (slow, since K drifts only with theta=0.0019).
K_DAY_ALPHA = 0.005

# Post-trade-flow adverse-selection list. Source: analysis/round5/mm_features.py,
# `mm_post_trade.csv`, products with mean_signed_dmid @ h=5 ≥ +0.5 ticks.
# For these, we DON'T penny-jump tight spreads (would pay adverse on every fill);
# we join L1 instead.
HIGH_ADVERSE_ASSETS = frozenset({
    UV_VISOR_RED,           # +1.91
    UV_VISOR_YELLOW,        # +1.76
    ROBOT_MOPPING,          # +1.51
    ROBOT_DISHES,           # +1.48
    UV_VISOR_MAGENTA,       # +1.42
    PANEL_1X2,              # +1.39
    MICROCHIP_RECTANGLE,    # +1.23
    TRANSLATOR_VOID_BLUE,   # +1.12
    TRANSLATOR_GRAPHITE_MIST,  # +0.60
    OXYGEN_SHAKE_GARLIC,    # +0.56  (also has highest OBI but mid follows trade)
    UV_VISOR_ORANGE,        # +0.40 (rest of the UVs cluster as adverse)
})


def _best_bid_ask(od: OrderDepth):
    bid = max(od.buy_orders.keys()) if od.buy_orders else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask


def _mid(od: OrderDepth) -> Optional[float]:
    bid, ask = _best_bid_ask(od)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def _microprice_and_obi(od: OrderDepth):
    """Return (microprice, obi_norm) at L1, or (mid, 0.0) if degenerate."""
    bid, ask = _best_bid_ask(od)
    if bid is None or ask is None:
        return None, 0.0
    bv = od.buy_orders[bid]
    av = -od.sell_orders[ask]
    if bv + av <= 0:
        return (bid + ask) / 2.0, 0.0
    mp = (ask * bv + bid * av) / (bv + av)
    obi = (bv - av) / (bv + av)
    return mp, obi


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # ---- decode persistent state -------------------------------------------
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}
        k_day_ema: Optional[float] = mem.get("k_day")
        k_init_count: int = mem.get("k_init_count", 0)

        # ---- Pebbles XL implied FV from constraint -----------------------------
        pebble_xl_fv = None
        if all(p in state.order_depths for p in PEBBLES_FREE):
            mids = [_mid(state.order_depths[p]) for p in PEBBLES_FREE]
            if all(m is not None for m in mids):
                pebble_xl_fv = PEBBLE_CONSTANT - sum(mids)

        # ---- Snackpack K_day EMA update ----------------------------------------
        snackpack_van_fv = None
        if (SNACKPACK_CHOCOLATE in state.order_depths
                and SNACKPACK_VANILLA in state.order_depths):
            mc = _mid(state.order_depths[SNACKPACK_CHOCOLATE])
            mv = _mid(state.order_depths[SNACKPACK_VANILLA])
            if mc is not None and mv is not None:
                k_obs = mc + mv
                if k_day_ema is None:
                    k_day_ema = k_obs
                    k_init_count = 1
                else:
                    k_day_ema = (1 - K_DAY_ALPHA) * k_day_ema + K_DAY_ALPHA * k_obs
                    k_init_count += 1
                if k_init_count >= 200:
                    snackpack_van_fv = k_day_ema - mc

        # ---- per-product market-making ----------------------------------------
        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            best_bid, best_ask = _best_bid_ask(od)
            if best_bid is None or best_ask is None:
                continue

            mp, obi = _microprice_and_obi(od)

            # FV with two constraint overrides; everything else uses microprice.
            if product == PEBBLES_XL and pebble_xl_fv is not None:
                fv = pebble_xl_fv
            elif product == SNACKPACK_VANILLA and snackpack_van_fv is not None:
                fv = snackpack_van_fv
            else:
                fv = mp if mp is not None else (best_bid + best_ask) / 2.0

            # capacity (worst-case-fill rule)
            bid_cap = max(0, POSITION_LIMIT - pos)
            ask_cap = max(0, POSITION_LIMIT + pos)
            orders: List[Order] = []

            # ---- TAKE: free fills if a level sits beyond fv +/- 1 -------------
            took_buy = 0
            for ask_px in sorted(od.sell_orders.keys()):
                if ask_px <= fv - 1.0 and bid_cap - took_buy > 0:
                    qty = min(-od.sell_orders[ask_px], bid_cap - took_buy)
                    if qty > 0:
                        orders.append(Order(product, ask_px, qty))
                        took_buy += qty
                else:
                    break

            took_sell = 0
            for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                if bid_px >= fv + 1.0 and ask_cap - took_sell > 0:
                    qty = min(od.buy_orders[bid_px], ask_cap - took_sell)
                    if qty > 0:
                        orders.append(Order(product, bid_px, -qty))
                        took_sell += qty
                else:
                    break

            remaining_bid = bid_cap - took_buy
            remaining_ask = ask_cap - took_sell

            # ---- MAKE: penny-jump with adverse-guard + inventory + OBI shifts -
            spread = best_ask - best_bid
            penny = 1
            if product in HIGH_ADVERSE_ASSETS:
                # On adverse-flow assets, only penny-jump when spread is wide.
                penny = 0 if spread < 4 else 1

            if spread >= 2:
                quote_bid = best_bid + penny
                quote_ask = best_ask - penny
            else:
                quote_bid = best_bid
                quote_ask = best_ask

            # Inventory skew: shift both quotes by -pos * SKEW_TICKS (rounded).
            inv_shift = -int(round(pos * SKEW_TICKS))

            # OBI skew: heavy bid (obi > 0) → push quotes up toward where mid
            # is about to move. Conservative (gain 1.0). Disabled for adverse
            # assets — flow there continues, so leaning into it is worse, not
            # better, for a passive maker.
            if product in HIGH_ADVERSE_ASSETS:
                obi_shift = 0
            else:
                obi_shift = int(round(OBI_GAIN * obi))

            quote_bid += inv_shift + obi_shift
            quote_ask += inv_shift + obi_shift

            # Stay safely on each side of fv.
            if quote_bid >= fv:
                quote_bid = math.floor(fv - 0.5)
            if quote_ask <= fv:
                quote_ask = math.ceil(fv + 0.5)
            if quote_ask <= quote_bid:
                quote_ask = quote_bid + 1

            mm_bid_size = min(10, remaining_bid)
            mm_ask_size = min(10, remaining_ask)

            if mm_bid_size > 0:
                orders.append(Order(product, quote_bid, mm_bid_size))
            if mm_ask_size > 0:
                orders.append(Order(product, quote_ask, -mm_ask_size))

            result[product] = orders

        out_data = json.dumps({
            "k_day": k_day_ema,
            "k_init_count": k_init_count,
        })
        return result, 0, out_data
