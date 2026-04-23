"""Reference trader implementing the optimizer param contract.

This file exists only so there's a minimal, working trader to point the
demo study at for smoke-testing the optimizer. It is NOT a shipping
submission — it's a one-asset passive maker with three tunable params.

The important thing here is the `_load_param_overrides` snippet and the
`self.p` pattern: copy-paste this into any trader you want the optimizer to
tune. In portal submission the env var won't be set, so `self.p` falls
through to `PARAMS` defaults.

Tunable params:
    MAKE_SPREAD    — half-width of the passive two-sided quote around FV.
    TAKE_EDGE      — cross the book for any price at least this far from FV.
    SOFT_POS_CAP   — stop quoting the side that grows inventory once |pos| > cap.
"""

from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
import json
import os


OSMIUM = "ASH_COATED_OSMIUM"
LIMIT = 80


def _load_param_overrides():
    raw = os.environ.get("PROSPERITY_PARAMS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class Trader:
    PARAMS = {
        "MAKE_SPREAD": 3,
        "TAKE_EDGE": 2,
        "SOFT_POS_CAP": 40,
    }

    def __init__(self):
        self.p = {**self.PARAMS, **_load_param_overrides()}

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        od = state.order_depths.get(OSMIUM)
        pos = state.position.get(OSMIUM, 0)

        if od is None:
            return result, 0, ""

        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []

        fv = self._estimate_fv(od, bids, asks)
        if fv is None:
            return {OSMIUM: []}, 0, ""
        fv_r = int(round(fv))

        orders: List[Order] = []
        buy_ordered = 0
        sell_ordered = 0

        take_edge = int(self.p["TAKE_EDGE"])
        make_spread = int(self.p["MAKE_SPREAD"])
        soft_cap = int(self.p["SOFT_POS_CAP"])

        # Take side: hit any ask <= fv - edge or any bid >= fv + edge.
        for ap in asks:
            if ap > fv_r - take_edge:
                break
            vol = -od.sell_orders[ap]
            can = LIMIT - pos - buy_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, ap, qty))
            buy_ordered += qty

        for bp in bids:
            if bp < fv_r + take_edge:
                break
            vol = od.buy_orders[bp]
            can = LIMIT + pos - sell_ordered
            if can <= 0:
                break
            qty = min(vol, can)
            orders.append(Order(OSMIUM, bp, -qty))
            sell_ordered += qty

        # Make side: passive two-sided quote, skipping the inventory-growing leg
        # once we've crossed the soft cap.
        if pos < soft_cap:
            room = LIMIT - pos - buy_ordered
            if room > 0:
                orders.append(Order(OSMIUM, fv_r - make_spread, min(room, 30)))
        if pos > -soft_cap:
            room = LIMIT + pos - sell_ordered
            if room > 0:
                orders.append(Order(OSMIUM, fv_r + make_spread, -min(room, 30)))

        return {OSMIUM: orders}, 0, ""

    def _estimate_fv(self, od: OrderDepth, bids, asks):
        # Bot 1 wall: volume >= 20 at ~FV ± 10.5 (±10 or ±11 depending on rounding).
        # Average the two sides if both present.
        estimates = []
        for p in bids:
            if od.buy_orders[p] >= 20:
                estimates.append(p + 10.5)
                break
        for p in asks:
            if -od.sell_orders[p] >= 20:
                estimates.append(p - 10.5)
                break
        if estimates:
            return sum(estimates) / len(estimates)
        if bids and asks:
            return (bids[0] + asks[0]) / 2.0
        return None
