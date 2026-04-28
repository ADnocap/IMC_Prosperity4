"""R5 trader v1 — penny-jump MM on all 50 products + PEBBLES_XL basket-FV.

Bot model (from calibration):
- All 50 products quoted at bid_1 = floor(FV - h + 0.5), ask_1 = ceil(FV + h - 0.5)
- h ranges from 3.0 to 9.0; all spreads >= 6 ticks → always room to penny-jump.
- Pulses lift L1 ask / hit L1 bid; ~0.024/tick V, 0.021/tick P, 0.019/tick M.
- Position limit 10 per product.

Strategy:
- For each product, observe best_bid/best_ask, compute mid as FV proxy.
- PEBBLES_XL FV is *exactly* 50000 - mid(XS) - mid(S) - mid(M) - mid(L) thanks to
  the constant-sum constraint. Use that instead of XL's own mid when estimating XL's FV.
- Penny-jump: bid at best_bid+1, ask at best_ask-1 (only if spread >= 2).
- Inventory-aware sizing: bid_size = min(10, 10 - pos); ask_size = min(10, 10 + pos).
  Worst-case: pos+bid_size <= 10 and pos-ask_size >= -10 → cancellation rule respected.
- Take any L1 ask < FV - h + 0.5 (free lunch) or L1 bid > FV + h - 0.5.
"""

from __future__ import annotations

from typing import Dict, List

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


# --- 50 product universe (declarations needed for Rust MC sim auto-detection) ---
GALAXY_SOUNDS_DARK_MATTER = "GALAXY_SOUNDS_DARK_MATTER"
GALAXY_SOUNDS_BLACK_HOLES = "GALAXY_SOUNDS_BLACK_HOLES"
GALAXY_SOUNDS_PLANETARY_RINGS = "GALAXY_SOUNDS_PLANETARY_RINGS"
GALAXY_SOUNDS_SOLAR_WINDS = "GALAXY_SOUNDS_SOLAR_WINDS"
GALAXY_SOUNDS_SOLAR_FLAMES = "GALAXY_SOUNDS_SOLAR_FLAMES"
SLEEP_POD_SUEDE = "SLEEP_POD_SUEDE"
SLEEP_POD_LAMB_WOOL = "SLEEP_POD_LAMB_WOOL"
SLEEP_POD_POLYESTER = "SLEEP_POD_POLYESTER"
SLEEP_POD_NYLON = "SLEEP_POD_NYLON"
SLEEP_POD_COTTON = "SLEEP_POD_COTTON"
MICROCHIP_CIRCLE = "MICROCHIP_CIRCLE"
MICROCHIP_OVAL = "MICROCHIP_OVAL"
MICROCHIP_SQUARE = "MICROCHIP_SQUARE"
MICROCHIP_RECTANGLE = "MICROCHIP_RECTANGLE"
MICROCHIP_TRIANGLE = "MICROCHIP_TRIANGLE"
PEBBLES_XS = "PEBBLES_XS"
PEBBLES_S = "PEBBLES_S"
PEBBLES_M = "PEBBLES_M"
PEBBLES_L = "PEBBLES_L"
PEBBLES_XL = "PEBBLES_XL"
ROBOT_VACUUMING = "ROBOT_VACUUMING"
ROBOT_MOPPING = "ROBOT_MOPPING"
ROBOT_DISHES = "ROBOT_DISHES"
ROBOT_LAUNDRY = "ROBOT_LAUNDRY"
ROBOT_IRONING = "ROBOT_IRONING"
UV_VISOR_YELLOW = "UV_VISOR_YELLOW"
UV_VISOR_AMBER = "UV_VISOR_AMBER"
UV_VISOR_ORANGE = "UV_VISOR_ORANGE"
UV_VISOR_RED = "UV_VISOR_RED"
UV_VISOR_MAGENTA = "UV_VISOR_MAGENTA"
TRANSLATOR_SPACE_GRAY = "TRANSLATOR_SPACE_GRAY"
TRANSLATOR_ASTRO_BLACK = "TRANSLATOR_ASTRO_BLACK"
TRANSLATOR_ECLIPSE_CHARCOAL = "TRANSLATOR_ECLIPSE_CHARCOAL"
TRANSLATOR_GRAPHITE_MIST = "TRANSLATOR_GRAPHITE_MIST"
TRANSLATOR_VOID_BLUE = "TRANSLATOR_VOID_BLUE"
PANEL_1X2 = "PANEL_1X2"
PANEL_2X2 = "PANEL_2X2"
PANEL_1X4 = "PANEL_1X4"
PANEL_2X4 = "PANEL_2X4"
PANEL_4X4 = "PANEL_4X4"
OXYGEN_SHAKE_MORNING_BREATH = "OXYGEN_SHAKE_MORNING_BREATH"
OXYGEN_SHAKE_EVENING_BREATH = "OXYGEN_SHAKE_EVENING_BREATH"
OXYGEN_SHAKE_MINT = "OXYGEN_SHAKE_MINT"
OXYGEN_SHAKE_CHOCOLATE = "OXYGEN_SHAKE_CHOCOLATE"
OXYGEN_SHAKE_GARLIC = "OXYGEN_SHAKE_GARLIC"
SNACKPACK_CHOCOLATE = "SNACKPACK_CHOCOLATE"
SNACKPACK_VANILLA = "SNACKPACK_VANILLA"
SNACKPACK_PISTACHIO = "SNACKPACK_PISTACHIO"
SNACKPACK_STRAWBERRY = "SNACKPACK_STRAWBERRY"
SNACKPACK_RASPBERRY = "SNACKPACK_RASPBERRY"

POSITION_LIMIT = 10
PEBBLES_FREE = (PEBBLES_XS, PEBBLES_S, PEBBLES_M, PEBBLES_L)
PEBBLE_CONSTANT = 50000.0


def _best_bid_ask(od: OrderDepth):
    bid = max(od.buy_orders.keys()) if od.buy_orders else None
    ask = min(od.sell_orders.keys()) if od.sell_orders else None
    return bid, ask


def _mid(od: OrderDepth):
    bid, ask = _best_bid_ask(od)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}

        # ---- compute PEBBLES_XL implied FV from constraint --------------------
        pebble_xl_fv = None
        if all(p in state.order_depths for p in PEBBLES_FREE):
            mids = [_mid(state.order_depths[p]) for p in PEBBLES_FREE]
            if all(m is not None for m in mids):
                pebble_xl_fv = PEBBLE_CONSTANT - sum(mids)

        # ---- per-product: penny-jump MM ----------------------------------------
        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            best_bid, best_ask = _best_bid_ask(od)
            if best_bid is None or best_ask is None:
                continue

            # FV: PEBBLES_XL uses basket constraint, others use mid
            if product == PEBBLES_XL and pebble_xl_fv is not None:
                fv = pebble_xl_fv
            else:
                fv = (best_bid + best_ask) / 2.0

            # capacity (worst-case-fill rule)
            bid_cap = max(0, POSITION_LIMIT - pos)
            ask_cap = max(0, POSITION_LIMIT + pos)

            orders: List[Order] = []

            # ---- TAKE side: free fills if any L1 sits beyond fv +/- spread ----
            # Take any ask priced strictly below fv (we'd buy below fair).
            # Conservative: only take if ask <= fv - 1 (one full tick of edge).
            took_buy = 0
            for ask_px in sorted(od.sell_orders.keys()):
                if ask_px <= fv - 1.0 and bid_cap - took_buy > 0:
                    qty = min(-od.sell_orders[ask_px], bid_cap - took_buy)
                    if qty > 0:
                        orders.append(Order(product, ask_px, qty))
                        took_buy += qty
                else:
                    break

            took_sell = 0
            for bid_px in sorted(od.buy_orders.keys(), reverse=True):
                if bid_px >= fv + 1.0 and ask_cap - took_sell > 0:
                    qty = min(od.buy_orders[bid_px], ask_cap - took_sell)
                    if qty > 0:
                        orders.append(Order(product, bid_px, -qty))
                        took_sell += qty
                else:
                    break

            # ---- MAKE side: penny-jump on remaining capacity ------------------
            remaining_bid = bid_cap - took_buy
            remaining_ask = ask_cap - took_sell

            # Re-derive best after we'd swept any takes (only takes on the
            # opposite side affect best — bid-side take consumed asks, etc.)
            spread = best_ask - best_bid
            if spread >= 2:
                quote_bid = best_bid + 1
                quote_ask = best_ask - 1
            else:
                # spread of 1 (rare given h>=3); join the best
                quote_bid = best_bid
                quote_ask = best_ask

            # Don't quote on the wrong side of fv (avoid stale fills near regime breaks)
            if quote_bid >= fv:
                quote_bid = int(fv - 0.5)  # post just below fv
            if quote_ask <= fv:
                quote_ask = int(fv + 0.5) + (1 if (fv * 2) % 2 == 0 else 0)
            if quote_ask <= quote_bid:
                quote_ask = quote_bid + 1

            mm_bid_size = min(10, remaining_bid)
            mm_ask_size = min(10, remaining_ask)

            if mm_bid_size > 0:
                orders.append(Order(product, quote_bid, mm_bid_size))
            if mm_ask_size > 0:
                orders.append(Order(product, quote_ask, -mm_ask_size))

            result[product] = orders

        return result, 0, ""