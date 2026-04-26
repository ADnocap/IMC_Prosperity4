"""VARIANT B - Mark-gated cross-spread takes.

Built on top of `traders/round4/submission.py` (stratton + Timo IV-scalp).
Adds an aggressive Mark-gated take layer that fires BEFORE the per-product
handler. When a strong informed-Mark signal triggers in the trailing 50-tick
window of `state.market_trades`, we take the corresponding side at top-of-book.

Selection of Mark signals (from calibration/marks/signals.json):
    confidence == "high"  AND  |drift_H200_mean| >= 5.0
    -> 8 signals total: Mark 14 / Mark 38 on HYDROGEL_PACK and VEV_4000.

Caveats / safety:
  - Rate-limited: each product can only fire one take per `MARK_TAKE_COOLDOWN`
    ticks (default 30) to avoid stacking on the same Mark trade.
  - Take size capped by remaining position-limit room AND by best-of-book size.
  - Effective post-take position is passed to the existing handler so that
    the worst-case position-limit cancellation rule is honored.

Lineage:
  submission.py (R4 baseline, +27,444 in 3-day replay)
  -> THIS adds a Mark-gated take layer on top.
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


# === Mark signals (filtered: confidence == "high" AND |drift_H200| >= 5.0)
# Each entry: (mark, product, mark_side, action_for_us, drift_H200_mean)
# Source: calibration/marks/signals.json (8 entries)
MARK_SIGNALS: List[Dict] = [
    {"mark": "Mark 14", "product": HYDROGEL,  "mark_side": "buyer",  "action": "BUY",  "drift": 8.938},
    {"mark": "Mark 38", "product": HYDROGEL,  "mark_side": "seller", "action": "BUY",  "drift": -8.554},
    {"mark": "Mark 14", "product": HYDROGEL,  "mark_side": "seller", "action": "SELL", "drift": 7.415},
    {"mark": "Mark 38", "product": HYDROGEL,  "mark_side": "buyer",  "action": "SELL", "drift": -7.321},
    {"mark": "Mark 14", "product": VEV_4000,  "mark_side": "seller", "action": "SELL", "drift": 11.263},
    {"mark": "Mark 38", "product": VEV_4000,  "mark_side": "buyer",  "action": "SELL", "drift": -11.081},
    {"mark": "Mark 38", "product": VEV_4000,  "mark_side": "seller", "action": "BUY",  "drift": -9.938},
    {"mark": "Mark 14", "product": VEV_4000,  "mark_side": "buyer",  "action": "BUY",  "drift": 9.892},
]

# Build a fast lookup: (product, mark, mark_side) -> action
MARK_LOOKUP: Dict[Tuple[str, str, str], str] = {
    (s["product"], s["mark"], s["mark_side"]): s["action"] for s in MARK_SIGNALS
}
MARK_PRODUCTS = set(s["product"] for s in MARK_SIGNALS)

# === Tunable take layer params ========================================
MARK_LOOKBACK_TICKS = 50      # window for matching Mark trades
MARK_TAKE_COOLDOWN = 30       # min ticks between successive takes per product
MARK_TAKE_SIZE = 5            # best of {5, 10, 20} sweep on R4 replay (least bad)


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

    # === Mark-gated take layer ============================================
    def _update_mark_trade_log(self, state: TradingState, td: dict) -> None:
        """Append fresh market_trades to td["mark_trades"] (bounded buffer)."""
        log: List[Dict] = td.get("mark_trades", [])
        cur_ts = state.timestamp
        cutoff = cur_ts - MARK_LOOKBACK_TICKS * 100
        # Drop stale entries
        log = [e for e in log if e["ts"] >= cutoff]
        # Append new
        seen = {(e["sym"], e["ts"], e["price"], e["qty"], e["buyer"], e["seller"])
                for e in log}
        for sym, trades in (state.market_trades or {}).items():
            if sym not in MARK_PRODUCTS:
                continue
            for t in trades:
                buyer = t.buyer or ""
                seller = t.seller or ""
                if not buyer and not seller:
                    continue
                # We only care about Marks we have signals for
                if (sym, buyer, "buyer") not in MARK_LOOKUP and \
                   (sym, seller, "seller") not in MARK_LOOKUP:
                    continue
                key = (sym, t.timestamp, t.price, t.quantity, buyer, seller)
                if key in seen:
                    continue
                log.append({
                    "sym": sym, "ts": t.timestamp, "price": t.price,
                    "qty": t.quantity, "buyer": buyer, "seller": seller,
                })
                seen.add(key)
        td["mark_trades"] = log

    def _mark_take_for(self, product: str, td: dict, cur_ts: int
                        ) -> Optional[str]:
        """Returns 'BUY'/'SELL' if a Mark signal fires for `product`, else None.
        Picks the most recent matching Mark trade in the lookback window.
        """
        # Cooldown gate
        last_ts_map: Dict[str, int] = td.get("last_mark_take_ts", {})
        last = last_ts_map.get(product, -10**9)
        if cur_ts - last < MARK_TAKE_COOLDOWN * 100:
            return None
        log: List[Dict] = td.get("mark_trades", [])
        cutoff = cur_ts - MARK_LOOKBACK_TICKS * 100
        # Walk newest -> oldest to find the most recent matching signal.
        best_action: Optional[str] = None
        best_ts = -1
        for e in log:
            if e["sym"] != product:
                continue
            if e["ts"] < cutoff:
                continue
            buyer, seller = e["buyer"], e["seller"]
            act = MARK_LOOKUP.get((product, buyer, "buyer"))
            if act is not None and e["ts"] > best_ts:
                best_action = act
                best_ts = e["ts"]
            act2 = MARK_LOOKUP.get((product, seller, "seller"))
            if act2 is not None and e["ts"] > best_ts:
                best_action = act2
                best_ts = e["ts"]
        return best_action

    def _emit_mark_take(self, product: str, action: str, od: OrderDepth,
                         pos: int) -> Tuple[List[Order], int]:
        """Returns (orders, signed_qty). signed_qty>0 means we bought."""
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return [], 0
        best_bid, best_ask = bids[0], asks[0]
        limit = LIMITS[product]
        buy_room = limit - pos
        sell_room = limit + pos
        if action == "BUY":
            ask_vol = -od.sell_orders[best_ask]
            qty = min(MARK_TAKE_SIZE, buy_room, ask_vol)
            if qty <= 0:
                return [], 0
            return [Order(product, best_ask, qty)], +qty
        else:  # SELL
            bid_vol = od.buy_orders[best_bid]
            qty = min(MARK_TAKE_SIZE, sell_room, bid_vol)
            if qty <= 0:
                return [], 0
            return [Order(product, best_bid, -qty)], -qty

    # === IV-deviation scalping (Timo) =====================================
    def _iv_scalp_orders(self, sym: str, od: OrderDepth, pos: int,
                          ctx: Dict[str, dict]) -> Tuple[List[Order], bool]:
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

        if switch_mean < self.IV_SCALPING_THR:
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

        # Maintain rolling Mark trade log
        self._update_mark_trade_log(state, td)

        ctx = self._build_market_ctx(state, td)
        S = ctx.get("__S__", {}).get("S", FALLBACK_FV[VELVETFRUIT])
        if CS_LAYER_ENABLED:
            cs_targets = self._cross_strike_targets(state, td, S, ctx)
        else:
            cs_targets = {}

        cur_ts = state.timestamp

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            # === Mark-gated take layer (priority 0) =====================
            mark_orders: List[Order] = []
            mark_qty_signed = 0
            if product in MARK_PRODUCTS:
                action = self._mark_take_for(product, td, cur_ts)
                if action is not None:
                    mark_orders, mark_qty_signed = self._emit_mark_take(
                        product, action, od, pos)
                    if mark_orders:
                        # Record cooldown
                        last_map = td.get("last_mark_take_ts", {})
                        last_map[product] = cur_ts
                        td["last_mark_take_ts"] = last_map

            # Effective post-take position so the existing handler computes
            # quote sizes against worst-case post-fill (avoids position-limit
            # cancellation when our take + handler quote could combined exceed
            # the limit).
            eff_pos = pos + mark_qty_signed

            if product == HYDROGEL:
                if HYDROGEL_PORUSH_HANDLER:
                    handler_orders = self._trade_hydrogel(od, eff_pos, td)
                else:
                    handler_orders = self._trade_vev_mm(product, od, eff_pos)
            elif product in SCALP_VOUCHERS:
                # Priority 1: IV-scalping (Timo)
                scalp_orders, fired = self._iv_scalp_orders(
                    product, od, eff_pos, ctx)
                if fired:
                    handler_orders = scalp_orders
                else:
                    target = cs_targets.get(product, 0)
                    if target != 0:
                        handler_orders = self._trade_cross_strike_target(
                            product, od, eff_pos, target)
                    else:
                        fallback = SCALP_FALLBACK_HANDLER[product]
                        if fallback == "mr":
                            handler_orders = self._trade_mr(
                                product, od, eff_pos, td)
                        else:
                            handler_orders = self._trade_vev_mm(
                                product, od, eff_pos)
            elif product in MR_ONLY_ASSETS:
                handler_orders = self._trade_mr(product, od, eff_pos, td)
            elif product in VEV_MM_ASSETS:
                handler_orders = self._trade_vev_mm(product, od, eff_pos)
            else:
                handler_orders = []

            # Combine: Mark take FIRST, then handler quotes
            combined = list(mark_orders) + list(handler_orders)
            result[product] = combined

        return result, 0, json.dumps(td)

    # === Helpers (verbatim from submission.py) ============================
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
