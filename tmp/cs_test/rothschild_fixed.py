"""Rothschild — stratton baseline + cross-strike vertical-spread MR overlay.
See analysis/round3/cross_strike.md.

Stratton handles HYDROGEL, VELVET, VEV_4000/4500/5000/5100/5200 (where its
MR/OBI MM dominates). For VEV_5300/5400/5500 we replace the per-strike MR
with cross-strike vertical-spread MR — the 5300/5400 vert has Sharpe 162
(half-life 9 ticks, EV 7,575/day) on the 3-day historical data. Naturally
delta-light (~0.20 spread delta), which is exactly the size-up unlock we
need without spot-hedge cost.

CANNOT BE MC-VALIDATED: Rust sim runs each voucher on an independent FV
process, so the spread mean-reversion seen in real data is decoupled in MC.
This trader is intended for portal subs only.
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

# Stratton (search-2 #233) MR/OBI core — applies to non-cross-strike strikes
MR_ASSETS_ROTH = (VELVETFRUIT, VEV_5000, VEV_5100)
VEV_MM_ASSETS_ROTH = (VEV_4000, VEV_4500)  # 5500 moved to cross-strike layer
OBI_MM_ASSETS_ROTH = (HYDROGEL,)
CROSS_STRIKE_ASSETS = (VEV_5200, VEV_5300, VEV_5400, VEV_5500)
STRIKES_CS = {VEV_5200: 5200, VEV_5300: 5300, VEV_5400: 5400, VEV_5500: 5500}

# BS smile (pooled across days 0/1/2 from analysis/round3/cross_strike.json):
#   iv(K, S) = SMILE_A + SMILE_B * m + SMILE_C * m²    where m = log(K/S)
SMILE_A = 0.24874922943238548
SMILE_B = 0.0033068871733395525
SMILE_C = 0.027240641751624436
SMILE_T = 6.0 / 365.0  # constant per smile-fit convention

# Cross-strike spread MR
# The 3 most reliable spreads (cross_strike.json, daily Sharpe ranked):
#   (5300, 5400) S=162 EV=7575 hl=9
#   (5300, 5500) S=110 EV=3415 hl=7.6
#   (Tail: 5400 cheap z=-0.73 vs smile, 5300 rich z=+0.36)
CS_PAIRS = [
    # (K_low, K_high, target spread position when dev > +k_sigma)
    # Sizes from final_audit.md sec 7 — 3-day historical replay:
    #   (5200, 5400) size 30: +11,265 over 3 days, 436 trades, all days +
    #   (5300, 5400) size 40: +4,540 over 3 days, 101 trades, all days +
    #   (5300, 5500) size 20: +3,470 over 3 days, 176 trades, all days +
    # 5200/5400 is the workhorse: 4x entry frequency at lower concentration.
    (VEV_5200, VEV_5400, 30),
    (VEV_5300, VEV_5400, 40),
    (VEV_5300, VEV_5500, 20),
]

# Trigger params — set conservative; MC can't validate, so we want only
# clear signals to fire on portal.
CS_K_SIGMA = 2.0            # |dev / dev_std| trigger (was 1.5)
CS_HOLD_TICKS = 30          # unwind via passive quotes after this many ticks
CS_DEV_STD_FALLBACK = 1.1   # rough std from cross_strike.json before EWMA warms up
CS_TAKE_MAX_PER_TICK = 6    # max aggressive lots per spread-leg per tick
CS_PASSIVE_SIZE = 10        # passive quote size while waiting for entry/exit

# Static structural overlay: DISABLED for v1 (was flying always-on tilt).
# Reason: in MC the static tilt loses ~10k because voucher FVs are independent
# of spot — so the "rich"/"cheap" mispricings vanish. Keep DISABLED until we
# get a portal sub confirming the cross-strike MR alone helps.
STATIC_TARGETS: Dict[str, int] = {}


# === stratton constants (search 2 winner #233) ============================
class Trader:
    EMA_ALPHA = 4.308428675778431e-05
    VAR_ALPHA = 0.03588256506509171
    MR_K = 0.06099200122271319
    MR_MAX_FRAC = 0.4925933073268412
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 14
    MR_MM_LEVELS = 1
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

    # === BS pricing ===========================================
    def _bs_call(self, S: float, K: float, sigma: float, T: float) -> float:
        if T <= 0 or sigma <= 0 or S <= 0:
            return max(S - K, 0.0)
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        N = NormalDist().cdf
        return S * N(d1) - K * N(d2)

    def _smile_iv(self, K: float, S: float) -> float:
        if S <= 0:
            return SMILE_A
        m = math.log(K / S)
        return SMILE_A + SMILE_B * m + SMILE_C * m * m

    def _smile_fair(self, K: float, S: float) -> float:
        iv = max(0.05, self._smile_iv(K, S))
        return self._bs_call(S, K, iv, SMILE_T)

    # === run loop ==============================================
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        result: Dict[str, List[Order]] = {}

        # Spot mid for cross-strike pricing
        velvet_od = state.order_depths.get(VELVETFRUIT)
        S = self._mid(velvet_od) if velvet_od else FALLBACK_FV[VELVETFRUIT]
        if S is None:
            S = FALLBACK_FV[VELVETFRUIT]

        # Cross-strike target positions for VEV_5300/5400/5500
        cs_targets = self._cross_strike_targets(state, td, S)

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in CROSS_STRIKE_ASSETS:
                target = cs_targets.get(product, 0) + STATIC_TARGETS.get(product, 0)
                result[product] = self._trade_cross_strike(product, od, pos, target)
            elif product in MR_ASSETS_ROTH:
                target_offset = STATIC_TARGETS.get(product, 0)
                result[product] = self._trade_mr(product, od, pos, td, target_offset)
            elif product in VEV_MM_ASSETS_ROTH or product in OBI_MM_ASSETS_ROTH:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    # === cross-strike layer ====================================
    def _cross_strike_targets(self, state: TradingState, td: dict, S: float) -> Dict[str, int]:
        """For each (Klow, Khigh) pair: compute spread deviation vs BS-smile
        theoretical, EWMA the std, then set target spread position based on
        signal direction."""
        targets: Dict[str, int] = {}
        for low_sym, high_sym, spread_size in CS_PAIRS:
            od_low = state.order_depths.get(low_sym)
            od_high = state.order_depths.get(high_sym)
            if not od_low or not od_high:
                continue
            mid_low = self._mid(od_low)
            mid_high = self._mid(od_high)
            if mid_low is None or mid_high is None:
                continue

            Klow = STRIKES_CS[low_sym]
            Khigh = STRIKES_CS[high_sym]
            theo_low = self._smile_fair(Klow, S)
            theo_high = self._smile_fair(Khigh, S)
            mkt_spread = mid_low - mid_high
            theo_spread = theo_low - theo_high
            dev = mkt_spread - theo_spread

            # EWMA dev std
            std_key = f"cs_std_{low_sym}_{high_sym}"
            mean_key = f"cs_mean_{low_sym}_{high_sym}"
            prev_mean = td.get(mean_key, 0.0)
            prev_var = td.get(std_key, CS_DEV_STD_FALLBACK ** 2)
            new_mean = 0.99 * prev_mean + 0.01 * dev
            new_var = 0.98 * prev_var + 0.02 * (dev - new_mean) ** 2
            td[mean_key] = new_mean
            td[std_key] = max(0.5, new_var)
            std = max(0.5, new_var ** 0.5)

            # Trigger
            z = (dev - new_mean) / std
            tgt = 0
            if z > CS_K_SIGMA:
                # spread is rich → SHORT spread (sell low, buy high)
                tgt = -spread_size
            elif z < -CS_K_SIGMA:
                tgt = +spread_size

            # Map spread target to per-leg position adjustment
            if tgt != 0:
                targets[low_sym] = targets.get(low_sym, 0) + tgt
                targets[high_sym] = targets.get(high_sym, 0) - tgt
        return targets

    def _trade_cross_strike(self, product: str, od: OrderDepth, pos: int, target: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []

        limit = LIMITS[product]
        target = max(-limit, min(limit, target))
        diff = target - pos
        buy_room = limit - pos
        sell_room = limit + pos

        orders: List[Order] = []
        # Aggressive take up to CS_TAKE_MAX_PER_TICK to hit target quickly
        if diff > 0:
            cap = min(diff, CS_TAKE_MAX_PER_TICK, buy_room)
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
            cap = min(-diff, CS_TAKE_MAX_PER_TICK, sell_room)
            for bp in bids:
                if cap <= 0:
                    break
                vol = od.buy_orders[bp]
                qty = min(vol, cap)
                if qty <= 0:
                    continue
                orders.append(Order(product, bp, -qty))
                cap -= qty

        # Plus penny-jump passive quotes for residual + bleed
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid < our_ask:
            # Bias size toward the side that helps us reach target
            if diff > 0:
                bsize, asize = CS_PASSIVE_SIZE, max(2, CS_PASSIVE_SIZE // 3)
            elif diff < 0:
                bsize, asize = max(2, CS_PASSIVE_SIZE // 3), CS_PASSIVE_SIZE
            else:
                bsize = asize = max(2, CS_PASSIVE_SIZE // 2)
            # Re-evaluate room after takes (worst-case = room before takes since takes only reduce open room)
            taken_buy = sum(o.quantity for o in orders if o.quantity > 0)
            taken_sell = -sum(o.quantity for o in orders if o.quantity < 0)
            rem_buy = max(0, buy_room - taken_buy)
            rem_sell = max(0, sell_room - taken_sell)
            bqty = min(bsize, rem_buy)
            aqty = min(asize, rem_sell)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
        return orders

    # === stratton MR (target_offset = static structural tilt) ==
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
            target_frac = max(-self.MR_MAX_FRAC, min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)
        target = max(-limit, min(limit, target + target_offset))

        buy_room = limit - pos
        sell_room = limit + pos
        diff = target - pos

        orders: List[Order] = []
        diff_after = diff
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

        remaining_buy_room = max(0, buy_room)
        remaining_sell_room = max(0, sell_room)
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

    def _mid(self, od: OrderDepth) -> Optional[float]:
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        return (bids[0] + asks[0]) / 2.0

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
