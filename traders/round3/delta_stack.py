# delta_stack.py — Strategy B: leverage VELVET's MR signal across all coupled vouchers.
#
# HYPOTHESIS: Vouchers move WITH VELVET (empirical delta correlations 0.37-0.79 from
# 30k ticks). So when VELVET mean-reverts from one extreme, vouchers do too. Taking
# full position on multiple vouchers multiplies the same signal's PnL.
#
# Deltas measured from d(VEV)/d(VELVET) regression:
#   VEV_4000: 0.745 (high — almost moves 1:1)
#   VEV_4500: 0.662
#   VEV_5000: 0.654
#   VEV_5100: 0.577
#   VEV_5200: 0.437
#   VEV_5300: 0.273
#   VEV_5400: 0.129
#   VEV_5500: 0.055
#
# When VELVET z > 1.5: go SHORT VELVET (−200) AND SHORT all vouchers delta-weighted
# up to −300 each. Total VELVET-equivalent short ≈ 200 + 300×sum(deltas) ≈ 1200.
# When VELVET z < -1.5: opposite, go LONG to full.
# Close positions when |z| < 0.3.
#
# Expected: one cycle = sum of (per-product move) × position. If VELVET moves 4
# XIRECs, VEV_4000 moves ~3, VEV_5000 ~2.6, etc. Total cycle PnL ≈ 200×4 + 300×3 +
# 300×2.6 + ... ≈ 6-10k per cycle. 3-5 cycles per day = 20-50k.
"""delta_stack — slam ±full position on VELVET AND all vouchers when VELVET z is extreme."""
try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple
import json


HYDROGEL = "HYDROGEL_PACK"
VELVETFRUIT = "VELVETFRUIT_EXTRACT"
VEV_4000 = "VEV_4000"; VEV_4500 = "VEV_4500"
VEV_5000 = "VEV_5000"; VEV_5100 = "VEV_5100"
VEV_5200 = "VEV_5200"; VEV_5300 = "VEV_5300"
VEV_5400 = "VEV_5400"; VEV_5500 = "VEV_5500"
VEV_6000 = "VEV_6000"; VEV_6500 = "VEV_6500"

LIMITS = {HYDROGEL: 200, VELVETFRUIT: 200,
          VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
          VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
          VEV_6000: 300, VEV_6500: 300}

# Empirical deltas (from 30k R3 ticks regression)
DELTAS = {
    VEV_4000: 0.745, VEV_4500: 0.662, VEV_5000: 0.654, VEV_5100: 0.577,
    VEV_5200: 0.437, VEV_5300: 0.273, VEV_5400: 0.129, VEV_5500: 0.055,
}
STACKED_VOUCHERS = list(DELTAS.keys())

FALLBACK_FV = {VELVETFRUIT: 5250.0}
FALLBACK_SIGMA = {VELVETFRUIT: 15.0}


class Trader:
    # VELVET MR signal
    VELVET_EMA_ALPHA = 0.0005
    VELVET_VAR_ALPHA = 0.01
    VELVET_MIN_N = 50

    # Thresholds for stacking
    STACK_OPEN_Z = 1.2       # open full-size stacked position at this |z|
    STACK_CLOSE_Z = 0.3      # unwind at this |z|
    VELVET_K = 0.55          # for VELVET's own target
    VELVET_MAX_FRAC = 0.85

    # Stacked voucher sizing — fraction of each voucher's limit to use
    VOUCHER_STACK_FRAC = 0.90

    # HYDROGEL / deep-ITM as safe OBI-MM base
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1; OBI_SKEW_2 = 0.4; OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8); VEV_SIZES_STRONG = (30, 2); VEV_SIZES_EXTREME = (40, 3)

    # Take max when entering stacked position
    STACK_TAKE_MAX = 80

    def run(self, state: TradingState):
        td = self._parse_td(state.traderData)
        result: Dict[str, List[Order]] = {}

        # Compute VELVET signal first
        velvet_z = 0.0
        velvet_mid = None
        if VELVETFRUIT in state.order_depths:
            od = state.order_depths[VELVETFRUIT]
            if od.buy_orders and od.sell_orders:
                best_bid = max(od.buy_orders); best_ask = min(od.sell_orders)
                if best_ask - best_bid >= 2:
                    velvet_mid = (best_bid + best_ask) / 2.0
                    fv, sigma, n = self._update_ema(td, VELVETFRUIT, velvet_mid)
                    if n >= self.VELVET_MIN_N and sigma > 0:
                        velvet_z = (velvet_mid - fv) / sigma

        # Trade VELVET itself (fullsize at threshold)
        if VELVETFRUIT in state.order_depths:
            result[VELVETFRUIT] = self._trade_velvet_stack(
                state.order_depths[VELVETFRUIT], state.position.get(VELVETFRUIT, 0), velvet_z)

        # Trade each voucher with a scaled-to-delta target position
        for sym in STACKED_VOUCHERS:
            if sym in state.order_depths:
                result[sym] = self._trade_voucher_stack(
                    sym, state.order_depths[sym], state.position.get(sym, 0), velvet_z)

        # HYDROGEL: safe OBI-MM
        if HYDROGEL in state.order_depths:
            result[HYDROGEL] = self._trade_vev_mm(HYDROGEL, state.order_depths[HYDROGEL],
                                                    state.position.get(HYDROGEL, 0))

        # Dead options
        for sym in (VEV_6000, VEV_6500):
            if sym in state.order_depths:
                result[sym] = []

        return result, 0, json.dumps(td)

    def _trade_velvet_stack(self, od: OrderDepth, pos: int, z: float) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        limit = LIMITS[VELVETFRUIT]

        # Target
        if abs(z) >= self.STACK_OPEN_Z:
            target_frac = max(-self.VELVET_MAX_FRAC, min(self.VELVET_MAX_FRAC, -self.VELVET_K * z))
            target = int(target_frac * limit)
        elif abs(z) < self.STACK_CLOSE_Z:
            target = 0  # flatten
        else:
            # Transitional zone — maintain current position
            return self._passive_layers(VELVETFRUIT, od, pos, 0)

        return self._execute_toward_target(VELVETFRUIT, od, pos, target,
                                             aggressive=abs(z) >= self.STACK_OPEN_Z)

    def _trade_voucher_stack(self, sym: str, od: OrderDepth, pos: int, velvet_z: float) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        delta = DELTAS[sym]

        # Target scaled by delta intensity
        if abs(velvet_z) >= self.STACK_OPEN_Z:
            # Full-size stack
            sign = -1 if velvet_z > 0 else 1
            target = int(sign * self.VOUCHER_STACK_FRAC * limit * min(1.0, abs(delta) + 0.3))
        elif abs(velvet_z) < self.STACK_CLOSE_Z:
            target = 0
        else:
            return self._passive_layers(sym, od, pos, 0)

        # Wide-spread products: never cross
        if spread >= 10:
            # Only passive
            return self._passive_layers(sym, od, pos, target - pos)
        return self._execute_toward_target(sym, od, pos, target,
                                             aggressive=abs(velvet_z) >= self.STACK_OPEN_Z)

    def _execute_toward_target(self, sym: str, od: OrderDepth, pos: int, target: int,
                                 aggressive: bool) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        buy_room = limit - pos; sell_room = limit + pos
        diff = target - pos
        orders = []
        buy_ordered = sell_ordered = 0

        if aggressive and spread <= 6:  # only cross on tight-spread
            if diff > 0:
                cap = min(diff, self.STACK_TAKE_MAX, buy_room)
                for ap in asks:
                    if cap <= 0: break
                    q = min(-od.sell_orders[ap], cap)
                    if q <= 0: continue
                    orders.append(Order(sym, ap, q)); buy_ordered += q; cap -= q
            elif diff < 0:
                cap = min(-diff, self.STACK_TAKE_MAX, sell_room)
                for bp in bids:
                    if cap <= 0: break
                    q = min(od.buy_orders[bp], cap)
                    if q <= 0: continue
                    orders.append(Order(sym, bp, -q)); sell_ordered += q; cap -= q

        # Passive layers toward target
        diff_after = target - (pos + buy_ordered - sell_ordered)
        orders.extend(self._passive_layers(sym, od, pos + buy_ordered - sell_ordered, diff_after))
        return orders

    def _passive_layers(self, sym: str, od: OrderDepth, pos: int, target_diff: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < 2: return []
        big, small = 25, 8
        if target_diff > 0: buy_e, sell_e = big, small
        elif target_diff < 0: buy_e, sell_e = small, big
        else: buy_e = sell_e = small
        limit = LIMITS[sym]
        rb = max(0, limit - pos); rs = max(0, limit + pos)
        orders = []
        for lvl in range(3):
            our_bid = best_bid + 1 + lvl; our_ask = best_ask - 1 - lvl
            if our_bid >= our_ask: break
            b = min(buy_e, rb); a = min(sell_e, rs)
            if b > 0: orders.append(Order(sym, our_bid, b)); rb -= b
            if a > 0: orders.append(Order(sym, our_ask, -a)); rs -= a
        return orders

    def _update_ema(self, td, product, mid):
        ek = f"ema_{product}"; vk = f"var_{product}"; nk = f"n_{product}"
        pe = td.get(ek); pv = td.get(vk, FALLBACK_SIGMA.get(product, 30.0) ** 2); n = td.get(nk, 0)
        if pe is None: pe = FALLBACK_FV.get(product, mid)
        r = mid - pe
        ne = pe + self.VELVET_EMA_ALPHA * r
        nv = pv + self.VELVET_VAR_ALPHA * (r * r - pv)
        td[ek] = ne; td[vk] = max(1.0, nv); td[nk] = n + 1
        return ne, max(1.0, nv) ** 0.5, n + 1

    def _trade_vev_mm(self, product, od, pos):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid = bids[0]; best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN: return []
        our_bid = best_bid + 1; our_ask = best_ask - 1
        if our_bid >= our_ask: return []
        b1v = od.buy_orders[best_bid]; a1v = -od.sell_orders[best_ask]
        obi = 0.0 if (b1v + a1v) == 0 else (b1v - a1v) / (b1v + a1v)
        buy_size, sell_size = self._obi_sizes(obi)
        limit = LIMITS[product]
        soft = int(self.VEV_SOFT_POS_FRAC * limit)
        buy_room = limit - pos; sell_room = limit + pos
        bq = min(buy_size, max(0, buy_room)); sq = min(sell_size, max(0, sell_room))
        if pos >= soft: bq = 0
        elif pos <= -soft: sq = 0
        orders = []
        if bq > 0: orders.append(Order(product, our_bid, bq))
        if sq > 0: orders.append(Order(product, our_ask, -sq))
        return orders

    def _obi_sizes(self, obi):
        a = abs(obi)
        if a < self.OBI_SKEW_1: return (self.VEV_BASE_SIZE, self.VEV_BASE_SIZE)
        if a < self.OBI_SKEW_2: big, small = self.VEV_SIZES_MILD
        elif a < self.OBI_SKEW_3: big, small = self.VEV_SIZES_STRONG
        else: big, small = self.VEV_SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)

    def _parse_td(self, s):
        if not s: return {}
        try: return json.loads(s)
        except: return {}
