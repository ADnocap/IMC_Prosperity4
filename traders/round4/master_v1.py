"""master_v1 — V10 base + pete_hegseth_v3 VELVETFRUIT handler. Notes after decls."""

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


# === Pete_hegseth_v3 VELVETFRUIT handler (verbatim params) =================
# These ONLY drive the new _trade_velvet path — the stratton MR constants on
# the Trader class still govern VEV_5000-5500 fallback unchanged.
VELVET_EMA_ALPHA = 0.0005
VELVET_VAR_ALPHA = 0.01
VELVET_MR_K = 0.55
VELVET_MR_MAX_FRAC = 0.85
VELVET_MR_MIN_N = 50
VELVET_MR_MM_LEVEL_SIZE = 30
VELVET_MR_TAKE_Z = 1.2
VELVET_MR_TAKE_MAX = 40
VELVET_MR_TIGHT_SPREAD_MIN = 2
VELVET_FALLBACK_FV = 5250.0
VELVET_FALLBACK_SIGMA = 15.0
VELVET_STOP_LOSS_THRESHOLD = -2500.0
VELVET_STOP_DURATION_TICKS = 300
VELVET_STOP_POS_GATE = 0.80
VELVET_STOP_PAUSE_TICKS = 500
VELVET_OBI_FACTOR = 1.0
VELVET_OBI_MULT_MIN = 0.3
VELVET_OBI_MULT_MAX = 1.8


# ============================================================================
# Design notes (moved out of module docstring so the rust MC scanner — which
# reads only the first 40 lines for `NAME = "SYMBOL"` declarations — works.)
# ============================================================================
#
# Composition rationale (R4 prosperity3bt --merge-pnl, 3-day per-asset PnL):
#
#     Asset                V10        Pete_v3      Pick
#     HYDROGEL             8,861      3,092        V10
#     VELVETFRUIT          3,936      9,506        PETE_V3   <- +5,570 swing
#     VEV_4000             8,360      7,942        V10
#     VEV_4500             -7         -7           tie
#     VEV_5000-5500        9,142      7,552        V10  (Timo IV-scalp)
#     VEV_6000/6500        0          0            tie
#     TOTAL                30,293     28,086
#
# master_v1 CSV replay (R4 days 1-3, prosperity3bt --merge-pnl):
#     D1 19,492 / D2 5,309 / D3 11,061  =>  TOTAL 35,862 (= theoretical max)
#     vs V10:                              +5,569 total, but D3 -1,674 OOS.
#
# master_v1 = V10 verbatim, except the VELVETFRUIT branch in run() now calls
# _trade_velvet (ported from pete_hegseth_v3). All velvet-specific constants
# are renamed VELVET_* so they don't collide with stratton's MR constants
# (still used for VEV_5000-5500 fallback).
#
# Why pete_v3's velvet handler wins on D1+D2: faster EMA (alpha=5e-4 vs V10
# 4.3e-5), much larger MR_K (0.55 vs 0.080), enables cross-spread takes at
# |z|>=1.2, 2-level passive MM with OBI tilt, and a stop-loss. V10's slow-MR
# was designed for noise-suppression — pete_v3 captures intra-day moves.
#
# OOS caveat: D3 (the only fresh tape — D1/D2 ≡ R3 D1/D2) shows pete_v3's
# velvet handler making 1,508 vs V10's 3,182 (-1,674). On a fresh-data day
# the slow-MR may still win. Watch this in the portal final eval.
#
# Lineage:
#   stratton (R3 search-2 #233): portal +11,140  passive MM
#   porush   (R3 search-4 #119): MC +11,774      adds HYDROGEL handler (broken)
#   wolf     (porush + CS):      MC +6,157       adds CS spread MR
#   submission_v2 (V1 + IV-scalp tune):   replay 29,934
#   submission_v10 (V2 + MR_K bump):      replay 30,293
#   pete_hegseth_v3 (smile dispersion):   replay 28,086 (BIG velvet edge)
#   THIS master_v1 (V10 + v3 velvet):     replay 35,862  (D3 OOS -1,674)
# ============================================================================


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
    MR_K = 0.080  # V10: bumped from V2's 0.04481 (+359 R4 replay; D3 +423)
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

        # Velvet signal computed once before the product loop (z-score MR).
        velvet_z, velvet_fv, velvet_sigma = self._velvet_signal(state, td)

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == HYDROGEL:
                if HYDROGEL_PORUSH_HANDLER:
                    result[product] = self._trade_hydrogel(od, pos, td)
                else:
                    result[product] = self._trade_vev_mm(product, od, pos)
            elif product in SCALP_VOUCHERS:
                # Priority 1: IV-scalping (Timo)
                scalp_orders, fired = self._iv_scalp_orders(product, od, pos, ctx)
                if fired:
                    result[product] = scalp_orders
                else:
                    # Priority 2: cross-strike target
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
            elif product == VELVETFRUIT:
                self._velvet_accumulate_fills(td, state)
                result[product] = self._trade_velvet(
                    od, pos, td, state.timestamp,
                    velvet_z, velvet_fv, velvet_sigma)
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

    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict
                   ) -> List[Order]:
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

    # ===== VELVETFRUIT handler (ported from pete_hegseth_v3) ===============
    def _velvet_signal(self, state: TradingState, td: dict
                        ) -> Tuple[float, float, float]:
        od = state.order_depths.get(VELVETFRUIT)
        if not od or not od.buy_orders or not od.sell_orders:
            return 0.0, VELVET_FALLBACK_FV, VELVET_FALLBACK_SIGMA
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        if ba - bb < VELVET_MR_TIGHT_SPREAD_MIN:
            return 0.0, VELVET_FALLBACK_FV, VELVET_FALLBACK_SIGMA
        mid = (bb + ba) / 2.0
        fv, sigma, n = self._velvet_update_ema(td, mid)
        if n < VELVET_MR_MIN_N or sigma <= 0:
            return 0.0, fv, sigma
        return (mid - fv) / sigma, fv, sigma

    def _velvet_update_ema(self, td: dict, mid: float
                            ) -> Tuple[float, float, int]:
        ema_key = "velvet_ema"
        var_key = "velvet_var"
        n_key = "velvet_n"
        prev_ema = td.get(ema_key)
        prev_var = td.get(var_key, VELVET_FALLBACK_SIGMA ** 2)
        n = td.get(n_key, 0)
        if prev_ema is None:
            prev_ema = VELVET_FALLBACK_FV
        residual = mid - prev_ema
        new_ema = prev_ema + VELVET_EMA_ALPHA * residual
        new_var = prev_var + VELVET_VAR_ALPHA * (residual * residual - prev_var)
        new_n = n + 1
        td[ema_key] = new_ema
        td[var_key] = max(1.0, new_var)
        td[n_key] = new_n
        sigma = max(1.0, new_var) ** 0.5
        return new_ema, sigma, new_n

    def _velvet_accumulate_fills(self, td: dict, state: TradingState) -> None:
        cash = td.get("velvet_cash", 0.0)
        last_ts = td.get("velvet_last_ts", -1)
        trades = (state.own_trades or {}).get(VELVETFRUIT, []) or []
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
        td["velvet_cash"] = cash
        td["velvet_last_ts"] = last_ts

    def _velvet_sl_active(self, td: dict, pos: int, mid: float, ts: int) -> bool:
        limit = LIMITS[VELVETFRUIT]
        pnl = td.get("velvet_cash", 0.0) + pos * mid
        below = td.get("velvet_below", 0)
        below = below + 1 if pnl < VELVET_STOP_LOSS_THRESHOLD else 0
        td["velvet_below"] = below
        pause_until = td.get("velvet_pause_until", -1)
        pos_gate_met = abs(pos) >= int(VELVET_STOP_POS_GATE * limit)
        if (below >= VELVET_STOP_DURATION_TICKS
                and pos_gate_met and pause_until < ts):
            td["velvet_pause_until"] = ts + VELVET_STOP_PAUSE_TICKS
            return True
        return pause_until >= ts

    def _velvet_unwind_passive(self, pos: int, best_bid: int, best_ask: int
                                ) -> List[Order]:
        orders: List[Order] = []
        if pos > 0:
            qty = min(pos, 30)
            if best_ask - 1 > best_bid:
                orders.append(Order(VELVETFRUIT, best_ask - 1, -qty))
        elif pos < 0:
            qty = min(-pos, 30)
            if best_bid + 1 < best_ask:
                orders.append(Order(VELVETFRUIT, best_bid + 1, qty))
        return orders

    def _trade_velvet(self, od: OrderDepth, pos: int, td: dict, ts: int,
                       z: float, fv: float, sigma: float) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < VELVET_MR_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0
        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        tot = b1 + a1
        obi = 0.0 if tot == 0 else (b1 - a1) / tot
        limit = LIMITS[VELVETFRUIT]

        if self._velvet_sl_active(td, pos, mid, ts):
            return self._velvet_unwind_passive(pos, best_bid, best_ask)

        if sigma > 0:
            target_frac = max(-VELVET_MR_MAX_FRAC,
                                min(VELVET_MR_MAX_FRAC, -VELVET_MR_K * z))
            target = int(target_frac * limit)
        else:
            target = 0
        diff = target - pos
        buy_room = limit - pos
        sell_room = limit + pos
        buy_ord = sell_ord = 0
        orders: List[Order] = []

        # (a) Cross-spread take when |z| >= VELVET_MR_TAKE_Z.
        if abs(z) >= VELVET_MR_TAKE_Z:
            if diff > 0:
                cap = min(diff, VELVET_MR_TAKE_MAX, buy_room)
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
                cap = min(-diff, VELVET_MR_TAKE_MAX, sell_room)
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

        # (b) 2-level passive layers, OBI-tilted.
        diff_after = target - (pos + buy_ord - sell_ord)
        layers = [(1, VELVET_MR_MM_LEVEL_SIZE), (2, VELVET_MR_MM_LEVEL_SIZE)]
        rem_buy = max(0, buy_room - buy_ord)
        rem_sell = max(0, sell_room - sell_ord)
        for offset, big_sz in layers:
            our_bid = best_bid + offset
            our_ask = best_ask - offset
            if our_bid >= our_ask:
                break
            small_sz = max(5, big_sz // 3)
            if diff_after > 0:
                mult = max(VELVET_OBI_MULT_MIN,
                            min(VELVET_OBI_MULT_MAX,
                                1.0 + VELVET_OBI_FACTOR * obi))
                b_each, a_each = int(big_sz * mult), small_sz
            elif diff_after < 0:
                mult = max(VELVET_OBI_MULT_MIN,
                            min(VELVET_OBI_MULT_MAX,
                                1.0 + VELVET_OBI_FACTOR * (-obi)))
                a_each, b_each = int(big_sz * mult), small_sz
            else:
                mult_b = max(VELVET_OBI_MULT_MIN,
                              min(VELVET_OBI_MULT_MAX,
                                  1.0 + VELVET_OBI_FACTOR * obi))
                mult_a = max(VELVET_OBI_MULT_MIN,
                              min(VELVET_OBI_MULT_MAX,
                                  1.0 + VELVET_OBI_FACTOR * (-obi)))
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
