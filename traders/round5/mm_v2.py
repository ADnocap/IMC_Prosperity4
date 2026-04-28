"""R5 trader v2 — penny-jump MM + inventory skew + 2 basket-FV constraints.

v1 result: mean PnL 116,843 / std 47,741 in MC.

v2 additions:
- Inventory skew: shift quote pair by -position * SKEW_TICKS (ticks per unit inventory).
  When long, both bid and ask shift down → cheaper to sell, harder to buy more.
  SKEW_TICKS = 0.3 → max 3-tick shift at full inventory (10 units).
- SNACKPACK_VANILLA implied FV = K_day_estimate - mid(SNACKPACK_CHOCOLATE).
  K_day_estimate = EMA of (mid_choc + mid_van) with slow alpha (0.005). Init from data
  in traderData; warm up over first ~200 ticks before relying on it.
- Per-asset adverse-selection guard: if observed sigma >> h, widen our quotes by 1 tick
  (don't penny-jump as aggressively). Hardcoded list from calibration.
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

# Inventory skew strength (ticks of quote shift per unit inventory).
SKEW_TICKS = 0.3

# Snackpack K_day EMA alpha (slow, since K drifts only with theta=0.0019).
K_DAY_ALPHA = 0.005

# Adverse-selection-prone assets: sigma / h > ~3. Widen quotes by 1 tick.
HIGH_SIGMA_ASSETS = frozenset({
    ROBOT_DISHES, ROBOT_IRONING, MICROCHIP_SQUARE, PEBBLES_XS,
    MICROCHIP_RECTANGLE, MICROCHIP_TRIANGLE, MICROCHIP_OVAL,
    ROBOT_LAUNDRY, ROBOT_MOPPING, ROBOT_VACUUMING, PEBBLES_S,
})


def _best_bid_ask(od: OrderDepth):
    bid = max(od.buy_orders.keys()) if od.buy_orders else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask


def _mid(od: OrderDepth):
    bid, ask = _best_bid_ask(od)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


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
                # Only trust the EMA after warmup; use it to imply VAN's FV.
                if k_init_count >= 200:
                    snackpack_van_fv = k_day_ema - mc

        # ---- per-product market-making ----------------------------------------
        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            best_bid, best_ask = _best_bid_ask(od)
            if best_bid is None or best_ask is None:
                continue

            # FV with two constraint overrides.
            if product == PEBBLES_XL and pebble_xl_fv is not None:
                fv = pebble_xl_fv
            elif product == SNACKPACK_VANILLA and snackpack_van_fv is not None:
                fv = snackpack_van_fv
            else:
                fv = (best_bid + best_ask) / 2.0

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

            # ---- MAKE: penny-jump with inventory skew + adverse-sel guard -----
            spread = best_ask - best_bid
            penny = 1
            if product in HIGH_SIGMA_ASSETS:
                # Don't penny-jump tight: stay 1 tick further from FV than v1.
                penny = 0 if spread >= 4 else 1
                # If spread tight, just match L1 (queue-share).

            if spread >= 2:
                quote_bid = best_bid + penny
                quote_ask = best_ask - penny
            else:
                quote_bid = best_bid
                quote_ask = best_ask

            # Inventory skew: shift both quotes by -pos * SKEW_TICKS (rounded).
            shift = -int(round(pos * SKEW_TICKS))
            quote_bid += shift
            quote_ask += shift

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
