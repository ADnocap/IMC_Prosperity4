"""Harry_potter_v1 — Round 3 "Gloves Off" trader.

Core insight: VEV voucher market makers price at sigma ~= 0.0125/day, but the
underlying VELVETFRUIT_EXTRACT realizes sigma ~= 0.018/day (microstructure-
robust). So market-implied vol is ~30% below realized, which makes ATM-to-
slightly-OTM calls persistently underpriced. We buy cheap vol on VEV_5000..5500
and delta-hedge via VELVETFRUIT_EXTRACT. Independent inventory-skewed MM on
HYDROGEL_PACK (wide 16-tick bot spread) and VELVETFRUIT_EXTRACT.

Strike allocation is budgeted by hedge capacity: with VELVETFRUIT position limit
of 200 and a peak single-strike net delta of 300 * ~0.9 = 270, we cap net
voucher delta at NET_DELTA_BUDGET = 180 to leave hedge headroom.

Deep-ITM VEV_4000/4500 are pinned at intrinsic (zero time value) and deep-OTM
VEV_6000/6500 are pinned at the 0.5 floor (no taker flow). Both skipped.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Optional, Tuple
import json
import math


# -------------------- Product constants --------------------

HYDROGEL = "HYDROGEL_PACK"
VELVETFRUIT = "VELVETFRUIT_EXTRACT"
VEV_STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_STRIKES_TRADE = [5000, 5100, 5200, 5300, 5400, 5500]
VEV_SYM = {K: f"VEV_{K}" for K in VEV_STRIKES_ALL}

LIM_HYDROGEL = 200
LIM_VELVETFRUIT = 200
LIM_VEV = 300


# -------------------- Vol parameters --------------------

# Microstructure-robust realized sigma/day on VELVETFRUIT_EXTRACT from
# variance-ratio analysis: tick-level sigma (0.02155) inflates by ~sqrt(0.71)
# from bid-ask bounce. VR(k)=0.71 plateau for k in [10..50] gives the
# de-noised value.
SIGMA_TRUE = 0.018

# Historical ATM IV extracted from VEV mids across days 0..2. Stable at
# ~0.0125/day across all ATM strikes and all 3 days -- the bot pricing param.
# Kept for reference; not directly used at runtime, but drives our prior
# that "our_fair > bot_fair" at ATM.
SIGMA_BOT = 0.0125


# -------------------- Time-to-expiry --------------------

# R3 eval starts at TTE = 5 days (6 rounds remain, 1 round per day); decrements
# linearly to 4 at end of eval. TICKS_PER_DAY * TICK_STEP = 10_000 * 100 =
# 1_000_000 timestamp units per day.
TTE_AT_START = 5.0
TIMESTAMP_PER_DAY = 1_000_000


# -------------------- Edge thresholds --------------------

# Minimum XIRECs below fair we need before taking an ask (covers tick
# quantization + delta slippage on the hedge).
EDGE_TAKE_HYDROGEL = 3
EDGE_TAKE_VELVETFRUIT = 2
EDGE_TAKE_VEV = 2

# Net voucher delta cap -- sized below VELVETFRUIT limit (200) to leave
# hedging headroom so we don't stall when UL moves.
NET_DELTA_BUDGET = 180

# Base MM quote size per side (before position/room clipping)
MM_BASE_SIZE_HYDROGEL = 30
MM_BASE_SIZE_VELVETFRUIT = 30

# Inventory-skew thresholds (tighten quotes once past this)
SKEW_THRESHOLD_HYDROGEL = 80
SKEW_THRESHOLD_VELVETFRUIT = 80


# -------------------- Black-Scholes --------------------

_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return max(S - K, 0.0)
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vol
    d2 = d1 - vol
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


def bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        return 1.0 if S > K else 0.0
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vol
    return _norm_cdf(d1)


# -------------------- Trader --------------------


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        tte = self._tte(state.timestamp, td)

        ul_mid = self._book_mid(state.order_depths.get(VELVETFRUIT))
        if ul_mid is None:
            ul_mid = td.get("last_ul_mid", 5250.0)
        td["last_ul_mid"] = ul_mid

        result: Dict[str, List[Order]] = {}

        # VEV takes first. Track running net voucher delta as we commit orders
        # so we stop before the hedge budget blows up.
        running_delta = self._current_voucher_delta(state, ul_mid, tte)

        for K in VEV_STRIKES_TRADE:
            sym = VEV_SYM[K]
            od = state.order_depths.get(sym)
            if od is None:
                result[sym] = []
                continue
            pos = state.position.get(sym, 0)
            orders, delta_added = self._trade_vev(sym, K, od, pos, ul_mid, tte, running_delta)
            result[sym] = orders
            running_delta += delta_added

        # Skipped VEV symbols (deep ITM / deep OTM) — no orders.
        for K in (4000, 4500, 6000, 6500):
            sym = VEV_SYM[K]
            if sym in state.order_depths and sym not in result:
                result[sym] = []

        # VELVETFRUIT: hedge target = -running_delta, inventory skew toward it.
        target_velv = max(-LIM_VELVETFRUIT, min(LIM_VELVETFRUIT, -int(round(running_delta))))
        velv_od = state.order_depths.get(VELVETFRUIT)
        if velv_od is not None:
            velv_pos = state.position.get(VELVETFRUIT, 0)
            result[VELVETFRUIT] = self._trade_velvetfruit(velv_od, velv_pos, target_velv, td)
        else:
            result[VELVETFRUIT] = []

        # HYDROGEL: standalone MM.
        hg_od = state.order_depths.get(HYDROGEL)
        if hg_od is not None:
            hg_pos = state.position.get(HYDROGEL, 0)
            result[HYDROGEL] = self._trade_hydrogel(hg_od, hg_pos, td)
        else:
            result[HYDROGEL] = []

        td["last_net_delta"] = running_delta
        td["last_target_velv"] = target_velv

        return result, 0, json.dumps(td)

    # -------------------- Helpers --------------------

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}

    def _tte(self, timestamp: int, td: dict) -> float:
        # Detect day rollovers in multi-day backtests by watching timestamp dips.
        day_counter = td.get("day_counter", 0)
        prev_ts = td.get("prev_ts", -1)
        if prev_ts >= 0 and timestamp < prev_ts:
            day_counter += 1
        td["day_counter"] = day_counter
        td["prev_ts"] = timestamp
        elapsed = day_counter + timestamp / TIMESTAMP_PER_DAY
        return max(0.0001, TTE_AT_START - elapsed)

    def _book_mid(self, od: Optional[OrderDepth]) -> Optional[float]:
        if od is None:
            return None
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if bids and asks:
            return (bids[0] + asks[0]) / 2.0
        if bids:
            return bids[0] + 1.0
        if asks:
            return asks[0] - 1.0
        return None

    def _sorted_book(self, od: OrderDepth) -> Tuple[List[int], List[int]]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        return bids, asks

    def _current_voucher_delta(self, state: TradingState, ul_mid: float, tte: float) -> float:
        total = 0.0
        for K in VEV_STRIKES_ALL:
            pos = state.position.get(VEV_SYM[K], 0)
            if pos == 0:
                continue
            total += pos * bs_delta(ul_mid, K, tte, SIGMA_TRUE)
        return total

    # -------------------- VEV trading --------------------

    def _trade_vev(
        self,
        sym: str,
        K: int,
        od: OrderDepth,
        pos: int,
        ul_mid: float,
        tte: float,
        running_delta: float,
    ) -> Tuple[List[Order], float]:
        orders: List[Order] = []
        bids, asks = self._sorted_book(od)

        our_fair = bs_call(ul_mid, K, tte, SIGMA_TRUE)
        delta = bs_delta(ul_mid, K, tte, SIGMA_TRUE)

        buy_room = LIM_VEV - pos   # per-product limit
        sell_room = LIM_VEV + pos

        delta_added = 0.0

        # Take cheap asks: price < fair - edge. Each fill pushes running_delta up
        # by qty * delta; stop when we'd breach the delta budget.
        buy_threshold = our_fair - EDGE_TAKE_VEV
        for ap in asks:
            if ap >= buy_threshold:
                break
            if buy_room <= 0:
                break
            vol_avail = -od.sell_orders[ap]
            if vol_avail <= 0:
                continue
            # Max qty from delta budget
            slack = NET_DELTA_BUDGET - (running_delta + delta_added)
            if delta > 1e-6 and slack < delta:
                break
            max_from_delta = int(slack / delta) if delta > 1e-6 else vol_avail
            qty = min(vol_avail, buy_room, max_from_delta)
            if qty <= 0:
                break
            orders.append(Order(sym, ap, qty))
            buy_room -= qty
            delta_added += qty * delta

        # Dump expensive bids: price > fair + edge. Rare for VEVs (bots quote near fair).
        sell_threshold = our_fair + EDGE_TAKE_VEV
        for bp in bids:
            if bp <= sell_threshold:
                break
            if sell_room <= 0:
                break
            vol_avail = od.buy_orders[bp]
            if vol_avail <= 0:
                continue
            # Selling reduces running_delta (good if we were long above target)
            slack_down = NET_DELTA_BUDGET + (running_delta + delta_added)
            if delta > 1e-6 and slack_down < delta:
                break
            max_from_delta = int(slack_down / delta) if delta > 1e-6 else vol_avail
            qty = min(vol_avail, sell_room, max_from_delta)
            if qty <= 0:
                break
            orders.append(Order(sym, bp, -qty))
            sell_room -= qty
            delta_added -= qty * delta

        return orders, delta_added

    # -------------------- VELVETFRUIT MM + hedge --------------------

    def _fv_velvetfruit(self, bids: List[int], asks: List[int], td: dict) -> float:
        if bids and asks:
            return (bids[0] + asks[0]) / 2.0
        if bids:
            return bids[0] + 3.0
        if asks:
            return asks[0] - 3.0
        return td.get("last_velv_fv", 5250.0)

    def _trade_velvetfruit(
        self, od: OrderDepth, pos: int, target: int, td: dict
    ) -> List[Order]:
        orders: List[Order] = []
        bids, asks = self._sorted_book(od)
        fv = self._fv_velvetfruit(bids, asks, td)
        td["last_velv_fv"] = fv
        fv_r = int(round(fv))

        buy_room = LIM_VELVETFRUIT - pos
        sell_room = LIM_VELVETFRUIT + pos

        buy_ordered = 0
        sell_ordered = 0

        # Take mispriced (rare on VELVETFRUIT — tight book).
        for ap in asks:
            if ap > fv_r - EDGE_TAKE_VELVETFRUIT:
                break
            vol = -od.sell_orders[ap]
            qty = min(vol, buy_room - buy_ordered)
            if qty <= 0:
                break
            orders.append(Order(VELVETFRUIT, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + EDGE_TAKE_VELVETFRUIT:
                break
            vol = od.buy_orders[bp]
            qty = min(vol, sell_room - sell_ordered)
            if qty <= 0:
                break
            orders.append(Order(VELVETFRUIT, bp, -qty))
            sell_ordered += qty

        # Quote passively: penny-jump inside layer 2 (which is ±2..4 from fv).
        our_bid = bids[0] + 1 if bids else fv_r - 2
        our_ask = asks[0] - 1 if asks else fv_r + 2

        # Hedge skew: target_dist > 0 → want to buy; target_dist < 0 → want to sell.
        target_dist = target - pos
        if target_dist > 0:
            buy_size = MM_BASE_SIZE_VELVETFRUIT + min(target_dist, 40)
            sell_size = max(5, MM_BASE_SIZE_VELVETFRUIT - target_dist // 2)
            our_bid = min(our_bid + 1, fv_r - 1)  # bid more aggressively
        elif target_dist < 0:
            sell_size = MM_BASE_SIZE_VELVETFRUIT + min(-target_dist, 40)
            buy_size = max(5, MM_BASE_SIZE_VELVETFRUIT + target_dist // 2)
            our_ask = max(our_ask - 1, fv_r + 1)
        else:
            buy_size = MM_BASE_SIZE_VELVETFRUIT
            sell_size = MM_BASE_SIZE_VELVETFRUIT

        # Inventory skew (in addition to hedge target) — prevents blowups.
        if pos > SKEW_THRESHOLD_VELVETFRUIT:
            our_ask = max(fv_r + 1, our_ask - 1)
        elif pos < -SKEW_THRESHOLD_VELVETFRUIT:
            our_bid = min(fv_r - 1, our_bid + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        buy_qty = min(buy_size, buy_room - buy_ordered)
        sell_qty = min(sell_size, sell_room - sell_ordered)

        if buy_qty > 0:
            orders.append(Order(VELVETFRUIT, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(VELVETFRUIT, our_ask, -sell_qty))

        return orders

    # -------------------- HYDROGEL MM --------------------

    def _fv_hydrogel(self, bids: List[int], asks: List[int], td: dict) -> float:
        if bids and asks:
            return (bids[0] + asks[0]) / 2.0
        if bids:
            return bids[0] + 8.0
        if asks:
            return asks[0] - 8.0
        return td.get("last_hg_fv", 10000.0)

    def _trade_hydrogel(self, od: OrderDepth, pos: int, td: dict) -> List[Order]:
        orders: List[Order] = []
        bids, asks = self._sorted_book(od)
        fv = self._fv_hydrogel(bids, asks, td)
        td["last_hg_fv"] = fv
        fv_r = int(round(fv))

        buy_room = LIM_HYDROGEL - pos
        sell_room = LIM_HYDROGEL + pos

        buy_ordered = 0
        sell_ordered = 0

        # Take anything clearly under / over FV.
        for ap in asks:
            if ap > fv_r - EDGE_TAKE_HYDROGEL:
                break
            vol = -od.sell_orders[ap]
            qty = min(vol, buy_room - buy_ordered)
            if qty <= 0:
                break
            orders.append(Order(HYDROGEL, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + EDGE_TAKE_HYDROGEL:
                break
            vol = od.buy_orders[bp]
            qty = min(vol, sell_room - sell_ordered)
            if qty <= 0:
                break
            orders.append(Order(HYDROGEL, bp, -qty))
            sell_ordered += qty

        # MM: penny-jump inside layer 2 (15-wide nominal).
        our_bid = bids[0] + 1 if bids else fv_r - 8
        our_ask = asks[0] - 1 if asks else fv_r + 8

        # Inventory skew
        if pos > SKEW_THRESHOLD_HYDROGEL:
            our_ask = max(fv_r + 1, our_ask - 1)
        elif pos < -SKEW_THRESHOLD_HYDROGEL:
            our_bid = min(fv_r - 1, our_bid + 1)

        if our_bid >= our_ask:
            our_bid = fv_r - 1
            our_ask = fv_r + 1

        buy_qty = min(MM_BASE_SIZE_HYDROGEL, buy_room - buy_ordered)
        sell_qty = min(MM_BASE_SIZE_HYDROGEL, sell_room - sell_ordered)

        if buy_qty > 0:
            orders.append(Order(HYDROGEL, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(HYDROGEL, our_ask, -sell_qty))

        return orders
