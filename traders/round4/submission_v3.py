"""DO-NOT-SHIP — V3 prototype: V2 + L2 Mark-flow directional layer (KILLED).

Status: KILLED 2026-04-27. L2 cannot beat V2 in either form tested.

L2 signal generator: Mark 01 (informed +2.05/+2.73 buyer/seller) and Mark 55
(adverse fade -1.62/-1.36) net flow on VELVETFRUIT over a 200-tick window.

Two execution variants tested vs V2 +29,934 R4 replay (--merge-pnl):

  V3a — REPLACE _trade_mr on VELVET when L2 fires (size 30, vouchers 0):
        Total +21,446 (D1 10,247 / D2 2,364 / D3 8,835). Δ vs V2 = -8,488.
        Replacing _trade_mr loses stratton MR alpha (+3,577 V2 baseline).

  V3a-bigger — vouchers up to ±100 too:
        Total -2,283,961 (D1 -787K / D2 -759K / D3 -738K). Catastrophic
        churn vs IV-scalp close-back. Per-leg whip-saw on 200t hold.

  V3b — ADDITIVELY BIAS _trade_mr's target by L2_DIR * 30 (no replacement):
        Total +26,102 (D1 14,646 / D2 2,713 / D3 8,743). Δ vs V2 = -3,832.
        D3 is the killer: VELVET D3 -810 vs V2 +2,759 (Δ -3,569). Same as
        marks_a kill verdict — net long-tilt fights D3 choppy tape.

Conclusions (consistent with marks_a..d, marks_only kill verdicts):
  - V2 already captures Mark counterparty signal via penny-jump MM and
    stratton MR. Explicit Mark layer just re-routes the same edge through
    a worse executor.
  - VELVET drift (~2 ticks) ≤ half-spread (2.5 ticks) → take economics
    fail.
  - 200t-hold position-builder loses to adverse selection on regime
    shifts (D3 specifically).

V2 baseline figures retained for reference:
    R3 stratton baseline:        +20,954 (D1 14,100 / D2  406  / D3  6,448)
    submission.py (V1):          +27,444 (D1 14,961 / D2  582  / D3 11,901)
    V2 (tuned IV-scalp):         +29,934 (D1 14,675 / D2 2,946 / D3 12,312)

Layers:
  HYDROGEL                  -> stratton _trade_vev_mm  (porush handler returned
                                                        0 PnL in replay)
  VELVETFRUIT               -> stratton _trade_mr      (slow EMA, tiny MR_K)
  VEV_5000..VEV_5500        -> stratton MR/MM baseline
                               + NEW Timo IV-deviation scalping (priority)
  VEV_4000/VEV_4500/5500    -> stratton _trade_vev_mm  (no porush BASE_MM
                                                        floor that bled VEV_4000)
  VEV_6000/VEV_6500         -> skip (pinned at 0/1)
  Cross-strike spread MR    -> DISABLED (cost -37k in replay; can't reconcile
                                          audit's +11k vs replay -3k for 5200/5400)
  Counterparty IDs          -> NOT YET USED (R4 baseline first)

IV-scalping (analysis/round4/bachelier_vs_bs.md, audited 2026-04-26):
  - BS smile, m = log(K/S)/sqrt(T_years), dynamic T from session timestamp,
    online EMA refit of smile_a (curvature b,c stable across days, level a
    drifts 0.41 -> 0.88 day-to-day).
  - Per voucher: dev = mid - bs_fair, mean_dev EMA, switch_mean = EMA(|dev-mean|).
    Activity gate switch_mean >= 0.7. Open when |dev - mean| > THR_OPEN=0.5
    (sell at best_bid / buy at best_ask). Close on signal-flip through 0.
  - Diagnostic on R4 day-1 confirmed signal direction: post-fire mid drift
    -7 to -12 XIRECs at horizon 200 across all 6 strikes (+17k per-fire PnL
    if executed in isolation).

Diagnostic toggles below let us reactivate the rejected layers for future
experiments without re-rolling the file.

Lineage:
  stratton (R3 search-2 #233): portal +11,140  passive MM (saved as round4/stratton.py)
  porush   (R3 search-4 #119): MC +11,774      adds HYDROGEL handler (broken in replay)
  wolf     (porush + CS):      MC +6,157       adds CS spread MR
  THIS:                        replay +27,444  IV-scalp on stratton, CS off, HYDROGEL=stratton
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

FALLBACK_FV: Dict[str, float] = {VELVETFRUIT: 5250.0, VEV_5000: 255.0,
                                  VEV_5100: 167.0, VEV_5200: 95.0,
                                  VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0}
FALLBACK_SIGMA: Dict[str, float] = {VELVETFRUIT: 15.0, VEV_5000: 14.0,
                                     VEV_5100: 13.0, VEV_5200: 10.0,
                                     VEV_5300: 6.0, VEV_5400: 3.4, VEV_5500: 1.7}

MR_ONLY_ASSETS = (VELVETFRUIT,)
VEV_MM_ASSETS = (VEV_4000, VEV_4500)
SCALP_VOUCHERS = (VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500)
SCALP_FALLBACK_HANDLER = {
    VEV_5000: "mr",
    VEV_5100: "mr",
    VEV_5200: "mr",
    VEV_5300: "mr",
    VEV_5400: "mr",
    VEV_5500: "mm",
}
STRIKES = {
    VEV_4000: 4000, VEV_4500: 4500,
    VEV_5000: 5000, VEV_5100: 5100, VEV_5200: 5200, VEV_5300: 5300,
    VEV_5400: 5400, VEV_5500: 5500, VEV_6000: 6000, VEV_6500: 6500,
}

# === Cross-strike spread MR pairs (per analysis/round3/final_audit.md sec 7).
# 3-day historical replay PnL totals (size shown):
#   (5200, 5400) size 30: +11,265 over 3 days, 436 trades, all days +
#   (5300, 5400) size 40: +4,540  over 3 days, 101 trades, all days +
#   (5300, 5500) size 20: +3,470  over 3 days, 176 trades, all days +
CS_PAIRS: List[Tuple[str, str, int]] = [
    (VEV_5200, VEV_5400, 30),
    (VEV_5300, VEV_5400, 40),
    (VEV_5300, VEV_5500, 20),
]

# Diagnostic toggle - when False, skip cross-strike layer entirely so we
# can attribute PnL impact of IV-scalping in isolation.
CS_LAYER_ENABLED = False

# Diagnostic toggle - when False, route HYDROGEL through stratton's OBI MM
# handler (which makes +8,861 in R4 replay) instead of porush's _trade_hydrogel
# handler (which silently produces 0 PnL in prosperity3bt replay).
HYDROGEL_PORUSH_HANDLER = False

# Diagnostic toggle - when False, use stratton's lean BASE_MM_SIZE behavior
# for VEV_4000/4500 (search-2 baseline, no porush 37-lot floor).
VEV_MM_BASE_SIZE_FLOOR = False

# === L2: Mark-flow leveraged directional layer ===========================
# Enable/disable L2 entirely. Default False after KILL verdict 2026-04-27;
# flip to True only to reproduce the negative-result diagnostic runs.
L2_ENABLED = False

# Marks tracked for the VELVET signal. Mark 01 is informed (follow direction);
# Mark 55 is adverse / fade (sign-flipped contribution to the net signal).
L2_INFORMED_MARK = "Mark 01"
L2_ADVERSE_MARK = "Mark 55"


class Trader:
    # === BS smile (analysis/round4/bachelier_vs_bs.md, audited 2026-04-26) =
    # iv = a + b*m + c*m^2 with m = log(K/S) / sqrt(T_years).
    # b, c stable across the 3 R3 days; a drifts 0.41 -> 0.50 -> 0.88.
    # Trader refits `a` online via EMA over per-tick avg residual.
    SMILE_A_INIT = 0.580261
    SMILE_B = 0.033704
    SMILE_C = 0.089775
    SMILE_A_ALPHA = 0.0052          # V2-tuned (was 0.01) - slower a refit

    # Time convention: assume "this is day 0" each session (we cannot tell
    # which day the portal feeds us). T_years constant-bias is absorbed by
    # the IV-scalp EMA, so this is robust.
    SESSION_TICKS = 30_000          # 3 days * 10K
    TICKS_PER_YEAR = 365 * 10_000   # = 3_650_000
    T_YEARS_FLOOR = 1e-4

    # === IV-deviation scalping (Timo style, p3_options_reference.md sec 3b) =
    # V2-tuned (2026-04-26): 80 random + 60 neighborhood probes; gated by
    # holdout D3 PnL >= V1 baseline. Total +29,934 (V1 +27,444).
    THEO_NORM_WINDOW = 100          # unchanged
    IV_SCALPING_WINDOW = 200        # V2 (was 100) - slower switch_mean EMA
    THR_OPEN = 0.536                # V2 (was 0.5)
    THR_CLOSE = -0.4                # V2 (was 0.0) - much more aggressive close;
                                    # let runners run instead of flipping at 0
    IV_SCALPING_THR = 1.0865        # V2 (was 0.7) - higher activity gate
    LOW_VEGA_THR_ADJ = 0.653        # V2 (was 0.5)
    LOW_VEGA_CUTOFF = 4.0984        # V2 (was 1.0) - more strikes get extra thr
    SCALP_MAX_PER_TICK = 35         # V2 (was 60) - smaller ladder cuts pinning

    # === Cross-strike spread MR ===========================================
    CS_K_SIGMA = 1.5                # lowered from wolf 2.0 (correct std)
    CS_HOLD_TICKS = 30
    CS_DEV_STD_FALLBACK = 1.0
    CS_TAKE_MAX_PER_TICK = 6
    CS_PASSIVE_SIZE = 10

    # === Porush (search-4 OOS winner) HYDROGEL params (locked) ============
    HY_OBI_THRESH = 0.11598037104847925
    HY_OBI_SKEW_TICKS = 1
    HY_OBI_SIZE_K_CONF = 1.0
    HY_OBI_SIZE_MAX = 97
    HY_OBI_SIZE_MIN = 5
    HY_MM_BASE_SIZE = 54
    HY_REVZ_WINDOW = 385
    HY_REVZ_THRESHOLD = 2.0
    HY_REVZ_OBI_GATE = 0.08054351512797084
    HY_REVZ_TAKE_SIZE = 22
    HY_REVZ_HOLD = 446
    HY_SOFT_POS_FRAC = 0.43174743324315
    HY_TIGHT_SPREAD_MIN = 2

    # === Stratton/porush MR + OBI MM params (locked) ======================
    EMA_ALPHA = 4.308428675778431e-05
    VAR_ALPHA = 0.03588256506509171
    MR_K = 0.04481152690538941
    MR_MAX_FRAC = 0.4925933073268412
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 13
    MR_MM_LEVELS = 1
    MR_TAKE_Z = 4.217298810150091
    MR_TAKE_MAX = 48
    MR_TIGHT_SPREAD_MIN = 2
    DISABLE_TAKES = True
    OBI_CONFIRM_TAKE = True

    VEV_BASE_SIZE = 3
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.17962297493671575
    OBI_SKEW_2 = 0.4541715247701739
    OBI_SKEW_3 = 0.7103899562397099
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    OBI_SKEW_T1_THRESH = 0.08480914085182328
    OBI_SKEW_T2_THRESH = 0.7984188975781722
    OBI_SKEW_T1_TICKS = 0
    OBI_SKEW_T2_TICKS = 2
    BASE_MM_SIZE = 37

    # === L2 — Mark-flow leveraged directional layer params =================
    # Window over which we accumulate Mark 01 / Mark 55 net flow on VELVET.
    L2_FLOW_WINDOW = 200          # ticks
    # Net imbalance (lots) needed to open. Mark 01 + Mark 55 average ~5
    # trades/200t each on VELVET, ~25 lots each, so net 30 is ~1 sigma.
    L2_OPEN_THR = 60
    # Close when |signal| falls below this (signal weakened or flipped).
    L2_CLOSE_THR = 15
    # Hard time-stop. Drift horizon was 200t in mark_profiles; we hold a
    # bit longer to capture full reversion.
    L2_HOLD_MAX = 200
    # Per-tick build/unwind cap (lots per asset).
    L2_MAX_PER_TICK = 8
    # Max position per asset when L2 fires (delta-weighted leverage).
    # SMALL prototype sizes to validate signal direction first; ramp later.
    L2_VELVET_SIZE = 30
    L2_VEV_5000_SIZE = 0          # vouchers OFF in v3-mini until VELVET works
    L2_VEV_5100_SIZE = 0
    L2_VEV_5200_SIZE = 0
    L2_VEV_5300_SIZE = 0
    # When True, L2 will use a voucher only if V2 IV-scalp is *not* fresh-
    # firing on it (per-strike gate). V2 IV-scalp keeps priority either way
    # for THE SAME TICK; L2 just doesn't fight it.
    L2_RESPECT_IV_SCALP = True

    MAF_BID = 500

    _N = NormalDist()

    def bid(self) -> int:
        return int(self.MAF_BID)

    # === BS pricing & IV inversion ========================================
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
        if T <= 0:
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
            mid = 0.5 * (lo + hi)
            pm = self._bs_call(S, K, mid, T) - price
            if abs(pm) < 1e-4:
                return mid
            if plo * pm < 0:
                hi, phi = mid, pm
            else:
                lo, plo = mid, pm
        return 0.5 * (lo + hi)

    def _T_years(self, ts: int) -> float:
        ticks_remaining = max(1000, self.SESSION_TICKS - ts // 100)
        return max(self.T_YEARS_FLOOR, ticks_remaining / self.TICKS_PER_YEAR)

    def _smile_iv(self, K: int, S: float, T_years: float, smile_a: float) -> float:
        if S <= 0 or T_years <= 0:
            return smile_a
        m = math.log(K / S) / math.sqrt(T_years)
        return smile_a + self.SMILE_B * m + self.SMILE_C * m * m

    def _smile_fair(self, K: int, S: float, T_years: float, smile_a: float) -> float:
        iv = max(0.05, self._smile_iv(K, S, T_years, smile_a))
        return self._bs_call(S, K, iv, T_years)

    # === Market state ======================================================
    def _build_market_ctx(self, state: TradingState, td: dict
                           ) -> Dict[str, dict]:
        """Compute per-voucher fair, dev, mean_dev, switch_mean. Refit
        smile_a online from observed IVs across the 6 core strikes.
        Returns ctx[symbol] -> {S, T, fair, dev, mean_dev, switch_mean,
                                vega, iv, mid}.
        """
        ctx: Dict[str, dict] = {}
        velvet_od = state.order_depths.get(VELVETFRUIT)
        S = self._mid(velvet_od) if velvet_od else None
        if S is None or S <= 0:
            S = FALLBACK_FV[VELVETFRUIT]
        T_years = self._T_years(state.timestamp)

        observed_ivs: Dict[int, float] = {}
        mids: Dict[str, float] = {}
        for sym in SCALP_VOUCHERS:
            od = state.order_depths.get(sym)
            if not od:
                continue
            mid = self._mid(od)
            if mid is None or mid <= 0:
                continue
            mids[sym] = mid
            iv = self._implied_vol(mid, S, STRIKES[sym], T_years)
            if iv is not None and 0.05 < iv < 4.5:
                observed_ivs[STRIKES[sym]] = iv

        prev_a = td.get("smile_a", self.SMILE_A_INIT)
        if observed_ivs:
            residuals = []
            for K, iv_obs in observed_ivs.items():
                iv_pred = self._smile_iv(K, S, T_years, prev_a)
                residuals.append(iv_obs - iv_pred)
            avg_res = sum(residuals) / len(residuals)
            new_a = prev_a + self.SMILE_A_ALPHA * avg_res
            new_a = max(0.05, min(3.0, new_a))
            td["smile_a"] = new_a
            smile_a = new_a
        else:
            smile_a = prev_a

        for sym in SCALP_VOUCHERS:
            mid = mids.get(sym)
            if mid is None:
                continue
            K = STRIKES[sym]
            fair = self._smile_fair(K, S, T_years, smile_a)
            iv_use = max(0.05, self._smile_iv(K, S, T_years, smile_a))
            vega = self._bs_vega(S, K, iv_use, T_years)
            dev = mid - fair

            mean_key = f"theo_mean_{sym}"
            sw_key = f"switch_mean_{sym}"
            prev_mean = td.get(mean_key, dev)
            alpha_m = 2.0 / (self.THEO_NORM_WINDOW + 1)
            new_mean = alpha_m * dev + (1 - alpha_m) * prev_mean
            td[mean_key] = new_mean
            prev_sw = td.get(sw_key, 0.0)
            alpha_s = 2.0 / (self.IV_SCALPING_WINDOW + 1)
            new_sw = alpha_s * abs(dev - new_mean) + (1 - alpha_s) * prev_sw
            td[sw_key] = new_sw
            ctx[sym] = {
                "S": S, "T": T_years, "fair": fair, "dev": dev,
                "mean_dev": new_mean, "switch_mean": new_sw,
                "vega": vega, "iv": iv_use, "mid": mid,
            }
        ctx["__S__"] = {"S": S, "T": T_years, "smile_a": smile_a}
        return ctx

    # === IV-deviation scalping (Timo) =====================================
    def _iv_scalp_orders(self, sym: str, od: OrderDepth, pos: int,
                          ctx: Dict[str, dict]) -> Tuple[List[Order], bool]:
        """Returns (orders, fired). When fired, caller skips other handlers
        for this voucher (we own the inventory decision)."""
        info = ctx.get(sym)
        if not info:
            return [], False
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return [], False
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < 1:
            return [], False

        fair = info["fair"]
        mean_dev = info["mean_dev"]
        switch_mean = info["switch_mean"]
        vega = info["vega"]
        limit = LIMITS[sym]
        buy_room = limit - pos
        sell_room = limit + pos

        # Activity gate: only scalp if recent vol-of-deviation is large enough
        # to expect signal > noise. Pinned vouchers fail this gate.
        if switch_mean < self.IV_SCALPING_THR:
            # Force-flatten residual position if we previously took one
            orders: List[Order] = []
            if pos > 0:
                qty = min(pos, sell_room)
                if qty > 0:
                    orders.append(Order(sym, best_bid, -qty))
            elif pos < 0:
                qty = min(-pos, buy_room)
                if qty > 0:
                    orders.append(Order(sym, best_ask, qty))
            return orders, bool(orders)

        thr = self.THR_OPEN + (self.LOW_VEGA_THR_ADJ
                                if vega <= self.LOW_VEGA_CUTOFF else 0.0)
        # Timo's exact trigger:
        #   sell @ best_bid when (best_bid - fair) - mean_dev >= thr
        #   buy  @ best_ask when (best_ask - fair) - mean_dev <= -thr
        sell_dev = (best_bid - fair) - mean_dev
        buy_dev = (best_ask - fair) - mean_dev

        orders: List[Order] = []
        fired = False
        if sell_dev >= thr and sell_room > 0:
            qty = min(self.SCALP_MAX_PER_TICK, sell_room,
                       od.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(sym, best_bid, -qty))
                fired = True
        elif buy_dev <= -thr and buy_room > 0:
            qty = min(self.SCALP_MAX_PER_TICK, buy_room,
                       -od.sell_orders[best_ask])
            if qty > 0:
                orders.append(Order(sym, best_ask, qty))
                fired = True

        # Close-back logic: when dev has reverted past THR_CLOSE relative to
        # mean_dev, unwind the existing position.
        sell_close_dev = (best_bid - fair) - mean_dev
        buy_close_dev = (best_ask - fair) - mean_dev
        if not fired:
            if pos > 0 and sell_close_dev >= self.THR_CLOSE:
                qty = min(pos, sell_room, od.buy_orders[best_bid])
                if qty > 0:
                    orders.append(Order(sym, best_bid, -qty))
                    fired = True
            elif pos < 0 and buy_close_dev <= -self.THR_CLOSE:
                qty = min(-pos, buy_room, -od.sell_orders[best_ask])
                if qty > 0:
                    orders.append(Order(sym, best_ask, qty))
                    fired = True
        return orders, fired

    # === Cross-strike spread MR ==========================================
    def _cross_strike_targets(self, state: TradingState, td: dict, S: float,
                               ctx: Dict[str, dict]) -> Dict[str, int]:
        targets: Dict[str, int] = {}
        T_years = ctx.get("__S__", {}).get("T", self._T_years(state.timestamp))
        smile_a = ctx.get("__S__", {}).get("smile_a", self.SMILE_A_INIT)
        for low_sym, high_sym, spread_size in CS_PAIRS:
            od_low = state.order_depths.get(low_sym)
            od_high = state.order_depths.get(high_sym)
            if not od_low or not od_high:
                continue
            mid_low = self._mid(od_low)
            mid_high = self._mid(od_high)
            if mid_low is None or mid_high is None:
                continue
            theo_low = self._smile_fair(STRIKES[low_sym], S, T_years, smile_a)
            theo_high = self._smile_fair(STRIKES[high_sym], S, T_years, smile_a)
            mkt_spread = mid_low - mid_high
            theo_spread = theo_low - theo_high
            dev = mkt_spread - theo_spread

            std_key = f"cs_var_{low_sym}_{high_sym}"
            mean_key = f"cs_mean_{low_sym}_{high_sym}"
            prev_mean = td.get(mean_key, 0.0)
            prev_var = td.get(std_key, self.CS_DEV_STD_FALLBACK ** 2)
            new_mean = 0.99 * prev_mean + 0.01 * dev
            new_var = 0.98 * prev_var + 0.02 * (dev - new_mean) ** 2
            td[mean_key] = new_mean
            td[std_key] = max(0.25, new_var)
            std = max(0.5, new_var ** 0.5)
            z = (dev - new_mean) / std

            tgt = 0
            if z > self.CS_K_SIGMA:
                tgt = -spread_size
            elif z < -self.CS_K_SIGMA:
                tgt = +spread_size
            if tgt != 0:
                targets[low_sym] = targets.get(low_sym, 0) + tgt
                targets[high_sym] = targets.get(high_sym, 0) - tgt
        return targets

    def _trade_cross_strike_target(self, sym: str, od: OrderDepth, pos: int,
                                    target: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        limit = LIMITS[sym]
        target = max(-limit, min(limit, target))
        diff = target - pos
        buy_room = limit - pos
        sell_room = limit + pos
        orders: List[Order] = []
        if diff > 0:
            cap = min(diff, self.CS_TAKE_MAX_PER_TICK, buy_room)
            for ap in asks:
                if cap <= 0:
                    break
                vol = -od.sell_orders[ap]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(sym, ap, qty))
                cap -= qty
        elif diff < 0:
            cap = min(-diff, self.CS_TAKE_MAX_PER_TICK, sell_room)
            for bp in bids:
                if cap <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(sym, bp, -qty))
                cap -= qty

        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid < our_ask:
            if diff > 0:
                bsize, asize = self.CS_PASSIVE_SIZE, max(2, self.CS_PASSIVE_SIZE // 3)
            elif diff < 0:
                bsize, asize = max(2, self.CS_PASSIVE_SIZE // 3), self.CS_PASSIVE_SIZE
            else:
                bsize = asize = max(2, self.CS_PASSIVE_SIZE // 2)
            taken_buy = sum(o.quantity for o in orders if o.quantity > 0)
            taken_sell = -sum(o.quantity for o in orders if o.quantity < 0)
            rem_buy = max(0, buy_room - taken_buy)
            rem_sell = max(0, sell_room - taken_sell)
            bqty = min(bsize, rem_buy)
            aqty = min(asize, rem_sell)
            if bqty > 0:
                orders.append(Order(sym, our_bid, bqty))
            if aqty > 0:
                orders.append(Order(sym, our_ask, -aqty))
        return orders

    # === L2 — Mark-flow signal & target executor ==========================
    def _l2_update_flow(self, state: TradingState, td: dict) -> int:
        """Update the rolling Mark 01 / Mark 55 flow buffer on VELVETFRUIT
        and return the net signed signal (positive = bullish)."""
        buf: List[List] = td.get("l2_flow", [])
        ts = state.timestamp
        velvet_trades = (state.market_trades or {}).get(VELVETFRUIT, []) or []
        for tr in velvet_trades:
            buyer = getattr(tr, "buyer", None)
            seller = getattr(tr, "seller", None)
            qty = abs(int(getattr(tr, "quantity", 0) or 0))
            if qty <= 0:
                continue
            t_ts = int(getattr(tr, "timestamp", ts) or ts)
            if buyer == L2_INFORMED_MARK:
                buf.append([t_ts, +qty])               # follow informed buy
            elif seller == L2_INFORMED_MARK:
                buf.append([t_ts, -qty])               # follow informed sell
            elif buyer == L2_ADVERSE_MARK:
                buf.append([t_ts, -qty])               # fade adverse buy
            elif seller == L2_ADVERSE_MARK:
                buf.append([t_ts, +qty])               # fade adverse sell
        # Prune entries older than L2_FLOW_WINDOW ticks (timestamp step = 100).
        cutoff = ts - self.L2_FLOW_WINDOW * 100
        buf = [e for e in buf if e[0] >= cutoff]
        td["l2_flow"] = buf
        return sum(e[1] for e in buf)

    def _l2_decide_dir(self, td: dict, signal: int, ts: int) -> int:
        """Open / hold / close logic. Returns the active direction (+1, 0, -1)."""
        cur_dir = int(td.get("l2_dir", 0))
        opened_ts = int(td.get("l2_opened_ts", -1))
        # Time-stop
        if cur_dir != 0 and opened_ts >= 0:
            age_ticks = (ts - opened_ts) // 100
            if age_ticks >= self.L2_HOLD_MAX:
                cur_dir = 0
                td["l2_dir"] = 0
                td["l2_opened_ts"] = -1
                return 0
        # Close on signal weakening / flip
        if cur_dir > 0 and signal < self.L2_CLOSE_THR:
            cur_dir = 0
            td["l2_dir"] = 0
            td["l2_opened_ts"] = -1
            return 0
        if cur_dir < 0 and signal > -self.L2_CLOSE_THR:
            cur_dir = 0
            td["l2_dir"] = 0
            td["l2_opened_ts"] = -1
            return 0
        # Open
        if cur_dir == 0:
            if signal >= self.L2_OPEN_THR:
                td["l2_dir"] = +1
                td["l2_opened_ts"] = ts
                return +1
            if signal <= -self.L2_OPEN_THR:
                td["l2_dir"] = -1
                td["l2_opened_ts"] = ts
                return -1
        return cur_dir

    def _l2_targets(self, l2_dir: int) -> Dict[str, int]:
        """Per-asset target position given the active L2 direction."""
        if l2_dir == 0:
            return {VELVETFRUIT: 0, VEV_5000: 0, VEV_5100: 0,
                    VEV_5200: 0, VEV_5300: 0}
        s = l2_dir
        return {
            VELVETFRUIT: s * self.L2_VELVET_SIZE,
            VEV_5000:    s * self.L2_VEV_5000_SIZE,
            VEV_5100:    s * self.L2_VEV_5100_SIZE,
            VEV_5200:    s * self.L2_VEV_5200_SIZE,
            VEV_5300:    s * self.L2_VEV_5300_SIZE,
        }

    def _trade_l2_target(self, product: str, od: OrderDepth, pos: int,
                          target: int) -> List[Order]:
        """Passive-first executor: penny-jump quote on the side that closes
        the gap, gentle take only on the closing side if cap allows.
        Reuses the same shape as _trade_cross_strike_target but L2-tuned
        (larger MAX_PER_TICK on the take, larger passive size)."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < 1:
            return []
        limit = LIMITS[product]
        target = max(-limit, min(limit, target))
        diff = target - pos
        buy_room = limit - pos
        sell_room = limit + pos
        orders: List[Order] = []

        # Take side gets a small budget per tick (use only if spread small).
        spread = best_ask - best_bid
        take_cap_per_tick = self.L2_MAX_PER_TICK if spread <= 4 else 0

        if diff > 0:
            cap = min(diff, take_cap_per_tick, buy_room)
            for ap in asks:
                if cap <= 0:
                    break
                vol = -od.sell_orders[ap]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(product, ap, qty))
                cap -= qty
        elif diff < 0:
            cap = min(-diff, take_cap_per_tick, sell_room)
            for bp in bids:
                if cap <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(product, bp, -qty))
                cap -= qty

        # Passive penny-jump on the side we still need.
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid < our_ask:
            taken_buy = sum(o.quantity for o in orders if o.quantity > 0)
            taken_sell = -sum(o.quantity for o in orders if o.quantity < 0)
            rem_buy = max(0, buy_room - taken_buy)
            rem_sell = max(0, sell_room - taken_sell)
            big = self.L2_MAX_PER_TICK
            small = max(2, big // 4)
            if diff > 0:
                bqty, aqty = min(big, rem_buy), min(small, rem_sell)
            elif diff < 0:
                bqty, aqty = min(small, rem_buy), min(big, rem_sell)
            else:
                bqty = min(small, rem_buy)
                aqty = min(small, rem_sell)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
        return orders

    # === Run loop =========================================================
    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        result: Dict[str, List[Order]] = {}

        ctx = self._build_market_ctx(state, td)
        S = ctx.get("__S__", {}).get("S", FALLBACK_FV[VELVETFRUIT])
        if CS_LAYER_ENABLED:
            cs_targets = self._cross_strike_targets(state, td, S, ctx)
        else:
            cs_targets = {}

        # L2 — Mark-flow signal + targets ----------------------------------
        if L2_ENABLED:
            l2_signal = self._l2_update_flow(state, td)
            l2_dir = self._l2_decide_dir(td, l2_signal, state.timestamp)
            l2_targets = self._l2_targets(l2_dir)
        else:
            l2_dir = 0
            l2_targets = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            l2_tgt = l2_targets.get(product, 0)
            if product == HYDROGEL:
                if HYDROGEL_PORUSH_HANDLER:
                    result[product] = self._trade_hydrogel(od, pos, td)
                else:
                    result[product] = self._trade_vev_mm(product, od, pos)
            elif product in SCALP_VOUCHERS:
                # Priority 1: IV-scalping (Timo) — keeps top priority
                scalp_orders, fired = self._iv_scalp_orders(product, od, pos, ctx)
                if fired:
                    result[product] = scalp_orders
                elif l2_tgt != 0 and product in l2_targets:
                    # Priority 1.5: L2 directional position (only while
                    # L2 is actively targeting; on close, residual
                    # inventory bleeds off through MR/MM naturally
                    # so we don't fight a future IV-scalp fire).
                    result[product] = self._trade_l2_target(
                        product, od, pos, l2_tgt)
                else:
                    # Priority 2: cross-strike target (currently disabled)
                    target = cs_targets.get(product, 0)
                    if target != 0:
                        result[product] = self._trade_cross_strike_target(
                            product, od, pos, target)
                    else:
                        # Priority 3: fallback MR or MM (matches wolf)
                        fallback = SCALP_FALLBACK_HANDLER[product]
                        if fallback == "mr":
                            result[product] = self._trade_mr(product, od, pos, td)
                        else:
                            result[product] = self._trade_vev_mm(product, od, pos)
            elif product in MR_ONLY_ASSETS:
                # L2 *additively biases* _trade_mr's target rather than
                # replacing it — preserves stratton MR alpha while tilting
                # the resting target by the Mark-flow signal.
                offset = l2_tgt if product == VELVETFRUIT else 0
                result[product] = self._trade_mr(
                    product, od, pos, td, target_offset=offset)
            elif product in VEV_MM_ASSETS:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    # === Helpers (ported from wolf) ======================================
    def _obi_skewed_quotes(self, best_bid: int, best_ask: int, obi: float
                            ) -> Tuple[int, int]:
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        a = abs(obi)
        if a >= self.OBI_SKEW_T2_THRESH:
            ticks = self.OBI_SKEW_T2_TICKS
        elif a >= self.OBI_SKEW_T1_THRESH:
            ticks = self.OBI_SKEW_T1_TICKS
        else:
            ticks = 0
        if ticks > 0:
            if obi > 0:
                our_ask = best_ask + ticks - 1
            else:
                our_bid = best_bid - ticks + 1
        if our_bid >= our_ask:
            our_bid = best_bid + 1
            our_ask = best_ask - 1
        return our_bid, our_ask

    def _mid(self, od: OrderDepth) -> Optional[float]:
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        return (bids[0] + asks[0]) / 2.0

    def _trade_hydrogel(self, od: OrderDepth, pos: int, td: dict) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.HY_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total
        abs_obi = abs(obi)

        orders: List[Order] = []
        limit = LIMITS[HYDROGEL]
        soft_thresh = int(self.HY_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos

        buf_key = "hy_mids"
        age_key = "hy_revz_age"
        side_key = "hy_revz_side"
        buf: List[float] = td.get(buf_key, [])
        buf.append(mid)
        win = max(10, int(self.HY_REVZ_WINDOW))
        if len(buf) > win:
            buf = buf[-win:]
        td[buf_key] = buf

        take_qty = 0
        if (len(buf) >= win and self.HY_REVZ_TAKE_SIZE > 0):
            mean = sum(buf) / len(buf)
            var = sum((x - mean) ** 2 for x in buf) / len(buf)
            std = var ** 0.5
            if std > 0:
                z = (mid - mean) / std
                if abs(z) > self.HY_REVZ_THRESHOLD and abs_obi > self.HY_REVZ_OBI_GATE:
                    desired_dir = -1 if z > 0 else 1
                    obi_dir = 1 if obi > 0 else -1
                    if desired_dir == obi_dir:
                        size = min(self.HY_REVZ_TAKE_SIZE,
                                    sell_room if desired_dir < 0 else buy_room)
                        if size > 0:
                            if desired_dir > 0:
                                take_qty = +size
                                orders.append(Order(HYDROGEL, best_ask, +size))
                            else:
                                take_qty = -size
                                orders.append(Order(HYDROGEL, best_bid, -size))
                            td[age_key] = 0
                            td[side_key] = desired_dir

        side = int(td.get(side_key, 0))
        if side != 0:
            age = int(td.get(age_key, 0)) + 1
            if age >= self.HY_REVZ_HOLD:
                td[age_key] = 0
                td[side_key] = 0
            else:
                td[age_key] = age

        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if abs_obi >= self.HY_OBI_THRESH:
            conf_size = max(self.HY_OBI_SIZE_MIN,
                             min(self.HY_OBI_SIZE_MAX,
                                 int(math.ceil(limit * abs_obi * self.HY_OBI_SIZE_K_CONF))))
            if obi > 0:
                buy_size = conf_size
                sell_size = self.HY_MM_BASE_SIZE
                our_ask = best_ask + max(0, self.HY_OBI_SKEW_TICKS) - 1
            else:
                buy_size = self.HY_MM_BASE_SIZE
                sell_size = conf_size
                our_bid = best_bid - max(0, self.HY_OBI_SKEW_TICKS) + 1
        else:
            buy_size = self.HY_MM_BASE_SIZE
            sell_size = self.HY_MM_BASE_SIZE

        if our_bid >= our_ask:
            our_bid = best_bid + 1
            our_ask = best_ask - 1

        used_buy = max(0, take_qty)
        used_sell = max(0, -take_qty)
        rem_buy = max(0, buy_room - used_buy)
        rem_sell = max(0, sell_room - used_sell)
        bqty = min(buy_size, rem_buy)
        aqty = min(sell_size, rem_sell)
        if pos >= soft_thresh:
            bqty = 0
        elif pos <= -soft_thresh:
            aqty = 0
        if bqty > 0:
            orders.append(Order(HYDROGEL, our_bid, bqty))
        if aqty > 0:
            orders.append(Order(HYDROGEL, our_ask, -aqty))
        return orders

    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict,
                   target_offset: int = 0) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.MR_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0
        fv, sigma, n = self._update_ema(td, product, mid)
        limit = LIMITS[product]
        if n < self.MR_MIN_N or sigma <= 0:
            target = 0
            z = 0.0
        else:
            z = (mid - fv) / sigma
            target_frac = max(-self.MR_MAX_FRAC,
                               min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)
        if target_offset:
            target = max(-limit, min(limit, target + int(target_offset)))
        buy_room = limit - pos
        sell_room = limit + pos
        buy_ordered = 0
        sell_ordered = 0
        orders: List[Order] = []
        diff = target - pos
        take_ok = (not self.DISABLE_TAKES) and abs(z) >= self.MR_TAKE_Z
        if take_ok and self.OBI_CONFIRM_TAKE:
            b1_vol = od.buy_orders[best_bid]
            a1_vol = -od.sell_orders[best_ask]
            tot = b1_vol + a1_vol
            obi = 0.0 if tot == 0 else (b1_vol - a1_vol) / tot
            take_ok = (z > 0 and obi <= 0) or (z < 0 and obi >= 0)
        if take_ok:
            if diff > 0:
                cap = min(diff, self.MR_TAKE_MAX, buy_room)
                for ap in asks:
                    if cap <= 0:
                        break
                    vol = -od.sell_orders[ap]
                    qty = min(vol, cap)
                    if qty <= 0:
                        continue
                    orders.append(Order(product, ap, qty))
                    buy_ordered += qty
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
                    orders.append(Order(product, bp, -qty))
                    sell_ordered += qty
                    cap -= qty
        diff_after = target - (pos + buy_ordered - sell_ordered)
        big_side_size = self.MR_MM_LEVEL_SIZE
        small_side_size = max(4, big_side_size // 3)
        if diff_after > 0:
            buy_size_each = big_side_size
            sell_size_each = small_side_size
        elif diff_after < 0:
            buy_size_each = small_side_size
            sell_size_each = big_side_size
        else:
            buy_size_each = small_side_size
            sell_size_each = small_side_size
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        tot = b1_vol + a1_vol
        obi = 0.0 if tot == 0 else (b1_vol - a1_vol) / tot
        rem_buy = max(0, buy_room - buy_ordered)
        rem_sell = max(0, sell_room - sell_ordered)
        for level in range(self.MR_MM_LEVELS):
            if level == 0:
                our_bid, our_ask = self._obi_skewed_quotes(best_bid, best_ask, obi)
            else:
                our_bid = best_bid + 1 + level
                our_ask = best_ask - 1 - level
            if our_bid >= our_ask:
                break
            bqty = min(buy_size_each, rem_buy)
            aqty = min(sell_size_each, rem_sell)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
                rem_buy -= bqty
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
                rem_sell -= aqty
        return orders

    def _update_ema(self, td: dict, product: str, mid: float
                     ) -> Tuple[float, float, int]:
        ema_key = f"ema_{product}"
        var_key = f"var_{product}"
        n_key = f"n_{product}"
        prev_ema = td.get(ema_key)
        prev_var = td.get(var_key, FALLBACK_SIGMA.get(product, 30.0) ** 2)
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

    def _trade_vev_mm(self, product: str, od: OrderDepth, pos: int
                       ) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total
        buy_size, sell_size = self._vev_obi_sizes(obi)
        if VEV_MM_BASE_SIZE_FLOOR and self.BASE_MM_SIZE > self.VEV_BASE_SIZE:
            if obi > 0:
                buy_size = max(buy_size, self.BASE_MM_SIZE)
            else:
                sell_size = max(sell_size, self.BASE_MM_SIZE)
        our_bid, our_ask = self._obi_skewed_quotes(best_bid, best_ask, obi)
        if our_bid >= our_ask:
            return []
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

    def _vev_obi_sizes(self, obi: float) -> Tuple[int, int]:
        abs_obi = abs(obi)
        if abs_obi < self.OBI_SKEW_1:
            return (self.VEV_BASE_SIZE, self.VEV_BASE_SIZE)
        if abs_obi < self.OBI_SKEW_2:
            big, small = self.VEV_SIZES_MILD
        elif abs_obi < self.OBI_SKEW_3:
            big, small = self.VEV_SIZES_STRONG
        else:
            big, small = self.VEV_SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
