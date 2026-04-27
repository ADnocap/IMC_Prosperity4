"""pete_hegseth_v3 — smile dispersion + velvet-z stacking, takes-only execution.

Three-paragraph diagnosis and fix:

v2 portal: -39,802 on R4 day 3 (friend's same-data submission: +35,956). Cause
was NOT the smile signal — it was inheriting Harry_potter_v8's "always-on
passive market making" machinery on top of the smile FV. R4 day 3 trended
hard (VELVETFRUIT crashed -42 ticks, whole voucher chain followed). Passive
buy quotes filled progressively at lower marks while sell quotes never
filled — classic adverse-selection bleed across 1,811 trades.

v3 keeps the v2 smile fitter unchanged but layers it with Hagrid's velvet-z
stacking signal (a totally orthogonal alpha — directional bet on VELVETFRUIT
itself, applied to the chain via option delta) and replaces v8's passive-MM
machinery with friend's "selective takes only, no passive layers, hysteresis-
based exits" execution. Plus Hagrid_v5's loose voucher SL as path-divergence
insurance.

Per-asset routing:
  HYDROGEL          -> OBI MM            (Hagrid: +610. v2 used v8 MR -> -3,817)
  VELVETFRUIT       -> v8 MR             (v2 won +4,889 here, narrow spread, OK)
  VEV_4000, 4500    -> OBI MM            (v2 won small, keep)
  VEV_5000..5500    -> NEW: composite    (smile dev + velvet z, takes only)
  VEV_6000, 6500    -> skip              (dead)

Composite voucher signal:
  smile_dev = mid - smile_fair - mean_dev    (per-voucher dispersion, price units)
  velvet_z  = (velvet_mid - EMA) / sigma     (chain-wide directional)

  smile_dir from smile_dev with HYSTERESIS:
    if flat:   open at |dev| >= SMILE_OPEN_THR  (sign-flipped: rich -> short)
    if long:   hold while dev < -SMILE_HOLD_THR; flip if dev >= +SMILE_OPEN_THR
    if short:  hold while dev >  +SMILE_HOLD_THR; flip if dev <= -SMILE_OPEN_THR
  Vega-adjusted threshold for low-value strikes.

  velvet_dir = -sign(velvet_z) if |velvet_z| >= STACK_OPEN_Z else 0

  Compose:
    both same dir       -> CONFLUENCE_FRAC * limit                 (max position)
    velvet alone        -> VELVET_ALONE_FRAC * limit * (|delta|+0.3) (Hagrid stack)
    smile alone         -> SMILE_ALONE_FRAC  * limit                (smaller, no confirm)
    conflict / no sig   -> 0                                       (don't bet, exit)

Execution: cross-spread takes ONLY for stacked vouchers. No passive layers.
SCALP_TAKE_MAX=35 per tick caps how fast the position moves. Holds position
silently when target unchanged.

Hagrid_v5 voucher SL: per-voucher pause when MTM < -5,000 for 500 ticks AND
|pos| >= 0.80 * limit. Pauses MR + force-flatten via passive unwind. Pause
500 ticks. Designed to not fire on normal MR build-up dips.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math


HYDROGEL = "HYDROGEL_PACK"
VELVETFRUIT = "VELVETFRUIT_EXTRACT"
VEV_4000 = "VEV_4000"
VEV_4500 = "VEV_4500"
VEV_5000 = "VEV_5000"
VEV_5100 = "VEV_5100"
VEV_5200 = "VEV_5200"
VEV_5300 = "VEV_5300"
VEV_5400 = "VEV_5400"
VEV_5500 = "VEV_5500"
VEV_6000 = "VEV_6000"
VEV_6500 = "VEV_6500"

LIMITS: Dict[str, int] = {
    HYDROGEL: 200, VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

STRIKES: Dict[str, int] = {
    VEV_4000: 4000, VEV_4500: 4500,
    VEV_5000: 5000, VEV_5100: 5100, VEV_5200: 5200,
    VEV_5300: 5300, VEV_5400: 5400, VEV_5500: 5500,
    VEV_6000: 6000, VEV_6500: 6500,
}

# Hagrid's per-voucher BS deltas (for delta-sized stack targets).
DELTAS: Dict[str, float] = {
    VEV_5000: 0.654, VEV_5100: 0.577, VEV_5200: 0.437,
    VEV_5300: 0.273, VEV_5400: 0.129, VEV_5500: 0.055,
}

FALLBACK_FV: Dict[str, float] = {
    HYDROGEL: 9990.0, VELVETFRUIT: 5250.0,
    VEV_5000: 255.0, VEV_5100: 167.0, VEV_5200: 95.0,
    VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0,
}
FALLBACK_SIGMA_MID: Dict[str, float] = {
    HYDROGEL: 30.0, VELVETFRUIT: 15.0,
}

SMILE_VOUCHERS = (VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500)
OBI_MM_ASSETS = (HYDROGEL, VEV_4000, VEV_4500)


class Trader:
    # ===== VELVETFRUIT MR (v8 verbatim) =====
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01
    MR_K = 0.55
    MR_MAX_FRAC = 0.85
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 30
    MR_TAKE_Z = 1.2
    MR_TAKE_MAX = 40
    MR_TIGHT_SPREAD_MIN = 2

    # Velvet stop-loss (v8). On the spot only — the voucher SL is separate.
    STOP_LOSS_THRESHOLD = -2500
    STOP_DURATION_TICKS = 300
    STOP_POS_GATE = 0.80
    STOP_PAUSE_TICKS = 500

    # OBI tilt on velvet's MR passive layers (v8)
    MR_OBI_FACTOR = 1.0
    MR_OBI_MULT_MIN = 0.3
    MR_OBI_MULT_MAX = 1.8

    # ===== OBI MM (HYDROGEL, VEV_4000, VEV_4500) =====
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # ===== Black-Scholes smile (v2 verbatim) =====
    SMILE_A_INIT = 0.580261
    SMILE_B = 0.033704
    SMILE_C = 0.089775
    SMILE_A_ALPHA = 0.0052
    SMILE_A_MIN = 0.05
    SMILE_A_MAX = 3.0
    SMILE_IV_FLOOR = 0.05
    SESSION_TICKS = 30_000
    TICKS_PER_YEAR = 365 * 10_000
    T_YEARS_FLOOR = 1e-4
    # Friend tracks mean_dev EMA (window 100) and switch_mean = EMA(|dev-mean_dev|)
    # (window 200). Activity gate fires on switch_mean, NOT on sigma.
    SMILE_DEV_MEAN_ALPHA = 2.0 / (100 + 1)            # ~0.0198
    SMILE_DEV_SWITCH_ALPHA = 2.0 / (200 + 1)          # ~0.00995

    # ===== NEW: voucher signal logic =====
    # Smile dispersion thresholds — friend-tuned values from sub 491539.
    # Open at THR_OPEN, close to flat when (signed) dev has reverted past
    # THR_CLOSE. NOTE THR_CLOSE is NEGATIVE — this is what "lets winners run"
    # past zero before closing, capturing more of each oscillation.
    SMILE_OPEN_THR = 0.536
    SMILE_CLOSE_THR = -0.4
    LOW_VEGA_THR_ADJ = 0.653
    LOW_VEGA_CUTOFF = 4.0984

    # Velvet-z stacking thresholds (Hagrid).  TEMPORARILY DISABLED — CSV
    # showed velvet-stack adds churn, not edge. Re-enable once smile alone works.
    STACK_OPEN_Z = 99.0          # effectively off
    STACK_CLOSE_Z = 0.3

    # Composite-target sizing fractions (of LIMIT). Smile is treated as the
    # primary per-voucher signal (friend proved it works on R4 day 3); velvet
    # is a confluence modulator. We always trade in the smile direction when
    # smile fires — velvet only changes the SIZE.
    CONFLUENCE_FRAC = 0.85       # smile + velvet agree -> max position
    SMILE_ALONE_FRAC = 0.55      # smile fires, velvet silent
    SMILE_CONFLICT_FRAC = 0.30   # smile fires AGAINST velvet -> reduced but smile-side
    VOUCHER_STACK_FRAC = 0.85    # smile silent, velvet alone -> Hagrid stack

    # Take cap for stacked vouchers (no passive layers — only takes move position).
    SCALP_TAKE_MAX = 35

    # Activity gate — operates on switch_mean (MAD), matching friend's
    # IV_SCALPING_THR exactly.
    SMILE_ACTIVITY_THR = 1.0865

    # ===== Voucher loose stop-loss (Hagrid_v5) =====
    VOUCHER_STOP_THRESHOLD = -5000
    VOUCHER_STOP_DURATION = 500
    VOUCHER_STOP_POS_GATE = 0.80
    VOUCHER_STOP_PAUSE = 500

    _N = NormalDist()

    # ----------------------------------------------------------------------
    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        ts = state.timestamp

        # Compute velvet z-score ONCE (shared across velvet's own MR and the
        # voucher stacking signal).
        velvet_z, velvet_fv, velvet_sigma = self._velvet_signal(state, td)

        # Smile context for VEV_5000..5500.
        smile_ctx = self._build_smile_ctx(state, td)

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            self._accumulate_fills(td, product, state)

            if product in SMILE_VOUCHERS:
                ctx = smile_ctx.get(product)
                result[product] = self._trade_voucher_composite(
                    product, od, pos, td, ts, ctx, velvet_z)
            elif product == VELVETFRUIT:
                result[product] = self._trade_velvet(
                    od, pos, td, ts, velvet_z, velvet_fv, velvet_sigma)
            elif product in OBI_MM_ASSETS:
                result[product] = self._trade_mm(product, od, pos)
            else:
                result[product] = []  # VEV_6000/6500 dead
        return result, 0, json.dumps(td)

    # ===== Velvet signal (z-score + MR FV) =================================
    def _velvet_signal(self, state: TradingState, td: dict
                        ) -> Tuple[float, float, float]:
        od = state.order_depths.get(VELVETFRUIT)
        if not od or not od.buy_orders or not od.sell_orders:
            return 0.0, FALLBACK_FV[VELVETFRUIT], FALLBACK_SIGMA_MID[VELVETFRUIT]
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        if ba - bb < self.MR_TIGHT_SPREAD_MIN:
            return 0.0, FALLBACK_FV[VELVETFRUIT], FALLBACK_SIGMA_MID[VELVETFRUIT]
        mid = (bb + ba) / 2.0
        fv, sigma, n = self._update_ema(td, VELVETFRUIT, mid)
        if n < self.MR_MIN_N or sigma <= 0:
            return 0.0, fv, sigma
        return (mid - fv) / sigma, fv, sigma

    # ===== Smile machinery (v2 verbatim) ==================================
    def _bs_call(self, S: float, K: float, sigma: float, T: float) -> float:
        if T <= 0 or sigma <= 0 or S <= 0:
            return max(S - K, 0.0)
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        return S * self._N.cdf(d1) - K * self._N.cdf(d2)

    def _bs_vega(self, S: float, K: float, sigma: float, T: float) -> float:
        if T <= 0 or sigma <= 0 or S <= 0:
            return 0.0
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
        return S * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) * sqrtT

    def _implied_vol(self, price: float, S: float, K: float, T: float
                      ) -> Optional[float]:
        if T <= 0 or S <= 0:
            return None
        intrinsic = max(S - K, 0.0)
        if price < intrinsic - 1e-6 or price > S + 1e-6:
            return None
        lo, hi = 1e-3, 5.0
        plo = self._bs_call(S, K, lo, T) - price
        phi = self._bs_call(S, K, hi, T) - price
        if plo * phi > 0:
            return None
        for _ in range(40):
            m = 0.5 * (lo + hi)
            pm = self._bs_call(S, K, m, T) - price
            if abs(pm) < 1e-4:
                return m
            if plo * pm < 0:
                hi, phi = m, pm
            else:
                lo, plo = m, pm
        return 0.5 * (lo + hi)

    def _T_years(self, ts: int) -> float:
        ticks_remaining = max(1000, self.SESSION_TICKS - ts // 100)
        return max(self.T_YEARS_FLOOR, ticks_remaining / self.TICKS_PER_YEAR)

    def _smile_iv(self, K: int, S: float, T_years: float, smile_a: float
                   ) -> float:
        if S <= 0 or T_years <= 0:
            return smile_a
        m = math.log(K / S) / math.sqrt(T_years)
        return smile_a + self.SMILE_B * m + self.SMILE_C * m * m

    def _smile_fair(self, K: int, S: float, T_years: float, smile_a: float
                     ) -> float:
        iv = max(self.SMILE_IV_FLOOR, self._smile_iv(K, S, T_years, smile_a))
        return self._bs_call(S, K, iv, T_years)

    def _build_smile_ctx(self, state: TradingState, td: dict
                          ) -> Dict[str, dict]:
        velvet_od = state.order_depths.get(VELVETFRUIT)
        S = self._mid(velvet_od) if velvet_od else None
        if S is None or S <= 0:
            S = FALLBACK_FV[VELVETFRUIT]
        T_years = self._T_years(state.timestamp)

        observed_ivs: Dict[int, float] = {}
        voucher_mids: Dict[str, float] = {}
        for sym in SMILE_VOUCHERS:
            od = state.order_depths.get(sym)
            if not od:
                continue
            m = self._mid(od)
            if m is None or m <= 0:
                continue
            voucher_mids[sym] = m
            iv = self._implied_vol(m, S, STRIKES[sym], T_years)
            if iv is not None and 0.05 < iv < 4.5:
                observed_ivs[STRIKES[sym]] = iv

        # Friend-style: NO cold-start. Initialize smile_a to SMILE_A_INIT and
        # let the slow EMA refit it toward truth. The "wrong" initial smile
        # produces predictable dev signals that the strategy capitalises on.
        prev_a = td.get("smile_a", self.SMILE_A_INIT)
        if observed_ivs:
            residuals = []
            for K, iv_obs in observed_ivs.items():
                iv_pred = self._smile_iv(K, S, T_years, prev_a)
                residuals.append(iv_obs - iv_pred)
            avg_res = sum(residuals) / len(residuals)
            new_a = max(self.SMILE_A_MIN,
                          min(self.SMILE_A_MAX,
                              prev_a + self.SMILE_A_ALPHA * avg_res))
            td["smile_a"] = new_a
            smile_a = new_a
        else:
            smile_a = prev_a

        ctx: Dict[str, dict] = {}
        for sym in SMILE_VOUCHERS:
            m = voucher_mids.get(sym)
            if m is None:
                continue
            K = STRIKES[sym]
            fair = self._smile_fair(K, S, T_years, smile_a)
            iv_use = max(self.SMILE_IV_FLOOR,
                          self._smile_iv(K, S, T_years, smile_a))
            vega = self._bs_vega(S, K, iv_use, T_years)
            dev = m - fair

            mean_key = f"smile_mean_{sym}"
            sw_key = f"smile_switch_{sym}"
            n_key = f"smile_n_{sym}"
            prev_mean = td.get(mean_key, dev)               # init at first dev (friend-style)
            prev_sw = td.get(sw_key, 0.0)                   # init at 0 (friend-style)
            n = td.get(n_key, 0)
            new_mean = (self.SMILE_DEV_MEAN_ALPHA * dev
                          + (1 - self.SMILE_DEV_MEAN_ALPHA) * prev_mean)
            new_sw = (self.SMILE_DEV_SWITCH_ALPHA * abs(dev - new_mean)
                        + (1 - self.SMILE_DEV_SWITCH_ALPHA) * prev_sw)
            td[mean_key] = new_mean
            td[sw_key] = new_sw
            td[n_key] = n + 1

            ctx[sym] = {
                "fair": fair, "mean_dev": new_mean,
                "switch_mean": new_sw,
                "vega": vega, "n": n + 1,
            }
        return ctx

    # ===== Voucher composite signal (the heart of v3) =====================
    def _trade_voucher_composite(self, sym: str, od: OrderDepth, pos: int,
                                    td: dict, ts: int,
                                    ctx: Optional[dict],
                                    velvet_z: float) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask <= best_bid:
            return []
        mid = (best_bid + best_ask) / 2.0
        limit = LIMITS[sym]
        delta = DELTAS.get(sym, 0.0)

        # Loose voucher SL (Hagrid_v5). Pause + flatten if MTM has been below
        # threshold for DURATION ticks AND we're loaded (>= GATE * limit).
        if self._sl_active(td, sym, pos, mid, limit, ts,
                            self.VOUCHER_STOP_THRESHOLD,
                            self.VOUCHER_STOP_DURATION,
                            self.VOUCHER_STOP_POS_GATE,
                            self.VOUCHER_STOP_PAUSE):
            return self._unwind_passive(sym, pos, best_bid, best_ask)

        # ===== 1. Smile direction with hysteresis (FRIEND-STYLE bid/ask trigger) =====
        # Use best_bid for sell triggers, best_ask for buy triggers — this
        # automatically accounts for the half-spread cost of crossing. v3a's
        # mid-based trigger fired 4-5x too often on wide-spread vouchers, paying
        # spread cost > captured edge.
        # Friend-style logic: open / close / hold decisions are driven directly
        # by ACTUAL POSITION at decision time, not a separately-tracked smile_dir.
        # We compute target = pos + delta_from_open + delta_from_close and let
        # _takes_only execute. This matches friend's _iv_scalp_orders exactly
        # except we do it through the (pos, target) interface rather than emit
        # orders here.
        if ctx is None or ctx["switch_mean"] < self.SMILE_ACTIVITY_THR:
            # Activity gate: voucher pinned/dead. Force-flatten any position.
            return self._flatten(sym, od, pos)

        sell_dev = (best_bid - ctx["fair"]) - ctx["mean_dev"]
        buy_dev = (best_ask - ctx["fair"]) - ctx["mean_dev"]
        thr_open = self.SMILE_OPEN_THR
        if ctx["vega"] < self.LOW_VEGA_CUTOFF:
            thr_open += self.LOW_VEGA_THR_ADJ
        thr_close = self.SMILE_CLOSE_THR

        smile_dir = 0
        if sell_dev >= thr_open:
            smile_dir = -1                         # rich: open/add SHORT
        elif buy_dev <= -thr_open:
            smile_dir = +1                         # cheap: open/add LONG
        else:
            # No open trigger. Check close-back (friend's THR_CLOSE = -0.4).
            if pos > 0 and sell_dev >= thr_close:
                smile_dir = 0                      # close LONG
                td[f"smile_dir_{sym}"] = 0
                # Force flatten via takes
                return self._flatten(sym, od, pos)
            elif pos < 0 and buy_dev <= -thr_close:
                td[f"smile_dir_{sym}"] = 0
                return self._flatten(sym, od, pos)
            else:
                # In hold zone — keep current pos.
                td[f"smile_dir_{sym}"] = (1 if pos > 0 else (-1 if pos < 0 else 0))
                return []
        td[f"smile_dir_{sym}"] = smile_dir

        # When smile fires, target max position (friend lets each tick add up to
        # SCALP_TAKE_MAX, ramping to limit over ~9 ticks of sustained signal).
        # Velvet-z stack disabled in this version (STACK_OPEN_Z=99) — it
        # produced too much churn in CSV testing.
        target = smile_dir * limit
        return self._takes_only(sym, od, pos, target,
                                  best_bid, best_ask, bids, asks)

    def _takes_only(self, sym: str, od: OrderDepth, pos: int, target: int,
                     best_bid: int, best_ask: int,
                     bids: List[int], asks: List[int]) -> List[Order]:
        diff = target - pos
        if diff == 0:
            return []
        limit = LIMITS[sym]
        buy_room = limit - pos
        sell_room = limit + pos
        orders: List[Order] = []
        if diff > 0:
            cap = min(diff, self.SCALP_TAKE_MAX, buy_room)
            for ap in asks:
                if cap <= 0:
                    break
                vol = -od.sell_orders[ap]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(sym, ap, qty))
                cap -= qty
        else:
            cap = min(-diff, self.SCALP_TAKE_MAX, sell_room)
            for bp in bids:
                if cap <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(sym, bp, -qty))
                cap -= qty
        return orders

    def _flatten(self, sym: str, od: OrderDepth, pos: int) -> List[Order]:
        if pos == 0:
            return []
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        if pos > 0:
            return [Order(sym, bids[0], -min(pos, self.SCALP_TAKE_MAX))]
        return [Order(sym, asks[0], min(-pos, self.SCALP_TAKE_MAX))]

    # ===== VELVETFRUIT (v8 MR — passive layers + take logic) ==============
    def _trade_velvet(self, od: OrderDepth, pos: int, td: dict, ts: int,
                       z: float, fv: float, sigma: float) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.MR_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0
        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        tot = b1 + a1
        obi = 0.0 if tot == 0 else (b1 - a1) / tot
        limit = LIMITS[VELVETFRUIT]

        # Velvet stop-loss (the SAME v8 SL, distinct from voucher SL).
        if self._sl_active(td, VELVETFRUIT, pos, mid, limit, ts,
                            self.STOP_LOSS_THRESHOLD,
                            self.STOP_DURATION_TICKS,
                            self.STOP_POS_GATE,
                            self.STOP_PAUSE_TICKS):
            return self._unwind_passive(VELVETFRUIT, pos, best_bid, best_ask)

        # Continuous z-target.
        if sigma > 0:
            target_frac = max(-self.MR_MAX_FRAC,
                                min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)
        else:
            target = 0
        diff = target - pos
        buy_room = limit - pos
        sell_room = limit + pos
        buy_ord = sell_ord = 0
        orders: List[Order] = []

        # (a) Cross-spread take when |z| >= MR_TAKE_Z.
        if abs(z) >= self.MR_TAKE_Z:
            if diff > 0:
                cap = min(diff, self.MR_TAKE_MAX, buy_room)
                for ap in asks:
                    if cap <= 0:
                        break
                    vol = -od.sell_orders[ap]
                    qty = min(vol, cap)
                    if qty <= 0:
                        continue
                    orders.append(Order(VELVETFRUIT, ap, qty))
                    buy_ord += qty
                    cap -= qty
            elif diff < 0:
                cap = min(-diff, self.MR_TAKE_MAX, sell_room)
                for bp in bids:
                    if cap <= 0:
                        break
                    vol = od.buy_orders[bp]
                    qty = min(vol, cap)
                    if qty <= 0:
                        continue
                    orders.append(Order(VELVETFRUIT, bp, -qty))
                    sell_ord += qty
                    cap -= qty

        # (b) Passive 2-level layers, OBI-tilted.
        diff_after = target - (pos + buy_ord - sell_ord)
        layers = [(1, self.MR_MM_LEVEL_SIZE), (2, self.MR_MM_LEVEL_SIZE)]
        rem_buy = max(0, buy_room - buy_ord)
        rem_sell = max(0, sell_room - sell_ord)
        for offset, big_sz in layers:
            our_bid = best_bid + offset
            our_ask = best_ask - offset
            if our_bid >= our_ask:
                break
            small_sz = max(5, big_sz // 3)
            if diff_after > 0:
                mult = max(self.MR_OBI_MULT_MIN,
                            min(self.MR_OBI_MULT_MAX,
                                1.0 + self.MR_OBI_FACTOR * obi))
                b_each, a_each = int(big_sz * mult), small_sz
            elif diff_after < 0:
                mult = max(self.MR_OBI_MULT_MIN,
                            min(self.MR_OBI_MULT_MAX,
                                1.0 + self.MR_OBI_FACTOR * (-obi)))
                a_each, b_each = int(big_sz * mult), small_sz
            else:
                mult_b = max(self.MR_OBI_MULT_MIN,
                              min(self.MR_OBI_MULT_MAX,
                                  1.0 + self.MR_OBI_FACTOR * obi))
                mult_a = max(self.MR_OBI_MULT_MIN,
                              min(self.MR_OBI_MULT_MAX,
                                  1.0 + self.MR_OBI_FACTOR * (-obi)))
                b_each = int(small_sz * mult_b)
                a_each = int(small_sz * mult_a)
            bqty = min(b_each, rem_buy)
            aqty = min(a_each, rem_sell)
            if bqty > 0:
                orders.append(Order(VELVETFRUIT, our_bid, bqty))
                rem_buy -= bqty
            if aqty > 0:
                orders.append(Order(VELVETFRUIT, our_ask, -aqty))
                rem_sell -= aqty
        return orders

    # ===== OBI MM (HYDROGEL, VEV_4000, VEV_4500) ===========================
    def _trade_mm(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []
        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        total = b1 + a1
        obi = 0.0 if total == 0 else (b1 - a1) / total
        buy_size, sell_size = self._obi_sizes(obi)
        limit = LIMITS[product]
        soft_thresh = int(self.VEV_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(buy_size, max(0, buy_room))
        sell_qty = min(sell_size, max(0, sell_room))
        if pos >= soft_thresh:
            buy_qty = 0
        elif pos <= -soft_thresh:
            sell_qty = 0
        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(product, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(product, our_ask, -sell_qty))
        return orders

    def _obi_sizes(self, obi: float) -> Tuple[int, int]:
        a = abs(obi)
        if a < self.OBI_SKEW_1:
            return (self.VEV_BASE_SIZE, self.VEV_BASE_SIZE)
        if a < self.OBI_SKEW_2:
            big, small = self.VEV_SIZES_MILD
        elif a < self.OBI_SKEW_3:
            big, small = self.VEV_SIZES_STRONG
        else:
            big, small = self.VEV_SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)

    # ===== Stop-loss helper (parameterised, used for both velvet + voucher) =
    def _sl_active(self, td: dict, product: str, pos: int, mid: float,
                    limit: int, ts: int, threshold: float, duration: int,
                    gate: float, pause: int) -> bool:
        pnl = td.get(f"cash_{product}", 0.0) + pos * mid
        below_key = f"below_ticks_{product}"
        below = td.get(below_key, 0)
        below = below + 1 if pnl < threshold else 0
        td[below_key] = below
        pause_until = td.get(f"pause_until_{product}", -1)
        pos_gate_met = abs(pos) >= int(gate * limit)
        if (below >= duration and pos_gate_met and pause_until < ts):
            td[f"pause_until_{product}"] = ts + pause
            return True
        return pause_until >= ts

    # ===== Fill / MTM tracking ============================================
    def _accumulate_fills(self, td: dict, product: str,
                           state: TradingState) -> None:
        key_cash = f"cash_{product}"
        key_last_ts = f"ot_ts_{product}"
        cash = td.get(key_cash, 0.0)
        last_ts = td.get(key_last_ts, -1)
        trades = (state.own_trades or {}).get(product, []) or []
        for t in trades:
            if t.timestamp <= last_ts:
                continue
            qty = abs(int(t.quantity))
            if t.buyer == "SUBMISSION":
                cash -= t.price * qty
            elif t.seller == "SUBMISSION":
                cash += t.price * qty
            if t.timestamp > last_ts:
                last_ts = t.timestamp
        td[key_cash] = cash
        td[key_last_ts] = last_ts

    # ===== EMA helpers (for velvet's MR) ==================================
    def _update_ema(self, td: dict, product: str, mid: float
                     ) -> Tuple[float, float, int]:
        ema_key = f"ema_{product}"
        var_key = f"var_{product}"
        n_key = f"n_{product}"
        prev_ema = td.get(ema_key)
        prev_var = td.get(var_key,
                            FALLBACK_SIGMA_MID.get(product, 30.0) ** 2)
        n = td.get(n_key, 0)
        if prev_ema is None:
            prev_ema = FALLBACK_FV.get(product, mid)
        residual = mid - prev_ema
        new_ema = prev_ema + self.EMA_ALPHA * residual
        new_var = prev_var + self.VAR_ALPHA * (residual * residual - prev_var)
        new_n = n + 1
        td[ema_key] = new_ema
        td[var_key] = max(1.0, new_var)
        td[n_key] = new_n
        sigma = max(1.0, new_var) ** 0.5
        return new_ema, sigma, new_n

    def _unwind_passive(self, product: str, pos: int,
                          best_bid: int, best_ask: int) -> List[Order]:
        orders: List[Order] = []
        if pos > 0:
            qty = min(pos, 30)
            if best_ask - 1 > best_bid:
                orders.append(Order(product, best_ask - 1, -qty))
        elif pos < 0:
            qty = min(-pos, 30)
            if best_bid + 1 < best_ask:
                orders.append(Order(product, best_bid + 1, qty))
        return orders

    # ===== Helpers ========================================================
    def _mid(self, od: OrderDepth) -> Optional[float]:
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        return (bids[0] + asks[0]) / 2.0

    @staticmethod
    def _parse_td(s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}