import json
from datamodel import Order, OrderDepth, TradingState

# ─── Product Names & Limits ──────────────────────────────────────────
OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

LIMITS = {OSMIUM: 80, PEPPER: 80}

# ─── OSMIUM Config ───────────────────────────────────────────────────
# From analysis: spread=16 in symmetric state, FV = midprice (integer)
# 65% reversal probability after each FV step → fade last move
# Mean-reverts to ~10000 (OU half-life 50-110 sym ticks)
OSMIUM_LONG_RUN_MEAN = 10000
OSMIUM_HALF_SPREAD = 7          # quote inside the 16-wide spread
OSMIUM_TIGHT_SPREAD = 6         # tighter when signals are strong
OSMIUM_WIDE_SPREAD = 8          # wider when uncertain or risky
OSMIUM_MAX_PASSIVE_SIZE = 15    # per-side passive order size
OSMIUM_TAKE_THRESHOLD = 3       # take if mispriced by >= this amount

# ─── PEPPER Config ───────────────────────────────────────────────────
# Trending asset (+1000/day). Passive-only MM, no taking (EMA lag kills).
PEPPER_EMA_ALPHA = 0.3          # fast EMA to reduce trend lag
PEPPER_HALF_SPREAD = 5          # quote inside typical 12-14 spread
PEPPER_MAX_PASSIVE_SIZE = 10


class Trader:

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result: dict[str, list[Order]] = {}

        # ── Restore State ────────────────────────────────────────────
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {}

        # ── OSMIUM ───────────────────────────────────────────────────
        if OSMIUM in state.order_depths:
            osmium_orders, td = self.trade_osmium(state, td)
            result[OSMIUM] = osmium_orders

        # ── PEPPER ───────────────────────────────────────────────────
        if PEPPER in state.order_depths:
            pepper_orders, td = self.trade_pepper(state, td)
            result[PEPPER] = pepper_orders

        return result, 0, json.dumps(td)

    # ══════════════════════════════════════════════════════════════════
    #  OSMIUM: Mean-reverting MM with step-reversal + distance signals
    # ══════════════════════════════════════════════════════════════════
    def trade_osmium(self, state: TradingState, td: dict) -> tuple[list[Order], dict]:
        orders: list[Order] = []
        od: OrderDepth = state.order_depths[OSMIUM]
        position = state.position.get(OSMIUM, 0)
        limit = LIMITS[OSMIUM]

        # --- Extract FV from symmetric book (spread=16) ---
        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None

        prev_fv = td.get("osm_fv")
        prev_step = td.get("osm_step", 0)  # last FV step direction

        fv = prev_fv  # default: keep old FV

        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0

            if spread == 16:
                # Symmetric state → clean FV extraction
                fv = int(mid)
            elif spread <= 19 and prev_fv is not None:
                # Wide state (post-hit): FV hasn't changed, keep previous
                pass
            else:
                # Fallback: use midprice rounded
                fv = round(mid)

        if fv is None:
            # No FV yet, skip
            td["osm_fv"] = None
            return orders, td

        # --- Detect FV step ---
        step = 0
        if prev_fv is not None and fv != prev_fv:
            step = 1 if fv > prev_fv else -1
            td["osm_step"] = step
        elif prev_step != 0:
            step = prev_step  # no new step, keep last direction

        td["osm_fv"] = fv

        # --- Compute signals ---
        # Signal 1: Step reversal (65% probability of reversal)
        reversal_bias = 0
        if step != 0:
            reversal_bias = -step  # expect reversal: if step was +1, bias is -1

        # Signal 2: Distance from long-run mean
        distance = fv - OSMIUM_LONG_RUN_MEAN
        distance_bias = 0
        if abs(distance) >= 3:
            distance_bias = -1 if distance > 0 else 1  # fade toward mean

        # Combined signal: -2 to +2
        combined = reversal_bias + distance_bias

        # --- Determine spread based on signal strength ---
        if abs(combined) == 2:
            half_spread = OSMIUM_TIGHT_SPREAD  # strong signal → tighter spread
        elif abs(combined) == 0:
            half_spread = OSMIUM_WIDE_SPREAD   # no signal → wider
        else:
            half_spread = OSMIUM_HALF_SPREAD   # normal

        # --- Skew quotes based on inventory + signal ---
        # inventory_skew: positive means we want to sell (we're long)
        inventory_skew = position / limit  # -1 to +1

        # signal_skew: positive means we expect price to go up → want to buy
        signal_skew = combined * 0.3  # scale the combined signal

        # Net skew applied to quotes (positive = shift quotes up)
        net_skew = signal_skew - inventory_skew * 2.0

        bid_price = round(fv - half_spread + net_skew)
        ask_price = round(fv + half_spread + net_skew)

        # Ensure we don't cross ourselves
        if bid_price >= ask_price:
            bid_price = fv - 1
            ask_price = fv + 1

        # --- Aggressive taking: grab mispriced orders ---
        # Compute a directional fair value adjustment based on signal
        adjusted_fv = fv + combined * 0.5

        buy_qty_used = 0
        sell_qty_used = 0

        # Take cheap asks (below our adjusted FV minus threshold)
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < adjusted_fv - OSMIUM_TAKE_THRESHOLD:
                    ask_vol = abs(od.sell_orders[ask_p])
                    can_buy = limit - position - buy_qty_used
                    take = min(ask_vol, can_buy)
                    if take > 0:
                        orders.append(Order(OSMIUM, ask_p, take))
                        buy_qty_used += take

        # Take expensive bids (above our adjusted FV plus threshold)
        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p > adjusted_fv + OSMIUM_TAKE_THRESHOLD:
                    bid_vol = od.buy_orders[bid_p]
                    can_sell = limit + position - sell_qty_used
                    take = min(bid_vol, can_sell)
                    if take > 0:
                        orders.append(Order(OSMIUM, bid_p, -take))
                        sell_qty_used += take

        # --- Passive quoting ---
        # Size: larger when signals are strong, smaller when inventory is extreme
        base_size = OSMIUM_MAX_PASSIVE_SIZE
        inv_penalty = abs(position) / limit  # 0 to 1
        passive_size = max(1, round(base_size * (1 - inv_penalty * 0.6)))

        # Passive buy
        buy_room = limit - position - buy_qty_used
        passive_buy = min(passive_size, buy_room)
        if passive_buy > 0:
            orders.append(Order(OSMIUM, bid_price, passive_buy))

        # Passive sell
        sell_room = limit + position - sell_qty_used
        passive_sell = min(passive_size, sell_room)
        if passive_sell > 0:
            orders.append(Order(OSMIUM, ask_price, -passive_sell))

        return orders, td

    # ══════════════════════════════════════════════════════════════════
    #  PEPPER: Trend-following adaptive MM (EMA-based FV, passive only)
    # ══════════════════════════════════════════════════════════════════
    def trade_pepper(self, state: TradingState, td: dict) -> tuple[list[Order], dict]:
        orders: list[Order] = []
        od: OrderDepth = state.order_depths[PEPPER]
        position = state.position.get(PEPPER, 0)
        limit = LIMITS[PEPPER]

        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None

        if best_bid is None or best_ask is None:
            return orders, td

        mid = (best_bid + best_ask) / 2.0

        # --- EMA fair value (fast alpha to reduce trend lag) ---
        prev_ema = td.get("pep_ema")
        if prev_ema is None:
            ema = mid
        else:
            ema = PEPPER_EMA_ALPHA * mid + (1 - PEPPER_EMA_ALPHA) * prev_ema

        td["pep_ema"] = ema

        # --- Trend detection via slow vs fast EMA crossover ---
        slow_alpha = 0.05
        prev_slow = td.get("pep_slow_ema")
        if prev_slow is None:
            slow_ema = mid
        else:
            slow_ema = slow_alpha * mid + (1 - slow_alpha) * prev_slow
        td["pep_slow_ema"] = slow_ema

        trend = 0
        ema_diff = ema - slow_ema
        if ema_diff > 1.0:
            trend = 1
        elif ema_diff < -1.0:
            trend = -1

        fv = round(ema)

        # --- Inventory skew + trend skew ---
        inventory_skew = position / limit  # -1 to +1

        # Strong trend skew: shift quotes to lean into trend
        trend_skew = trend * 1.5

        # Heavy inventory penalty to avoid getting stuck on one side
        net_skew = trend_skew - inventory_skew * 3.0

        bid_price = round(fv - PEPPER_HALF_SPREAD + net_skew)
        ask_price = round(fv + PEPPER_HALF_SPREAD + net_skew)

        if bid_price >= ask_price:
            bid_price = fv - 1
            ask_price = fv + 1

        # --- Passive quoting only (NO aggressive taking on trending asset) ---
        inv_penalty = abs(position) / limit
        passive_size = max(1, round(PEPPER_MAX_PASSIVE_SIZE * (1 - inv_penalty * 0.5)))

        buy_room = limit - position
        passive_buy = min(passive_size, buy_room)
        if passive_buy > 0:
            orders.append(Order(PEPPER, bid_price, passive_buy))

        sell_room = limit + position
        passive_sell = min(passive_size, sell_room)
        if passive_sell > 0:
            orders.append(Order(PEPPER, ask_price, -passive_sell))

        return orders, td
