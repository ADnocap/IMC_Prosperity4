"""Round 5 master trader — composes 3 disjoint per-symbol sub-strategies.

Each sub-trader owns a fixed slice of the 50-symbol universe; their orders are
unioned and their state is JSON-namespaced so they don't step on each other.

  * Pebble layer       (5 symbols) — `_pebble_step`, port of Pebble_fucker_v1.
                        Basket-residual MM: r = sum(5 pebbles) − 50000;
                        if r > 1, post asks only; if r < −1, post bids only;
                        else 2-sided penny-jump. Stateless.

  * Snackpack layer    (5 symbols) — `_snackpack_step`, port of snackpack.py.
                        Per-asset OU-MR + K_pair (CHOC+VAN) + K_factor (triplet)
                        + Bollinger range-pos on PIS/RASP. Stateful (EMAs + hist).

  * Factor-v12 layer   (40 symbols) — `_factor_step`, port of factor_v12.
                        EMA-MR drift capture on fast-OU assets (one-sided
                        close-the-gap), 2-sided MM on slow-OU + RW assets,
                        snackpack pair signal stripped (handled by snackpack layer).
                        Stateful (per-asset EMAs).

The factor universe excludes PEBBLES + SNACKPACKS so the master never
double-quotes or fights its own subs.

State namespace inside `traderData`:
    { "pf": {}, "sp": {pebble snackpack state}, "fv": {factor state} }
"""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
PEBBLES = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")
SNACKPACKS = ("SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA",
              "SNACKPACK_PISTACHIO", "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY")

# Factor-v12 universe = original 50 minus pebbles & snackpacks
FACTOR_ASSETS: Tuple[str, ...] = (
    'GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES',
    'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS',
    'GALAXY_SOUNDS_SOLAR_FLAMES', 'SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON',
    'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
    'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE',
    'ROBOT_VACUUMING', 'ROBOT_MOPPING', 'ROBOT_DISHES',
    'ROBOT_LAUNDRY', 'ROBOT_IRONING',
    'UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE',
    'UV_VISOR_RED', 'UV_VISOR_MAGENTA',
    'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK',
    'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST',
    'TRANSLATOR_VOID_BLUE',
    'PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4', 'PANEL_2X4', 'PANEL_4X4',
    'OXYGEN_SHAKE_MORNING_BREATH', 'OXYGEN_SHAKE_EVENING_BREATH',
    'OXYGEN_SHAKE_MINT', 'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC',
)
assert len(FACTOR_ASSETS) == 40
FACTOR_IDX = {s: i for i, s in enumerate(FACTOR_ASSETS)}

POS_LIMIT = 10


# ---------------------------------------------------------------------------
# Pebble layer (port of Pebble_fucker_v2 — adds take layer for extreme residuals)
# ---------------------------------------------------------------------------
PEBBLE_BASKET_SUM = 50_000
PEBBLE_RESIDUAL_THRESHOLD = 1.0
PEBBLE_MAX_QUOTE_SIZE = POS_LIMIT
PEBBLE_HALF_SPREAD: Dict[str, float] = {
    "PEBBLES_XS": 4.5, "PEBBLES_S": 6.0, "PEBBLES_M": 6.5,
    "PEBBLES_L": 6.5, "PEBBLES_XL": 8.5,
}
PEBBLE_TAKE_CUSHION = 1.0


def _pebble_step(state: TradingState, _td: dict) -> Dict[str, List[Order]]:
    out: Dict[str, List[Order]] = {}
    mids: Dict[str, float] = {}
    for p in PEBBLES:
        od = state.order_depths.get(p)
        if od is None or not od.buy_orders or not od.sell_orders:
            return out
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mids[p] = (best_bid + best_ask) / 2.0

    sum_all = sum(mids.values())
    residual = sum_all - PEBBLE_BASKET_SUM

    for p in PEBBLES:
        od = state.order_depths[p]
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        best_bid_qty = od.buy_orders[best_bid]
        best_ask_qty = abs(od.sell_orders[best_ask])
        position = state.position.get(p, 0)
        passive_bid_px = best_bid + 1
        passive_ask_px = best_ask - 1
        if passive_bid_px >= passive_ask_px:
            continue
        max_buy = max(0, POS_LIMIT - position)
        max_sell = max(0, POS_LIMIT + position)
        t_thresh = PEBBLE_HALF_SPREAD[p] + PEBBLE_TAKE_CUSHION
        orders: List[Order] = []

        if residual > t_thresh:
            take_qty = min(best_bid_qty, max_sell, PEBBLE_MAX_QUOTE_SIZE)
            if take_qty > 0:
                orders.append(Order(p, best_bid, -take_qty))
            remaining_sell = min(max_sell - take_qty, PEBBLE_MAX_QUOTE_SIZE)
            if remaining_sell > 0:
                orders.append(Order(p, passive_ask_px, -remaining_sell))
        elif residual < -t_thresh:
            take_qty = min(best_ask_qty, max_buy, PEBBLE_MAX_QUOTE_SIZE)
            if take_qty > 0:
                orders.append(Order(p, best_ask, take_qty))
            remaining_buy = min(max_buy - take_qty, PEBBLE_MAX_QUOTE_SIZE)
            if remaining_buy > 0:
                orders.append(Order(p, passive_bid_px, remaining_buy))
        elif residual > PEBBLE_RESIDUAL_THRESHOLD:
            ask_qty = min(PEBBLE_MAX_QUOTE_SIZE, max_sell)
            if ask_qty > 0:
                orders.append(Order(p, passive_ask_px, -ask_qty))
        elif residual < -PEBBLE_RESIDUAL_THRESHOLD:
            bid_qty = min(PEBBLE_MAX_QUOTE_SIZE, max_buy)
            if bid_qty > 0:
                orders.append(Order(p, passive_bid_px, bid_qty))
        else:
            bid_qty = min(PEBBLE_MAX_QUOTE_SIZE, max_buy)
            ask_qty = min(PEBBLE_MAX_QUOTE_SIZE, max_sell)
            if bid_qty > 0:
                orders.append(Order(p, passive_bid_px, bid_qty))
            if ask_qty > 0:
                orders.append(Order(p, passive_ask_px, -ask_qty))
        if orders:
            out[p] = orders
    return out


# ---------------------------------------------------------------------------
# Snackpack layer (port of snackpack.py)
# ---------------------------------------------------------------------------
SP_CHOC = "SNACKPACK_CHOCOLATE"
SP_VAN = "SNACKPACK_VANILLA"
SP_PIS = "SNACKPACK_PISTACHIO"
SP_STRAW = "SNACKPACK_STRAWBERRY"
SP_RASP = "SNACKPACK_RASPBERRY"

SP_TRIPLET = (SP_PIS, SP_STRAW, SP_RASP)

SP_SIGMA_USE: Dict[str, float] = {
    SP_CHOC: 6.575, SP_VAN: 6.513,
    SP_PIS: 2.023, SP_STRAW: 1.397, SP_RASP: 1.957,
}
SP_LOADINGS: Dict[str, float] = {
    SP_PIS: -0.39556131996287075,
    SP_STRAW: -0.6559670557472661,
    SP_RASP: 0.6428362652522759,
}

SP_HL_FV = 400
SP_HL_K = 1500
SP_HL_F = 1500
SP_HL_RANGE = 200
SP_ALPHA_FV = 1.0 - 2.0 ** (-1.0 / SP_HL_FV)
SP_ALPHA_K = 1.0 - 2.0 ** (-1.0 / SP_HL_K)
SP_ALPHA_F = 1.0 - 2.0 ** (-1.0 / SP_HL_F)
SP_SIGMA_K_USE = 42.0
SP_SIGMA_F_USE = 215.0
SP_KAPPA_OU = 4.0
SP_KAPPA_PAIR = 5.0
SP_KAPPA_TRIP = 6.0
SP_KAPPA_RANGE = 3.0
SP_ALPHA_CAP = 3.0
SP_MM_SMALL_QTY = 2
SP_MM_BIG_QTY = 5
SP_RANGE_TARGETS = frozenset([SP_PIS, SP_RASP])


def _ema(prev, x: float, alpha: float) -> float:
    if prev is None:
        return x
    return (1.0 - alpha) * prev + alpha * x


def _clip(x: float, lo: float, hi: float) -> float:
    if x > hi:
        return hi
    if x < lo:
        return lo
    return x


def _snackpack_step(state: TradingState, td: dict) -> Dict[str, List[Order]]:
    out: Dict[str, List[Order]] = {}

    mids: Dict[str, float] = {}
    best_bids: Dict[str, int] = {}
    best_asks: Dict[str, int] = {}
    for sym in SNACKPACKS:
        od = state.order_depths.get(sym)
        if od is None or not od.buy_orders or not od.sell_orders:
            continue
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        mids[sym] = 0.5 * (bb + ba)
        best_bids[sym] = bb
        best_asks[sym] = ba

    for sym, mid in mids.items():
        key = f"fv_{sym}"
        td[key] = _ema(td.get(key), mid, SP_ALPHA_FV)

    hist: Dict[str, List[float]] = td.get("hist", {})
    for sym in SP_RANGE_TARGETS:
        mid = mids.get(sym)
        if mid is None:
            continue
        buf = hist.get(sym, [])
        buf.append(mid)
        if len(buf) > SP_HL_RANGE:
            buf = buf[-SP_HL_RANGE:]
        hist[sym] = buf
    td["hist"] = hist

    K = None
    if SP_CHOC in mids and SP_VAN in mids:
        K = mids[SP_CHOC] + mids[SP_VAN]
        td["ema_K"] = _ema(td.get("ema_K"), K, SP_ALPHA_K)

    F = None
    if all(s in mids for s in SP_TRIPLET):
        F = sum(SP_LOADINGS[s] * mids[s] for s in SP_TRIPLET)
        td["ema_F"] = _ema(td.get("ema_F"), F, SP_ALPHA_F)

    target: Dict[str, float] = {s: 0.0 for s in SNACKPACKS}

    for sym, mid in mids.items():
        fv = td.get(f"fv_{sym}")
        if fv is None:
            continue
        sigma = SP_SIGMA_USE[sym]
        z = _clip((fv - mid) / sigma, -SP_ALPHA_CAP, SP_ALPHA_CAP)
        target[sym] += SP_KAPPA_OU * z

    if K is not None and td.get("ema_K") is not None:
        z_K = _clip((K - td["ema_K"]) / SP_SIGMA_K_USE, -SP_ALPHA_CAP, SP_ALPHA_CAP)
        pair_pos = -SP_KAPPA_PAIR * z_K
        target[SP_CHOC] += pair_pos
        target[SP_VAN] += pair_pos

    if F is not None and td.get("ema_F") is not None:
        z_F = _clip((F - td["ema_F"]) / SP_SIGMA_F_USE, -SP_ALPHA_CAP, SP_ALPHA_CAP)
        for sym in SP_TRIPLET:
            target[sym] += -SP_KAPPA_TRIP * SP_LOADINGS[sym] * z_F

    for sym in SP_RANGE_TARGETS:
        buf = hist.get(sym, [])
        if len(buf) < SP_HL_RANGE // 2:
            continue
        mid = mids.get(sym)
        if mid is None:
            continue
        mn = min(buf)
        mx = max(buf)
        spread = mx - mn
        if spread < 1e-6:
            continue
        range_pos = (mid - mn) / spread
        range_signal = -2.0 * (range_pos - 0.5)
        target[sym] += SP_KAPPA_RANGE * range_signal

    target_int: Dict[str, int] = {}
    for sym in SNACKPACKS:
        t = _clip(target[sym], -POS_LIMIT, POS_LIMIT)
        target_int[sym] = int(round(t))

    for sym in SNACKPACKS:
        if sym not in mids:
            continue
        bb = best_bids[sym]
        ba = best_asks[sym]
        if ba - bb < 2:
            continue
        pos = state.position.get(sym, 0)
        buy_room = POS_LIMIT - pos
        sell_room = POS_LIMIT + pos
        our_bid = bb + 1
        our_ask = ba - 1
        tgt = target_int[sym]
        diff = tgt - pos
        orders: List[Order] = []
        if diff >= 1:
            qty_b = min(diff, buy_room)
            if qty_b > 0:
                orders.append(Order(sym, our_bid, qty_b))
            qty_a = min(SP_MM_SMALL_QTY, sell_room)
            if qty_a > 0:
                orders.append(Order(sym, our_ask, -qty_a))
        elif diff <= -1:
            qty_a = min(-diff, sell_room)
            if qty_a > 0:
                orders.append(Order(sym, our_ask, -qty_a))
            qty_b = min(SP_MM_SMALL_QTY, buy_room)
            if qty_b > 0:
                orders.append(Order(sym, our_bid, qty_b))
        else:
            if pos > 0:
                bid_q, ask_q = SP_MM_SMALL_QTY, SP_MM_BIG_QTY
            elif pos < 0:
                bid_q, ask_q = SP_MM_BIG_QTY, SP_MM_SMALL_QTY
            else:
                bid_q = ask_q = SP_MM_BIG_QTY
            bid_q = min(bid_q, buy_room)
            ask_q = min(ask_q, sell_room)
            if bid_q > 0:
                orders.append(Order(sym, our_bid, bid_q))
            if ask_q > 0:
                orders.append(Order(sym, our_ask, -ask_q))
        if orders:
            out[sym] = orders

    return out


# ---------------------------------------------------------------------------
# Factor v12 layer (40 non-basket assets)
# ---------------------------------------------------------------------------
# Per-asset σ (raw mid-diff std)
FACTOR_SIGMA: Dict[str, float] = {
    'GALAXY_SOUNDS_DARK_MATTER': 10.2457, 'GALAXY_SOUNDS_BLACK_HOLES': 11.4797,
    'GALAXY_SOUNDS_PLANETARY_RINGS': 10.8791, 'GALAXY_SOUNDS_SOLAR_WINDS': 10.5392,
    'GALAXY_SOUNDS_SOLAR_FLAMES': 11.0946, 'SLEEP_POD_SUEDE': 11.4217,
    'SLEEP_POD_LAMB_WOOL': 10.7125, 'SLEEP_POD_POLYESTER': 11.8908,
    'SLEEP_POD_NYLON': 9.6210, 'SLEEP_POD_COTTON': 11.6766,
    'MICROCHIP_CIRCLE': 9.2342, 'MICROCHIP_OVAL': 12.4780,
    'MICROCHIP_SQUARE': 20.7075, 'MICROCHIP_RECTANGLE': 13.1303,
    'MICROCHIP_TRIANGLE': 14.5040,
    'ROBOT_VACUUMING': 9.2356, 'ROBOT_MOPPING': 11.1458,
    'ROBOT_DISHES': 17.7795, 'ROBOT_LAUNDRY': 9.8223, 'ROBOT_IRONING': 10.4437,
    'UV_VISOR_YELLOW': 11.0062, 'UV_VISOR_AMBER': 8.0050,
    'UV_VISOR_ORANGE': 10.4606, 'UV_VISOR_RED': 11.0305,
    'UV_VISOR_MAGENTA': 11.2025,
    'TRANSLATOR_SPACE_GRAY': 9.4238, 'TRANSLATOR_ASTRO_BLACK': 9.4489,
    'TRANSLATOR_ECLIPSE_CHARCOAL': 9.8573, 'TRANSLATOR_GRAPHITE_MIST': 10.1300,
    'TRANSLATOR_VOID_BLUE': 10.8332,
    'PANEL_1X2': 9.0543, 'PANEL_2X2': 9.5962, 'PANEL_1X4': 9.4831,
    'PANEL_2X4': 11.2892, 'PANEL_4X4': 9.9571,
    'OXYGEN_SHAKE_MORNING_BREATH': 10.1008, 'OXYGEN_SHAKE_EVENING_BREATH': 10.9833,
    'OXYGEN_SHAKE_MINT': 9.8836, 'OXYGEN_SHAKE_CHOCOLATE': 10.8903,
    'OXYGEN_SHAKE_GARLIC': 12.0146,
}

# Per-asset HL (0 = MM-only, > 0 = directional with EMA-MR signal)
# Identical to factor_v12.HL_PER_ASSET with PEBBLES & SNACKPACKS removed.
FACTOR_HL: Dict[str, int] = {
    'GALAXY_SOUNDS_DARK_MATTER': 1108, 'GALAXY_SOUNDS_BLACK_HOLES': 0,
    'GALAXY_SOUNDS_PLANETARY_RINGS': 0, 'GALAXY_SOUNDS_SOLAR_WINDS': 0,
    'GALAXY_SOUNDS_SOLAR_FLAMES': 1671,
    'SLEEP_POD_SUEDE': 1671, 'SLEEP_POD_LAMB_WOOL': 1671,
    'SLEEP_POD_POLYESTER': 0, 'SLEEP_POD_NYLON': 1671, 'SLEEP_POD_COTTON': 0,
    'MICROCHIP_CIRCLE': 0, 'MICROCHIP_OVAL': 0, 'MICROCHIP_SQUARE': 0,
    'MICROCHIP_RECTANGLE': 1270, 'MICROCHIP_TRIANGLE': 1108,
    'ROBOT_VACUUMING': 1108, 'ROBOT_MOPPING': 0, 'ROBOT_DISHES': 1000,
    'ROBOT_LAUNDRY': 1000, 'ROBOT_IRONING': 0,
    'UV_VISOR_YELLOW': 0, 'UV_VISOR_AMBER': 0, 'UV_VISOR_ORANGE': 0,
    'UV_VISOR_RED': 1000, 'UV_VISOR_MAGENTA': 1457,
    'TRANSLATOR_SPACE_GRAY': 0, 'TRANSLATOR_ASTRO_BLACK': 1000,
    'TRANSLATOR_ECLIPSE_CHARCOAL': 1671, 'TRANSLATOR_GRAPHITE_MIST': 0,
    'TRANSLATOR_VOID_BLUE': 1671,
    'PANEL_1X2': 0, 'PANEL_2X2': 0, 'PANEL_1X4': 0,
    'PANEL_2X4': 1457, 'PANEL_4X4': 0,
    'OXYGEN_SHAKE_MORNING_BREATH': 0, 'OXYGEN_SHAKE_EVENING_BREATH': 0,
    'OXYGEN_SHAKE_MINT': 0, 'OXYGEN_SHAKE_CHOCOLATE': 1916,
    'OXYGEN_SHAKE_GARLIC': 0,
}
FACTOR_EMA_ALPHA: Dict[str, float] = {
    s: (1.0 - 2.0 ** (-1.0 / hl)) if hl > 0 else 0.0
    for s, hl in FACTOR_HL.items()
}

FACTOR_KAPPA = 4.0
FACTOR_ALPHA_CAP = 3.0
FACTOR_MM_BIG_QTY = 6
FACTOR_MM_SMALL_QTY = 2
FACTOR_MM_BAL_QTY = 4


def _factor_step(state: TradingState, td: dict) -> Dict[str, List[Order]]:
    out: Dict[str, List[Order]] = {}

    mids: Dict[str, float] = {}
    for sym in FACTOR_ASSETS:
        od = state.order_depths.get(sym)
        if od is None or not od.buy_orders or not od.sell_orders:
            continue
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = 0.5 * (best_bid + best_ask)
        mids[sym] = mid
        alpha_i = FACTOR_EMA_ALPHA[sym]
        if alpha_i > 0:
            key = f"fv_{sym}"
            prev = td.get(key)
            td[key] = mid if prev is None else (1.0 - alpha_i) * prev + alpha_i * mid

    target: Dict[str, float] = {s: 0.0 for s in FACTOR_ASSETS}
    for sym in FACTOR_ASSETS:
        mid = mids.get(sym)
        if mid is None or FACTOR_EMA_ALPHA[sym] <= 0:
            continue
        sigma = FACTOR_SIGMA[sym]
        if sigma <= 0:
            continue
        fv = td.get(f"fv_{sym}")
        if fv is None:
            continue
        z = (fv - mid) / sigma
        if z > FACTOR_ALPHA_CAP:
            z = FACTOR_ALPHA_CAP
        elif z < -FACTOR_ALPHA_CAP:
            z = -FACTOR_ALPHA_CAP
        target[sym] = FACTOR_KAPPA * z

    target_int: Dict[str, int] = {}
    for sym in FACTOR_ASSETS:
        t = target[sym]
        if t > POS_LIMIT:
            t = POS_LIMIT
        elif t < -POS_LIMIT:
            t = -POS_LIMIT
        target_int[sym] = int(round(t))

    for sym in FACTOR_ASSETS:
        od = state.order_depths.get(sym)
        if od is None or not od.buy_orders or not od.sell_orders:
            continue
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        if best_ask - best_bid < 2:
            continue
        pos = state.position.get(sym, 0)
        buy_room = POS_LIMIT - pos
        sell_room = POS_LIMIT + pos
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        orders: List[Order] = []

        if FACTOR_EMA_ALPHA[sym] > 0:
            tgt = target_int[sym]
            diff = tgt - pos
            if diff > 0:
                qty = min(diff, buy_room)
                if qty > 0:
                    orders.append(Order(sym, our_bid, qty))
            elif diff < 0:
                qty = min(-diff, sell_room)
                if qty > 0:
                    orders.append(Order(sym, our_ask, -qty))
        else:
            if pos > 0:
                bid_q, ask_q = FACTOR_MM_SMALL_QTY, FACTOR_MM_BIG_QTY
            elif pos < 0:
                bid_q, ask_q = FACTOR_MM_BIG_QTY, FACTOR_MM_SMALL_QTY
            else:
                bid_q = ask_q = FACTOR_MM_BAL_QTY
            bid_q = min(bid_q, buy_room)
            ask_q = min(ask_q, sell_room)
            if bid_q > 0:
                orders.append(Order(sym, our_bid, bid_q))
            if ask_q > 0:
                orders.append(Order(sym, our_ask, -ask_q))

        if orders:
            out[sym] = orders

    return out


# ---------------------------------------------------------------------------
# Master Trader
# ---------------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        try:
            outer: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            outer = {}
        td_pf = outer.get("pf", {})
        td_sp = outer.get("sp", {})
        td_fv = outer.get("fv", {})

        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        for orders in (
            _pebble_step(state, td_pf),
            _snackpack_step(state, td_sp),
            _factor_step(state, td_fv),
        ):
            for sym, lst in orders.items():
                if lst:
                    result[sym] = lst

        outer = {"pf": td_pf, "sp": td_sp, "fv": td_fv}
        return result, 0, json.dumps(outer, separators=(",", ":"))
