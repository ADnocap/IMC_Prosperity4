"""Toby — selective MR variant of harry_potter_v4. Trades less often,
smaller, only on high-confidence signals to dampen PnL swings.

Gates: stricter take threshold (z>=2.0), smaller targets (K=0.4,
max=0.6), smaller per-trade size (TAKE_MAX=20, LEVEL=18), OBI
confirmation on takes (only cross when OBI agrees with z direction),
quiet-period damping (1 MM level when |z|<0.3), drop MR on tiny-sigma
vouchers (5400/5500). HYDROGEL stays on OBI MM. Full notes at top of
toby_notes.md or in the FINDINGS doc.
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

LIMITS: Dict[str, int] = {
    HYDROGEL: 200, VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
}

FALLBACK_FV: Dict[str, float] = {VELVETFRUIT: 5250.0, VEV_5000: 255.0,
                                  VEV_5100: 167.0, VEV_5200: 95.0,
                                  VEV_5300: 47.0}
FALLBACK_SIGMA: Dict[str, float] = {VELVETFRUIT: 15.0, VEV_5000: 14.0,
                                     VEV_5100: 13.0, VEV_5200: 10.0,
                                     VEV_5300: 6.0}

# MR only on assets with non-trivial sigma. Drop 5400/5500.
MR_ASSETS = (VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300)
# Was VEV_4000/4500 in harry; add 5400/5500 here for OBI MM treatment.
VEV_MM_ASSETS = (VEV_4000, VEV_4500, VEV_5400, VEV_5500)
OBI_MM_ASSETS = (HYDROGEL,)


class Trader:
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01

    # Selective MR knobs
    MR_K = 0.40              # was 0.55 (gentler scaling)
    MR_MAX_FRAC = 0.60       # was 0.85 (cap at 60% of limit)
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 18    # was 30 (smaller passive)
    MR_MM_LEVELS = 2
    MR_TAKE_Z = 2.0          # was 1.2 (much stricter take threshold)
    MR_TAKE_MAX = 20         # was 40 (smaller take per tick)
    MR_TIGHT_SPREAD_MIN = 2

    # New gates
    OBI_CONFIRM_REQUIRED = True   # require OBI to agree with z sign on takes
    QUIET_Z_THRESHOLD = 0.3       # below this, post only 1 MM level

    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
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

        # OBI for confirmation gate (best-level only — same as harry).
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total

        buy_room = limit - pos
        sell_room = limit + pos
        buy_ordered = 0
        sell_ordered = 0
        orders: List[Order] = []
        diff = target - pos

        # ---- Cross-spread take (now gated on z magnitude AND OBI agreement)
        if abs(z) >= self.MR_TAKE_Z:
            # z>0 means mid is high vs FV -> we want to SHORT.
            # OBI<=0 means more sell pressure -> agrees with our short bias.
            obi_agrees = (z > 0 and obi <= 0) or (z < 0 and obi >= 0) or (not self.OBI_CONFIRM_REQUIRED)
            if obi_agrees:
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

        # ---- Passive MM (skewed toward target)
        diff_after = target - (pos + buy_ordered - sell_ordered)
        big_side_size = self.MR_MM_LEVEL_SIZE
        small_side_size = max(4, self.MR_MM_LEVEL_SIZE // 3)

        if diff_after > 0:
            buy_size_each = big_side_size
            sell_size_each = small_side_size
        elif diff_after < 0:
            buy_size_each = small_side_size
            sell_size_each = big_side_size
        else:
            buy_size_each = small_side_size
            sell_size_each = small_side_size

        # Quiet-period damping: only 1 layer when no signal.
        active_levels = self.MR_MM_LEVELS
        if abs(z) < self.QUIET_Z_THRESHOLD:
            active_levels = 1

        remaining_buy_room = max(0, buy_room - buy_ordered)
        remaining_sell_room = max(0, sell_room - sell_ordered)

        for level in range(active_levels):
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
