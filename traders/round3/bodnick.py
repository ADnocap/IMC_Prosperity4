"""Bodnick — Brad Bodnick, the workhorse middleman who knew which deals
to size up and which to leave small. Hypothesis test on top of
harry_potter_v4 (portal sub 370288, +17,449): same logic, but tune
EMA_ALPHA, MR_K, and MR_TAKE_Z PER asset based on the observed magnitude
and noise of each one.

Why: harry_v4 uses one EMA_ALPHA (0.0005, half-life ~1386 ticks) and one
MR_TAKE_Z (1.2) for everything from VELVET (mean 5262, sigma ~15) to
VEV_5500 (mean 6.4, sigma ~1.7). On a small-magnitude noisy voucher a
z=1.2 fires constantly on near-zero deviations; on VELVET it's much
rarer.

Tuning rationale:
  - VELVET — slow EMA + low z (same as harry_v4): clean random walk with
    big notional, slow drift to mean.
  - Near-ATM vouchers (VEV_5000-5200) — slightly faster EMA, higher z:
    noise washes out faster, but we want to be sure before crossing
    spreads.
  - OTM vouchers (VEV_5300-5500) — much faster EMA, much higher z:
    these are decay-dominated processes, so the EMA needs to chase
    theta. Z thresholds are higher because raw noise is large relative
    to magnitude.
  - Sizing on tiny-magnitude assets (5400/5500) — smaller MR_MM_LEVEL
    because each contract has tiny notional and adverse fills hurt PnL
    proportionally more.

Everything else (HYDROGEL OBI MM, VEV_4000/4500 OBI MM, dead VEV_6000/6500
skip) identical to harry_v4.
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
                                  VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0}
FALLBACK_SIGMA: Dict[str, float] = {VELVETFRUIT: 15.0, VEV_5000: 14.0,
                                     VEV_5100: 13.0, VEV_5200: 10.0,
                                     VEV_5300: 6.0, VEV_5400: 3.4, VEV_5500: 1.7}

# Per-asset MR config: alpha, take_z, mm_level_size.
# Defaults match harry_v4. Tuned values are in the inline comments.
MR_CONFIG: Dict[str, dict] = {
    VELVETFRUIT: {"alpha": 0.0005, "take_z": 1.2, "level_size": 30},
    VEV_5000:    {"alpha": 0.0008, "take_z": 1.3, "level_size": 30},
    VEV_5100:    {"alpha": 0.0008, "take_z": 1.3, "level_size": 30},
    VEV_5200:    {"alpha": 0.0010, "take_z": 1.4, "level_size": 25},
    VEV_5300:    {"alpha": 0.0015, "take_z": 1.5, "level_size": 25},
    VEV_5400:    {"alpha": 0.0020, "take_z": 1.7, "level_size": 18},
    VEV_5500:    {"alpha": 0.0030, "take_z": 1.9, "level_size": 12},
}

VEV_MM_ASSETS = (VEV_4000, VEV_4500)
OBI_MM_ASSETS = (HYDROGEL,)


class Trader:
    VAR_ALPHA = 0.01
    MR_K = 0.55
    MR_MAX_FRAC = 0.85
    MR_MIN_N = 50
    MR_MM_LEVELS = 2
    MR_TAKE_MAX = 40
    MR_TIGHT_SPREAD_MIN = 2

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
            cfg = MR_CONFIG.get(product)
            if cfg is not None:
                result[product] = self._trade_mr(
                    product, od, pos, td,
                    alpha=cfg["alpha"], take_z=cfg["take_z"],
                    level_size=cfg["level_size"],
                )
            elif product in VEV_MM_ASSETS or product in OBI_MM_ASSETS:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict,
                  *, alpha: float, take_z: float, level_size: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.MR_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0

        fv, sigma, n = self._update_ema(td, product, mid, alpha)
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

        if abs(z) >= take_z:
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
        big_side_size = level_size
        small_side_size = max(4, level_size // 3)

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

    def _update_ema(self, td: dict, product: str, mid: float,
                    alpha: float) -> Tuple[float, float, int]:
        ema_key = f"ema_{product}"
        var_key = f"var_{product}"
        n_key = f"n_{product}"

        prev_ema = td.get(ema_key)
        prev_var = td.get(var_key, FALLBACK_SIGMA.get(product, 30.0) ** 2)
        n = td.get(n_key, 0)

        if prev_ema is None:
            prev_ema = FALLBACK_FV.get(product, mid)

        residual = mid - prev_ema
        new_ema = prev_ema + alpha * residual
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
