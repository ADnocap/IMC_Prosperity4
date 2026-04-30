"""Round 5 factor_v14 — v12 + range-position (Bollinger) MR signal.

Diagnosis on R5 historical: corr(range_position_in_200tick, future_100tick_diff)
ranges from -0.05 to **-0.16** for many assets (PEBBLES_XL -0.156, ROBOT_LAUNDRY
-0.098, GALAXY_SOUNDS_DARK_MATTER -0.089, OXYGEN_SHAKE_CHOCOLATE -0.082, etc).
This is a Bollinger-style signal: when mid is at the top of its rolling window,
expect a pullback over the next ~100 ticks (and vice versa). The signal is
ORTHOGONAL to EMA-MR (which compares to a running mean, not extremes) and
typically *aligns* with EMA-MR — both push toward mean reversion at extremes.

Implementation:
  range_pos = (mid - min_200) / (max_200 - min_200)        ∈ [0, 1]
  range_signal = -2 * (range_pos - 0.5)                    ∈ [-1, +1]
  target += RANGE_KAPPA * range_signal

Storage: per-asset deque of last 200 mids in traderData.

Layered on top of v12's existing per-asset EMA-MR + snackpack pair signal.
Routing (DIR vs MM) unchanged.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


ASSETS: Tuple[str, ...] = (
    'GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES',
    'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS',
    'GALAXY_SOUNDS_SOLAR_FLAMES', 'SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON',
    'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
    'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE', 'PEBBLES_XS', 'PEBBLES_S',
    'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL', 'ROBOT_VACUUMING',
    'ROBOT_MOPPING', 'ROBOT_DISHES', 'ROBOT_LAUNDRY', 'ROBOT_IRONING',
    'UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE', 'UV_VISOR_RED',
    'UV_VISOR_MAGENTA', 'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK',
    'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST',
    'TRANSLATOR_VOID_BLUE', 'PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4',
    'PANEL_2X4', 'PANEL_4X4', 'OXYGEN_SHAKE_MORNING_BREATH',
    'OXYGEN_SHAKE_EVENING_BREATH', 'OXYGEN_SHAKE_MINT',
    'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC', 'SNACKPACK_CHOCOLATE',
    'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY',
    'SNACKPACK_RASPBERRY',
)
N_ASSETS = 50
ASSET_IDX = {s: i for i, s in enumerate(ASSETS)}

SIGMA: Tuple[float, ...] = (
    10.2457, 11.4797, 10.8791, 10.5392, 11.0946, 11.4217, 10.7125, 11.8908,
    9.6210, 11.6766, 9.2342, 12.4780, 20.7075, 13.1303, 14.5040, 15.0524,
    15.0203, 15.1336, 15.0255, 30.3142, 9.2356, 11.1458, 17.7795, 9.8223,
    10.4437, 11.0062, 8.0050, 10.4606, 11.0305, 11.2025, 9.4238, 9.4489,
    9.8573, 10.1300, 10.8332, 9.0543, 9.5962, 9.4831, 11.2892, 9.9571,
    10.1008, 10.9833, 9.8836, 10.8903, 12.0146, 6.5756, 6.5131, 5.2378,
    8.1330, 8.0918,
)

HL_PER_ASSET: Tuple[int, ...] = (
    1108, 0, 0, 0, 1671, 1671, 1671, 0, 1671, 0,
    0, 0, 0, 1270, 1108, 0, 1000, 1457, 0, 1500,
    1108, 0, 1000, 1000, 0, 0, 1270, 0, 1000, 1457,
    0, 1000, 1671, 0, 1671, 0, 0, 0, 1457, 0,
    0, 0, 0, 1916, 0, 1000, 1500, 1000, 1000, 1000,
)
EMA_ALPHA: Tuple[float, ...] = tuple(
    (1.0 - 2.0 ** (-1.0 / hl)) if hl > 0 else 0.0 for hl in HL_PER_ASSET
)

POS_LIMIT = 10
KAPPA = 4.0
ALPHA_CAP = 3.0

# MM layer params
MM_BIG_QTY = 6
MM_SMALL_QTY = 2
MM_BAL_QTY = 4

# Range-position signal — only the 12 assets where corr_rngpos_fut100 > 0.05 in historical
RANGE_WINDOW = 100
RANGE_KAPPA = 3.0
RANGE_ASSETS = frozenset([
    'PEBBLES_XL', 'ROBOT_LAUNDRY', 'GALAXY_SOUNDS_DARK_MATTER',
    'OXYGEN_SHAKE_CHOCOLATE', 'PEBBLES_XS', 'SLEEP_POD_POLYESTER',
    'OXYGEN_SHAKE_EVENING_BREATH', 'UV_VISOR_MAGENTA',
    'SNACKPACK_PISTACHIO', 'SNACKPACK_RASPBERRY',
    'TRANSLATOR_GRAPHITE_MIST', 'UV_VISOR_AMBER', 'OXYGEN_SHAKE_GARLIC',
])

# Snackpack pair
SP_CHOC = 'SNACKPACK_CHOCOLATE'
SP_VAN = 'SNACKPACK_VANILLA'
HL_K = 3000
EMA_ALPHA_K = 1.0 - 2.0 ** (-1.0 / HL_K)
PAIR_SIGMA_K = 35.0
PAIR_KAPPA = 6.0
PAIR_ALPHA_CAP = 3.0


class Trader:
    def run(self, state: TradingState):
        try:
            td: Dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            td = {}

        # Restore mid history (per-asset deque, capped at RANGE_WINDOW)
        hist: Dict[str, List[float]] = td.get('hist', {})

        mids: Dict[str, float] = {}
        for i, sym in enumerate(ASSETS):
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = 0.5 * (best_bid + best_ask)
            mids[sym] = mid
            # update mid history ONLY for range-targeted assets
            if sym in RANGE_ASSETS:
                h = hist.get(sym, [])
                h.append(mid)
                if len(h) > RANGE_WINDOW:
                    h = h[-RANGE_WINDOW:]
                hist[sym] = h
            # update FV EMA
            alpha_i = EMA_ALPHA[i]
            if alpha_i > 0:
                key = f"fv_{sym}"
                prev = td.get(key)
                td[key] = mid if prev is None else (1.0 - alpha_i) * prev + alpha_i * mid

        td['hist'] = hist

        # Per-asset target from EMA-MR
        target: List[float] = [0.0] * N_ASSETS
        for i, sym in enumerate(ASSETS):
            mid = mids.get(sym)
            if mid is None or EMA_ALPHA[i] <= 0:
                continue
            sigma = SIGMA[i]
            if sigma <= 0:
                continue
            fv = td.get(f"fv_{sym}")
            if fv is None:
                continue
            z = (fv - mid) / sigma
            if z > ALPHA_CAP:
                z = ALPHA_CAP
            elif z < -ALPHA_CAP:
                z = -ALPHA_CAP
            target[i] = KAPPA * z

        # Range-position MR layer (only for selected high-signal assets)
        for sym in RANGE_ASSETS:
            mid = mids.get(sym)
            if mid is None:
                continue
            h = hist.get(sym, [])
            if len(h) < RANGE_WINDOW // 2:  # warmup
                continue
            mn = min(h)
            mx = max(h)
            spread = mx - mn
            if spread < 1e-6:
                continue
            range_pos = (mid - mn) / spread
            range_signal = -2.0 * (range_pos - 0.5)
            target[ASSET_IDX[sym]] += RANGE_KAPPA * range_signal

        # Snackpack pair
        if SP_CHOC in mids and SP_VAN in mids:
            K = mids[SP_CHOC] + mids[SP_VAN]
            ema_K = td.get('ema_K')
            td['ema_K'] = K if ema_K is None else (1.0 - EMA_ALPHA_K) * ema_K + EMA_ALPHA_K * K
            K_resid = K - td['ema_K']
            z_K = K_resid / PAIR_SIGMA_K
            if z_K > PAIR_ALPHA_CAP:
                z_K = PAIR_ALPHA_CAP
            elif z_K < -PAIR_ALPHA_CAP:
                z_K = -PAIR_ALPHA_CAP
            pair_target = -PAIR_KAPPA * z_K
            target[ASSET_IDX[SP_CHOC]] += pair_target
            target[ASSET_IDX[SP_VAN]] += pair_target

        # Clip and round
        target_int: List[int] = [0] * N_ASSETS
        for i in range(N_ASSETS):
            t = target[i]
            if t > POS_LIMIT:
                t = POS_LIMIT
            elif t < -POS_LIMIT:
                t = -POS_LIMIT
            target_int[i] = int(round(t))

        # Generate orders
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        for i, sym in enumerate(ASSETS):
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

            # DIR layer: only assets with EMA-MR signal active OR snackpack pair member
            tgt = target_int[i]
            in_pair = i in (ASSET_IDX[SP_CHOC], ASSET_IDX[SP_VAN])

            if EMA_ALPHA[i] > 0 or in_pair:
                # Directional close-the-gap (target driven by EMA-MR + range + pair)
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
                # MM layer: 2-sided penny-jump, sizes skewed by (target - pos)
                # target may be non-zero from range signal
                diff_mm = tgt - pos
                if diff_mm > 0:
                    bid_q, ask_q = MM_BIG_QTY, MM_SMALL_QTY
                elif diff_mm < 0:
                    bid_q, ask_q = MM_SMALL_QTY, MM_BIG_QTY
                else:
                    bid_q = ask_q = MM_BAL_QTY
                bid_q = min(bid_q, buy_room)
                ask_q = min(ask_q, sell_room)
                if bid_q > 0:
                    orders.append(Order(sym, our_bid, bid_q))
                if ask_q > 0:
                    orders.append(Order(sym, our_ask, -ask_q))

            if orders:
                result[sym] = orders

        return result, 0, json.dumps(td, separators=(",", ":"))
