"""Harry_potter_v6 — v5 with POSITION-GATED stop-loss.

v4 portal: +17,450.  v5 portal: +9,967 (-7,483).

v5's instantaneous MTM stop-loss fired during normal MR build-up
drawdowns and unwound winning positions right before the reversion.
CSV replay showed +232 over v4 (overfit to day 2's specific drift);
on portal where drawdowns reverted, it was pure cost.

Tested for v6:
  - Duration-filtered SL (require N consecutive ticks below threshold).
    Every duration/threshold/pause combo scored WORSE than v4 on CSV
    — letting the drawdown go deeper before firing only amplified the
    locked-in loss.
  - POSITION-GATED SL — fires only when BOTH (a) |pos| >= 80% of limit
    (stuck at limit) AND (b) MTM below threshold for 300 consecutive
    ticks. On normal data, MR reverts before positions saturate, so
    this never fires — v6 produces identical 50,816 to v4 on CSV
    regardless of threshold / duration within the gate. On the
    sanity-flip anti-strategy, positions do saturate and stay
    underwater, so SL fires and caps the loss at -67,268 (vs v4's
    -72,601). Pure insurance policy with ZERO observed cost on
    profitable runs.

All other mechanics identical to v4/v5:
  - Hybrid routing (HYDROGEL + VEV_4000/4500 on OBI MM, VELVETFRUIT +
    VEV_5000..5500 on MR).
  - Slow EMA (alpha=0.0005) as FV.
  - Z-target with K=0.55, MAX_FRAC=0.85.
  - Aggressive cross-spread take at |z| >= 1.2.
  - Passive inside-spread layers (2 levels of 30/10 by side).
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
    HYDROGEL: 200,
    VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

FALLBACK_FV: Dict[str, float] = {
    VELVETFRUIT: 5250.0,
    VEV_5000: 255.0, VEV_5100: 167.0, VEV_5200: 95.0,
    VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0,
}
FALLBACK_SIGMA: Dict[str, float] = {
    VELVETFRUIT: 15.0,
    VEV_5000: 14.0, VEV_5100: 13.0, VEV_5200: 10.0,
    VEV_5300: 6.0, VEV_5400: 3.4, VEV_5500: 1.7,
}

MR_ASSETS = (VELVETFRUIT, VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500)
VEV_MM_ASSETS = (VEV_4000, VEV_4500)
OBI_MM_ASSETS = (HYDROGEL,)


class Trader:
    # -------------------- MR params --------------------
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01
    MR_K = 0.55
    MR_MAX_FRAC = 0.85
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 30
    MR_MM_LEVELS = 2
    MR_TAKE_Z = 1.2
    MR_TAKE_MAX = 40
    MR_TIGHT_SPREAD_MIN = 2

    # -------------------- Position-gated stop-loss --------------------
    # Only triggers when BOTH: (a) |pos| >= STOP_POS_GATE * limit (genuinely
    # stuck at position limit), and (b) MTM PnL < STOP_LOSS_THRESHOLD for
    # STOP_DURATION_TICKS consecutive observations (not a transient dip).
    #
    # On profitable CSV runs, MR reverts before positions saturate, so this
    # never fires — v6 == v4 exactly on normal data. On the sanity-flip
    # anti-strategy, positions do saturate and MTM stays bad, so the SL
    # fires and caps the loss at -67k (vs -72k unprotected). Pure
    # insurance policy with zero observed cost.
    STOP_LOSS_THRESHOLD = -2500   # per-asset MTM PnL (XIRECs)
    STOP_DURATION_TICKS = 300     # consecutive ticks below threshold
    STOP_POS_GATE = 0.80          # fraction of position limit required for trigger
    STOP_PAUSE_TICKS = 500        # pause MR for this long after triggering

    # -------------------- OBI MM params --------------------
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # -------------------- Entry --------------------

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        timestamp = state.timestamp

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)

            # Tally any new fills into per-asset cash flow.
            self._accumulate_fills(td, product, state)

            if product in MR_ASSETS:
                result[product] = self._trade_mr(product, od, pos, td, timestamp)
            elif product in VEV_MM_ASSETS or product in OBI_MM_ASSETS:
                result[product] = self._trade_mm(product, od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(td)

    # -------------------- Fill tracking + MTM --------------------

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

    def _session_pnl(self, td: dict, product: str, mid: float, pos: int) -> float:
        return td.get(f"cash_{product}", 0.0) + pos * mid

    # -------------------- MR execution --------------------

    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict,
                  timestamp: int) -> List[Order]:
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

        # Duration-filtered stop-loss: only trigger if MTM < threshold for
        # STOP_DURATION_TICKS consecutive observations. Resets when MTM
        # rises back above threshold, even for one tick.
        pnl = self._session_pnl(td, product, mid, pos)
        below_key = f"below_ticks_{product}"
        below = td.get(below_key, 0)
        if pnl < self.STOP_LOSS_THRESHOLD:
            below += 1
        else:
            below = 0
        td[below_key] = below

        pause_until = td.get(f"pause_until_{product}", -1)
        # Position gate: only trigger when genuinely stuck at position limit
        # (both conditions required — the gate is what prevents premature
        # fires during normal MR build-up drawdowns).
        pos_gate_met = abs(pos) >= int(self.STOP_POS_GATE * limit)
        if below >= self.STOP_DURATION_TICKS and pos_gate_met and pause_until < timestamp:
            td[f"pause_until_{product}"] = timestamp + self.STOP_PAUSE_TICKS

        if pause_until >= timestamp:
            return self._unwind_passive(product, pos, best_bid, best_ask)

        # Z-scored target position.
        if sigma > 0 and n >= self.MR_MIN_N:
            z = (mid - fv) / sigma
            target_frac = max(-self.MR_MAX_FRAC, min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)
        else:
            target = 0
            z = 0.0

        buy_room = limit - pos
        sell_room = limit + pos
        buy_ordered = 0
        sell_ordered = 0
        orders: List[Order] = []
        diff = target - pos

        # (a) Aggressive cross-spread take on strong |z|.
        if abs(z) >= self.MR_TAKE_Z:
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

        # (b) Passive inside-the-spread MM layers, sized by target direction.
        diff_after = target - (pos + buy_ordered - sell_ordered)
        big_each = self.MR_MM_LEVEL_SIZE
        small_each = max(5, self.MR_MM_LEVEL_SIZE // 3)
        if diff_after > 0:
            b_each, a_each = big_each, small_each
        elif diff_after < 0:
            b_each, a_each = small_each, big_each
        else:
            b_each, a_each = small_each, small_each

        rem_buy = max(0, buy_room - buy_ordered)
        rem_sell = max(0, sell_room - sell_ordered)
        for level in range(self.MR_MM_LEVELS):
            our_bid = best_bid + 1 + level
            our_ask = best_ask - 1 - level
            if our_bid >= our_ask:
                break
            bqty = min(b_each, rem_buy)
            aqty = min(a_each, rem_sell)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
                rem_buy -= bqty
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
                rem_sell -= aqty

        return orders

    def _unwind_passive(self, product: str, pos: int,
                        best_bid: int, best_ask: int) -> List[Order]:
        orders: List[Order] = []
        if pos > 0:
            qty = min(pos, 30)
            if best_ask - 1 > best_bid:
                orders.append(Order(product, best_ask - 1, -qty))
        elif pos < 0:
            qty = min(-pos, 30)
            if best_bid + 1 < best_ask:
                orders.append(Order(product, best_bid + 1, qty))
        return orders

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
        new_n = n + 1

        td[k_fv] = new_fv
        td[k_var] = max(1.0, new_var)
        td[k_n] = new_n

        sigma = max(1.0, new_var) ** 0.5
        return new_fv, sigma, new_n

    # -------------------- OBI-tilted MM --------------------

    def _trade_mm(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
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
        buy_size, sell_size = self._obi_sizes(obi)

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

    def _obi_sizes(self, obi: float) -> Tuple[int, int]:
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
