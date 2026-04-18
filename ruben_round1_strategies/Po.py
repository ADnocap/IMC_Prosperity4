"""
Round 1 Strategy v1 — IPR buy-and-hold + ACO signal-informed MM

IPR: Deterministic +0.1/tick drift. Buy to max position ASAP.
ACO: Mean-reverting integer FV. Exploit:
  1. 65% reversal on FV steps (fade last move)
  2. OU mean-reversion toward ~10000
  3. Bot1 (L2, vol 20-30) asymmetry for real-time FV detection
  4. Asymmetric MM: tighten quotes on the side FV is heading
"""

import json
from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order

IPR = "INTARIAN_PEPPER_ROOT"
ACO = "ASH_COATED_OSMIUM"
LIMIT = 80  # position limit for both products
MU = 10000  # long-run ACO mean


class Trader:

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        # ── Restore persisted state ──────────────────────────────────
        data = self._load(state.traderData)

        # ── Trade each product ───────────────────────────────────────
        if IPR in state.order_depths:
            result[IPR] = self._trade_ipr(state)

        if ACO in state.order_depths:
            result[ACO] = self._trade_aco(state, data)

        return result, 0, self._save(data)

    # ── IPR: buy-and-hold ────────────────────────────────────────────

    def _trade_ipr(self, state: TradingState) -> List[Order]:
        orders = []
        pos = state.position.get(IPR, 0)
        od = state.order_depths[IPR]

        remaining = LIMIT - pos
        if remaining <= 0:
            return orders

        # Take any available asks (aggressive buy)
        for price in sorted(od.sell_orders.keys()):
            qty = min(remaining, -od.sell_orders[price])
            if qty > 0:
                orders.append(Order(IPR, price, qty))
                remaining -= qty
            if remaining <= 0:
                break

        # Post a passive bid for the rest
        if remaining > 0:
            best_bid = max(od.buy_orders.keys()) if od.buy_orders else 9990
            orders.append(Order(IPR, best_bid + 1, remaining))

        return orders

    # ── ACO: signal-informed market making ───────────────────────────

    def _trade_aco(self, state: TradingState, data: dict) -> List[Order]:
        od = state.order_depths[ACO]
        pos = state.position.get(ACO, 0)

        # ── 1. Extract FV from Bot2 walls (vol 10-15, spread 16) ────
        fv = self._extract_fv(od)
        bot1_fv = self._extract_bot1_fv(od)

        # Use best available FV estimate
        if fv is not None:
            data["fv"] = fv
        elif bot1_fv is not None:
            # Bot1 updates before Bot2; use it if Bot2 walls are gone
            data["fv"] = bot1_fv
        fv = data.get("fv")

        if fv is None:
            return []  # no FV estimate yet, skip

        # ── 2. Compute signals ──────────────────────────────────────
        prev_fv = data.get("prev_fv", fv)
        step = fv - prev_fv

        # Signal 1: Fade last step (65% reversal)
        last_step_dir = data.get("last_step_dir", 0)
        reversal_signal = -last_step_dir  # +1 = expect up, -1 = expect down

        # Update last step direction (only on actual FV changes)
        if step != 0:
            data["last_step_dir"] = 1 if step > 0 else -1

        # Signal 2: Mean-reversion (fade distance from mu)
        distance = fv - MU
        if abs(distance) >= 3:
            mr_signal = -1 if distance > 0 else 1
        else:
            mr_signal = 0

        # Signal 3: Bot1 asymmetry (real-time FV detection)
        bot1_signal = self._get_bot1_signal(od, fv)

        # Combine: weighted sum
        # Reversal is the strongest short-term signal
        # Mean-reversion helps at extremes
        # Bot1 confirms direction
        combined = (
            reversal_signal * 3
            + mr_signal * 2
            + bot1_signal * 1
        )

        data["prev_fv"] = fv

        # ── 3. Compute target position ──────────────────────────────
        # Scale position by signal strength, cap at ±LIMIT
        target_pos = int(max(-LIMIT, min(LIMIT, combined * 5)))

        # ── 4. Generate orders ──────────────────────────────────────
        orders = []

        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is None or best_ask is None:
            return orders

        spread = best_ask - best_bid

        # ── Phase A: Take favorable prices (cross the spread) ───────
        # If signal is bullish and there's a cheap ask (near/below FV)
        if combined > 0 and pos < target_pos:
            take_qty = min(3, target_pos - pos, LIMIT - pos)
            # Only take if ask is reasonably close to FV
            if best_ask <= fv + 2 and take_qty > 0:
                orders.append(Order(ACO, best_ask, take_qty))
                pos += take_qty

        elif combined < 0 and pos > target_pos:
            take_qty = min(3, pos - target_pos, LIMIT + pos)
            # Only take if bid is reasonably close to FV
            if best_bid >= fv - 2 and take_qty > 0:
                orders.append(Order(ACO, best_bid, -take_qty))
                pos -= take_qty

        # ── Phase B: Post asymmetric passive quotes ─────────────────
        # Tighten on the side we expect FV to move, widen on the other

        if combined > 0:
            # Bullish: tighter bid, wider ask
            bid_offset = 7   # closer to FV (normally 8)
            ask_offset = 9   # further from FV
        elif combined < 0:
            # Bearish: wider bid, tighter ask
            bid_offset = 9
            ask_offset = 7
        else:
            # Neutral: symmetric
            bid_offset = 8
            ask_offset = 8

        my_bid = int(fv - bid_offset)
        my_ask = int(fv + ask_offset)

        # Penny-jump: improve by 1 if we can
        if best_bid is not None and my_bid <= best_bid:
            my_bid = best_bid + 1
        if best_ask is not None and my_ask >= best_ask:
            my_ask = best_ask - 1

        # Ensure bid < ask
        if my_bid >= my_ask:
            my_bid = my_ask - 1

        # Sizes: adjust based on position and signal direction
        buy_room = LIMIT - pos
        sell_room = LIMIT + pos

        # Level 1: primary quotes
        bid_qty = min(3, buy_room)
        ask_qty = min(3, sell_room)

        if bid_qty > 0:
            orders.append(Order(ACO, my_bid, bid_qty))
        if ask_qty > 0:
            orders.append(Order(ACO, my_ask, -ask_qty))

        # Level 2: wider backup quotes (catch big moves)
        wide_bid = int(fv - 10)
        wide_ask = int(fv + 10)
        wide_bid_qty = min(5, buy_room - bid_qty)
        wide_ask_qty = min(5, sell_room - ask_qty)

        if wide_bid_qty > 0:
            orders.append(Order(ACO, wide_bid, wide_bid_qty))
        if wide_ask_qty > 0:
            orders.append(Order(ACO, wide_ask, -wide_ask_qty))

        # ── Phase C: Inventory unwind pressure ──────────────────────
        # If position is getting large, add aggressive unwind orders
        if abs(pos) > 40:
            if pos > 40:
                # Need to sell — post tighter ask
                unwind_ask = int(fv + 3)
                unwind_qty = min(5, LIMIT + pos)
                if unwind_qty > 0:
                    orders.append(Order(ACO, unwind_ask, -unwind_qty))
            elif pos < -40:
                # Need to buy — post tighter bid
                unwind_bid = int(fv - 3)
                unwind_qty = min(5, LIMIT - pos)
                if unwind_qty > 0:
                    orders.append(Order(ACO, unwind_bid, unwind_qty))

        return orders

    # ── FV extraction helpers ────────────────────────────────────────

    def _extract_fv(self, od: OrderDepth) -> int | None:
        """Extract FV from Bot2 inner walls (vol 10-15, offset ±8)."""
        bot2_bids = []
        bot2_asks = []

        for price, vol in od.buy_orders.items():
            if 10 <= vol <= 15:
                bot2_bids.append(price)
        for price, vol in od.sell_orders.items():
            if 10 <= abs(vol) <= 15:
                bot2_asks.append(price)

        if bot2_bids and bot2_asks:
            fv_from_bid = max(bot2_bids) + 8
            fv_from_ask = min(bot2_asks) - 8
            if fv_from_bid == fv_from_ask:
                return int(fv_from_bid)

        return None

    def _extract_bot1_fv(self, od: OrderDepth) -> int | None:
        """Estimate FV from Bot1 outer walls (vol 20-30).
        Bot1 updates faster than Bot2, giving early FV signal."""
        bot1_bids = []
        bot1_asks = []

        for price, vol in od.buy_orders.items():
            if 20 <= vol <= 30:
                bot1_bids.append(price)
        for price, vol in od.sell_orders.items():
            if 20 <= abs(vol) <= 30:
                bot1_asks.append(price)

        if bot1_bids and bot1_asks:
            # Bot1 at FV ± {10, 11} — use average
            fv_from_bid = max(bot1_bids) + 10.5
            fv_from_ask = min(bot1_asks) - 10.5
            return int(round((fv_from_bid + fv_from_ask) / 2))

        return None

    def _get_bot1_signal(self, od: OrderDepth, fv: int) -> int:
        """Detect Bot1 asymmetry: +1 = bullish, -1 = bearish, 0 = unknown."""
        bot1_bid_off = None
        bot1_ask_off = None

        for price, vol in od.buy_orders.items():
            if 20 <= vol <= 30:
                bot1_bid_off = fv - price

        for price, vol in od.sell_orders.items():
            if 20 <= abs(vol) <= 30:
                bot1_ask_off = price - fv

        if bot1_bid_off is not None and bot1_ask_off is not None:
            asym = bot1_ask_off - bot1_bid_off
            if asym > 0:
                return 1   # ask wider -> bullish
            elif asym < 0:
                return -1  # bid wider -> bearish

        return 0

    # ── State persistence ────────────────────────────────────────────

    def _load(self, trader_data: str) -> dict:
        if trader_data:
            try:
                return json.loads(trader_data)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def _save(self, data: dict) -> str:
        return json.dumps(data)
