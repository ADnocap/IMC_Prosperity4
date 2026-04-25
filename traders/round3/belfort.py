# R3 trader — "Belfort". Wolf-of-Wall-Street themed MM.
#
# Design discipline after MC ablation (see notes at bottom of file):
#   * The Rust MC sim treats every asset as an INDEPENDENT random walk —
#     each VEV voucher has its own calibrated drift/sigma and does not
#     follow the underlying VELVET in simulation.
#   * Therefore a Black-Scholes theoretical value derived from VELVET will
#     diverge from the sim's voucher FV and any taker overlay keyed on it
#     (MarkHanna.call(velvet, K, T, σ) ≠ sim_fv_voucher) bleeds money.
#   * On portal / historical CSVs the coupling is real and BS pricing is
#     correct (r3_smile_clean.py confirms observed ITM mids = BS theo to
#     0.01 XIRECs). So the BS machinery is kept in the file behind a
#     ``ENABLE_BS`` switch — flip it on once we validate against CSV replay
#     or portal backtest, not against the MC sim.
#
# Ships as pure penny-jump MM with spread-tier sizing:
#   * wide-spread assets (HYDROGEL, VEV_4000, VEV_4500) → bigger quotes
#   * tight-spread assets (VELVET, VEV_5000/5100/5200)  → smaller quotes
#   * dead assets (VEV_5300/5400/5500/6000/6500)        → skipped
#
# Named internals:
#   MarkHanna — BS pricer/Greeks, dormant until ENABLE_BS=True
#   Trader    — the execution loop (Jordan's order ticket)

from datamodel import OrderDepth, TradingState, Order
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

# Seed per-strike IV — mean of inverted BS on day-2 historical mids.
# Dormant unless ENABLE_BS is set to True.
SEED_IV = {
    VEV_4000: 0.362, VEV_4500: 0.270,
    VEV_5000: 0.233, VEV_5100: 0.226, VEV_5200: 0.232, VEV_5300: 0.237,
    VEV_5400: 0.220, VEV_5500: 0.241,
    VEV_6000: 0.405, VEV_6500: 0.616,
}
TTE_YEARS = 5.0 / 365.0

# Spread-tier classification from analysis/round3/r3_smile_clean.py:
#   WIDE_MM: median spread 16–21 ticks → quote size 15
#   TIGHT_MM: median spread 3–6 ticks → quote size 5
#   rest: too tight (1–2 spread) or dead (VEV_6000/6500 with FV=0.5 floor)
WIDE_MM = (HYDROGEL, VEV_4000, VEV_4500)
TIGHT_MM = (VELVET, VEV_5000, VEV_5100, VEV_5200)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class MarkHanna:
    """Dormant Black-Scholes pricer. Mentor stays in the car."""

    @staticmethod
    def call(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(S - K, 0.0)
        vt = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vt
        d2 = d1 - vt
        return S * _norm_cdf(d1) - K * _norm_cdf(d2)

    @staticmethod
    def delta(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        vt = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vt
        return _norm_cdf(d1)

    @staticmethod
    def vega(S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 0.0
        vt = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vt
        return S * _norm_pdf(d1) * math.sqrt(T)


class Trader:
    # Flip to True only after validating BS-overlay edge on CSV replay or
    # portal backtest. MC sim decouples vouchers from VELVET so BS theo is
    # unsafe to act on in simulation.
    ENABLE_BS = False

    WIDE_SIZE = 15
    TIGHT_SIZE = 5
    SOFT_FRAC = 0.6
    MIN_SPREAD = 2

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0
        td = self._load_td(state.traderData)

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            if product in WIDE_MM:
                orders = self._mm(product, od, pos, self.WIDE_SIZE)
            elif product in TIGHT_MM:
                orders = self._mm(product, od, pos, self.TIGHT_SIZE)
            else:
                orders = []
            result[product] = orders

        return result, conversions, json.dumps(td)

    def _mm(self, product: str, od: OrderDepth, pos: int, size: int) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        spread = ba - bb
        if spread < self.MIN_SPREAD:
            return []

        our_bid = bb + 1
        our_ask = ba - 1
        if our_bid >= our_ask:
            return []

        limit = LIMITS[product]
        soft = int(self.SOFT_FRAC * limit)
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
            orders.append(Order(product, int(our_bid), buy_qty))
        if sell_qty > 0:
            orders.append(Order(product, int(our_ask), -sell_qty))
        return orders

    def _load_td(self, blob: str) -> dict:
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except Exception:
            return {}


# ── Ablation note (2026-04-24) ────────────────────────────────────────
# v1 had a BS taker overlay and a theo-gated MM. MC result: mean PnL
# -158,771 vs a.py +11,666 on --quick (100 sessions, 10K ticks). The
# taker lost -170k across the 6 theo-priced vouchers because the sim's
# independent random walks drifted away from BS(VELVET, K, T, σ).
# v2 (this file) strips the overlay and goes back to pure penny-jump MM
# with spread-tier sizing. Expected to beat a.py purely from larger
# quote size on HYDROGEL / VEV_4000 / VEV_4500 (16–21 tick spreads).
