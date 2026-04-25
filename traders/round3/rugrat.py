# R3 "Rugrat" — tiered-conviction OBI signal, max leverage on extremes.
# See analysis/round3/velvet_strong_signal.py for edge measurements.

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Optional, Tuple
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

SEED_IV = {
    VEV_4000: 0.362, VEV_4500: 0.270,
    VEV_5000: 0.233, VEV_5100: 0.226, VEV_5200: 0.232, VEV_5300: 0.237,
    VEV_5400: 0.220, VEV_5500: 0.241,
    VEV_6000: 0.405, VEV_6500: 0.616,
}
TTE_YEARS = 5.0 / 365.0

LEVER_VOUCHERS = (VEV_4000, VEV_4500)
WIDE_MM_VOUCHERS = (VEV_4000, VEV_4500)
TIGHT_MM_VOUCHERS = (VEV_5000, VEV_5100, VEV_5200)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class MarkHanna:
    @staticmethod
    def delta(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        vt = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vt
        return _norm_cdf(d1)


class DonnieAzoff:
    """OBI + microprice composite signal on VELVET."""

    @staticmethod
    def obi(od: OrderDepth) -> float:
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
        obi = cls.obi(od)
        mp = cls.microprice_skew_norm(od) * 2.0
        return 0.6 * obi + 0.4 * mp


class Rugrat:
    """Signal tier → (bid_size, ask_size) MM biasing for VELVET.

    Positive signal: bid side grows, ask shrinks. Negative: mirror.
    Contra side is kept ≥ 2 so we can still unwind into the signal fade.
    """
    # Three clean tiers. Intermediate OBI (|s|<0.5) has mediocre 66% hit
    # rate so light bias only; high-conviction (|s|≥0.5) corresponds to
    # the |OBI|≥0.75 regime (95% hit, +1.5-tick expected move).
    VELVET_TIERS: Tuple[Tuple[float, int, int], ...] = (
        (0.15, 8, 8),     # Tier 0: neutral MM (weak signals are noise)
        (0.50, 14, 4),    # Tier 1: moderate bias (≈donnie)
        (1.01, 30, 2),    # Tier 2: max leverage (the bimodal-edge regime)
    )

    @classmethod
    def velvet_sizes(cls, signal: float) -> Tuple[int, int]:
        mag = abs(signal)
        for thresh, big, small in cls.VELVET_TIERS:
            if mag < thresh:
                if signal > 0:
                    return big, small
                elif signal < 0:
                    return small, big
                else:
                    return big, big
        return cls.VELVET_TIERS[-1][1], cls.VELVET_TIERS[-1][2]

    @staticmethod
    def is_tier3(signal: float) -> bool:
        return abs(signal) >= 0.50


class Trader:
    # HYDROGEL MM
    HYDROGEL_SIZE = 15
    HYDROGEL_MIN_SPREAD = 2
    HYDROGEL_SOFT_FRAC = 0.6

    # Voucher baseline MM
    WIDE_VOUCHER_SIZE = 15
    TIGHT_VOUCHER_SIZE = 5
    VOUCHER_MM_MIN_SPREAD = 2
    VOUCHER_MM_SOFT_FRAC = 0.6

    # VELVET
    VELVET_MIN_SPREAD = 2
    VELVET_SOFT_FRAC = 0.85
    VELVET_UNWIND_MIN = 10  # forced min size on contra side when pos ≥ soft

    # Tier 3 escalation
    TIER3_LEVER_SIZE = 30  # per-tick aggressive passive add on each ITM voucher

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0
        td = self._load_td(state.traderData)

        # ── HYDROGEL MM
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

        # ── Signal
        signal = DonnieAzoff.combined(vod)
        raw_obi = DonnieAzoff.obi(vod)
        td["last_signal"] = signal
        vpos = state.position.get(VELVET, 0)

        # ── VELVET tiered MM
        result[VELVET] = self._mm_velvet(vod, vpos, signal)

        # ── Voucher baseline MM (always on)
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

        # ── Tier 3 max-leverage overlay: aggressive passive voucher entry
        # in the signal direction. Gated by BOTH composite strength AND
        # raw |OBI| ≥ 0.75 — the bimodal-edge regime (95% hit rate).
        # Portal-valid edge; in MC vouchers are independent walks so this
        # adds noise rather than signal there.
        if Rugrat.is_tier3(signal) and abs(raw_obi) >= 0.75:
            for voucher in LEVER_VOUCHERS:
                od_v = state.order_depths.get(voucher)
                if od_v is None:
                    continue
                cur = state.position.get(voucher, 0)
                existing = result.get(voucher, [])
                overlay = self._tier3_voucher(voucher, od_v, cur, signal,
                                              existing)
                if overlay:
                    result[voucher] = existing + overlay

        return result, conversions, json.dumps(td)

    # ── HYDROGEL MM (same as belfort v2)
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

    # ── VELVET tiered-conviction MM
    def _mm_velvet(self, od: OrderDepth, pos: int, signal: float) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < self.VELVET_MIN_SPREAD:
            return []
        our_bid = bb + 1
        our_ask = ba - 1
        if our_bid >= our_ask:
            return []
        limit = LIMITS[VELVET]
        soft = int(self.VELVET_SOFT_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos

        buy_qty, sell_qty = Rugrat.velvet_sizes(signal)
        buy_qty = min(buy_qty, max(0, buy_room))
        sell_qty = min(sell_qty, max(0, sell_room))

        # Inventory brake: past soft, shut off the extending side AND force
        # a minimum on the unwind side (even against signal, to reduce pos)
        if pos >= soft:
            buy_qty = 0
            sell_qty = max(sell_qty, min(self.VELVET_UNWIND_MIN, sell_room))
        elif pos <= -soft:
            sell_qty = 0
            buy_qty = max(buy_qty, min(self.VELVET_UNWIND_MIN, buy_room))

        orders: List[Order] = []
        if buy_qty > 0:
            orders.append(Order(VELVET, int(our_bid), buy_qty))
        if sell_qty > 0:
            orders.append(Order(VELVET, int(our_ask), -sell_qty))
        return orders

    # ── Voucher baseline MM (belfort)
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

    # ── Tier 3 aggressive voucher stack
    def _tier3_voucher(self, prod: str, od: OrderDepth, cur: int,
                       signal: float, existing: List[Order]) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if ba - bb < 2:
            return []
        limit = LIMITS[prod]
        queued_buy = sum(o.quantity for o in existing if o.quantity > 0)
        queued_sell = sum(-o.quantity for o in existing if o.quantity < 0)
        if signal > 0:
            room = max(0, limit - cur - queued_buy)
            qty = min(self.TIER3_LEVER_SIZE, room)
            if qty <= 0:
                return []
            return [Order(prod, int(bb + 1), qty)]
        else:
            room = max(0, limit + cur - queued_sell)
            qty = min(self.TIER3_LEVER_SIZE, room)
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
