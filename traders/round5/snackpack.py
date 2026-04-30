"""Round 5 — snackpack-only trader.

Five symbols (limit ±10 each):
    SNACKPACK_CHOCOLATE, SNACKPACK_VANILLA,
    SNACKPACK_PISTACHIO, SNACKPACK_STRAWBERRY, SNACKPACK_RASPBERRY

Edges (additive in target-position space, then clipped to ±10):
  1. Pair MR on K = CHOC + VAN. Slow OU, σ_K ~ 30-50 in-day.
     target_CHOC = target_VAN = -KAPPA_PAIR * z_K
  2. Triplet MR on K_factor = sum(loading_i * mid_i) for {PIS, STRAW, RASP}.
     target_i += -KAPPA_TRIP * loading_i * z_F
  3. Per-asset OU-MR (mid -> EMA_FV) using σ_idio for triplet, σ_total for pair.
  4. Bollinger range-position on PIS + RASP (validated -0.05..-0.16 corr in
     factor_v14 historical fit).

Execution: passive penny-jump only.
  our_bid = best_bid + 1, our_ask = best_ask - 1
  qty = sign(target - pos) * min(|target - pos|, room)
  Plus a small residual MM layer when |target - pos| <= 1, to keep skin in
  the V-pulse path (~244 fills/day; we're paid h ~ 7.5 ticks per fill).

Position-limit math uses the **starting position** (state.position[sym]),
since the exchange checks worst-case against ALL outstanding orders before
running the strategy on the next tick.

Calibration source: calibration/r5/scenario_params.json (frozen 2026-04-28).
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
SP_CHOC = "SNACKPACK_CHOCOLATE"
SP_VAN = "SNACKPACK_VANILLA"
SP_PIS = "SNACKPACK_PISTACHIO"
SP_STRAW = "SNACKPACK_STRAWBERRY"
SP_RASP = "SNACKPACK_RASPBERRY"

SNACKPACKS: Tuple[str, ...] = (SP_CHOC, SP_VAN, SP_PIS, SP_STRAW, SP_RASP)
TRIPLET: Tuple[str, ...] = (SP_PIS, SP_STRAW, SP_RASP)

POS_LIMIT = 10

# σ used for per-asset z-scoring. σ_idio for triplet (after stripping K_factor),
# σ_total for pair members (CHOC/VAN are dominated by idio anyway).
SIGMA_USE: Dict[str, float] = {
    SP_CHOC: 6.575,
    SP_VAN: 6.513,
    SP_PIS: 2.023,    # σ_idio
    SP_STRAW: 1.397,  # σ_idio
    SP_RASP: 1.957,   # σ_idio
}

# Triplet factor loadings (calibrated in calibration/r5/scenario_params.json)
LOADINGS: Dict[str, float] = {
    SP_PIS: -0.39556131996287075,
    SP_STRAW: -0.6559670557472661,
    SP_RASP: 0.6428362652522759,
}

# ---------------------------------------------------------------------------
# Tunable knobs
# ---------------------------------------------------------------------------
# EMA half-lives (ticks). Each "day" runs 10K ticks; warmup must be < ~2K.
HL_FV = 400         # per-asset fair value
HL_K = 1500         # K_pair
HL_F = 1500         # K_factor
HL_RANGE = 200      # Bollinger window for PIS+RASP

ALPHA_FV = 1.0 - 2.0 ** (-1.0 / HL_FV)
ALPHA_K = 1.0 - 2.0 ** (-1.0 / HL_K)
ALPHA_F = 1.0 - 2.0 ** (-1.0 / HL_F)

# Empirical residual stds against an EMA at HL_K=1500 ticks, fit on R5 historical
# days 2-4 (warmup-trimmed). Don't tune these by feel; they're directly observable.
#   HL  500 -> K_pair 28.7, K_factor 178.7
#   HL 1000 -> K_pair 36.9, K_factor 198.8
#   HL 1500 -> K_pair 41.9, K_factor 215.1
#   HL 2000 -> K_pair 45.4, K_factor 228.7
SIGMA_K_USE = 42.0
SIGMA_F_USE = 215.0

# Aggression knobs (units = contracts per +1σ deviation).
KAPPA_OU = 4.0      # per-asset OU-MR
KAPPA_PAIR = 5.0    # K_pair MR (applies to both CHOC and VAN equally)
KAPPA_TRIP = 6.0    # K_factor MR (per-leg = KAPPA_TRIP * |loading|)
KAPPA_RANGE = 3.0   # Bollinger pull on PIS + RASP

# z-score caps to avoid runaway position from one outlier tick.
ALPHA_CAP = 3.0

# Residual MM layer (when target is close to current position).
# v2 with MM_BIG_QTY=7 was worse (21K vs 26K) — exposing more inventory at the
# at-target case attracted adverse-selection fills. Stick with conservative
# 2/5 sizing.
MM_SMALL_QTY = 2
MM_BIG_QTY = 5

# Bollinger applies only to these two (validated edges).
RANGE_TARGETS = frozenset([SP_PIS, SP_RASP])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        try:
            td: Dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            td = {}

        # ---- 1. Read mids ---------------------------------------------------
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

        # ---- 2. Update EMAs and Bollinger window ---------------------------
        for sym, mid in mids.items():
            key = f"fv_{sym}"
            td[key] = _ema(td.get(key), mid, ALPHA_FV)

        # Bollinger: keep a rolling deque of mids for PIS + RASP only
        hist: Dict[str, List[float]] = td.get("hist", {})
        for sym in RANGE_TARGETS:
            mid = mids.get(sym)
            if mid is None:
                continue
            buf = hist.get(sym, [])
            buf.append(mid)
            if len(buf) > HL_RANGE:
                buf = buf[-HL_RANGE:]
            hist[sym] = buf
        td["hist"] = hist

        # K_pair EMA
        K = None
        if SP_CHOC in mids and SP_VAN in mids:
            K = mids[SP_CHOC] + mids[SP_VAN]
            td["ema_K"] = _ema(td.get("ema_K"), K, ALPHA_K)

        # K_factor EMA  (sum(loading * mid) for triplet members)
        F = None
        if all(s in mids for s in TRIPLET):
            F = sum(LOADINGS[s] * mids[s] for s in TRIPLET)
            td["ema_F"] = _ema(td.get("ema_F"), F, ALPHA_F)

        # ---- 3. Build per-asset target position ----------------------------
        target: Dict[str, float] = {s: 0.0 for s in SNACKPACKS}

        # 3a. Per-asset OU-MR
        for sym, mid in mids.items():
            fv = td.get(f"fv_{sym}")
            if fv is None:
                continue
            sigma = SIGMA_USE[sym]
            z = _clip((fv - mid) / sigma, -ALPHA_CAP, ALPHA_CAP)
            target[sym] += KAPPA_OU * z

        # 3b. K_pair MR — both legs same sign (basket direction)
        if K is not None and td.get("ema_K") is not None:
            z_K = _clip((K - td["ema_K"]) / SIGMA_K_USE, -ALPHA_CAP, ALPHA_CAP)
            pair_pos = -KAPPA_PAIR * z_K
            target[SP_CHOC] += pair_pos
            target[SP_VAN] += pair_pos

        # 3c. K_factor (triplet) MR
        if F is not None and td.get("ema_F") is not None:
            z_F = _clip((F - td["ema_F"]) / SIGMA_F_USE, -ALPHA_CAP, ALPHA_CAP)
            for sym in TRIPLET:
                target[sym] += -KAPPA_TRIP * LOADINGS[sym] * z_F

        # 3d. Bollinger range-pos on PIS + RASP
        for sym in RANGE_TARGETS:
            buf = hist.get(sym, [])
            if len(buf) < HL_RANGE // 2:
                continue
            mid = mids.get(sym)
            if mid is None:
                continue
            mn = min(buf)
            mx = max(buf)
            spread = mx - mn
            if spread < 1e-6:
                continue
            range_pos = (mid - mn) / spread       # 0 .. 1
            range_signal = -2.0 * (range_pos - 0.5)  # -1 .. +1
            target[sym] += KAPPA_RANGE * range_signal

        # 3e. Clip target to ±POS_LIMIT (worst-case sanity)
        target_int: Dict[str, int] = {}
        for sym in SNACKPACKS:
            t = _clip(target[sym], -POS_LIMIT, POS_LIMIT)
            target_int[sym] = int(round(t))

        # ---- 4. Generate orders --------------------------------------------
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        for sym in SNACKPACKS:
            if sym not in mids:
                continue
            od = state.order_depths.get(sym)
            if od is None:
                continue
            bb = best_bids[sym]
            ba = best_asks[sym]
            if ba - bb < 2:
                # spread is too tight to penny-jump without crossing — skip
                continue

            # IMPORTANT: use STARTING position (state.position) for limit math.
            pos = state.position.get(sym, 0)
            buy_room = POS_LIMIT - pos
            sell_room = POS_LIMIT + pos

            our_bid = bb + 1
            our_ask = ba - 1

            tgt = target_int[sym]
            diff = tgt - pos

            orders: List[Order] = []

            if diff >= 1:
                # we want to be more long -> aggressive bid, smaller passive ask
                qty_b = min(diff, buy_room)
                if qty_b > 0:
                    orders.append(Order(sym, our_bid, qty_b))
                # tiny ask to harvest opposite-direction pulses (within room)
                qty_a = min(MM_SMALL_QTY, sell_room)
                if qty_a > 0:
                    orders.append(Order(sym, our_ask, -qty_a))
            elif diff <= -1:
                # we want to be more short
                qty_a = min(-diff, sell_room)
                if qty_a > 0:
                    orders.append(Order(sym, our_ask, -qty_a))
                qty_b = min(MM_SMALL_QTY, buy_room)
                if qty_b > 0:
                    orders.append(Order(sym, our_bid, qty_b))
            else:
                # at target; pure 2-sided MM, skewed toward flattening
                if pos > 0:
                    bid_q, ask_q = MM_SMALL_QTY, MM_BIG_QTY
                elif pos < 0:
                    bid_q, ask_q = MM_BIG_QTY, MM_SMALL_QTY
                else:
                    bid_q = ask_q = MM_BIG_QTY
                bid_q = min(bid_q, buy_room)
                ask_q = min(ask_q, sell_room)
                if bid_q > 0:
                    orders.append(Order(sym, our_bid, bid_q))
                if ask_q > 0:
                    orders.append(Order(sym, our_ask, -ask_q))

            if orders:
                result[sym] = orders

        return result, 0, json.dumps(td, separators=(",", ":"))
