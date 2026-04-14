from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math


class Trader:
    """
    EMERALDS: Take at fair (10000) during spread-tightening (~320/day).
              Single-level penny-jump passive MM.
    TOMATOES: EMA mean-reversion taking + 3-regime passive MM.
              Slow EMA (alpha=0.02) tracks fair value; when mid deviates
              by >=3 ticks, aggressively takes in the reversion direction
              with inventory-aware sizing. Passive quotes use regime
              detection (Quiet/Dispersed/Toxic) for spread/size control.
    """

    PARAMS = {
        "EMERALDS": {
            "fair_value": 10000,
            "limit": 80,
            "soft_limit": 80,
        },
        "TOMATOES": {
            "limit": 80,
            "soft_limit": 80,
            # Regime detection
            "vol_window": 5,
            "flow_window": 5,
            "vol_toxic_mult": 2.0,
            "flow_toxic_thresh": 0.3,
            "obi_dispersed_thresh": 0.15,
            # Regime multipliers
            "quiet_spread_mult": 1.0,
            "dispersed_spread_mult": 1.0,
            "toxic_spread_mult": 1.2,
            "toxic_size_mult": 0.2,
            # EMA fair value
            "ema_alpha": 0.02,
            # Mean-reversion taking
            "take_threshold": 3,  # min |mid - ema| to trigger take
            "take_size": 15,  # base contracts per take
        },
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except json.JSONDecodeError:
                td = {}

        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                orders = self._trade_emeralds(od, position)
            elif product == "TOMATOES":
                orders, td = self._trade_tomatoes(od, position, td)
            else:
                orders = []

            result[product] = orders

        return result, conversions, json.dumps(td)

    # ------------------------------------------------------------------
    # EMERALDS
    # ------------------------------------------------------------------
    def _trade_emeralds(self, od: OrderDepth, position: int) -> List[Order]:
        orders = []
        p = self.PARAMS["EMERALDS"]
        fair = p["fair_value"]
        limit = p["limit"]
        soft = p["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        buy_ordered = 0
        sell_ordered = 0

        # Phase 1: take at fair value or better (spread-tightening events)
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fair:
                break
            vol = -od.sell_orders[ask_price]
            can_buy = limit - position - buy_ordered
            if can_buy <= 0:
                break
            qty = min(vol, can_buy)
            orders.append(Order("EMERALDS", ask_price, qty))
            buy_ordered += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fair:
                break
            vol = od.buy_orders[bid_price]
            can_sell = limit + position - sell_ordered
            if can_sell <= 0:
                break
            qty = min(vol, can_sell)
            orders.append(Order("EMERALDS", bid_price, -qty))
            sell_ordered += qty

        # Phase 2: single-level penny-jump passive quotes
        eff_pos = position + buy_ordered - sell_ordered
        skew = self._inventory_skew(eff_pos, soft, limit)

        our_bid = int(min(best_bid + 1, fair - 1) + skew)
        our_ask = int(max(best_ask - 1, fair + 1) + skew)
        if our_bid >= our_ask:
            our_bid = fair - 1
            our_ask = fair + 1

        remaining_buy = limit - position - buy_ordered
        remaining_sell = limit + position - sell_ordered

        if remaining_buy > 0:
            orders.append(Order("EMERALDS", our_bid, remaining_buy))
        if remaining_sell > 0:
            orders.append(Order("EMERALDS", our_ask, -remaining_sell))

        return orders

    # ------------------------------------------------------------------
    # TOMATOES — Regime-Detection Market Making
    # ------------------------------------------------------------------
    def _classify_regime(self, td: dict, p: dict) -> str:
        """Classify current regime as 'toxic', 'dispersed', or 'quiet'."""
        mid_history = td.get("mids", [])
        if len(mid_history) < 3:
            return "quiet"

        # Volatility: rolling absolute mid returns
        returns = td.get("returns", [])
        if len(returns) >= 5:
            mean_vol = sum(returns) / len(returns)
            var_vol = sum((r - mean_vol) ** 2 for r in returns) / len(returns)
            std_vol = math.sqrt(var_vol) if var_vol > 0 else 0.001
            current_vol = returns[-1] if returns else 0

            if current_vol > mean_vol + p["vol_toxic_mult"] * std_vol:
                return "toxic"

        # Flow imbalance (VPIN proxy): rolling buy/sell volume ratio
        flow_hist = td.get("flow", [])
        if len(flow_hist) >= 3:
            recent_flow = flow_hist[-min(len(flow_hist), p["flow_window"]):]
            avg_flow = sum(recent_flow) / len(recent_flow)
            if abs(avg_flow) > p["flow_toxic_thresh"]:
                return "toxic"

        # Deep OBI for dispersed regime
        current_obi = td.get("last_obi", 0)
        if abs(current_obi) > p["obi_dispersed_thresh"]:
            return "dispersed"

        return "quiet"

    def _trade_tomatoes(self, od: OrderDepth, position: int, td: dict):
        orders = []
        p = self.PARAMS["TOMATOES"]
        limit = p["limit"]
        soft = p["soft_limit"]

        if not od.buy_orders or not od.sell_orders:
            return orders, td

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        # --- Update rolling state in traderData ---
        mids = td.get("mids", [])
        returns = td.get("returns", [])
        flow_hist = td.get("flow", [])

        # Mid-price return (absolute, for volatility)
        if mids:
            ret = abs(mid - mids[-1])
            returns.append(ret)
            if len(returns) > p["vol_window"]:
                returns = returns[-p["vol_window"]:]

        mids.append(mid)
        if len(mids) > p["vol_window"] + 1:
            mids = mids[-(p["vol_window"] + 1):]

        # --- EMA fair value ---
        alpha = p["ema_alpha"]
        ema = td.get("ema", mid)
        ema = alpha * mid + (1 - alpha) * ema
        td["ema"] = ema

        # L1 volume imbalance as flow signal (VPIN proxy)
        bid_vol_l1 = od.buy_orders.get(best_bid, 0)
        ask_vol_l1 = -od.sell_orders.get(best_ask, 0)
        total_l1 = bid_vol_l1 + ask_vol_l1
        imbalance = (bid_vol_l1 - ask_vol_l1) / total_l1 if total_l1 > 0 else 0

        flow_hist.append(imbalance)
        if len(flow_hist) > p["flow_window"]:
            flow_hist = flow_hist[-p["flow_window"]:]

        # Deep OBI (use all available book levels)
        total_bid_depth = sum(od.buy_orders.values())
        total_ask_depth = sum(-v for v in od.sell_orders.values())
        deep_obi = 0
        if total_bid_depth + total_ask_depth > 0:
            deep_obi = (total_bid_depth - total_ask_depth) / (total_bid_depth + total_ask_depth)

        td["mids"] = mids
        td["returns"] = returns
        td["flow"] = flow_hist
        td["last_obi"] = deep_obi

        # --- Regime classification ---
        regime = self._classify_regime(td, p)

        # Spread multiplier from regime
        if regime == "toxic":
            spread_mult = p["toxic_spread_mult"]
            size_mult = p["toxic_size_mult"]
        elif regime == "dispersed":
            spread_mult = p["dispersed_spread_mult"]
            size_mult = 1.0
        else:
            spread_mult = p["quiet_spread_mult"]
            size_mult = 1.0

        # --- Phase 1: Mean-reversion taking ---
        # When mid deviates from EMA, take liquidity to capture reversion.
        # Scale size inversely with inventory in that direction to prevent buildup.
        buy_taken = 0
        sell_taken = 0
        take_thresh = p["take_threshold"]
        take_size = p["take_size"]
        gap = mid - ema  # positive = mid above fair, expect drop

        if regime != "toxic":
            if gap < -take_thresh:
                # Mid is below EMA — buy. But reduce size if already long.
                inv_penalty = max(0, position) / limit  # 0 when flat/short, 1 at limit
                qty = max(1, int(take_size * (1 - inv_penalty)))
                qty = min(qty, limit - position)
                if qty > 0:
                    for ask_price in sorted(od.sell_orders.keys()):
                        if ask_price > ema:
                            break
                        vol = -od.sell_orders[ask_price]
                        can = min(vol, qty - buy_taken)
                        if can > 0:
                            orders.append(Order("TOMATOES", ask_price, can))
                            buy_taken += can
                        if buy_taken >= qty:
                            break

            elif gap > take_thresh:
                # Mid is above EMA — sell. But reduce size if already short.
                inv_penalty = max(0, -position) / limit  # 0 when flat/long, 1 at limit
                qty = max(1, int(take_size * (1 - inv_penalty)))
                qty = min(qty, limit + position)
                if qty > 0:
                    for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                        if bid_price < ema:
                            break
                        vol = od.buy_orders[bid_price]
                        can = min(vol, qty - sell_taken)
                        if can > 0:
                            orders.append(Order("TOMATOES", bid_price, -can))
                            sell_taken += can
                        if sell_taken >= qty:
                            break

        # --- Phase 2: Passive market making ---
        eff_pos = position + buy_taken - sell_taken
        inv_skew = self._inventory_skew(eff_pos, soft, limit)

        # Directional skew from imbalance
        if imbalance > 0.2:
            dir_skew = 1
        elif imbalance < -0.2:
            dir_skew = -1
        else:
            dir_skew = 0

        total_skew = inv_skew + dir_skew

        # Base spread: penny-jump, widened by regime multiplier
        base_half_spread = max(1, int(round((best_ask - best_bid) / 2 * spread_mult)))

        mid_int = int(mid)
        our_bid = mid_int - base_half_spread + total_skew
        our_ask = mid_int + base_half_spread + total_skew

        # Ensure we don't cross
        if our_bid >= our_ask:
            our_bid = mid_int - 1
            our_ask = mid_int + 1

        # Penny-jump: improve on best bid/ask if possible without crossing
        if our_bid < best_bid and best_bid + 1 < our_ask:
            our_bid = best_bid + 1
        if our_ask > best_ask and best_ask - 1 > our_bid:
            our_ask = best_ask - 1

        # Size: reduced in toxic regime, account for taken volume
        remaining_buy = int((limit - eff_pos) * size_mult)
        remaining_sell = int((limit + eff_pos) * size_mult)

        if remaining_buy > 0:
            orders.append(Order("TOMATOES", our_bid, remaining_buy))
        if remaining_sell > 0:
            orders.append(Order("TOMATOES", our_ask, -remaining_sell))

        return orders, td

    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_skew(position: int, soft_limit: int, hard_limit: int) -> int:
        if abs(position) <= soft_limit:
            return 0
        excess = abs(position) - soft_limit
        max_excess = hard_limit - soft_limit
        if max_excess == 0:
            return 0
        magnitude = min(round((excess / max_excess) * 2), 2)
        return -magnitude if position > 0 else magnitude