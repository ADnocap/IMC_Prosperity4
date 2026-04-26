"""VARIANT C — submission.py (stratton + IV-scalp) + Mark-aware defensive widen.

Pure-defensive layer: when a recent (<=50t) high-confidence Mark trade
indicates the price is about to move against the side we'd be passive on,
WIDEN that side's quote (= post farther from market = less likely to be
adversely selected). Don't take cross-spread, don't tilt sizes — just
don't get picked off.

Convention: signals.json `action_side_for_us` is the side WE want to do.
  - action_side_for_us == "BUY"  => mid will RISE  => our ASK is in danger
                                       (we'd sell low before the rise) =>
                                       widen the ASK (post higher).
  - action_side_for_us == "SELL" => mid will FALL  => our BID is in danger
                                       (we'd buy high before the fall) =>
                                       widen the BID (post lower).

Widen ladder by |drift_H200_mean| of the firing signal:
  - 0.5  <= |d| < 2  => 1 tick
  - 2    <= |d| < 5  => 2 ticks
  - |d|  >= 5        => 3 ticks (or skip the side if widen would invert)

Skip widening when our existing position is already on the safe side
(e.g. long HYDROGEL + signal "mid will RISE" = no need to widen ask).

Hooked into: _trade_vev_mm, _trade_mr, and the IV-scalp close-back leg.
"""

try:
    from datamodel import Order, OrderDepth, TradingState, Trade
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState, Trade

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

CS_PAIRS: List[Tuple[str, str, int]] = [
    (VEV_5200, VEV_5400, 30),
    (VEV_5300, VEV_5400, 40),
    (VEV_5300, VEV_5500, 20),
]

CS_LAYER_ENABLED = False
HYDROGEL_PORUSH_HANDLER = False
VEV_MM_BASE_SIZE_FLOOR = False


# === Mark defensive-widen signals (high-confidence only, from
#     calibration/marks/signals.json). Each entry is keyed by
#     (mark, product, mark_side) and stores (action_side_for_us, |drift|).
# action_side_for_us == "BUY"  => mid will RISE  => widen our ASK
# action_side_for_us == "SELL" => mid will FALL  => widen our BID
# Inlined to keep submission self-contained. ====================
HIGH_CONF_SIGNALS: Dict[Tuple[str, str, str], Tuple[str, float]] = {
    # HYDROGEL_PACK
    ("Mark 14", "HYDROGEL_PACK", "buyer"):  ("BUY",  8.938),
    ("Mark 38", "HYDROGEL_PACK", "seller"): ("BUY",  8.554),
    ("Mark 14", "HYDROGEL_PACK", "seller"): ("SELL", 7.415),
    ("Mark 38", "HYDROGEL_PACK", "buyer"):  ("SELL", 7.321),
    # VEV_4000
    ("Mark 14", "VEV_4000", "seller"): ("SELL", 11.263),
    ("Mark 38", "VEV_4000", "buyer"):  ("SELL", 11.081),
    ("Mark 38", "VEV_4000", "seller"): ("BUY",  9.938),
    ("Mark 14", "VEV_4000", "buyer"):  ("BUY",  9.892),
    # VELVETFRUIT_EXTRACT
    ("Mark 01", "VELVETFRUIT_EXTRACT", "seller"): ("SELL", 2.730),
    ("Mark 55", "VELVETFRUIT_EXTRACT", "buyer"):  ("SELL", 1.622),
    ("Mark 55", "VELVETFRUIT_EXTRACT", "seller"): ("BUY",  1.363),
    ("Mark 01", "VELVETFRUIT_EXTRACT", "buyer"):  ("BUY",  2.054),
    ("Mark 14", "VELVETFRUIT_EXTRACT", "buyer"):  ("BUY",  0.910),
    # VEV_5300
    ("Mark 22", "VEV_5300", "seller"): ("BUY",  1.270),
    ("Mark 01", "VEV_5300", "buyer"):  ("BUY",  1.205),
    # VEV_5400
    ("Mark 01", "VEV_5400", "buyer"):  ("BUY",  0.660),
    ("Mark 22", "VEV_5400", "seller"): ("BUY",  0.601),
    # VEV_5500
    ("Mark 01", "VEV_5500", "buyer"):  ("BUY",  0.538),
    ("Mark 22", "VEV_5500", "seller"): ("BUY",  0.518),
    # VEV_6000 / VEV_6500 (effectively dead — pinned at 0/1)
    ("Mark 01", "VEV_6000", "buyer"):  ("BUY",  0.500),
    ("Mark 01", "VEV_6500", "buyer"):  ("BUY",  0.500),
    ("Mark 22", "VEV_6000", "seller"): ("BUY",  0.500),
    ("Mark 22", "VEV_6500", "seller"): ("BUY",  0.500),
}

# Lookback for "did a relevant Mark trade in the last 50 ticks"
MARK_LOOKBACK_TICKS = 50
# Position-fraction at which we consider ourselves "already on the safe side"
SAFE_SIDE_POS_FRAC = 0.10


def _widen_ticks_for_drift(abs_drift: float) -> int:
    if abs_drift < 0.5:
        return 0
    if abs_drift < 2.0:
        return 1
    if abs_drift < 5.0:
        return 2
    return 3


class Trader:
    SMILE_A_INIT = 0.580261
    SMILE_B = 0.033704
    SMILE_C = 0.089775
    SMILE_A_ALPHA = 0.01

    SESSION_TICKS = 30_000
    TICKS_PER_YEAR = 365 * 10_000
    T_YEARS_FLOOR = 1e-4

    THEO_NORM_WINDOW = 100
    IV_SCALPING_WINDOW = 100
    THR_OPEN = 0.5
    THR_CLOSE = 0.0
    IV_SCALPING_THR = 0.7
    LOW_VEGA_THR_ADJ = 0.5
    LOW_VEGA_CUTOFF = 1.0
    SCALP_MAX_PER_TICK = 60

    CS_K_SIGMA = 1.5
    CS_HOLD_TICKS = 30
    CS_DEV_STD_FALLBACK = 1.0
    CS_TAKE_MAX_PER_TICK = 6
    CS_PASSIVE_SIZE = 10

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

    # === Mark trade log + danger-side widen ==============================
    def _update_mark_trades(self, state: TradingState, td: dict) -> None:
        """Append every market_trade with both buyer+seller populated to the
        rolling per-product log (timestamp, mark_buyer, mark_seller, qty).
        Drop entries older than MARK_LOOKBACK_TICKS * 100 timestamp units.
        """
        log: dict = td.get("mark_trades", {})
        cutoff = state.timestamp - MARK_LOOKBACK_TICKS * 100
        for product, trades in (state.market_trades or {}).items():
            buf: List[List] = log.get(product, [])
            for tr in trades or []:
                buyer = getattr(tr, "buyer", None)
                seller = getattr(tr, "seller", None)
                if not buyer or not seller:
                    continue
                ts = getattr(tr, "timestamp", state.timestamp)
                buf.append([int(ts), str(buyer), str(seller),
                             int(getattr(tr, "quantity", 0))])
            buf = [e for e in buf if e[0] >= cutoff]
            if buf:
                log[product] = buf
            elif product in log:
                del log[product]
        td["mark_trades"] = log

    def _danger_widen(self, product: str, td: dict, pos: int
                       ) -> Tuple[int, int]:
        """Return (bid_widen_ticks, ask_widen_ticks) for this product based on
        the strongest high-conf Mark signal in the last 50t.

        action_side_for_us == BUY  => price will rise  => danger = our ASK.
        action_side_for_us == SELL => price will fall  => danger = our BID.

        Skip widening if our existing position is already on the safe side
        (long & price rising / short & price falling).
        """
        log: dict = td.get("mark_trades", {})
        trades = log.get(product, [])
        if not trades:
            return 0, 0

        limit = LIMITS.get(product, 1)
        safe_long = pos >= max(1, int(SAFE_SIDE_POS_FRAC * limit))
        safe_short = pos <= -max(1, int(SAFE_SIDE_POS_FRAC * limit))

        bid_widen, ask_widen = 0, 0
        for ts, buyer, seller, _qty in trades:
            for mark, side in ((buyer, "buyer"), (seller, "seller")):
                key = (mark, product, side)
                sig = HIGH_CONF_SIGNALS.get(key)
                if sig is None:
                    continue
                action, abs_drift = sig
                w = _widen_ticks_for_drift(abs_drift)
                if w <= 0:
                    continue
                if action == "BUY":
                    # mid rising => widen ASK; safe if already long
                    if not safe_long and w > ask_widen:
                        ask_widen = w
                else:  # SELL
                    # mid falling => widen BID; safe if already short
                    if not safe_short and w > bid_widen:
                        bid_widen = w
        return bid_widen, ask_widen

    # === IV-deviation scalping (Timo) ===================================
    def _iv_scalp_orders(self, sym: str, od: OrderDepth, pos: int,
                          ctx: Dict[str, dict], td: dict
                          ) -> Tuple[List[Order], bool]:
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

        # Defensive widen for the close-back leg: when we're flattening into
        # the book, don't bother defending — we want the fill. So only honor
        # widen for the "open new position" branch below.
        bid_widen, ask_widen = self._danger_widen(sym, td, pos)

        if switch_mean < self.IV_SCALPING_THR:
            orders: List[Order] = []
            # Force-flatten residual position. We're SELLING (pos>0) at
            # best_bid; danger is "price will rise" => ask_widen > 0 =>
            # lift the sell px so we don't sell into a rise. Symmetric for
            # BUYING (pos<0): danger is bid_widen > 0 => lower the buy px.
            if pos > 0:
                qty = min(pos, sell_room)
                if qty > 0:
                    px = best_bid
                    if ask_widen > 0:
                        px2 = best_bid + ask_widen
                        if px2 < best_ask:
                            px = px2
                    orders.append(Order(sym, px, -qty))
            elif pos < 0:
                qty = min(-pos, buy_room)
                if qty > 0:
                    px = best_ask
                    if bid_widen > 0:
                        px2 = best_ask - bid_widen
                        if px2 > best_bid:
                            px = px2
                    orders.append(Order(sym, px, qty))
            return orders, bool(orders)

        thr = self.THR_OPEN + (self.LOW_VEGA_THR_ADJ
                                if vega <= self.LOW_VEGA_CUTOFF else 0.0)
        sell_dev = (best_bid - fair) - mean_dev
        buy_dev = (best_ask - fair) - mean_dev

        orders: List[Order] = []
        fired = False
        # Active-scalp opens are still aggressive (cross-spread). Defensive
        # widen does not gate them per spec ("don't take cross-spread" applies
        # to the widen layer adding new takes — IV-scalp's existing takes are
        # part of submission.py and untouched).
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

        # Close-back leg — passive against the same book level. Widen if
        # the danger side aligns with our exit side.
        sell_close_dev = (best_bid - fair) - mean_dev
        buy_close_dev = (best_ask - fair) - mean_dev
        if not fired:
            if pos > 0 and sell_close_dev >= self.THR_CLOSE:
                qty = min(pos, sell_room, od.buy_orders[best_bid])
                if qty > 0:
                    px = best_bid
                    # We're SELLING at best_bid. Widening the BID = post lower
                    # = sell cheaper = bad. So if signal says price will FALL
                    # (bid_widen>0 for our normal MM), we actually want to
                    # accelerate the exit; just hit best_bid as before.
                    # Conversely, if ASK is in danger (price will rise), our
                    # close-back sell is risky — widen up by ask_widen ticks
                    # so we sell into the rise.
                    if ask_widen > 0:
                        px2 = best_bid + ask_widen
                        if px2 < best_ask:
                            px = px2
                    orders.append(Order(sym, px, -qty))
                    fired = True
            elif pos < 0 and buy_close_dev <= -self.THR_CLOSE:
                qty = min(-pos, buy_room, -od.sell_orders[best_ask])
                if qty > 0:
                    px = best_ask
                    if bid_widen > 0:
                        px2 = best_ask - bid_widen
                        if px2 > best_bid:
                            px = px2
                    orders.append(Order(sym, px, qty))
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

        # Maintain rolling 50t Mark trade log BEFORE handlers consume it.
        self._update_mark_trades(state, td)

        ctx = self._build_market_ctx(state, td)
        S = ctx.get("__S__", {}).get("S", FALLBACK_FV[VELVETFRUIT])
        if CS_LAYER_ENABLED:
            cs_targets = self._cross_strike_targets(state, td, S, ctx)
        else:
            cs_targets = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == HYDROGEL:
                if HYDROGEL_PORUSH_HANDLER:
                    result[product] = self._trade_hydrogel(od, pos, td)
                else:
                    result[product] = self._trade_vev_mm(product, od, pos, td)
            elif product in SCALP_VOUCHERS:
                scalp_orders, fired = self._iv_scalp_orders(
                    product, od, pos, ctx, td)
                if fired:
                    result[product] = scalp_orders
                else:
                    target = cs_targets.get(product, 0)
                    if target != 0:
                        result[product] = self._trade_cross_strike_target(
                            product, od, pos, target)
                    else:
                        fallback = SCALP_FALLBACK_HANDLER[product]
                        if fallback == "mr":
                            result[product] = self._trade_mr(
                                product, od, pos, td)
                        else:
                            result[product] = self._trade_vev_mm(
                                product, od, pos, td)
            elif product in MR_ONLY_ASSETS:
                result[product] = self._trade_mr(product, od, pos, td)
            elif product in VEV_MM_ASSETS:
                result[product] = self._trade_vev_mm(product, od, pos, td)
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

        # Defensive widen on the passive levels.
        bid_widen, ask_widen = self._danger_widen(product, td, pos)

        for level in range(self.MR_MM_LEVELS):
            if level == 0:
                our_bid, our_ask = self._obi_skewed_quotes(
                    best_bid, best_ask, obi)
            else:
                our_bid = best_bid + 1 + level
                our_ask = best_ask - 1 - level

            # Apply widen: bid lower, ask higher (= farther from market).
            if bid_widen > 0:
                our_bid -= bid_widen
            if ask_widen > 0:
                our_ask += ask_widen

            bqty = min(buy_size_each, rem_buy)
            aqty = min(sell_size_each, rem_sell)

            if our_bid >= our_ask:
                # Widen would invert -> drop the dangerous side(s).
                if ask_widen >= bid_widen:
                    aqty = 0
                    if bid_widen > 0:
                        # if bid widen also active, also drop bid
                        bqty = 0
                else:
                    bqty = 0
                # Reset other side to original aggressive level
                if aqty > 0:
                    our_bid = best_bid + 1 + level
                    if our_bid >= our_ask:
                        aqty = 0
                if bqty > 0:
                    our_ask = best_ask - 1 - level
                    if our_bid >= our_ask:
                        bqty = 0

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

    def _trade_vev_mm(self, product: str, od: OrderDepth, pos: int,
                       td: dict) -> List[Order]:
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

        # Defensive widen.
        bid_widen, ask_widen = self._danger_widen(product, td, pos)
        if bid_widen > 0:
            our_bid -= bid_widen
        if ask_widen > 0:
            our_ask += ask_widen

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

        if our_bid >= our_ask:
            # Widen inverted: prefer to drop the dangerous side and keep the
            # safe one. Re-derive a safe price for the surviving side.
            if ask_widen >= bid_widen and ask_widen > 0:
                # Ask is the dangerous side -> drop it.
                sell_qty = 0
                our_bid_safe = best_bid + 1
                if bid_widen > 0:
                    our_bid_safe -= bid_widen
                our_bid = our_bid_safe
            elif bid_widen > 0:
                buy_qty = 0
                our_ask_safe = best_ask - 1
                if ask_widen > 0:
                    our_ask_safe += ask_widen
                our_ask = our_ask_safe
            else:
                # No widen but still inverted -> fall back to inside quotes
                our_bid = best_bid + 1
                our_ask = best_ask - 1

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
