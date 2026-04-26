"""Tunable v3 — stratton + HYDROGEL rev_z50 + L1-OBI tiered passive skew
+ BASE_MM_SIZE override. See FINDINGS_v2.md for design rationale."""

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


class Trader:
    # === Stratton (search 2 #233) winner defaults ===
    EMA_ALPHA = 4.308428675778431e-05
    VAR_ALPHA = 0.03588256506509171
    MR_K = 0.06099200122271319
    MR_MAX_FRAC = 0.4925933073268412
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 14
    MR_MM_LEVELS = 1
    MR_TAKE_Z = 4.217298810150091
    MR_TAKE_MAX = 48
    MR_TIGHT_SPREAD_MIN = 2

    # OBI MM
    VEV_BASE_SIZE = 3
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.17962297493671575
    OBI_SKEW_2 = 0.4541715247701739
    OBI_SKEW_3 = 0.7103899562397099
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # Categorical toggles (locked)
    OBI_CONFIRM_TAKE = True
    INCLUDE_5400_MR = True
    INCLUDE_5500_MR = False
    DISABLE_TAKES = True

    # === Layer B: HYDROGEL rev_z50 directional (NEW) ===
    # Defaults: rev_z DISABLED (threshold 99 = never fires).
    # The search will turn it on by lowering threshold to e.g. 1.0.
    HYDROGEL_REVZ_WINDOW = 50
    HYDROGEL_REVZ_THRESHOLD = 99.0
    HYDROGEL_REVZ_SIZE = 0
    HYDROGEL_REVZ_HOLD = 200

    # === Layer C: L1-OBI tiered passive skew (NEW) ===
    # Defaults: skew DISABLED (T1 threshold 99 = never fires).
    OBI_SKEW_T1_THRESH = 99.0
    OBI_SKEW_T2_THRESH = 99.0
    OBI_SKEW_T1_TICKS = 0
    OBI_SKEW_T2_TICKS = 0

    # === Layer F: base MM size override (NEW) ===
    # Default = stratton's VEV_BASE_SIZE so behavior is identical.
    # Search will lift this to 10-50 to test if more passive size helps.
    BASE_MM_SIZE = 3

    def __init__(self):
        overrides = _load_param_overrides()
        for k, v in overrides.items():
            if k in ("OBI_CONFIRM_TAKE", "INCLUDE_5400_MR",
                     "INCLUDE_5500_MR", "DISABLE_TAKES"):
                setattr(self, k, _coerce_bool(v))
            elif k in ("VEV_SIZE_MILD_BIG", "VEV_SIZE_MILD_SMALL"):
                pair = list(self.VEV_SIZES_MILD)
                pair[0 if k.endswith("_BIG") else 1] = int(v)
                self.VEV_SIZES_MILD = tuple(pair)
            elif k in ("VEV_SIZE_STRONG_BIG", "VEV_SIZE_STRONG_SMALL"):
                pair = list(self.VEV_SIZES_STRONG)
                pair[0 if k.endswith("_BIG") else 1] = int(v)
                self.VEV_SIZES_STRONG = tuple(pair)
            elif k in ("VEV_SIZE_EXTREME_BIG", "VEV_SIZE_EXTREME_SMALL"):
                pair = list(self.VEV_SIZES_EXTREME)
                pair[0 if k.endswith("_BIG") else 1] = int(v)
                self.VEV_SIZES_EXTREME = tuple(pair)
            else:
                if hasattr(self, k):
                    cur = getattr(self, k)
                    if isinstance(cur, bool):
                        v = _coerce_bool(v)
                    elif isinstance(cur, int):
                        v = int(v)
                    elif isinstance(cur, float):
                        v = float(v)
                setattr(self, k, v)

        # Asset routing based on toggles (#233: 5500 routes to OBI MM)
        mr = [VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300]
        obi_mm = [VEV_4000, VEV_4500]
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
        # HYDROGEL handled separately in _trade_hydrogel (Layer B)

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            if product == HYDROGEL:
                result[product] = self._trade_hydrogel(od, pos, td)
            elif product in self._mr_assets:
                result[product] = self._trade_mr(product, od, pos, td)
            elif product in self._obi_mm_assets:
                result[product] = self._trade_vev_mm(product, od, pos)
            else:
                result[product] = []
        return result, 0, json.dumps(td)

    # --- Layer C helper: tiered OBI skew on penny-jump --------------
    def _obi_skewed_quotes(self, best_bid: int, best_ask: int, obi: float
                            ) -> Tuple[int, int]:
        """Return (our_bid, our_ask) after applying OBI skew.
        Default = penny-jump (best+1, best-1)."""
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
            # obi > 0 → buy pressure → mid will move up.
            # We want to be at the front of buys (penny-jump) and pull back the ask.
            if obi > 0:
                our_ask = best_ask + ticks - 1  # pull ask away from mid
            else:
                our_bid = best_bid - ticks + 1  # pull bid away from mid
        # Safety: never invert
        if our_bid >= our_ask:
            our_bid = best_bid + 1
            our_ask = best_ask - 1
        return our_bid, our_ask

    # --- Layer B + F: HYDROGEL handler ------------------------------
    def _trade_hydrogel(self, od: OrderDepth, pos: int, td: dict) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        mid = (best_bid + best_ask) / 2.0
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total

        orders: List[Order] = []
        limit = LIMITS[HYDROGEL]

        # --- Layer B: rev_z50 directional take ------------
        # Buffer maintenance: append current mid, trim to window
        buf_key = "hydro_mids"
        age_key = "hydro_revz_age"
        side_key = "hydro_revz_side"
        buf: List[float] = td.get(buf_key, [])
        buf.append(mid)
        if len(buf) > self.HYDROGEL_REVZ_WINDOW:
            buf = buf[-self.HYDROGEL_REVZ_WINDOW:]
        td[buf_key] = buf

        # Forced unwind after hold horizon
        age = int(td.get(age_key, 0))
        side = int(td.get(side_key, 0))  # +1 long, -1 short, 0 flat
        force_unwind_buy = 0
        force_unwind_sell = 0
        if side != 0:
            age += 1
            td[age_key] = age
            if age >= self.HYDROGEL_REVZ_HOLD:
                # Reset
                td[age_key] = 0
                td[side_key] = 0
                # Don't add hard unwind orders; the natural MM quotes will bleed.

        # Compute z and trigger
        if (len(buf) >= self.HYDROGEL_REVZ_WINDOW
                and self.HYDROGEL_REVZ_SIZE > 0
                and self.HYDROGEL_REVZ_THRESHOLD < 50.0):
            mean = sum(buf) / len(buf)
            var = sum((x - mean) ** 2 for x in buf) / len(buf)
            std = var ** 0.5
            if std > 0:
                z = (mid - mean) / std
                if z >= self.HYDROGEL_REVZ_THRESHOLD and pos > -limit:
                    # Mid is high → fade by selling
                    qty = min(self.HYDROGEL_REVZ_SIZE, limit + pos)
                    if qty > 0 and side != -1:
                        orders.append(Order(HYDROGEL, best_bid, -qty))
                        td[age_key] = 0
                        td[side_key] = -1
                elif z <= -self.HYDROGEL_REVZ_THRESHOLD and pos < limit:
                    qty = min(self.HYDROGEL_REVZ_SIZE, limit - pos)
                    if qty > 0 and side != 1:
                        orders.append(Order(HYDROGEL, best_ask, qty))
                        td[age_key] = 0
                        td[side_key] = 1

        # --- Layer F + C: tiered OBI MM with skew, Layer F floor -----
        # Mirrors _trade_vev_mm so defaults match stratton's HYDROGEL handler.
        buy_size, sell_size = self._vev_obi_sizes(obi)
        if self.BASE_MM_SIZE > self.VEV_BASE_SIZE:
            if obi > 0:
                buy_size = max(buy_size, self.BASE_MM_SIZE)
            else:
                sell_size = max(sell_size, self.BASE_MM_SIZE)
        our_bid, our_ask = self._obi_skewed_quotes(best_bid, best_ask, obi)
        if our_bid >= our_ask:
            return orders
        soft_thresh = int(self.VEV_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(buy_size, max(0, buy_room))
        sell_qty = min(sell_size, max(0, sell_room))
        if pos >= soft_thresh:
            buy_qty = 0
        elif pos <= -soft_thresh:
            sell_qty = 0
        if buy_qty > 0:
            orders.append(Order(HYDROGEL, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(HYDROGEL, our_ask, -sell_qty))
        return orders

    # --- Stratton MR (unchanged from v2) ----------------------------
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

        # Apply OBI skew (Layer C) to MR-MM quotes too
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        tot = b1_vol + a1_vol
        obi = 0.0 if tot == 0 else (b1_vol - a1_vol) / tot
        # Default penny-jump per level
        remaining_buy_room = max(0, buy_room - buy_ordered)
        remaining_sell_room = max(0, sell_room - sell_ordered)

        for level in range(self.MR_MM_LEVELS):
            our_bid_base = best_bid + 1 + level
            our_ask_base = best_ask - 1 - level
            # Apply skew on level 0 only
            if level == 0:
                our_bid, our_ask = self._obi_skewed_quotes(best_bid, best_ask, obi)
            else:
                our_bid, our_ask = our_bid_base, our_ask_base
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
        b1_vol = od.buy_orders[best_bid]
        a1_vol = -od.sell_orders[best_ask]
        total = b1_vol + a1_vol
        obi = 0.0 if total == 0 else (b1_vol - a1_vol) / total

        # OBI tiered sizing (stratton heritage)
        buy_size, sell_size = self._vev_obi_sizes(obi)

        # Layer F: never go below BASE_MM_SIZE on the favoured side
        if self.BASE_MM_SIZE > self.VEV_BASE_SIZE:
            if obi > 0:
                buy_size = max(buy_size, self.BASE_MM_SIZE)
            else:
                sell_size = max(sell_size, self.BASE_MM_SIZE)

        # Layer C: skew quote levels by OBI
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
