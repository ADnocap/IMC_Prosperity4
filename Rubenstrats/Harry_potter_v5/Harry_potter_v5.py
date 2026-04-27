"""Harry_potter_v5 — v4 + per-asset stop-loss.

v4 scored +17,450 on portal with full-budget MR on VELVETFRUIT + 6 near-
money VEVs. Two weaknesses considered:

  1. Day 2 underperformed on CSV (7k vs 19-24k) because VELVETFRUIT
     drifted 5267 -> 5295 and slow EMA didn't catch up.
  2. No stop-loss: a runaway regime could stack losing positions up to
     the position limit with no exit.

Tested a drift-adaptive EMA (blend slow + fast by divergence) and it
consistently HURT PnL across every variant. The reason: slow EMA
anchoring to the long-run mean is itself the alpha — even during
apparent drifts, the position eventually reverts and pays off. The fast
EMA chases noise and shrinks the target exactly when the real signal
(divergence from long-run mean) is strongest. Dropped.

What we kept:

  - Per-asset session-PnL stop-loss. Track cash flow via own_trades,
    compute MTM PnL = cash + position * mid. When it drops below
    STOP_LOSS_THRESHOLD, pause MR on that asset for STOP_PAUSE_TICKS
    and passively unwind position to zero. Tested at -2500, -3000,
    -3500; -2500 gives the best total with day 2 jumping from 7,404
    -> 8,757 (+18% on the historically weak day).

  - Sanity-flip check with stop-loss: -53,168 (vs v4's -72,601),
    confirming the stop-loss genuinely limits tail risk — the
    anti-strategy doesn't get to run all the way into the ground.

All other mechanics identical to v4: hybrid routing (HYDROGEL +
VEV_4000/4500 on OBI MM, VELVETFRUIT + VEV_5000..5500 on MR), passive
inside-spread layers, aggressive cross-spread take at |z| >= 1.2,
K=0.55, MAX_FRAC=0.85, slow EMA alpha=0.0005.
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
    EMA_ALPHA = 0.0005        # half-life ~1,386 ticks; long-run anchor
    VAR_ALPHA = 0.01
    MR_K = 0.55
    MR_MAX_FRAC = 0.85
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 30
    MR_MM_LEVELS = 2
    MR_TAKE_Z = 1.2
    MR_TAKE_MAX = 40
    MR_TIGHT_SPREAD_MIN = 2

    # -------------------- Stop-loss --------------------
    STOP_LOSS_THRESHOLD = -2500   # per-asset MTM PnL trigger (XIRECs)
    STOP_PAUSE_TICKS = 1000       # pause MR on this asset for N ticks after trigger

    # -------------------- OBI MM params (for HYDROGEL + VEV_4000/4500) --------
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

            # Update per-asset cash flow from any new fills before any PnL check.
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
        """Keep a running cash flow per asset by consuming own_trades.

        Convention:
            bought -> cash -= price*qty   (paid out)
            sold   -> cash += price*qty   (received)

        MTM PnL = cash_flow + position * mid
        """
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

        # Stop-loss gate: compute session PnL; trigger pause if below threshold.
        pnl = self._session_pnl(td, product, mid, pos)
        pause_until = td.get(f"pause_until_{product}", -1)

        if pnl < self.STOP_LOSS_THRESHOLD and pause_until < timestamp:
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
        """Stop-loss pause: no MR, push position toward zero via passive quote
        on the reducing side."""
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
        """EWMA update on fair value + variance. Returns (FV, sigma, n)."""
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

    # -------------------- OBI-tilted MM (HYDROGEL + VEV_4000/4500) --------

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
