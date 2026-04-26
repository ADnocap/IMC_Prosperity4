"""Stratton — named for Stratton Oakmont, the firm. The aggregated
wisdom of search 2's 400 trials. Trial #233 baked in.

Search 2 OOS retest (200 fresh-seed sessions, vs search 1 / max.py):
  max.py (search 1 #324) : Sharpe 1.48, mean 13,355, std 9,010, p05 -1,686
  stratton (search 2 #233): Sharpe 1.81, mean 10,884, std 5,999, p05  +646

Trade-off: ~19% lower mean, ~33% lower std, p05 flipped POSITIVE.
Risk-adjusted return is much better. Validators all PASS this round
(DSR P=1.0, PBO=0.03).

Key insight from search 2: DISABLE_TAKES=True won. Cross-spread takes
are net-negative when you're already this selective on positions
(MR_K=0.06 means at z=2 we target only 12% of limit). This is
essentially passive MM with TINY inventory accumulation.

Logic identical to harry_v4 / max.py — only the constants differ.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Optional, Tuple
import json


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

# INCLUDE_5500_MR=False -> route 5500 to OBI MM (locked from search 1).
MR_ASSETS = (VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400)
VEV_MM_ASSETS = (VEV_4000, VEV_4500, VEV_5500)
OBI_MM_ASSETS = (HYDROGEL,)


class Trader:
    # === Trial #233 winner (search 2) ===
    EMA_ALPHA = 4.308428675778431e-05   # very slow (half-life ~16,000 ticks)
    VAR_ALPHA = 0.03588256506509171
    MR_K = 0.06099200122271319          # tiny positioning
    MR_MAX_FRAC = 0.4925933073268412    # cap at 49% of limit
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 14
    MR_MM_LEVELS = 1
    MR_TIGHT_SPREAD_MIN = 2

    # Takes are DISABLED entirely — never cross spread (search 2 finding).
    DISABLE_TAKES = True
    MR_TAKE_Z = 4.217298810150091   # unused (DISABLE_TAKES=True)
    MR_TAKE_MAX = 48                # unused
    OBI_CONFIRM_TAKE = True         # locked from search 1 (irrelevant here)

    # OBI MM (locked OBI_SKEW from search 1; tiny VEV_BASE_SIZE from search 2)
    VEV_BASE_SIZE = 3
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.17962297493671575
    OBI_SKEW_2 = 0.4541715247701739
    OBI_SKEW_3 = 0.7103899562397099
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in MR_ASSETS:
                result[product] = self._trade_mr(product, od, pos, td)
            elif product in VEV_MM_ASSETS or product in OBI_MM_ASSETS:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict) -> List[Order]:
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
            target_frac = max(-self.MR_MAX_FRAC, min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)

        buy_room = limit - pos
        sell_room = limit + pos
        buy_ordered = 0
        sell_ordered = 0
        orders: List[Order] = []
        diff = target - pos

        # Cross-spread take (DISABLED in this config; gate via OBI_CONFIRM if enabled)
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

        remaining_buy_room = max(0, buy_room - buy_ordered)
        remaining_sell_room = max(0, sell_room - sell_ordered)

        for level in range(self.MR_MM_LEVELS):
            our_bid = best_bid + 1 + level
            our_ask = best_ask - 1 - level
            if our_bid >= our_ask:
                break
            bqty = min(buy_size_each, remaining_buy_room)
            aqty = min(sell_size_each, remaining_sell_room)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
                remaining_buy_room -= bqty
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
                remaining_sell_room -= aqty
        return orders

    def _update_ema(self, td: dict, product: str, mid: float) -> Tuple[float, float, int]:
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

    def _trade_vev_mm(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total
        buy_size, sell_size = self._vev_obi_sizes(obi)

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