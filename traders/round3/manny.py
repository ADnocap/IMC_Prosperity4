# Manny — Manny Riskin, Belfort's lawyer. The sophisticated one with the
# pricing model. Hypothesis test: does a fitted Black-Scholes vol smile
# beat the model-free Chester approach when applied across all 8 active
# vouchers (4000..5500)?
#
# Strategy:
#   - Hard-coded parabolic vol smile fitted offline from Day 2 data
#     (analysis/round3/smile_coefs_day2.json):
#         iv(m) = smile_a + smile_b * m + smile_c * m^2,
#         m = log(K / S)
#     with TTE = 6/365 years, BS r = 0, Normal CDF from statistics stdlib.
#   - Per voucher: compute theoretical price from VELVETFRUIT_EXTRACT mid,
#     compare to market mid. If |market_mid - theo| > THRESHOLD (XIRECs):
#       * market_mid >> theo -> sell aggressively, take their bids
#       * market_mid << theo -> buy aggressively, lift their asks
#     up to the full 300-lot position limit on each strike.
#   - VELVETFRUIT_EXTRACT and HYDROGEL_PACK use the same penny-jump MM
#     as hanna.py (size 30) — those aren't the model's edge.
#   - VEV_6000 / VEV_6500 stay skipped (dead, FV ~ 0).

from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
from statistics import NormalDist
import json
import math


HYDROGEL = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"

VEV_STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500,
    "VEV_5000": 5000, "VEV_5100": 5100,
    "VEV_5200": 5200, "VEV_5300": 5300,
    "VEV_5400": 5400, "VEV_5500": 5500,
}

LIMITS = {
    HYDROGEL: 200, VELVET: 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
}

# Smile coefficients fit on Day 2 (analysis/round3/smile_coefs_day2.json).
# Formula: iv(m) = SMILE_A + SMILE_B * m + SMILE_C * m**2, m = log(K/S).
SMILE_A = 0.23191586677818826
SMILE_B = 0.04357235171166418
SMILE_C = 1.9376638984839945
TTE_YEARS = 6.0 / 365.0
IV_FLOOR = 0.05

# Take when market mid deviates from theoretical by this many XIRECs.
# Smile residual std ~= 0.010 IV units; ATM vega ~= 269 -> 1 XIREC ~= 0.4
# IV stdev. Threshold of 1.5 XIRECs is ~0.6 stdev — comfortable margin.
TAKE_THRESHOLD = 1.5
MAX_TAKE_PER_TICK = 80


_NORM = NormalDist()


def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * _NORM.cdf(d1) - K * _NORM.cdf(d2)


def smile_iv(K: float, S: float) -> float:
    m = math.log(K / S)
    iv = SMILE_A + SMILE_B * m + SMILE_C * m * m
    return max(iv, IV_FLOOR)


def best_levels(od: OrderDepth):
    bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
    asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
    return bids, asks


def mid_price(od: OrderDepth):
    bids, asks = best_levels(od)
    if not bids or not asks:
        return None
    return (bids[0] + asks[0]) / 2.0


class Trader:
    R3_QUOTE_SIZE = 30
    R3_TIGHT_SPREAD_THRESHOLD = 2
    R3_SOFT_POS_FRAC = 0.6

    MM_ASSETS = (HYDROGEL, VELVET)

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td: dict = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        # Underlying spot mid for the BS pricer. If the spot book is empty
        # we skip voucher trading this tick (no anchor).
        S = None
        if VELVET in state.order_depths:
            S = mid_price(state.order_depths[VELVET])

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            if product in VEV_STRIKES and S is not None:
                K = VEV_STRIKES[product]
                result[product] = self._trade_voucher(product, K, S, od, pos)
            elif product in self.MM_ASSETS:
                result[product] = self._mm(product, od, pos)
            else:
                result[product] = []

        return result, conversions, json.dumps(td)

    def _trade_voucher(self, product: str, K: int, S: float,
                       od: OrderDepth, pos: int) -> List[Order]:
        bids, asks = best_levels(od)
        if not bids or not asks:
            return []

        iv = smile_iv(K, S)
        theo = bs_call(S, K, TTE_YEARS, iv)
        market_mid = (bids[0] + asks[0]) / 2.0
        diff = market_mid - theo
        limit = LIMITS[product]

        orders: List[Order] = []

        if diff > TAKE_THRESHOLD:
            # Market is rich -> sell. Hit bids at or above theo + small buffer.
            sell_room = limit + pos
            if sell_room <= 0:
                return []
            remaining = min(MAX_TAKE_PER_TICK, sell_room)
            min_acceptable_bid = theo + 0.5  # leave some edge per share
            for bid_price in bids:
                if remaining <= 0:
                    break
                if bid_price < min_acceptable_bid:
                    break
                qty = min(remaining, od.buy_orders[bid_price])
                orders.append(Order(product, bid_price, -qty))
                remaining -= qty
            return orders

        if diff < -TAKE_THRESHOLD:
            # Market is cheap -> buy. Lift asks at or below theo - buffer.
            buy_room = limit - pos
            if buy_room <= 0:
                return []
            remaining = min(MAX_TAKE_PER_TICK, buy_room)
            max_acceptable_ask = theo - 0.5
            for ask_price in asks:
                if remaining <= 0:
                    break
                if ask_price > max_acceptable_ask:
                    break
                qty = min(remaining, -od.sell_orders[ask_price])
                orders.append(Order(product, ask_price, qty))
                remaining -= qty
            return orders

        # Within threshold -> passively MM with tight quotes if there's room.
        return self._mm(product, od, pos)

    def _mm(self, product: str, od: OrderDepth, pos: int) -> List[Order]:
        bids, asks = best_levels(od)
        if not bids or not asks:
            return []

        best_bid, best_ask = bids[0], asks[0]
        if best_ask - best_bid < self.R3_TIGHT_SPREAD_THRESHOLD:
            return []

        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []

        limit = LIMITS[product]
        soft_thresh = int(self.R3_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(self.R3_QUOTE_SIZE, max(0, buy_room))
        sell_qty = min(self.R3_QUOTE_SIZE, max(0, sell_room))

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
