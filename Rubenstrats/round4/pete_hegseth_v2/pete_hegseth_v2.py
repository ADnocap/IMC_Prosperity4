"""pete_hegseth_v2 — Harry_potter_v8 + Black-Scholes smile FV on VEV_5000..5500.

Background:
  - pete_hegseth_v1 (Mark 67/49 counterparty follower): -570 on portal. Spread
    crossing eats more than the +2 mid-unit signal can deliver. Diagnosis at
    Rubenstrats/pete_hegseth_v1/portal_log/.
  - Friend's submission 491539 (+35,956): >97% of PnL from a Black-Scholes
    smile fitter on the 6 ATM vouchers (VEV_5000..5500). Each voucher priced
    as a call on VELVETFRUIT, fair = BS_call(S, K, smile_iv(K), T) with
    smile_iv = a + b*log(K/S)/sqrt(T) + c*[...]^2. b/c locked from R3
    calibration (curvature stable across days), a refit online via EMA.

v2 keeps Harry_potter_v8 wholesale and replaces the FV source for the 6 core
vouchers with smile_fair + slow EMA of residuals. Everything else — z-score
target sizing, OBI-tilted passive layers, |z|>=MR_TAKE_Z take logic, position-
gated stop-loss, HYDROGEL MR, VELVETFRUIT MR, VEV_4000/4500 OBI MM — is
unchanged.

Why smile FV beats v8's univariate EMA on vouchers:
  - When VELVETFRUIT moves +1, voucher fair moves +Δ (call delta) immediately.
    v8's per-voucher EMA (alpha=0.0005) lags catastrophically; z-score spikes
    the wrong way and v8 fades the legitimate underlying move.
  - When ONE voucher drifts away from the chain (true smile signal), smile_fair
    stays anchored by the other 5 strikes; dev grows; z fires; we trade.
    v8 misses this entirely because its FV is just per-voucher EMA.

Per voucher:
    fair      = BS_call(S, K, smile_iv(K), T_years)
    dev       = mid - fair
    mean_dev  = EMA(dev)              (slow drift in smile residual)
    sigma_dev = sqrt(EMA(residual^2)) (z-score scale)
    fv_used   = fair + mean_dev
    z         = (mid - fv_used) / sigma_dev
    target    = clamp(-MR_K * z, ±MR_MAX_FRAC) * limit   # v8 plumbing

Activity gate: vouchers with sigma_dev < SMILE_MIN_SIGMA (pinned/dead) get
force-flattened. VEV_6000/VEV_6500 stay disabled (mid pinned at 0.5).

All Harry_potter_v8 params unchanged. Only the FV source on the 6 core
vouchers is replaced. Tunable knobs at the top of the class.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math


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

LIMITS: Dict[str, int] = {
    HYDROGEL: 200, VELVETFRUIT: 200,
    VEV_4000: 300, VEV_4500: 300, VEV_5000: 300, VEV_5100: 300,
    VEV_5200: 300, VEV_5300: 300, VEV_5400: 300, VEV_5500: 300,
    VEV_6000: 300, VEV_6500: 300,
}

STRIKES: Dict[str, int] = {
    VEV_4000: 4000, VEV_4500: 4500,
    VEV_5000: 5000, VEV_5100: 5100, VEV_5200: 5200,
    VEV_5300: 5300, VEV_5400: 5400, VEV_5500: 5500,
    VEV_6000: 6000, VEV_6500: 6500,
}

FALLBACK_FV: Dict[str, float] = {
    HYDROGEL: 9990.0, VELVETFRUIT: 5250.0,
    VEV_5000: 255.0, VEV_5100: 167.0, VEV_5200: 95.0,
    VEV_5300: 47.0, VEV_5400: 16.0, VEV_5500: 7.0,
}
FALLBACK_SIGMA_MID: Dict[str, float] = {
    HYDROGEL: 30.0, VELVETFRUIT: 15.0,
    VEV_5000: 14.0, VEV_5100: 13.0, VEV_5200: 10.0,
    VEV_5300: 6.0, VEV_5400: 3.4, VEV_5500: 1.7,
}

LAYER_CONFIG: Dict[str, List[Tuple[int, int]]] = {
    HYDROGEL:    [(1, 15)],
    VELVETFRUIT: [(1, 30), (2, 30)],
    VEV_5000:    [(1, 30), (2, 30)],
    VEV_5100:    [(1, 30), (2, 30)],
    VEV_5200:    [(1, 30), (2, 30)],
    VEV_5300:    [(1, 30), (2, 30)],
    VEV_5400:    [(1, 30), (2, 30)],
    VEV_5500:    [(1, 30), (2, 30)],
}

EMA_MR_ASSETS = (HYDROGEL, VELVETFRUIT)
SMILE_VOUCHERS = (VEV_5000, VEV_5100, VEV_5200, VEV_5300, VEV_5400, VEV_5500)
VEV_MM_ASSETS = (VEV_4000, VEV_4500)


class Trader:
    # ===== Harry_potter_v8 MR params (verbatim) =====
    EMA_ALPHA = 0.0005
    VAR_ALPHA = 0.01
    MR_K = 0.55
    MR_MAX_FRAC = 0.85
    MR_MIN_N = 50
    MR_MM_LEVEL_SIZE = 30
    MR_TAKE_Z = 1.2
    MR_TAKE_MAX = 40
    MR_TIGHT_SPREAD_MIN = 2

    STOP_LOSS_THRESHOLD = -2500
    STOP_DURATION_TICKS = 300
    STOP_POS_GATE = 0.80
    STOP_PAUSE_TICKS = 500

    MR_OBI_FACTOR = 1.0
    MR_OBI_MULT_MIN = 0.3
    MR_OBI_MULT_MAX = 1.8

    # ===== v8 OBI MM params (VEV_4000/4500) =====
    VEV_BASE_SIZE = 15
    VEV_TIGHT_SPREAD_MIN = 2
    VEV_SOFT_POS_FRAC = 0.6
    OBI_SKEW_1 = 0.1
    OBI_SKEW_2 = 0.4
    OBI_SKEW_3 = 0.7
    VEV_SIZES_MILD = (22, 8)
    VEV_SIZES_STRONG = (30, 2)
    VEV_SIZES_EXTREME = (40, 3)

    # ===== NEW: Black-Scholes smile (friend's R3 calibration) =====
    SMILE_A_INIT = 0.580261
    SMILE_B = 0.033704
    SMILE_C = 0.089775
    SMILE_A_ALPHA = 0.0052          # online refit rate of `a`
    SMILE_A_MIN = 0.05
    SMILE_A_MAX = 3.0
    SMILE_IV_FLOOR = 0.05

    SESSION_TICKS = 30_000          # 3 trading days * 10K ticks/day
    TICKS_PER_YEAR = 365 * 10_000
    T_YEARS_FLOOR = 1e-4

    # Voucher residual EMA — dev = mid - smile_fair. Slow alpha so a single
    # mispriced strike doesn't get absorbed into the residual (and lose its
    # signal). Friend uses ~0.02 (window 100); match that.
    SMILE_DEV_MEAN_ALPHA = 0.02
    SMILE_DEV_VAR_ALPHA = 0.02
    # Conservative starting variance so initial z-scores stay small until
    # the variance EMA has had time to converge to the true noise scale.
    SMILE_DEV_VAR_INIT = 4.0

    # Activity gate. Below this sigma the voucher is pinned (e.g., VEV_5500
    # often parks at mid=7) and the z-score divides by ~0 -> meaningless.
    # Force-flatten any existing position rather than overtrade noise.
    SMILE_MIN_SIGMA = 0.4

    # Smile-mode-only take threshold. v8's MR_TAKE_Z=1.2 is too conservative
    # for smile mode where sigma_dev is typically 1-2 (so dev >= 1.2-2.4 is
    # required to fire). Friend's portal-validated threshold THR_OPEN=0.536
    # in absolute price units corresponds to z~0.3-0.5 here. We sit between.
    SMILE_TAKE_Z = 0.6
    # Min absolute deviation (in price units) before we'll cross the spread.
    # Belt-and-braces: a small dev paired with a small sigma could otherwise
    # produce a large z that triggers a take whose spread cost > captured edge.
    SMILE_TAKE_MIN_ABS_DEV = 0.4

    _N = NormalDist()

    # ----------------------------------------------------------------------
    def run(self, state: TradingState
             ) -> Tuple[Dict[str, List[Order]], int, str]:
        td: dict = self._parse_td(state.traderData)
        ts = state.timestamp

        smile_ctx = self._build_smile_ctx(state, td)

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od: OrderDepth = state.order_depths[product]
            pos = state.position.get(product, 0)
            self._accumulate_fills(td, product, state)

            if product in SMILE_VOUCHERS:
                ctx = smile_ctx.get(product)
                if ctx is None:
                    result[product] = []
                    continue
                if ctx["sigma_dev"] < self.SMILE_MIN_SIGMA:
                    # Pinned/dead voucher — flatten and stand down.
                    result[product] = self._flatten(product, od, pos)
                    continue
                fv = ctx["fair"] + ctx["mean_dev"]
                result[product] = self._trade_mr(
                    product, od, pos, td, ts,
                    fair_override=fv, sigma_override=ctx["sigma_dev"])
            elif product in EMA_MR_ASSETS:
                result[product] = self._trade_mr(product, od, pos, td, ts)
            elif product in VEV_MM_ASSETS:
                result[product] = self._trade_mm(product, od, pos)
            else:
                result[product] = []  # VEV_6000/6500 are dead
        return result, 0, json.dumps(td)

    # ===== Smile machinery =================================================
    def _bs_call(self, S: float, K: float, sigma: float, T: float) -> float:
        if T <= 0 or sigma <= 0 or S <= 0:
            return max(S - K, 0.0)
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        return S * self._N.cdf(d1) - K * self._N.cdf(d2)

    def _implied_vol(self, price: float, S: float, K: float, T: float
                      ) -> Optional[float]:
        if T <= 0 or S <= 0:
            return None
        intrinsic = max(S - K, 0.0)
        if price < intrinsic - 1e-6 or price > S + 1e-6:
            return None
        lo, hi = 1e-3, 5.0
        plo = self._bs_call(S, K, lo, T) - price
        phi = self._bs_call(S, K, hi, T) - price
        if plo * phi > 0:
            return None
        for _ in range(40):
            m = 0.5 * (lo + hi)
            pm = self._bs_call(S, K, m, T) - price
            if abs(pm) < 1e-4:
                return m
            if plo * pm < 0:
                hi, phi = m, pm
            else:
                lo, plo = m, pm
        return 0.5 * (lo + hi)

    def _T_years(self, ts: int) -> float:
        ticks_remaining = max(1000, self.SESSION_TICKS - ts // 100)
        return max(self.T_YEARS_FLOOR, ticks_remaining / self.TICKS_PER_YEAR)

    def _smile_iv(self, K: int, S: float, T_years: float, smile_a: float
                   ) -> float:
        if S <= 0 or T_years <= 0:
            return smile_a
        m = math.log(K / S) / math.sqrt(T_years)
        return smile_a + self.SMILE_B * m + self.SMILE_C * m * m

    def _smile_fair(self, K: int, S: float, T_years: float, smile_a: float
                     ) -> float:
        iv = max(self.SMILE_IV_FLOOR, self._smile_iv(K, S, T_years, smile_a))
        return self._bs_call(S, K, iv, T_years)

    def _build_smile_ctx(self, state: TradingState, td: dict
                          ) -> Dict[str, dict]:
        """Refit smile_a from observed IVs across the chain, then compute
        per-voucher dev = mid - smile_fair plus EMA mean and variance.
        Returns dict[symbol] -> {fair, mean_dev, sigma_dev, n}.
        """
        velvet_od = state.order_depths.get(VELVETFRUIT)
        S = self._mid(velvet_od) if velvet_od else None
        if S is None or S <= 0:
            S = FALLBACK_FV[VELVETFRUIT]
        T_years = self._T_years(state.timestamp)

        observed_ivs: Dict[int, float] = {}
        voucher_mids: Dict[str, float] = {}
        for sym in SMILE_VOUCHERS:
            od = state.order_depths.get(sym)
            if not od:
                continue
            m = self._mid(od)
            if m is None or m <= 0:
                continue
            voucher_mids[sym] = m
            iv = self._implied_vol(m, S, STRIKES[sym], T_years)
            if iv is not None and 0.05 < iv < 4.5:
                observed_ivs[STRIKES[sym]] = iv

        prev_a = td.get("smile_a")
        if prev_a is None and observed_ivs:
            # Cold-start: solve smile_iv(K) = a + b*m + c*m^2 for a in one shot
            # by averaging (iv_obs - b*m - c*m^2) across the chain. Avoids
            # ~200 ticks of bad-FV trading while a slow EMA crawls from
            # SMILE_A_INIT to the day's true IV level.
            curveless = []
            for K, iv_obs in observed_ivs.items():
                m = math.log(K / S) / math.sqrt(T_years) if S > 0 and T_years > 0 else 0.0
                curve = self.SMILE_B * m + self.SMILE_C * m * m
                curveless.append(iv_obs - curve)
            smile_a = sum(curveless) / len(curveless)
            smile_a = max(self.SMILE_A_MIN, min(self.SMILE_A_MAX, smile_a))
            td["smile_a"] = smile_a
        else:
            prev_a = prev_a if prev_a is not None else self.SMILE_A_INIT
            if observed_ivs:
                residuals = []
                for K, iv_obs in observed_ivs.items():
                    iv_pred = self._smile_iv(K, S, T_years, prev_a)
                    residuals.append(iv_obs - iv_pred)
                avg_res = sum(residuals) / len(residuals)
                new_a = max(self.SMILE_A_MIN,
                              min(self.SMILE_A_MAX,
                                  prev_a + self.SMILE_A_ALPHA * avg_res))
                td["smile_a"] = new_a
                smile_a = new_a
            else:
                smile_a = prev_a

        ctx: Dict[str, dict] = {}
        for sym in SMILE_VOUCHERS:
            m = voucher_mids.get(sym)
            if m is None:
                continue
            fair = self._smile_fair(STRIKES[sym], S, T_years, smile_a)
            dev = m - fair

            mean_key = f"smile_mean_{sym}"
            var_key = f"smile_var_{sym}"
            n_key = f"smile_n_{sym}"
            prev_mean = td.get(mean_key, 0.0)
            prev_var = td.get(var_key, self.SMILE_DEV_VAR_INIT)
            n = td.get(n_key, 0)

            residual = dev - prev_mean
            new_mean = prev_mean + self.SMILE_DEV_MEAN_ALPHA * residual
            new_var = prev_var + self.SMILE_DEV_VAR_ALPHA * (
                residual * residual - prev_var)
            new_var = max(0.01, new_var)

            td[mean_key] = new_mean
            td[var_key] = new_var
            td[n_key] = n + 1

            ctx[sym] = {
                "fair": fair, "mean_dev": new_mean,
                "sigma_dev": math.sqrt(new_var), "n": n + 1,
            }
        return ctx

    # ===== Fill / MTM tracking (v8 verbatim) ==============================
    def _accumulate_fills(self, td: dict, product: str,
                           state: TradingState) -> None:
        key_cash = f"cash_{product}"
        key_last_ts = f"ot_ts_{product}"
        cash = td.get(key_cash, 0.0)
        last_ts = td.get(key_last_ts, -1)
        trades = (state.own_trades or {}).get(product, []) or []
        for t in trades:
            if t.timestamp <= last_ts:
                continue
            qty = abs(int(t.quantity))
            if t.buyer == "SUBMISSION":
                cash -= t.price * qty
            elif t.seller == "SUBMISSION":
                cash += t.price * qty
            if t.timestamp > last_ts:
                last_ts = t.timestamp
        td[key_cash] = cash
        td[key_last_ts] = last_ts

    def _session_pnl(self, td: dict, product: str, mid: float,
                       pos: int) -> float:
        return td.get(f"cash_{product}", 0.0) + pos * mid

    # ===== MR core (v8's, with optional fair_override) =====================
    def _trade_mr(self, product: str, od: OrderDepth, pos: int, td: dict,
                   ts: int,
                   fair_override: Optional[float] = None,
                   sigma_override: Optional[float] = None) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        spread = best_ask - best_bid
        # In smile mode, allow takes on 1-tick spreads (passive layers will
        # be skipped further down). In non-smile mode preserve v8's behavior.
        min_spread = 1 if fair_override is not None else self.MR_TIGHT_SPREAD_MIN
        if spread < min_spread:
            return []
        passive_ok = spread >= self.MR_TIGHT_SPREAD_MIN
        mid = (best_bid + best_ask) / 2.0

        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        tot = b1 + a1
        obi = 0.0 if tot == 0 else (b1 - a1) / tot

        # FV source: smile (if provided) or v8's per-asset slow EMA.
        if fair_override is not None and sigma_override is not None:
            fv = fair_override
            sigma = max(0.5, sigma_override)
            n_ok = True   # smile FV is reasonable from tick 1
        else:
            fv, sigma, n = self._update_ema(td, product, mid)
            n_ok = n >= self.MR_MIN_N

        # Stop-loss tracking + pause (v8 verbatim) - works for either FV.
        limit = LIMITS[product]
        pnl = self._session_pnl(td, product, mid, pos)
        below_key = f"below_ticks_{product}"
        below = td.get(below_key, 0)
        below = below + 1 if pnl < self.STOP_LOSS_THRESHOLD else 0
        td[below_key] = below
        pause_until = td.get(f"pause_until_{product}", -1)
        pos_gate_met = abs(pos) >= int(self.STOP_POS_GATE * limit)
        if (below >= self.STOP_DURATION_TICKS and pos_gate_met
                and pause_until < ts):
            td[f"pause_until_{product}"] = ts + self.STOP_PAUSE_TICKS
        if pause_until >= ts:
            return self._unwind_passive(product, pos, best_bid, best_ask)

        if n_ok and sigma > 0:
            z = (mid - fv) / sigma
            target_frac = max(-self.MR_MAX_FRAC,
                                min(self.MR_MAX_FRAC, -self.MR_K * z))
            target = int(target_frac * limit)
        else:
            target = 0
            z = 0.0

        buy_room = limit - pos
        sell_room = limit + pos
        buy_ord = sell_ord = 0
        orders: List[Order] = []
        diff = target - pos

        # (a) Aggressive cross-spread take when |z| is large enough.
        # Smile mode uses a lower z gate (purer signal) plus a price-floor
        # so a tiny dev paired with a tiny sigma can't trigger a take whose
        # spread cost exceeds the captured edge.
        if fair_override is not None:
            take_ok = (abs(z) >= self.SMILE_TAKE_Z
                        and abs(mid - fv) >= self.SMILE_TAKE_MIN_ABS_DEV)
        else:
            take_ok = abs(z) >= self.MR_TAKE_Z

        if take_ok:
            if diff > 0:
                cap = min(diff, self.MR_TAKE_MAX, buy_room)
                for ap in asks:
                    if cap <= 0:
                        break
                    vol = -od.sell_orders[ap]
                    qty = min(vol, cap)
                    if qty <= 0:
                        continue
                    orders.append(Order(product, ap, qty))
                    buy_ord += qty
                    cap -= qty
            elif diff < 0:
                cap = min(-diff, self.MR_TAKE_MAX, sell_room)
                for bp in bids:
                    if cap <= 0:
                        break
                    vol = od.buy_orders[bp]
                    qty = min(vol, cap)
                    if qty <= 0:
                        continue
                    orders.append(Order(product, bp, -qty))
                    sell_ord += qty
                    cap -= qty

        # (b) Passive inside-the-spread MM layers, sized by target direction.
        # Skip on 1-tick spreads (only reachable in smile mode); takes already
        # handled the inventory move there.
        if not passive_ok:
            return orders
        diff_after = target - (pos + buy_ord - sell_ord)
        layers = LAYER_CONFIG.get(product, [(1, self.MR_MM_LEVEL_SIZE),
                                              (2, self.MR_MM_LEVEL_SIZE)])
        rem_buy = max(0, buy_room - buy_ord)
        rem_sell = max(0, sell_room - sell_ord)
        for offset, big_sz in layers:
            our_bid = best_bid + offset
            our_ask = best_ask - offset
            if our_bid >= our_ask:
                break
            small_sz = max(5, big_sz // 3)
            if diff_after > 0:
                mult = max(self.MR_OBI_MULT_MIN,
                            min(self.MR_OBI_MULT_MAX,
                                1.0 + self.MR_OBI_FACTOR * obi))
                b_each, a_each = int(big_sz * mult), small_sz
            elif diff_after < 0:
                mult = max(self.MR_OBI_MULT_MIN,
                            min(self.MR_OBI_MULT_MAX,
                                1.0 + self.MR_OBI_FACTOR * (-obi)))
                a_each, b_each = int(big_sz * mult), small_sz
            else:
                mult_b = max(self.MR_OBI_MULT_MIN,
                              min(self.MR_OBI_MULT_MAX,
                                  1.0 + self.MR_OBI_FACTOR * obi))
                mult_a = max(self.MR_OBI_MULT_MIN,
                              min(self.MR_OBI_MULT_MAX,
                                  1.0 + self.MR_OBI_FACTOR * (-obi)))
                b_each = int(small_sz * mult_b)
                a_each = int(small_sz * mult_a)
            bqty = min(b_each, rem_buy)
            aqty = min(a_each, rem_sell)
            if bqty > 0:
                orders.append(Order(product, our_bid, bqty))
                rem_buy -= bqty
            if aqty > 0:
                orders.append(Order(product, our_ask, -aqty))
                rem_sell -= aqty
        return orders

    def _unwind_passive(self, product: str, pos: int,
                          best_bid: int, best_ask: int) -> List[Order]:
        orders: List[Order] = []
        if pos > 0:
            qty = min(pos, 30)
            if best_ask - 1 > best_bid:
                orders.append(Order(product, best_ask - 1, -qty))
        elif pos < 0:
            qty = min(-pos, 30)
            if best_bid + 1 < best_ask:
                orders.append(Order(product, best_bid + 1, qty))
        return orders

    def _flatten(self, product: str, od: OrderDepth, pos: int
                  ) -> List[Order]:
        """Aggressive flatten on activity-gate failure."""
        if pos == 0:
            return []
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        if pos > 0:
            return [Order(product, bids[0], -min(pos, self.MR_TAKE_MAX))]
        return [Order(product, asks[0], min(-pos, self.MR_TAKE_MAX))]

    def _update_ema(self, td: dict, product: str, mid: float
                     ) -> Tuple[float, float, int]:
        ema_key = f"ema_{product}"
        var_key = f"var_{product}"
        n_key = f"n_{product}"
        prev_ema = td.get(ema_key)
        prev_var = td.get(var_key,
                            FALLBACK_SIGMA_MID.get(product, 30.0) ** 2)
        n = td.get(n_key, 0)
        if prev_ema is None:
            prev_ema = FALLBACK_FV.get(product, mid)
        residual = mid - prev_ema
        new_ema = prev_ema + self.EMA_ALPHA * residual
        new_var = prev_var + self.VAR_ALPHA * (
            residual * residual - prev_var)
        new_n = n + 1
        td[ema_key] = new_ema
        td[var_key] = max(1.0, new_var)
        td[n_key] = new_n
        sigma = max(1.0, new_var) ** 0.5
        return new_ema, sigma, new_n

    # ===== OBI MM (v8 verbatim — VEV_4000/4500) ===========================
    def _trade_mm(self, product: str, od: OrderDepth,
                    pos: int) -> List[Order]:
        bids = sorted(od.buy_orders.keys(), reverse=True) if od.buy_orders else []
        asks = sorted(od.sell_orders.keys()) if od.sell_orders else []
        if not bids or not asks:
            return []
        best_bid = bids[0]
        best_ask = asks[0]
        if best_ask - best_bid < self.VEV_TIGHT_SPREAD_MIN:
            return []
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        if our_bid >= our_ask:
            return []
        b1 = od.buy_orders[best_bid]
        a1 = -od.sell_orders[best_ask]
        total = b1 + a1
        obi = 0.0 if total == 0 else (b1 - a1) / total
        buy_size, sell_size = self._obi_sizes(obi)
        limit = LIMITS[product]
        soft_thresh = int(self.VEV_SOFT_POS_FRAC * limit)
        buy_room = limit - pos
        sell_room = limit + pos
        buy_qty = min(buy_size, max(0, buy_room))
        sell_qty = min(sell_size, max(0, sell_room))
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

    def _obi_sizes(self, obi: float) -> Tuple[int, int]:
        a = abs(obi)
        if a < self.OBI_SKEW_1:
            return (self.VEV_BASE_SIZE, self.VEV_BASE_SIZE)
        if a < self.OBI_SKEW_2:
            big, small = self.VEV_SIZES_MILD
        elif a < self.OBI_SKEW_3:
            big, small = self.VEV_SIZES_STRONG
        else:
            big, small = self.VEV_SIZES_EXTREME
        return (big, small) if obi > 0 else (small, big)

    # ===== Helpers ========================================================
    def _mid(self, od: OrderDepth) -> Optional[float]:
        if not od or not od.buy_orders or not od.sell_orders:
            return None
        bids = sorted(od.buy_orders.keys(), reverse=True)
        asks = sorted(od.sell_orders.keys())
        return (bids[0] + asks[0]) / 2.0

    @staticmethod
    def _parse_td(s: Optional[str]) -> dict:
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
