# feedback_size.py — Idea #3 v1: dynamic quote SIZING based on recent own-fill rate.
#
# HYPOTHESIS: state.own_trades tells us what WE filled in the previous tick.
# If we're getting filled FAST on one side (3+ fills in last 5 ticks), either:
#   (a) we're on the right side — great, keep going
#   (b) we're getting ADVERSELY SELECTED — takers are picking off our quote
#       because they have an informational edge
# Case (b) is the concern. Defensive move: reduce size on the fast-filling side.
#
# v2 approach: when we're filling fast AGAINST OUR SIGNAL side (e.g., we want
# short but sells are hot), that means takers are coming in our favor.
# Increase TAKE_MAX to press harder. If filling against us, back off takes.
#
# Pure overlay on delta_stack — only affects take size in aggressive mode.
"""feedback_aggr — delta_stack + dynamic TAKE_MAX based on own-fill feedback."""
try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
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

LIMITS = {HYDROGEL: 200, VELVETFRUIT: 200,
          VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
          VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
          VEV_6000: 300, VEV_6500: 300}

DELTAS = {VEV_4000: 0.745, VEV_4500: 0.662, VEV_5000: 0.654, VEV_5100: 0.577,
          VEV_5200: 0.437, VEV_5300: 0.273, VEV_5400: 0.129, VEV_5500: 0.055}
STACKED_VOUCHERS = list(DELTAS.keys())

FALLBACK_FV = {VELVETFRUIT: 5250.0}
FALLBACK_SIGMA = {VELVETFRUIT: 15.0}


class Trader:
    # delta_stack signal params
    VELVET_EMA_ALPHA = 0.0005
    VELVET_VAR_ALPHA = 0.01
    VELVET_MIN_N = 50
    STACK_OPEN_Z = 1.2
    STACK_CLOSE_Z = 0.3
    VELVET_K = 0.55
    VELVET_MAX_FRAC = 0.85
    VOUCHER_STACK_FRAC = 0.90
    STACK_TAKE_MAX = 80

    # Own-trade feedback params
    FILL_WINDOW_TICKS = 1000
    FILL_HOT_THR = 3                 # 3+ fills on same side → press advantage
    TAKE_BOOST_FRAC = 1.5            # boost take_max by this when hot-aligned
    TAKE_BACKOFF_FRAC = 0.5          # reduce take_max when hot-against

    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1; OBI_SKEW_2 = 0.4; OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8); VEV_SIZES_STRONG = (30, 2); VEV_SIZES_EXTREME = (40, 3)

    def run(self, state: TradingState):
        td = self._parse_td(state.traderData)
        self._update_fills(td, state)

        velvet_z = 0.0
        if VELVETFRUIT in state.order_depths:
            od = state.order_depths[VELVETFRUIT]
            if od.buy_orders and od.sell_orders:
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                if ba - bb >= 2:
                    mid = (bb + ba) / 2.0
                    fv, sigma, n = self._update_ema(td, VELVETFRUIT, mid)
                    if n >= self.VELVET_MIN_N and sigma > 0:
                        velvet_z = (mid - fv) / sigma

        result: Dict[str, List[Order]] = {}

        if VELVETFRUIT in state.order_depths:
            result[VELVETFRUIT] = self._trade_velvet(
                state.order_depths[VELVETFRUIT], state.position.get(VELVETFRUIT, 0), velvet_z, td)

        for sym in STACKED_VOUCHERS:
            if sym in state.order_depths:
                result[sym] = self._trade_voucher(
                    sym, state.order_depths[sym], state.position.get(sym, 0), velvet_z, td)

        if HYDROGEL in state.order_depths:
            result[HYDROGEL] = self._trade_vev_mm(HYDROGEL, state.order_depths[HYDROGEL],
                                                    state.position.get(HYDROGEL, 0))
        for sym in (VEV_6000, VEV_6500):
            if sym in state.order_depths:
                result[sym] = []

        return result, 0, json.dumps(td)

    def _update_fills(self, td, state):
        """Track our own fills in a rolling window per product per side."""
        fills = td.setdefault('fills', {})
        for prod, trades in (state.own_trades or {}).items():
            hist = fills.setdefault(prod, [])
            for t in trades:
                # own_trades timestamps are PREVIOUS tick. Capture all fills.
                side = 'buy' if t.buyer == 'SUBMISSION' else 'sell'
                hist.append([state.timestamp, side, t.quantity])
            cutoff = state.timestamp - self.FILL_WINDOW_TICKS
            fills[prod] = [h for h in hist if h[0] > cutoff]

    def _fill_counts(self, td, prod):
        """(buy_fills_count, sell_fills_count) in recent window."""
        hist = td.get('fills', {}).get(prod, [])
        buys = sum(1 for _, s, _ in hist if s == 'buy')
        sells = sum(1 for _, s, _ in hist if s == 'sell')
        return buys, sells

    def _size_adjust(self, td, prod, default_buy, default_sell):
        """Shrink hot-side size based on recent own fills."""
        buys, sells = self._fill_counts(td, prod)
        if buys >= self.FILL_HOT_THR:
            default_buy = max(5, int(default_buy * self.FILL_SHRINK_FRAC))
        if sells >= self.FILL_HOT_THR:
            default_sell = max(5, int(default_sell * self.FILL_SHRINK_FRAC))
        return default_buy, default_sell

    def _trade_velvet(self, od, pos, z, td):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        limit = LIMITS[VELVETFRUIT]

        if abs(z) >= self.STACK_OPEN_Z:
            tf = max(-self.VELVET_MAX_FRAC, min(self.VELVET_MAX_FRAC, -self.VELVET_K * z))
            target = int(tf * limit)
            aggressive = True
        elif abs(z) < self.STACK_CLOSE_Z:
            target = 0
            aggressive = False
        else:
            return self._passive_layers(VELVETFRUIT, od, pos, 0, td)

        return self._execute(VELVETFRUIT, od, pos, target, aggressive=aggressive,
                              take_max=self.STACK_TAKE_MAX, td=td)

    def _trade_voucher(self, sym, od, pos, velvet_z, td):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        delta = DELTAS[sym]

        if abs(velvet_z) >= self.STACK_OPEN_Z:
            sign = -1 if velvet_z > 0 else 1
            target = int(sign * self.VOUCHER_STACK_FRAC * limit * min(1.0, abs(delta) + 0.3))
            aggressive = True
        elif abs(velvet_z) < self.STACK_CLOSE_Z:
            target = 0
            aggressive = False
        else:
            return self._passive_layers(sym, od, pos, 0, td)

        if spread >= 10:
            return self._passive_layers(sym, od, pos, target - pos, td)

        return self._execute(sym, od, pos, target, aggressive=aggressive,
                              take_max=self.STACK_TAKE_MAX, td=td)

    def _execute(self, sym, od, pos, target, aggressive, take_max, td):
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        best_bid, best_ask = bids[0], asks[0]
        spread = best_ask - best_bid
        limit = LIMITS[sym]
        buy_room = limit - pos; sell_room = limit + pos
        diff = target - pos
        orders = []
        buy_ordered = sell_ordered = 0
        # Dynamic take_max based on own-fill feedback
        buys, sells = self._fill_counts(td, sym)
        if diff > 0:  # we want to BUY (take asks)
            if buys >= self.FILL_HOT_THR:
                take_max = int(take_max * self.TAKE_BOOST_FRAC)  # already winning on buys, press
            elif sells >= self.FILL_HOT_THR:
                take_max = int(take_max * self.TAKE_BACKOFF_FRAC)  # adverse on sells
        elif diff < 0:  # we want to SELL
            if sells >= self.FILL_HOT_THR:
                take_max = int(take_max * self.TAKE_BOOST_FRAC)
            elif buys >= self.FILL_HOT_THR:
                take_max = int(take_max * self.TAKE_BACKOFF_FRAC)
        if aggressive and spread <= 6:
            if diff > 0:
                cap = min(diff, take_max, buy_room)
                for ap in asks:
                    if cap <= 0: break
                    q = min(-od.sell_orders[ap], cap)
                    if q <= 0: continue
                    orders.append(Order(sym, ap, q)); buy_ordered += q; cap -= q
            elif diff < 0:
                cap = min(-diff, take_max, sell_room)
                for bp in bids:
                    if cap <= 0: break
                    q = min(od.buy_orders[bp], cap)
                    if q <= 0: continue
                    orders.append(Order(sym, bp, -q)); sell_ordered += q; cap -= q
        diff_after = target - (pos + buy_ordered - sell_ordered)
        orders.extend(self._passive_layers(sym, od, pos + buy_ordered - sell_ordered,
                                             diff_after, td, buy_ordered, sell_ordered))
        return orders

    def _passive_layers(self, sym, od, pos, target_diff, td, already_buy=0, already_sell=0):
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks: return []
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < 2: return []
        big, small = 25, 8
        if target_diff > 0: be, se = big, small
        elif target_diff < 0: be, se = small, big
        else: be = se = small

        limit = LIMITS[sym]
        rb = max(0, limit - pos - already_buy); rs = max(0, limit + pos - already_sell)
        orders = []
        for lvl in range(3):
            ob = best_bid + 1 + lvl; oa = best_ask - 1 - lvl
            if ob >= oa: break
            b = min(be, rb); a = min(se, rs)
            if b > 0: orders.append(Order(sym, ob, b)); rb -= b
            if a > 0: orders.append(Order(sym, oa, -a)); rs -= a
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
        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN: return []
        ob, oa = best_bid + 1, best_ask - 1
        if ob >= oa: return []
        bv = od.buy_orders[best_bid]; av = -od.sell_orders[best_ask]
        obi = 0.0 if (bv + av) == 0 else (bv - av) / (bv + av)
        bs, ss = self._obi_sizes(obi)
        limit = LIMITS[product]
        soft = int(self.VEV_SOFT_POS_FRAC * limit)
        bq = min(bs, max(0, limit - pos)); sq = min(ss, max(0, limit + pos))
        if pos >= soft: bq = 0
        elif pos <= -soft: sq = 0
        orders = []
        if bq > 0: orders.append(Order(product, ob, bq))
        if sq > 0: orders.append(Order(product, oa, -sq))
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
