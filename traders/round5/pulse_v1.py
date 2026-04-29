"""Round 5 pulse_v1 — factor_v10 + post-pulse defensive gate on the MM layer.

Bot takers fire in 3 shared Poisson pulses (V/M/P) hitting all members of a
group on the same side, same qty, in a single tick at exactly L1. We can
detect the pulse one tick later from state.market_trades + state.own_trades
(filtered by trade.timestamp == prev_tick).

When a pulse just hit us, the MM layer's pos-skew response over-reacts: the
book is asymmetric for ~1 tick post-pulse (one side depleted, refill in
flight), so quoting BIG on the side opposite our new inventory just gives
the next pulse another easy fill. pulse_v1's intervention: for the single
tick after a pulse, hold MM quotes symmetric (BAL/BAL, capped by remaining
room) on the affected products. Directional MR layer is untouched.

Detector specifics:
  - V-pulse: ≥30 of 40 vanilla members traded same side same qty
  - M-pulse: ≥4 of 5 microchips traded same side same qty
  - P-pulse: ≥4 of 5 pebbles traded same side same qty
  Direction inferred from price vs prev mid (in traderData) or from
  explicit bid_price_1/ask_price_1 match.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import Order, OrderDepth, Trade, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, Trade, TradingState


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

PEBBLE_MEMBERS = frozenset({'PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL'})
MICROCHIP_MEMBERS = frozenset({'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
                               'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE'})
VANILLA_MEMBERS = frozenset(ASSETS) - PEBBLE_MEMBERS - MICROCHIP_MEMBERS  # 40 members

V_PULSE_THRESH = 30   # ≥30 of 40 vanilla → V-pulse
M_PULSE_THRESH = 4    # ≥4 of 5 microchip → M-pulse
P_PULSE_THRESH = 4    # ≥4 of 5 pebble → P-pulse


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
    0, 0, 0, 1270, 1108, 1916, 1000, 1457, 0, 1500,
    1108, 0, 1000, 1000, 0, 0, 0, 0, 1000, 1457,
    1671, 1000, 1671, 0, 1671, 0, 0, 0, 1457, 0,
    0, 1457, 0, 1916, 0, 1000, 1500, 1000, 1000, 1000,
)
EMA_ALPHA: Tuple[float, ...] = tuple(
    (1.0 - 2.0 ** (-1.0 / hl)) if hl > 0 else 0.0 for hl in HL_PER_ASSET
)

POS_LIMIT = 10
KAPPA = 4.0
ALPHA_CAP = 3.0

MM_BIG_QTY = 6
MM_SMALL_QTY = 2
MM_BAL_QTY = 4

SP_CHOC = 'SNACKPACK_CHOCOLATE'
SP_VAN = 'SNACKPACK_VANILLA'
HL_K = 3000
EMA_ALPHA_K = 1.0 - 2.0 ** (-1.0 / HL_K)
PAIR_SIGMA_K = 35.0
PAIR_KAPPA = 6.0
PAIR_ALPHA_CAP = 3.0


def _detect_pulse(state: TradingState, td: Dict) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Returns (kind, side, qty) where kind ∈ {'V','M','P', None}, side ∈ {-1,+1}.

    Inspects state.market_trades + state.own_trades for trades whose timestamp
    equals the previous tick. Same-side same-qty members per category counted
    against the threshold.
    """
    prev_ts = state.timestamp - 100
    if prev_ts < 0:
        return None, None, None

    # Need prev mids to infer direction (saved in td as 'prev_mids').
    prev_mids: Dict[str, float] = td.get('prev_mids', {})
    if not prev_mids:
        return None, None, None

    # Collect all trades from previous tick across both feeds, dedupe by (sym, price, qty).
    members_by_sig: Dict[Tuple[str, int], Dict[str, int]] = {}
    # signature key = (side, qty)  value = {sym: True}
    def add_trade(sym: str, price: float, qty: int):
        pm = prev_mids.get(sym)
        if pm is None:
            return
        if price > pm:
            side = +1   # BUY-side pulse (taker bought at ask)
        elif price < pm:
            side = -1   # SELL-side pulse (taker hit bid)
        else:
            return  # ambiguous
        key = (side, abs(qty))
        members_by_sig.setdefault(key, {})[sym] = True

    for sym in ASSETS:
        for tr in state.market_trades.get(sym, []):
            if getattr(tr, 'timestamp', prev_ts) != prev_ts:
                continue
            add_trade(sym, tr.price, tr.quantity)
        for tr in state.own_trades.get(sym, []):
            if getattr(tr, 'timestamp', prev_ts) != prev_ts:
                continue
            add_trade(sym, tr.price, tr.quantity)

    if not members_by_sig:
        return None, None, None

    # Pick the signature with the most members fired.
    (best_side, best_qty), best_members = max(
        members_by_sig.items(), key=lambda kv: len(kv[1])
    )
    syms = best_members.keys()
    n_v = sum(1 for s in syms if s in VANILLA_MEMBERS)
    n_m = sum(1 for s in syms if s in MICROCHIP_MEMBERS)
    n_p = sum(1 for s in syms if s in PEBBLE_MEMBERS)

    if n_v >= V_PULSE_THRESH:
        return 'V', best_side, best_qty
    if n_m >= M_PULSE_THRESH:
        return 'M', best_side, best_qty
    if n_p >= P_PULSE_THRESH:
        return 'P', best_side, best_qty
    return None, None, None


def _affected_members(kind: str) -> frozenset:
    if kind == 'V':
        return VANILLA_MEMBERS
    if kind == 'M':
        return MICROCHIP_MEMBERS
    if kind == 'P':
        return PEBBLE_MEMBERS
    return frozenset()


class Trader:
    def run(self, state: TradingState):
        try:
            td: Dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            td = {}

        pulse_kind, _pulse_side, _pulse_qty = _detect_pulse(state, td)
        affected = _affected_members(pulse_kind) if pulse_kind else frozenset()

        # Update prev_mids for next tick BEFORE computing this tick's mids
        # (we want NEXT-tick detection to compare to THIS tick's mid).
        new_prev_mids: Dict[str, float] = {}

        mids: Dict[str, float] = {}
        for i, sym in enumerate(ASSETS):
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = 0.5 * (best_bid + best_ask)
            mids[sym] = mid
            new_prev_mids[sym] = mid
            alpha_i = EMA_ALPHA[i]
            if alpha_i > 0:
                key = f"fv_{sym}"
                prev = td.get(key)
                td[key] = mid if prev is None else (1.0 - alpha_i) * prev + alpha_i * mid
        td['prev_mids'] = new_prev_mids

        # Per-asset directional target
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

        # Snackpack pair signal
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

        target_int: List[int] = [0] * N_ASSETS
        for i in range(N_ASSETS):
            t = target[i]
            if t > POS_LIMIT:
                t = POS_LIMIT
            elif t < -POS_LIMIT:
                t = -POS_LIMIT
            target_int[i] = int(round(t))

        # Pulse counters for telemetry / sanity
        if pulse_kind:
            ck = f'pulse_count_{pulse_kind}'
            td[ck] = td.get(ck, 0) + 1

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

            if EMA_ALPHA[i] > 0 or i in (ASSET_IDX[SP_CHOC], ASSET_IDX[SP_VAN]):
                # Directional layer untouched (pulse gate is MM-only)
                tgt = target_int[i]
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
                # MM layer with post-pulse defensive gate
                if sym in affected:
                    # 1-tick after pulse: symmetric balanced quotes, no pos-skew
                    bid_q = ask_q = MM_BAL_QTY
                else:
                    if pos > 0:
                        bid_q, ask_q = MM_SMALL_QTY, MM_BIG_QTY
                    elif pos < 0:
                        bid_q, ask_q = MM_BIG_QTY, MM_SMALL_QTY
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
