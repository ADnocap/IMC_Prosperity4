# R3 trader — "Donnie Azoff". Signal-directional on VELVET + voucher leverage.
#
# Edge detection (analysis/round3/velvet_signal_check.py): VELVET's
# top-of-book OBI has corr ≈ +0.28 with next-tick Δmid on days 0/1/2 and
# 68.5% hit rate; microprice skew corr ≈ +0.23 with same horizon. Both
# signals decay to noise at horizon ≥ 2 ticks. So edge is purely 1-tick.
#
# Strategy:
#   * HYDROGEL: keep belfort v2 penny-jump MM (size 15, works in MC).
#   * VELVET: MM with SIGNAL-BIASED SIZES — penny-jump both sides but
#     shrink the contra side when OBI is strong. Builds inventory with
#     the predicted direction while still collecting spread.
#   * VEV_4000 / VEV_4500: when VELVET position saturates at limit, extend
#     exposure via deep-ITM vouchers (BS delta ≈ 1.0 at T=5/365). This
#     gives up to ~800 spot-equivalent delta (200 + 300 + 300) vs 200 on
#     VELVET alone.
#
# Caveat: the Rust MC backtester treats every asset as an INDEPENDENT
# random walk, so the voucher-leverage leg is portal-valid only. HYDROGEL
# MM + VELVET signal-MM survive in MC because OBI has real predictive
# power against the simulated VELVET random walk (bots' layer presence
# carries through into the sim's order book).
#
# Named internals:
#   DonnieAzoff — OBI + microprice signal ("my gut is never wrong, bro")
#   MarkHanna   — BS delta for voucher sizing (mentor, kept sober)
#   Trader      — execution loop

from datamodel import OrderDepth, TradingState, Order, Trade
from typing import Dict, List, Optional
import json
import math


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
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

STRIKES = {
    VEV_4000: 4000, VEV_4500: 4500, VEV_5000: 5000, VEV_5100: 5100,
    VEV_5200: 5200, VEV_5300: 5300, VEV_5400: 5400, VEV_5500: 5500,
    VEV_6000: 6000, VEV_6500: 6500,
}

LIMITS = {
    HYDROGEL: 200, VELVET: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

# Seed per-strike IV — used for BS delta in voucher sizing.
SEED_IV = {
    VEV_4000: 0.362, VEV_4500: 0.270,
    VEV_5000: 0.233, VEV_5100: 0.226, VEV_5200: 0.232, VEV_5300: 0.237,
    VEV_5400: 0.220, VEV_5500: 0.241,
    VEV_6000: 0.405, VEV_6500: 0.616,
}
TTE_YEARS = 5.0 / 365.0

# Vouchers used as spot leverage. Deep ITM → BS δ ≈ 1.0 at T=5/365.
LEVER_VOUCHERS = (VEV_4000, VEV_4500)

# Penny-jump MM on tradeable vouchers (belfort-style baseline PnL source,
# independent of the VELVET signal). Quote sizes split by median spread.
WIDE_MM_VOUCHERS = (VEV_4000, VEV_4500)           # median spread 16–21
TIGHT_MM_VOUCHERS = (VEV_5000, VEV_5100, VEV_5200)  # median spread 3–6
# Skipped: VEV_5300 (spread 2 — no penny-jump room most ticks),
# VEV_5400/5500 (spread 1), VEV_6000/6500 (FV=0.5 floor).


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class MarkHanna:
    """BS delta for voucher-as-spot sizing."""

    @staticmethod
    def delta(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        vt = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vt
        return _norm_cdf(d1)


class DonnieAzoff:
    """Short-horizon microstructure signal on the underlying."""

    @staticmethod
    def obi(od: OrderDepth) -> float:
        """Top-of-book order-book imbalance in [-1, +1]."""
        if not od.buy_orders or not od.sell_orders:
            return 0.0
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = od.buy_orders[bb]
        av = -od.sell_orders[ba]
        tot = bv + av
        return 0.0 if tot == 0 else (bv - av) / tot

    @staticmethod
    def microprice_skew_norm(od: OrderDepth) -> float:
        """(microprice − mid) / spread, roughly in [-0.5, +0.5]."""
        if not od.buy_orders or not od.sell_orders:
            return 0.0
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bv = od.buy_orders[bb]
        av = -od.sell_orders[ba]
        tot = bv + av
        if tot == 0:
            return 0.0
        mid = 0.5 * (bb + ba)
        micro = (ba * bv + bb * av) / tot
        spread = ba - bb
        if spread <= 0:
            return 0.0
        return (micro - mid) / spread

    @classmethod
    def combined(cls, od: OrderDepth) -> float:
        """Weighted composite signal in approximately [-1, +1]."""
        obi = cls.obi(od)
        mp = cls.microprice_skew_norm(od) * 2.0  # rescale to ~[-1, +1]
        return 0.6 * obi + 0.4 * mp


class Trader:
    # HYDROGEL MM (reuse belfort v2 config — working in MC)
    HYDROGEL_SIZE = 15
    HYDROGEL_MIN_SPREAD = 2
    HYDROGEL_SOFT_FRAC = 0.6

    # Voucher MM (belfort v2 baseline)
    WIDE_VOUCHER_SIZE = 15
    TIGHT_VOUCHER_SIZE = 5
    VOUCHER_MM_MIN_SPREAD = 2
    VOUCHER_MM_SOFT_FRAC = 0.6

    # VELVET signal MM: size splits by OBI
    VELVET_BASE_SIZE = 6
    VELVET_BIAS_SIZE = 14        # strong-side size when signal is firing
    VELVET_WEAK_SIZE = 2         # contra-side size when signal is firing
    VELVET_SIGNAL_GATE = 0.15    # |signal| below this → neutral MM
    VELVET_SOFT_FRAC = 0.8       # protect against runaway inventory

    # Voucher leverage: only engage when VELVET is near its limit and
    # the signal is clear. Place passive orders on ITM vouchers.
    VOUCHER_SIGNAL_GATE = 0.25
    VOUCHER_VELVET_THRESHOLD = 0.8   # VELVET pos ≥ 80% of limit → extend
    VOUCHER_CHUNK = 20               # max per-tick add per voucher

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0
        td = self._load_td(state.traderData)

        # ── HYDROGEL MM (independent of the directional leg)
        hod = state.order_depths.get(HYDROGEL)
        if hod:
            hpos = state.position.get(HYDROGEL, 0)
            result[HYDROGEL] = self._mm_hydrogel(hod, hpos)

        vod = state.order_depths.get(VELVET)
        if vod is None:
            return result, conversions, json.dumps(td)
        velvet_mid = self._book_mid(vod)
        if velvet_mid is None:
            return result, conversions, json.dumps(td)

        # ── Signal from VELVET book
        signal = DonnieAzoff.combined(vod)
        td["last_signal"] = signal

        # ── VELVET signal-biased MM
        vpos = state.position.get(VELVET, 0)
        result[VELVET] = self._mm_velvet(vod, vpos, signal)

        # ── Voucher baseline MM (belfort-style, independent of signal)
        for voucher in WIDE_MM_VOUCHERS:
            od_v = state.order_depths.get(voucher)
            if od_v is None:
                continue
            cpos = state.position.get(voucher, 0)
            result[voucher] = self._mm_voucher(voucher, od_v, cpos,
                                               self.WIDE_VOUCHER_SIZE)
        for voucher in TIGHT_MM_VOUCHERS:
            od_v = state.order_depths.get(voucher)
            if od_v is None:
                continue
            cpos = state.position.get(voucher, 0)
            result[voucher] = self._mm_voucher(voucher, od_v, cpos,
                                               self.TIGHT_VOUCHER_SIZE)

        # ── Voucher leverage overlay: when VELVET is near its limit AND
        #    signal agrees, STACK extra voucher exposure. Appended to the
        #    baseline MM orders above (both still respect position limits).
        velvet_limit = LIMITS[VELVET]
        if abs(signal) >= self.VOUCHER_SIGNAL_GATE and \
           abs(vpos) >= self.VOUCHER_VELVET_THRESHOLD * velvet_limit and \
           (vpos * signal) > 0:
            for voucher in LEVER_VOUCHERS:
                od_v = state.order_depths.get(voucher)
                if od_v is None:
                    continue
                cur = state.position.get(voucher, 0)
                existing = result.get(voucher, [])
                overlay = self._extend_voucher(voucher, od_v, cur, signal,
                                               velvet_mid, existing)
                if overlay:
                    result[voucher] = existing + overlay

        return result, conversions, json.dumps(td)

    # ── HYDROGEL MM
    def _mm_hydrogel(self, od: OrderDepth, pos: int) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < self.HYDROGEL_MIN_SPREAD:
            return []
        our_bid = bb + 1
        our_ask = ba - 1
        if our_bid >= our_ask:
            return []
        limit = LIMITS[HYDROGEL]
        soft = int(self.HYDROGEL_SOFT_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(self.HYDROGEL_SIZE, max(0, buy_room))
        sell_qty = min(self.HYDROGEL_SIZE, max(0, sell_room))
        if pos >= soft:
            buy_qty = 0
        elif pos <= -soft:
            sell_qty = 0
        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(HYDROGEL, int(our_bid), buy_qty))
        if sell_qty > 0:
            orders.append(Order(HYDROGEL, int(our_ask), -sell_qty))
        return orders

    # ── VELVET signal-biased MM
    def _mm_velvet(self, od: OrderDepth, pos: int, signal: float) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < 2:
            return []
        our_bid = bb + 1
        our_ask = ba - 1
        if our_bid >= our_ask:
            return []
        limit = LIMITS[VELVET]
        soft = int(self.VELVET_SOFT_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos

        # Signal-dependent sizing. When OBI > gate, bid harder / ask lightly.
        if signal >= self.VELVET_SIGNAL_GATE:
            buy_qty = self.VELVET_BIAS_SIZE
            sell_qty = self.VELVET_WEAK_SIZE
        elif signal <= -self.VELVET_SIGNAL_GATE:
            buy_qty = self.VELVET_WEAK_SIZE
            sell_qty = self.VELVET_BIAS_SIZE
        else:
            buy_qty = self.VELVET_BASE_SIZE
            sell_qty = self.VELVET_BASE_SIZE

        buy_qty = min(buy_qty, max(0, buy_room))
        sell_qty = min(sell_qty, max(0, sell_room))

        # Protect against runaway inventory
        if pos >= soft:
            buy_qty = 0
        elif pos <= -soft:
            sell_qty = 0

        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(VELVET, int(our_bid), buy_qty))
        if sell_qty > 0:
            orders.append(Order(VELVET, int(our_ask), -sell_qty))
        return orders

    # ── Baseline voucher MM (penny-jump, no signal)
    def _mm_voucher(self, prod: str, od: OrderDepth, pos: int,
                    size: int) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < self.VOUCHER_MM_MIN_SPREAD:
            return []
        our_bid = bb + 1
        our_ask = ba - 1
        if our_bid >= our_ask:
            return []
        limit = LIMITS[prod]
        soft = int(self.VOUCHER_MM_SOFT_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(size, max(0, buy_room))
        sell_qty = min(size, max(0, sell_room))
        if pos >= soft:
            buy_qty = 0
        elif pos <= -soft:
            sell_qty = 0
        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(prod, int(our_bid), buy_qty))
        if sell_qty > 0:
            orders.append(Order(prod, int(our_ask), -sell_qty))
        return orders

    # ── Voucher leverage extension (appended to baseline MM orders).
    # Must respect remaining position-limit room after the MM quotes.
    def _extend_voucher(self, prod: str, od: OrderDepth, cur: int,
                        signal: float, spot: float,
                        existing: List[Order]) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < 2:
            return []
        limit = LIMITS[prod]
        # Account for MM orders already queued on each side.
        queued_buy = sum(o.quantity for o in existing if o.quantity > 0)
        queued_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        if signal > 0:
            room = max(0, limit - cur - queued_buy)
            qty = min(self.VOUCHER_CHUNK, room)
            if qty <= 0:
                return []
            return [Order(prod, int(bb + 1), qty)]
        else:
            room = max(0, limit + cur - queued_sell)
            qty = min(self.VOUCHER_CHUNK, room)
            if qty <= 0:
                return []
            return [Order(prod, int(ba - 1), -qty)]

    def _book_mid(self, od: OrderDepth) -> Optional[float]:
        if not od.buy_orders or not od.sell_orders:
            return None
        return 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))

    def _load_td(self, blob: str) -> dict:
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except Exception:
            return {}
