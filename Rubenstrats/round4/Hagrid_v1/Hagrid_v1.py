"""Hagrid_v1 — voucher-stacking on VELVETFRUIT z, with our v6 hybrid + SL.

Friend's submission (sub 386072) hit +25,281 vs our v6 +17,450. The
delta: their VEV_5000 +7,042 / VEV_5100 +6,682 (vs our ~1.2k/1.5k each).

Why: they drove ALL voucher MR trades from VELVETFRUIT's z-score, sized
by option delta. Same signal × 8 vouchers × 300-limit each = far bigger
position bank than our voucher-by-voucher z-scoring.

Hagrid_v1 = friend's stacking engine + our v6 wins:
  - HYDROGEL → OBI MM (same on both — +610)
  - VEV_4000, VEV_4500 → OBI MM (we beat them: +2,300 vs +104)
  - VELVETFRUIT → MR with regime gating + flow signal
  - VEV_5000..5500 → MR driven by velvet_z, target = sign × 0.9 × limit × (|delta|+0.3)
  - Position-gated SL kept as insurance
  - Trade-flow signal (signed taker prints over 5000 ticks) used for
    defensive quote-skew + middle-zone position bias

Three regimes per friend:
  - |z| >= 1.2 → pure MR stack, take aggressively, no flow noise
  - |z| < 0.3  → flatten to 0, defensive skew only
  - middle    → flow-bias target + defensive skew
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

DELTAS: Dict[str, float] = {
    VEV_5000: 0.654, VEV_5100: 0.577, VEV_5200: 0.437,
    VEV_5300: 0.273, VEV_5400: 0.129, VEV_5500: 0.055,
}
STACKED_VOUCHERS = list(DELTAS.keys())  # MR-stacked, driven by velvet_z

VEV_MM_ASSETS = (VEV_4000, VEV_4500)    # OBI MM (we beat friend here)
OBI_MM_ASSETS = (HYDROGEL,)
DEAD_ASSETS = (VEV_6000, VEV_6500)

# Flow signal applies to the most liquid / signal-rich subset
FLOW_PRODUCTS = (VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300)

FALLBACK_FV: Dict[str, float] = {VELVETFRUIT: 5250.0}
FALLBACK_SIGMA: Dict[str, float] = {VELVETFRUIT: 15.0}


class Trader:
    # -------- VELVET MR core --------
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01
    MR_MIN_N = 50
    STACK_OPEN_Z = 1.2          # |z| above this → aggressive stack mode
    STACK_CLOSE_Z = 0.3         # |z| below this → flatten / defensive
    VELVET_K = 0.55
    VELVET_MAX_FRAC = 0.85
    VOUCHER_STACK_FRAC = 0.90
    STACK_TAKE_MAX = 80         # max contracts taken aggressively per tick
    MR_TIGHT_SPREAD_MIN = 2

    # -------- Trade-flow signal --------
    FLOW_WINDOW_TICKS = 5000
    FLOW_SKEW_THR = 10          # quote-price skew fires above this signed score
    FLOW_FOLLOW_THR = 20        # position bias needs stronger signal
    FLOW_BIAS_MAX_FRAC = 0.15   # conservative — don't fight MR

    # -------- Passive layer sizes --------
    PASSIVE_BIG = 25
    PASSIVE_SMALL = 8
    PASSIVE_LEVELS = 3

    # -------- OBI MM (HYDROGEL + VEV_4000/4500) --------
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # -------- Position-gated stop-loss --------
    STOP_LOSS_THRESHOLD = -2500
    STOP_DURATION_TICKS = 300
    STOP_POS_GATE = 0.80
    STOP_PAUSE_TICKS = 500

    # ============================ Entry ============================

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td = self._parse_td(state.traderData)
        timestamp = state.timestamp

        self._update_flow(td, state)

        velvet_z, velvet_fv, velvet_sigma = self._velvet_signal(td, state)

        result: Dict[str, List[Order]] = {}

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            self._accumulate_fills(td, product, state)

            if product == VELVETFRUIT:
                result[product] = self._trade_velvet(
                    od, pos, velvet_z, velvet_fv, velvet_sigma, td, timestamp)
            elif product in STACKED_VOUCHERS:
                result[product] = self._trade_voucher(
                    product, od, pos, velvet_z, td, timestamp)
            elif product in VEV_MM_ASSETS or product in OBI_MM_ASSETS:
                result[product] = self._trade_obi_mm(product, od, pos)
            elif product in DEAD_ASSETS:
                result[product] = []
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    # ====================== VELVET signal ===========================

    def _velvet_signal(self, td: dict, state: TradingState) -> Tuple[float, float, float]:
        if VELVETFRUIT not in state.order_depths:
            return 0.0, FALLBACK_FV[VELVETFRUIT], FALLBACK_SIGMA[VELVETFRUIT]
        od = state.order_depths[VELVETFRUIT]
        if not od.buy_orders or not od.sell_orders:
            return 0.0, FALLBACK_FV[VELVETFRUIT], FALLBACK_SIGMA[VELVETFRUIT]
        bb, ba = max(od.buy_orders), min(od.sell_orders)
        if ba - bb < self.MR_TIGHT_SPREAD_MIN:
            return 0.0, FALLBACK_FV[VELVETFRUIT], FALLBACK_SIGMA[VELVETFRUIT]
        mid = (bb + ba) / 2.0
        fv, sigma, n = self._update_ema(td, VELVETFRUIT, mid)
        if n < self.MR_MIN_N or sigma <= 0:
            return 0.0, fv, sigma
        return (mid - fv) / sigma, fv, sigma

    # =================== Trade-flow signal =========================

    def _update_flow(self, td: dict, state: TradingState) -> None:
        flow = td.setdefault('flow', {})
        for prod in FLOW_PRODUCTS:
            history = flow.setdefault(prod, [])
            trades = (state.market_trades or {}).get(prod, []) or []
            od = state.order_depths.get(prod)
            if od and od.buy_orders and od.sell_orders:
                mid = (max(od.buy_orders) + min(od.sell_orders)) / 2.0
                for t in trades:
                    if t.price > mid:
                        history.append([state.timestamp, t.quantity])
                    elif t.price < mid:
                        history.append([state.timestamp, -t.quantity])
            cutoff = state.timestamp - self.FLOW_WINDOW_TICKS
            flow[prod] = [[ts, v] for ts, v in history if ts > cutoff]

    def _flow_score(self, td: dict, prod: str) -> int:
        return sum(v for _, v in td.get('flow', {}).get(prod, []))

    def _flow_skew(self, td: dict, prod: str) -> Tuple[int, int]:
        score = self._flow_score(td, prod)
        if score > self.FLOW_SKEW_THR:
            return 0, 1     # buying pressure → ask one tick higher
        if score < -self.FLOW_SKEW_THR:
            return -1, 0    # selling pressure → bid one tick lower
        return 0, 0

    def _flow_bias(self, td: dict, prod: str, limit: int) -> int:
        score = self._flow_score(td, prod)
        if abs(score) < self.FLOW_FOLLOW_THR:
            return 0
        scale = min(1.0, (abs(score) - self.FLOW_FOLLOW_THR) / (2 * self.FLOW_FOLLOW_THR))
        sign = 1 if score > 0 else -1
        return int(sign * scale * self.FLOW_BIAS_MAX_FRAC * limit)

    # ====================== VELVETFRUIT trade =======================

    def _trade_velvet(self, od: OrderDepth, pos: int, z: float,
                      fv: float, sigma: float, td: dict,
                      timestamp: int) -> List[Order]:
        bids, asks, ok = self._book(od)
        if not ok:
            return []
        best_bid, best_ask = bids[0], asks[0]
        limit = LIMITS[VELVETFRUIT]
        mid = (best_bid + best_ask) / 2.0

        if self._sl_check(td, VELVETFRUIT, pos, mid, limit, timestamp):
            return self._unwind_passive(VELVETFRUIT, pos, best_bid, best_ask)

        if abs(z) >= self.STACK_OPEN_Z:
            tf = max(-self.VELVET_MAX_FRAC, min(self.VELVET_MAX_FRAC, -self.VELVET_K * z))
            target = int(tf * limit)
            aggressive = True
            use_skew = False
        elif abs(z) < self.STACK_CLOSE_Z:
            target = 0
            aggressive = False
            use_skew = True
        else:
            target = self._flow_bias(td, VELVETFRUIT, limit)
            aggressive = False
            use_skew = True

        return self._execute(VELVETFRUIT, od, pos, target, aggressive,
                             self.STACK_TAKE_MAX, use_skew, td)

    # ===================== Voucher (stacked) trade ==================

    def _trade_voucher(self, sym: str, od: OrderDepth, pos: int,
                       velvet_z: float, td: dict,
                       timestamp: int) -> List[Order]:
        bids, asks, ok = self._book(od)
        if not ok:
            return []
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        delta = DELTAS[sym]
        mid = (best_bid + best_ask) / 2.0

        if self._sl_check(td, sym, pos, mid, limit, timestamp):
            return self._unwind_passive(sym, pos, best_bid, best_ask)

        if abs(velvet_z) >= self.STACK_OPEN_Z:
            sign = -1 if velvet_z > 0 else 1
            target = int(sign * self.VOUCHER_STACK_FRAC * limit
                         * min(1.0, abs(delta) + 0.3))
            aggressive = True
            use_skew = False
        elif abs(velvet_z) < self.STACK_CLOSE_Z:
            target = 0
            aggressive = False
            use_skew = True
        else:
            if sym in FLOW_PRODUCTS:
                target = self._flow_bias(td, sym, limit)
            else:
                target = 0
            aggressive = False
            use_skew = True

        # Wide-spread vouchers (~10+ ticks): no aggressive take, passive only.
        if spread >= 10:
            bs, as_ = self._flow_skew(td, sym) if (use_skew and sym in FLOW_PRODUCTS) else (0, 0)
            return self._passive_layers(sym, od, pos, target - pos, bs, as_)

        return self._execute(sym, od, pos, target, aggressive,
                             self.STACK_TAKE_MAX, use_skew, td)

    # ==================== Generic execute ============================

    def _execute(self, sym: str, od: OrderDepth, pos: int, target: int,
                 aggressive: bool, take_max: int, use_skew: bool,
                 td: dict) -> List[Order]:
        bids, asks, _ = self._book(od)
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        buy_room = limit - pos
        sell_room = limit + pos
        diff = target - pos

        orders: List[Order] = []
        buy_ordered = sell_ordered = 0

        if aggressive and spread <= 6:
            if diff > 0:
                cap = min(diff, take_max, buy_room)
                for ap in asks:
                    if cap <= 0:
                        break
                    q = min(-od.sell_orders[ap], cap)
                    if q <= 0:
                        continue
                    orders.append(Order(sym, ap, q))
                    buy_ordered += q
                    cap -= q
            elif diff < 0:
                cap = min(-diff, take_max, sell_room)
                for bp in bids:
                    if cap <= 0:
                        break
                    q = min(od.buy_orders[bp], cap)
                    if q <= 0:
                        continue
                    orders.append(Order(sym, bp, -q))
                    sell_ordered += q
                    cap -= q

        diff_after = target - (pos + buy_ordered - sell_ordered)
        bs, as_ = self._flow_skew(td, sym) if (use_skew and sym in FLOW_PRODUCTS) else (0, 0)

        orders.extend(self._passive_layers(
            sym, od, pos + buy_ordered - sell_ordered,
            diff_after, bs, as_, buy_ordered, sell_ordered))
        return orders

    def _passive_layers(self, sym: str, od: OrderDepth, pos_after: int,
                        target_diff: int, bid_skew: int = 0, ask_skew: int = 0,
                        already_buy: int = 0, already_sell: int = 0) -> List[Order]:
        bids, asks, ok = self._book(od)
        if not ok:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.MR_TIGHT_SPREAD_MIN:
            return []

        big, small = self.PASSIVE_BIG, self.PASSIVE_SMALL
        if target_diff > 0:
            be, se = big, small
        elif target_diff < 0:
            be, se = small, big
        else:
            be = se = small

        limit = LIMITS[sym]
        rb = max(0, limit - pos_after - already_buy)
        rs = max(0, limit + pos_after - already_sell)
        orders: List[Order] = []
        for lvl in range(self.PASSIVE_LEVELS):
            ob = best_bid + 1 + lvl + bid_skew
            oa = best_ask - 1 - lvl + ask_skew
            if ob >= oa:
                break
            b = min(be, rb)
            a = min(se, rs)
            if b > 0:
                orders.append(Order(sym, ob, b))
                rb -= b
            if a > 0:
                orders.append(Order(sym, oa, -a))
                rs -= a
        return orders

    def _unwind_passive(self, sym: str, pos: int,
                        best_bid: int, best_ask: int) -> List[Order]:
        if pos > 0 and best_ask - 1 > best_bid:
            return [Order(sym, best_ask - 1, -min(pos, 30))]
        if pos < 0 and best_bid + 1 < best_ask:
            return [Order(sym, best_bid + 1, min(-pos, 30))]
        return []

    # ==================== OBI MM (HYDROGEL + VEV_4000/4500) ============

    def _trade_obi_mm(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids, asks, ok = self._book(od)
        if not ok:
            return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        total = b1 + a1
        obi = 0.0 if total == 0 else (b1 - a1) / total
        bs, ss = self._obi_sizes(obi)

        limit = LIMITS[product]
        soft = int(self.VEV_SOFT_POS_FRAC * limit)
        bq = min(bs, max(0, limit - pos))
        sq = min(ss, max(0, limit + pos))
        if pos >= soft:
            bq = 0
        elif pos <= -soft:
            sq = 0

        orders: List[Order] = []
        if bq > 0:
            orders.append(Order(product, our_bid, bq))
        if sq > 0:
            orders.append(Order(product, our_ask, -sq))
        return orders

    def _obi_sizes(self, obi: float) -> Tuple[int, int]:
        a = abs(obi)
        if a < self.OBI_SKEW_1:
            return (self.VEV_BASE_SIZE, self.VEV_BASE_SIZE)
        if a < self.OBI_SKEW_2:
            big, small = self.VEV_SIZES_MILD
        elif a < self.OBI_SKEW_3:
            big, small = self.VEV_SIZES_STRONG
        else:
            big, small = self.VEV_SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)

    # ==================== EMA + SL plumbing ===========================

    def _update_ema(self, td: dict, product: str, mid: float
                    ) -> Tuple[float, float, int]:
        k_fv = f"ema_{product}"
        k_var = f"var_{product}"
        k_n = f"n_{product}"
        prev_fv = td.get(k_fv)
        prev_var = td.get(k_var, FALLBACK_SIGMA.get(product, 30.0) ** 2)
        n = td.get(k_n, 0)
        if prev_fv is None:
            prev_fv = FALLBACK_FV.get(product, mid)
        residual = mid - prev_fv
        new_fv = prev_fv + self.EMA_ALPHA * residual
        new_var = prev_var + self.VAR_ALPHA * (residual * residual - prev_var)
        td[k_fv] = new_fv
        td[k_var] = max(1.0, new_var)
        td[k_n] = n + 1
        sigma = max(1.0, new_var) ** 0.5
        return new_fv, sigma, n + 1

    def _accumulate_fills(self, td: dict, product: str, state: TradingState) -> None:
        key_cash = f"cash_{product}"
        key_last_ts = f"ot_ts_{product}"
        cash = td.get(key_cash, 0.0)
        last_ts = td.get(key_last_ts, -1)
        trades = (state.own_trades or {}).get(product, []) or []
        for t in trades:
            if t.timestamp <= last_ts:
                continue
            qty = abs(int(t.quantity))
            if t.buyer == "SUBMISSION":
                cash -= t.price * qty
            elif t.seller == "SUBMISSION":
                cash += t.price * qty
            if t.timestamp > last_ts:
                last_ts = t.timestamp
        td[key_cash] = cash
        td[key_last_ts] = last_ts

    def _sl_check(self, td: dict, product: str, pos: int, mid: float,
                  limit: int, timestamp: int) -> bool:
        """Returns True if SL pause is currently active for this product."""
        pnl = td.get(f"cash_{product}", 0.0) + pos * mid
        below_key = f"below_ticks_{product}"
        below = td.get(below_key, 0)
        if pnl < self.STOP_LOSS_THRESHOLD:
            below += 1
        else:
            below = 0
        td[below_key] = below

        pause_until = td.get(f"pause_until_{product}", -1)
        pos_gate_met = abs(pos) >= int(self.STOP_POS_GATE * limit)
        if (below >= self.STOP_DURATION_TICKS and pos_gate_met
                and pause_until < timestamp):
            td[f"pause_until_{product}"] = timestamp + self.STOP_PAUSE_TICKS
            return True
        return pause_until >= timestamp

    # ==================== misc ========================================

    def _book(self, od: OrderDepth) -> Tuple[List[int], List[int], bool]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        ok = bool(bids) and bool(asks)
        return bids, asks, ok

    def _parse_td(self, s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
