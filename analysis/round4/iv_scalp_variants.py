"""IV-scalp execution variants — compare position-management policies.

Diagnostic 1 confirmed the signal direction is right (+17k per-fire PnL at
h=200). But the actual trader lost -33k on these vouchers. So the signal
is real; the position-management logic is what blew up.

Test 4 variants on the same signal stream, tracking PnL trajectory each:

  V1 (current timo): open + close-back at THR_CLOSE=0 + force-flatten on
      switch_mean < 0.7. SCALP_MAX_PER_TICK = 60.
  V2: drop force-flatten. Keep open + close-back.
  V3: drop close-back too. Open with fixed hold horizon H=200, then close.
  V4: small cap (max position 50), no force-flatten, hold until close-back.

Output per variant per voucher: cumulative PnL trajectory + final.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "prosperity4" / "round4"
OUT_DIR = REPO / "analysis" / "round4"

UNDERLYING = "VELVETFRUIT_EXTRACT"
SCALP_STRIKES = {5000: "VEV_5000", 5100: "VEV_5100", 5200: "VEV_5200",
                 5300: "VEV_5300", 5400: "VEV_5400", 5500: "VEV_5500"}

SMILE_A_INIT = 0.580261
SMILE_B = 0.033704
SMILE_C = 0.089775
SMILE_A_ALPHA = 0.01
THEO_NORM_WINDOW = 100
IV_SCALPING_WINDOW = 100
THR_OPEN = 0.5
THR_CLOSE = 0.0
IV_SCALPING_THR = 0.7
LOW_VEGA_THR_ADJ = 0.5
LOW_VEGA_CUTOFF = 1.0
LIMIT = 300
SESSION_TICKS = 30_000
TICKS_PER_YEAR = 365 * 10_000
T_FLOOR = 1e-4

_N = NormalDist()


def bs_call(S, K, sigma, T):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0.0)
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    d2 = d1 - sd
    return S * _N.cdf(d1) - K * _N.cdf(d2)


def bs_vega(S, K, sigma, T):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sd = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sd
    return S * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) * math.sqrt(T)


def implied_vol(price, S, K, T):
    if T <= 0:
        return None
    intrinsic = max(S - K, 0.0)
    if price < intrinsic - 1e-6 or price > S + 1e-6:
        return None
    lo, hi = 1e-3, 5.0
    plo = bs_call(S, K, lo, T) - price
    phi = bs_call(S, K, hi, T) - price
    if plo * phi > 0:
        return None
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        pm = bs_call(S, K, mid, T) - price
        if abs(pm) < 1e-4:
            return mid
        if plo * pm < 0:
            hi, phi = mid, pm
        else:
            lo, plo = mid, pm
    return 0.5 * (lo + hi)


def smile_iv(K, S, T_years, smile_a):
    if S <= 0 or T_years <= 0:
        return smile_a
    m = math.log(K / S) / math.sqrt(T_years)
    return smile_a + SMILE_B * m + SMILE_C * m * m


def smile_fair(K, S, T_years, smile_a):
    iv = max(0.05, smile_iv(K, S, T_years, smile_a))
    return bs_call(S, K, iv, T_years)


def t_years(ts: int) -> float:
    ticks_remaining = max(1000, SESSION_TICKS - ts // 100)
    return max(T_FLOOR, ticks_remaining / TICKS_PER_YEAR)


def load_day(day: int):
    df = pd.read_csv(DATA_DIR / f"prices_round_4_day_{day}.csv", sep=";")
    df = df[["timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]]
    pv_mid = df.pivot_table(index="timestamp", columns="product",
                            values="mid_price", aggfunc="first").sort_index()
    pv_bid = df.pivot_table(index="timestamp", columns="product",
                            values="bid_price_1", aggfunc="first").sort_index()
    pv_ask = df.pivot_table(index="timestamp", columns="product",
                            values="ask_price_1", aggfunc="first").sort_index()
    return pv_mid, pv_bid, pv_ask


def simulate_voucher(K, sym, mids, bids, asks, S_arr, ts_arr,
                     variant: str, scalp_max_per_tick: int = 60,
                     pos_cap: int = LIMIT, hold_horizon: int | None = None):
    """Run one voucher through the IV-scalp logic and return per-tick PnL.

    PnL convention: realized cash from fills + unrealized mark-to-mid on
    current position. Cash starts at 0.
    """
    smile_a = SMILE_A_INIT
    mean_dev = None
    switch_mean = 0.0
    pos = 0
    cash = 0.0
    a_m = 2.0 / (THEO_NORM_WINDOW + 1)
    a_s = 2.0 / (IV_SCALPING_WINDOW + 1)
    pnl_traj = []
    open_age = 0  # for hold_horizon variant
    n_fires = 0
    n_force_flats = 0
    n_close_backs = 0
    n_at_limit = 0

    for i, ts in enumerate(ts_arr):
        S = float(S_arr[i])
        T = t_years(ts)
        mid = float(mids[i])
        best_bid = float(bids[i])
        best_ask = float(asks[i])
        if math.isnan(mid) or math.isnan(best_bid) or math.isnan(best_ask):
            pnl_traj.append(cash + pos * mid if not math.isnan(mid) else
                            (pnl_traj[-1] if pnl_traj else 0))
            continue

        # Refit smile_a from this voucher's IV (single-strike refit; in
        # the trader it's all 6 strikes pooled. For diagnosis we proxy with
        # the constant init since the cross-strike refit is global anyway.)
        # Simpler: just use the global trajectory of smile_a using this strike's
        # observed IV. (Conservatively this is fine because switch_mean and
        # mean_dev re-anchor the actual trade signal.)
        iv_obs = implied_vol(mid, S, K, T)
        if iv_obs is not None and 0.05 < iv_obs < 4.5:
            res = iv_obs - smile_iv(K, S, T, smile_a)
            smile_a = max(0.05, min(3.0, smile_a + SMILE_A_ALPHA * res))

        fair = smile_fair(K, S, T, smile_a)
        iv_use = max(0.05, smile_iv(K, S, T, smile_a))
        vega = bs_vega(S, K, iv_use, T)
        dev = mid - fair
        if mean_dev is None:
            mean_dev = dev
        else:
            mean_dev = a_m * dev + (1 - a_m) * mean_dev
        switch_mean = a_s * abs(dev - mean_dev) + (1 - a_s) * switch_mean

        sell_room = pos_cap + pos
        buy_room = pos_cap - pos

        # ----- Variant logic -----
        action = None  # ('sell', qty) or ('buy', qty)

        if variant == "V1":  # current timo
            if switch_mean < IV_SCALPING_THR:
                if pos > 0:
                    action = ("sell", min(pos, sell_room))
                    n_force_flats += 1
                elif pos < 0:
                    action = ("buy", min(-pos, buy_room))
                    n_force_flats += 1
            else:
                thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
                sell_dev = (best_bid - fair) - mean_dev
                buy_dev = (best_ask - fair) - mean_dev
                if sell_dev >= thr and sell_room > 0:
                    qty = min(scalp_max_per_tick, sell_room)
                    action = ("sell", qty); n_fires += 1
                elif buy_dev <= -thr and buy_room > 0:
                    qty = min(scalp_max_per_tick, buy_room)
                    action = ("buy", qty); n_fires += 1
                else:
                    if pos > 0 and sell_dev >= THR_CLOSE:
                        action = ("sell", min(pos, sell_room))
                        n_close_backs += 1
                    elif pos < 0 and buy_dev <= -THR_CLOSE:
                        action = ("buy", min(-pos, buy_room))
                        n_close_backs += 1

        elif variant == "V2":  # no force-flatten
            if switch_mean >= IV_SCALPING_THR:
                thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
                sell_dev = (best_bid - fair) - mean_dev
                buy_dev = (best_ask - fair) - mean_dev
                if sell_dev >= thr and sell_room > 0:
                    qty = min(scalp_max_per_tick, sell_room)
                    action = ("sell", qty); n_fires += 1
                elif buy_dev <= -thr and buy_room > 0:
                    qty = min(scalp_max_per_tick, buy_room)
                    action = ("buy", qty); n_fires += 1
                else:
                    if pos > 0 and sell_dev >= THR_CLOSE:
                        action = ("sell", min(pos, sell_room))
                        n_close_backs += 1
                    elif pos < 0 and buy_dev <= -THR_CLOSE:
                        action = ("buy", min(-pos, buy_room))
                        n_close_backs += 1

        elif variant == "V3":  # open + fixed hold horizon, no close-back
            if switch_mean >= IV_SCALPING_THR:
                thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
                sell_dev = (best_bid - fair) - mean_dev
                buy_dev = (best_ask - fair) - mean_dev
                if pos != 0:
                    open_age += 1
                    if hold_horizon and open_age >= hold_horizon:
                        if pos > 0:
                            action = ("sell", min(pos, sell_room))
                        else:
                            action = ("buy", min(-pos, buy_room))
                        open_age = 0
                if action is None:
                    if sell_dev >= thr and sell_room > 0:
                        qty = min(scalp_max_per_tick, sell_room)
                        action = ("sell", qty); n_fires += 1
                        if pos == 0:
                            open_age = 0
                    elif buy_dev <= -thr and buy_room > 0:
                        qty = min(scalp_max_per_tick, buy_room)
                        action = ("buy", qty); n_fires += 1
                        if pos == 0:
                            open_age = 0

        elif variant == "V4":  # small cap, no force-flatten
            if switch_mean >= IV_SCALPING_THR:
                thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
                sell_dev = (best_bid - fair) - mean_dev
                buy_dev = (best_ask - fair) - mean_dev
                if sell_dev >= thr and sell_room > 0:
                    qty = min(scalp_max_per_tick, sell_room)
                    action = ("sell", qty); n_fires += 1
                elif buy_dev <= -thr and buy_room > 0:
                    qty = min(scalp_max_per_tick, buy_room)
                    action = ("buy", qty); n_fires += 1
                else:
                    if pos > 0 and sell_dev >= THR_CLOSE:
                        action = ("sell", min(pos, sell_room))
                        n_close_backs += 1
                    elif pos < 0 and buy_dev <= -THR_CLOSE:
                        action = ("buy", min(-pos, buy_room))
                        n_close_backs += 1

        # Apply action
        if action is not None:
            side, qty = action
            if qty > 0:
                if side == "sell":
                    cash += best_bid * qty
                    pos -= qty
                else:
                    cash -= best_ask * qty
                    pos += qty

        if abs(pos) >= pos_cap:
            n_at_limit += 1

        pnl_traj.append(cash + pos * mid)
    return pnl_traj, {"n_fires": n_fires, "n_force_flats": n_force_flats,
                      "n_close_backs": n_close_backs, "n_at_limit": n_at_limit,
                      "final_pos": pos, "final_cash": cash,
                      "final_pnl": cash + pos * mid}


def main():
    results = {}
    for day in (1, 2, 3):
        pv_mid, pv_bid, pv_ask = load_day(day)
        needed = [UNDERLYING] + list(SCALP_STRIKES.values())
        panel = pv_mid.dropna(subset=needed)
        ts_arr = panel.index.to_list()
        S_arr = panel[UNDERLYING].to_numpy()
        for K, sym in SCALP_STRIKES.items():
            mids = panel[sym].to_numpy()
            bids = pv_bid.loc[panel.index, sym].to_numpy()
            asks = pv_ask.loc[panel.index, sym].to_numpy()
            for variant, kwargs in [
                ("V1", {}),
                ("V2", {}),
                ("V3", {"hold_horizon": 200}),
                ("V4", {"pos_cap": 50}),
            ]:
                key = f"day{day}__{sym}__{variant}"
                _traj, stats = simulate_voucher(
                    K, sym, mids, bids, asks, S_arr, ts_arr,
                    variant=variant, **kwargs)
                results[key] = stats

    # Aggregate per (sym, variant) totals across days
    agg = {}
    for sym in SCALP_STRIKES.values():
        for variant in ("V1", "V2", "V3", "V4"):
            tot = sum(results[f"day{d}__{sym}__{variant}"]["final_pnl"]
                      for d in (1, 2, 3))
            tot_fires = sum(results[f"day{d}__{sym}__{variant}"]["n_fires"]
                            for d in (1, 2, 3))
            tot_flats = sum(results[f"day{d}__{sym}__{variant}"]["n_force_flats"]
                            for d in (1, 2, 3))
            tot_closes = sum(results[f"day{d}__{sym}__{variant}"]["n_close_backs"]
                             for d in (1, 2, 3))
            agg[f"{sym}__{variant}"] = {
                "total_pnl": tot, "fires": tot_fires,
                "force_flats": tot_flats, "close_backs": tot_closes,
            }

    out_json = OUT_DIR / "iv_scalp_variants.json"
    out_json.write_text(json.dumps({"per_day_per_sym": results,
                                    "totals_per_sym_variant": agg}, indent=2))
    print(json.dumps(agg, indent=2))
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
