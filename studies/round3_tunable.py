"""Tunable harry_potter_v4 (portal +17,449). Identical trade logic; PARAMS
copied into instance attrs from PROSPERITY_PARAMS env var. Param search
target for studies/round3_param_search.yaml."""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Optional, Tuple
import json
import os


def _load_param_overrides():
    raw = os.environ.get("PROSPERITY_PARAMS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return False


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
    HYDROGEL: 200,
    VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

# Hardcoded fair-value + sigma fallbacks for warmup. From 30k tick historical data.
FALLBACK_FV: Dict[str, float] = {VELVETFRUIT: 5250.0, VEV_5000: 255.0, VEV_5100: 167.0, VEV_5200: 95.0, VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0}
FALLBACK_SIGMA: Dict[str, float] = {VELVETFRUIT: 15.0, VEV_5000: 14.0, VEV_5100: 13.0, VEV_5200: 10.0, VEV_5300: 6.0, VEV_5400: 3.4, VEV_5500: 1.7}

# MR only on VELVETFRUIT (tight spread + random walk + clean reversion =>
# passive MR orders fill well). HYDROGEL's wider spread makes passive MR
# slow-filling; VEV_4000/4500's proportional offsets reward OBI MM more
# than MR. Tested both on CSV — these routings are best.
MR_ASSETS = (VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500)
VEV_MM_ASSETS = (VEV_4000, VEV_4500)
OBI_MM_ASSETS = (HYDROGEL,)


class Trader:
    # -------------------- Mean-reversion params --------------------
    # EMA_ALPHA = 0.0005 → half-life ~1,386 ticks. Slow EMA works best because
    # the true per-asset mean is stable (the random walks hover around a long-run
    # anchor); faster EMAs chase short-term noise instead of measuring deviation.
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01           # faster for sigma estimation
    MR_K = 0.55                # scales target position size with z. z=1.5 → 83% of limit.
    MR_MAX_FRAC = 0.85         # clip target at this fraction of position limit
    MR_MIN_N = 50              # warmup ticks before trusting the EMA
    MR_MM_LEVEL_SIZE = 30      # per-level size on passive MM quotes
    MR_MM_LEVELS = 2           # how many price levels to post (inside the spread)
    MR_TAKE_Z = 1.2            # cross-spread above this |z|
    MR_TAKE_MAX = 40           # max contracts to cross-spread per tick
    MR_TIGHT_SPREAD_MIN = 2

    # -------------------- VEV MM params (same as v3) --------------------
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # Categorical toggles (override via PROSPERITY_PARAMS).
    OBI_CONFIRM_TAKE = False  # only cross-spread when OBI agrees with z
    INCLUDE_5400_MR = True    # if False, VEV_5400 routes to OBI MM
    INCLUDE_5500_MR = True

    # -------------------- Entry --------------------

    def __init__(self):
        # Copy any PROSPERITY_PARAMS overrides into instance attrs. Trade
        # methods then read self.X exactly like the original harry_v4 code.
        overrides = _load_param_overrides()
        for k, v in overrides.items():
            if k in ("OBI_CONFIRM_TAKE", "INCLUDE_5400_MR", "INCLUDE_5500_MR"):
                setattr(self, k, _coerce_bool(v))
            elif k in ("VEV_SIZE_MILD_BIG", "VEV_SIZE_MILD_SMALL"):
                pair = list(self.VEV_SIZES_MILD)
                if k.endswith("_BIG"):
                    pair[0] = int(v)
                else:
                    pair[1] = int(v)
                self.VEV_SIZES_MILD = tuple(pair)
            elif k in ("VEV_SIZE_STRONG_BIG", "VEV_SIZE_STRONG_SMALL"):
                pair = list(self.VEV_SIZES_STRONG)
                if k.endswith("_BIG"):
                    pair[0] = int(v)
                else:
                    pair[1] = int(v)
                self.VEV_SIZES_STRONG = tuple(pair)
            elif k in ("VEV_SIZE_EXTREME_BIG", "VEV_SIZE_EXTREME_SMALL"):
                pair = list(self.VEV_SIZES_EXTREME)
                if k.endswith("_BIG"):
                    pair[0] = int(v)
                else:
                    pair[1] = int(v)
                self.VEV_SIZES_EXTREME = tuple(pair)
            else:
                # Numeric param: coerce to type of the current attribute if known
                if hasattr(self, k):
                    cur = getattr(self, k)
                    if isinstance(cur, bool):
                        v = _coerce_bool(v)
                    elif isinstance(cur, int):
                        v = int(v)
                    elif isinstance(cur, float):
                        v = float(v)
                setattr(self, k, v)

        # Build asset routing based on the (possibly-overridden) toggles.
        mr = [VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300]
        obi_mm = [VEV_4000, VEV_4500, HYDROGEL]
        if self.INCLUDE_5400_MR:
            mr.append(VEV_5400)
        else:
            obi_mm.append(VEV_5400)
        if self.INCLUDE_5500_MR:
            mr.append(VEV_5500)
        else:
            obi_mm.append(VEV_5500)
        self._mr_assets = tuple(mr)
        self._obi_mm_assets = tuple(obi_mm)

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product in self._mr_assets:
                result[product] = self._trade_mr(product, od, pos, td)
            elif product in self._obi_mm_assets:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    # -------------------- MR execution (HYDROGEL, VELVETFRUIT) --------------------

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
        # Target position from z-score
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

        # Direction we need to move
        diff = target - pos

        # (a) Aggressive cross-spread take when |z| is strong and we're behind target.
        # Optionally gate on OBI agreement (toby's idea — only take when book
        # imbalance agrees with the MR direction).
        take_ok = abs(z) >= self.MR_TAKE_Z
        if take_ok and self.OBI_CONFIRM_TAKE:
            b1_vol = od.buy_orders[best_bid]
            a1_vol = -od.sell_orders[best_ask]
            tot = b1_vol + a1_vol
            obi = 0.0 if tot == 0 else (b1_vol - a1_vol) / tot
            # z>0 (mid high, want short) needs obi<=0 (sell pressure showing).
            take_ok = (z > 0 and obi <= 0) or (z < 0 and obi >= 0)
        if take_ok:
            if diff > 0:
                # Buy up to min(diff, TAKE_MAX, buy_room). Sweep best asks.
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

        # (b) Passive MM layers — bias the BID side size up when we want long,
        # ASK side size up when we want short. Multiple levels catch more flow.
        diff_after = target - (pos + buy_ordered - sell_ordered)

        # Big-side size per level; small-side is the usual penny-jump baseline.
        big_side_size = self.MR_MM_LEVEL_SIZE
        small_side_size = max(5, self.MR_MM_LEVEL_SIZE // 3)

        if diff_after > 0:
            buy_size_each = big_side_size
            sell_size_each = small_side_size
        elif diff_after < 0:
            buy_size_each = small_side_size
            sell_size_each = big_side_size
        else:
            buy_size_each = small_side_size
            sell_size_each = small_side_size

        # Position-limit safety: sum of passive buys ≤ buy_room − buy_ordered
        remaining_buy_room = max(0, buy_room - buy_ordered)
        remaining_sell_room = max(0, sell_room - sell_ordered)

        for level in range(self.MR_MM_LEVELS):
            # Layer orders INSIDE the spread so each level keeps priority vs the
            # bot. level=0: best_bid+1 / best_ask-1; level=1: best_bid+2 /
            # best_ask-2; etc. Stop when the ladder would cross itself.
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
            # First observation: seed with fallback for stability.
            prev_ema = FALLBACK_FV.get(product, mid)

        residual = mid - prev_ema
        new_ema = prev_ema + self.EMA_ALPHA * residual
        new_var = prev_var + self.VAR_ALPHA * (residual * residual - prev_var)
        new_n = n + 1

        td[ema_key] = new_ema
        td[var_key] = max(1.0, new_var)  # floor to avoid div-by-zero
        td[n_key] = new_n

        sigma = max(1.0, new_var) ** 0.5
        return new_ema, sigma, new_n

    # -------------------- VEV OBI-tilted MM (from v3) --------------------

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

    # -------------------- Helpers --------------------

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}