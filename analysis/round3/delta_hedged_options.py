"""
Delta-hedged short-vol options analysis for IMC Prosperity 4 R3.

Quantifies whether delta hedging unlocks larger position sizing on R3 vouchers
or whether the bid-ask spread on VELVETFRUIT_EXTRACT eats the hedge value
(Chris's P3 critique).

Outputs:
    analysis/round3/delta_hedged_options.json  (headline numbers)

The companion .md report is hand-written from these numbers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Constants & paths
# ----------------------------------------------------------------------------
DATA_DIR = Path("C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/data/prosperity4/round3")
OUT_DIR = Path("C:/Users/alexa/OneDrive/Documents/IMC_trading_hack/analysis/round3")
SMILE_PATH = OUT_DIR / "smile_coefs_day2.json"

UNDERLYING = "VELVETFRUIT_EXTRACT"
# We focus on ATM/OTM strikes per task spec — these are the rich-IV strikes.
SHORT_STRIKES = [5200, 5300, 5400, 5500]
ALL_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]  # skip dead 6000/6500

VOUCHER_LIMIT = 300
SPOT_LIMIT = 200
TICKS_PER_DAY = 10_000
DAYS = [0, 1, 2]

# Smile from prior analysis (analysis/round3/smile_coefs_day2.json)
# iv = a + b*m + c*m^2  where  m = log(K/S)/sqrt(T)
with open(SMILE_PATH) as f:
    SMILE = json.load(f)

SMILE_A = SMILE["smile_a"]
SMILE_B = SMILE["smile_b"]
SMILE_C = SMILE["smile_c"]
RESID_STD_IV = SMILE["resid_std"]  # ~0.0102 — std of IV residual around smile

# T convention: prior analysis used T = days_remaining/365, with 6 days at start of day-0.
# We replicate that across the 3 historical days. day d has 6-d days remaining (start of day).
DAYS_TOTAL = 6
DAYS_PER_YEAR = 365.0

N = NormalDist().cdf
PDF = NormalDist().pdf


# ----------------------------------------------------------------------------
# Black-Scholes
# ----------------------------------------------------------------------------
def bs_call(S: float, K: float, T: float, sigma: float) -> tuple[float, float]:
    """Vanilla BS call. Returns (price, delta). r=0."""
    if T <= 0 or sigma <= 0 or S <= 0:
        intrinsic = max(0.0, S - K)
        delta = 1.0 if S > K else 0.0
        return intrinsic, delta
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    price = S * N(d1) - K * N(d2)
    delta = N(d1)
    return price, delta


def bs_vega(S: float, K: float, T: float, sigma: float) -> float:
    """BS vega — dC/dsigma. Per 1.0-unit vol move (so divide by 100 for 1%)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    return S * PDF(d1) * sqrtT


def smile_iv(S: float, K: float, T: float) -> float:
    """Fitted smile IV. Smile uses moneyness m = log(K/S) (no sqrt(T) divisor),
    matching r3_smile_clean.py:94."""
    if S <= 0:
        return SMILE_A
    m = math.log(K / S)
    iv = SMILE_A + SMILE_B * m + SMILE_C * m * m
    return max(0.01, iv)


# T convention: smile was fit at fixed T = 6/365 (r3_smile_clean.py:78).
# Use the same constant T for back-test consistency. This is the natural choice:
# the historical CSVs are 3 days that all share approximately the same TTE
# from the perspective of the option-pricing surface (calibrated as a snapshot).
T_CONST = 6.0 / DAYS_PER_YEAR


def t_for_day(day: int, ts: int) -> float:
    """Years to expiry. Held constant per the smile-fit convention."""
    return T_CONST


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"prices_round_3_day_{day}.csv", sep=";")
    df["day"] = day
    return df


def pivot_quotes(df: pd.DataFrame, products: list[str]) -> dict[str, pd.DataFrame]:
    """Return per-product DataFrame indexed by timestamp, with bid/ask/mid columns."""
    out = {}
    for p in products:
        sub = df[df["product"] == p].sort_values("timestamp").reset_index(drop=True)
        sub = sub[["timestamp", "bid_price_1", "ask_price_1", "mid_price"]].copy()
        sub.columns = ["ts", "bid", "ask", "mid"]
        out[p] = sub
    return out


# ----------------------------------------------------------------------------
# Portfolio simulation
# ----------------------------------------------------------------------------
@dataclass
class PortfolioResult:
    net_pnl: float
    option_pnl: float       # mark-to-market of option short positions
    hedge_pnl: float        # mark-to-market of spot delta hedge
    hedge_spread_cost: float  # spread paid on hedge rebalances
    option_spread_cost: float  # spread paid on initial voucher shorts
    residual_delta_std: float  # std of net delta over the path
    total_vega: float       # avg signed vega of the book (per 1.0 vol unit)
    n_rebalances: int


def simulate(
    days_data: list[dict],
    rebalance_every: int,
    short_strikes: list[int],
    short_per_strike: int,
    do_hedge: bool,
    signal_threshold_sigma: float = 0.0,
    direction: str = "short",  # "short", "long", or "both"
    fill_at: str = "cross",     # "cross" (take spread) or "mid" (passive MM)
) -> PortfolioResult:
    """
    Walk the historical path. At each rebalance point:
      - For each strike in short_strikes, shift target voucher position to ±short_per_strike
        IF |market_mid - bs_fair| > signal_threshold_sigma * sigma_diff (per-strike).
      - Recompute net delta. If do_hedge, rebalance VELVETFRUIT spot to neutralize.
    Track PnL = MTM(voucher positions) + MTM(spot hedge) - spread_costs.
    """
    # Combine all days into one continuous path.
    spot_mids = []
    spot_bids = []
    spot_asks = []
    voucher_mids = {k: [] for k in short_strikes}
    voucher_bids = {k: [] for k in short_strikes}
    voucher_asks = {k: [] for k in short_strikes}
    Ts = []

    for dd in days_data:
        spot = dd["spot"]
        n = len(spot)
        spot_mids.extend(spot["mid"].tolist())
        spot_bids.extend(spot["bid"].tolist())
        spot_asks.extend(spot["ask"].tolist())
        for k in short_strikes:
            v = dd["vouchers"][k]
            voucher_mids[k].extend(v["mid"].tolist())
            voucher_bids[k].extend(v["bid"].tolist())
            voucher_asks[k].extend(v["ask"].tolist())
        for ts in spot["ts"]:
            Ts.append(t_for_day(dd["day"], int(ts)))

    n_total = len(spot_mids)
    voucher_pos = {k: 0 for k in short_strikes}
    spot_pos = 0
    cash = 0.0
    hedge_spread_cost = 0.0
    option_spread_cost = 0.0
    delta_track = []
    vega_track = []
    n_rebalances = 0

    # Pre-compute sigma_diff per strike from historical (mid - bs_fair) std.
    # This is the natural noise scale for the IV-deviation signal.
    sigma_diffs = {}
    for k in short_strikes:
        diffs = []
        # Sample every 100 ticks to keep it fast.
        for i in range(0, n_total, 100):
            S = spot_mids[i]
            T = Ts[i]
            iv = smile_iv(S, k, T)
            fair, _ = bs_call(S, k, T, iv)
            diffs.append(voucher_mids[k][i] - fair)
        sigma_diffs[k] = float(np.std(diffs)) if diffs else 1.0

    for i in range(n_total):
        S = spot_mids[i]
        T = Ts[i]

        # Should we rebalance this tick?
        is_rebalance = (i % rebalance_every == 0) or (i == n_total - 1)

        if is_rebalance:
            n_rebalances += 1
            # 1) Update voucher positions per signal.
            for k in short_strikes:
                iv = smile_iv(S, k, T)
                fair, _ = bs_call(S, k, T, iv)
                mkt = voucher_mids[k][i]
                signal = mkt - fair  # positive => option is rich, short it
                threshold = signal_threshold_sigma * sigma_diffs[k]

                # Default target: flat (we close out when signal disappears).
                # For signal_threshold == 0: always-on directional short/long.
                target = 0
                if signal_threshold_sigma == 0.0:
                    if direction == "short":
                        target = -short_per_strike
                    elif direction == "long":
                        target = +short_per_strike
                else:
                    if direction in ("short", "both") and signal > threshold:
                        target = -short_per_strike
                    elif direction in ("long", "both") and signal < -threshold:
                        target = +short_per_strike

                # Cap at limit.
                target = max(-VOUCHER_LIMIT, min(VOUCHER_LIMIT, target))

                delta_qty = target - voucher_pos[k]
                if delta_qty != 0:
                    # Selling at bid (negative qty), buying at ask (positive qty).
                    # Or if fill_at=='mid' assume passive MM fills at mid (no spread cost).
                    bid = voucher_bids[k][i]
                    ask = voucher_asks[k][i]
                    if fill_at == "mid":
                        fill_px = mkt
                    elif delta_qty < 0:
                        fill_px = bid
                    else:
                        fill_px = ask
                    if delta_qty < 0:  # selling
                        cash += -delta_qty * fill_px
                    else:  # buying
                        cash -= delta_qty * fill_px
                    if fill_at == "cross":
                        if delta_qty < 0:
                            option_spread_cost += abs(delta_qty) * (mkt - bid)
                        else:
                            option_spread_cost += abs(delta_qty) * (ask - mkt)
                    voucher_pos[k] = target

            # 2) Compute net portfolio delta and rebalance spot if hedging.
            net_delta = 0.0
            net_vega = 0.0
            for k in short_strikes:
                iv = smile_iv(S, k, T)
                _, delta = bs_call(S, k, T, iv)
                net_delta += voucher_pos[k] * delta
                net_vega += voucher_pos[k] * bs_vega(S, k, T, iv)

            if do_hedge:
                target_spot = -int(round(net_delta))
                target_spot = max(-SPOT_LIMIT, min(SPOT_LIMIT, target_spot))
                delta_qty = target_spot - spot_pos
                if delta_qty != 0:
                    bid = spot_bids[i]
                    ask = spot_asks[i]
                    spot_mid = spot_mids[i]
                    if delta_qty > 0:  # buying spot
                        cash -= delta_qty * ask
                        hedge_spread_cost += abs(delta_qty) * (ask - spot_mid)
                    else:
                        cash += -delta_qty * bid
                        hedge_spread_cost += abs(delta_qty) * (spot_mid - bid)
                    spot_pos = target_spot

            # Track residual delta after hedge.
            resid = net_delta + spot_pos
            delta_track.append(resid)
            vega_track.append(net_vega)

    # Mark to market at final tick using mids.
    final_mark = 0.0
    for k in short_strikes:
        final_mark += voucher_pos[k] * voucher_mids[k][-1]
    final_mark += spot_pos * spot_mids[-1]
    net_pnl = cash + final_mark

    # Decompose option vs hedge PnL by re-running just the option leg?
    # Easier: option_pnl = cash_options + final_option_mark; hedge_pnl = the rest.
    # Since all spread costs already deducted from cash, this is approximate.
    option_pnl = net_pnl - 0.0  # not cleanly separable — report as net.

    return PortfolioResult(
        net_pnl=net_pnl,
        option_pnl=net_pnl,  # placeholder — see report
        hedge_pnl=0.0,
        hedge_spread_cost=hedge_spread_cost,
        option_spread_cost=option_spread_cost,
        residual_delta_std=float(np.std(delta_track)) if delta_track else 0.0,
        total_vega=float(np.mean(vega_track)) if vega_track else 0.0,
        n_rebalances=n_rebalances,
    )


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("Loading data...")
    days_data = []
    for d in DAYS:
        df = load_day(d)
        spot_q = pivot_quotes(df, [UNDERLYING])[UNDERLYING]
        voucher_q_full = pivot_quotes(
            df, [f"VEV_{k}" for k in ALL_VEV_STRIKES]
        )
        voucher_q = {k: voucher_q_full[f"VEV_{k}"] for k in ALL_VEV_STRIKES}
        days_data.append({"day": d, "spot": spot_q, "vouchers": voucher_q})
        print(f"  Day {d}: spot {len(spot_q)} ticks, vouchers loaded")

    # Sanity check sizes match
    for d in days_data:
        n_spot = len(d["spot"])
        for k, v in d["vouchers"].items():
            assert len(v) == n_spot, f"Day {d['day']} VEV_{k} size mismatch"

    n_days = len(days_data)
    n_total = sum(len(d["spot"]) for d in days_data)
    print(f"Total ticks: {n_total} ({n_days} days)\n")

    summary = {}

    # ===== TASK 3: Rebalance frequency sweep (signal off, hedge on, full short) =====
    print("=" * 60)
    print("TASK 3: Rebalance frequency sweep (always-on short, with hedge)")
    print("=" * 60)
    print("--- 3a. Full-size short (300 per strike) — total delta exceeds spot cap")
    freq_table = []
    for freq in [1, 10, 50, 100, 500, 1000]:
        res = simulate(
            days_data,
            rebalance_every=freq,
            short_strikes=SHORT_STRIKES,
            short_per_strike=VOUCHER_LIMIT,
            do_hedge=True,
            signal_threshold_sigma=0.0,
            direction="short",
        )
        per_day = res.net_pnl / n_days
        spread_per_day = res.hedge_spread_cost / n_days
        freq_table.append({
            "rebalance_every": freq,
            "net_pnl_per_day": round(per_day),
            "hedge_spread_cost_per_day": round(spread_per_day),
            "opt_spread_cost_per_day": round(res.option_spread_cost / n_days),
            "residual_delta_std": round(res.residual_delta_std, 2),
            "n_rebalances": res.n_rebalances,
        })
        print(
            f"  every {freq:5d} ticks: net={per_day:+8.0f}/day  "
            f"hedge_spread={spread_per_day:7.0f}/day  "
            f"resid_delta_std={res.residual_delta_std:5.2f}  "
            f"n_reb={res.n_rebalances}"
        )
    summary["rebalance_freq_sweep_full"] = freq_table

    # 3b. Smaller book (100 per strike) where hedging is feasible within spot cap
    print("--- 3b. Smaller book (100 per strike) — hedge fits within spot cap")
    freq_table_small = []
    for freq in [1, 10, 50, 100, 500, 1000]:
        res = simulate(
            days_data,
            rebalance_every=freq,
            short_strikes=SHORT_STRIKES,
            short_per_strike=100,
            do_hedge=True,
            signal_threshold_sigma=0.0,
            direction="short",
        )
        per_day = res.net_pnl / n_days
        spread_per_day = res.hedge_spread_cost / n_days
        freq_table_small.append({
            "rebalance_every": freq,
            "net_pnl_per_day": round(per_day),
            "hedge_spread_cost_per_day": round(spread_per_day),
            "residual_delta_std": round(res.residual_delta_std, 2),
            "n_rebalances": res.n_rebalances,
        })
        print(
            f"  every {freq:5d} ticks: net={per_day:+8.0f}/day  "
            f"hedge_spread={spread_per_day:7.0f}/day  "
            f"resid_delta_std={res.residual_delta_std:5.2f}  "
            f"n_reb={res.n_rebalances}"
        )
    summary["rebalance_freq_sweep_small"] = freq_table_small

    # ===== TASK 4: Cross-check unhedged baseline =====
    print()
    print("=" * 60)
    print("TASK 4: Hedged vs unhedged comparison (best rebalance freq)")
    print("=" * 60)
    best_freq = max(
        freq_table_small, key=lambda r: r["net_pnl_per_day"]
    )["rebalance_every"]
    print(f"  Best freq from sweep: every {best_freq} ticks")

    hedge_compare = []
    for size, label in [(VOUCHER_LIMIT, "full_300"), (100, "small_100")]:
        rh = simulate(
            days_data, best_freq, SHORT_STRIKES, size,
            do_hedge=True, signal_threshold_sigma=0.0, direction="short",
        )
        ru = simulate(
            days_data, best_freq, SHORT_STRIKES, size,
            do_hedge=False, signal_threshold_sigma=0.0, direction="short",
        )
        row = {
            "size_per_strike": size,
            "label": label,
            "freq": best_freq,
            "hedged_pnl_per_day": round(rh.net_pnl / n_days),
            "hedged_spread_cost_per_day": round(rh.hedge_spread_cost / n_days),
            "hedged_resid_delta_std": round(rh.residual_delta_std, 2),
            "unhedged_pnl_per_day": round(ru.net_pnl / n_days),
            "unhedged_resid_delta_std": round(ru.residual_delta_std, 2),
            "delta_per_day": round((rh.net_pnl - ru.net_pnl) / n_days),
        }
        hedge_compare.append(row)
        print(f"  Size={size:3d}: hedged={row['hedged_pnl_per_day']:+6d}  "
              f"unhedged={row['unhedged_pnl_per_day']:+6d}  "
              f"delta={row['delta_per_day']:+6d}/day  "
              f"(hedge_resid_std={row['hedged_resid_delta_std']}, "
              f"unhedge_resid_std={row['unhedged_resid_delta_std']})")
    summary["hedge_vs_unhedged"] = hedge_compare
    hedge_table = hedge_compare[0]  # default for headline

    # ===== TASK 5: Per-strike signal threshold sweep =====
    print()
    print("=" * 60)
    print("TASK 5: Signal-threshold sweep (short only, with hedge, freq=100)")
    print("=" * 60)
    signal_table_short = []
    for k in [0.0, 0.5, 1.0, 1.5, 2.0]:
        res = simulate(
            days_data, 100, SHORT_STRIKES, VOUCHER_LIMIT,
            do_hedge=True, signal_threshold_sigma=k, direction="short",
        )
        per_day = res.net_pnl / n_days
        signal_table_short.append({
            "k_sigma": k,
            "net_pnl_per_day": round(per_day),
            "hedge_spread_cost_per_day": round(res.hedge_spread_cost / n_days),
        })
        print(f"  k={k:.1f}: net={per_day:+8.0f}/day  "
              f"hedge_spread={res.hedge_spread_cost / n_days:7.0f}/day")
    summary["signal_sweep_short"] = signal_table_short

    # ===== TASK 6: Long-vol direction =====
    print()
    print("=" * 60)
    print("TASK 6: Long-vol direction (buy when mid < fair)")
    print("=" * 60)
    signal_table_long = []
    for k in [0.0, 0.5, 1.0, 1.5, 2.0]:
        res = simulate(
            days_data, 100, SHORT_STRIKES, VOUCHER_LIMIT,
            do_hedge=True, signal_threshold_sigma=k, direction="long",
        )
        per_day = res.net_pnl / n_days
        signal_table_long.append({
            "k_sigma": k,
            "net_pnl_per_day": round(per_day),
        })
        print(f"  k={k:.1f}: net={per_day:+8.0f}/day")
    summary["signal_sweep_long"] = signal_table_long

    # Symmetry check: average mid - fair across all strikes/ticks
    all_signal = []
    for k_strike in SHORT_STRIKES:
        for d in days_data:
            spot = d["spot"]
            v = d["vouchers"][k_strike]
            for i in range(0, len(spot), 100):
                S = spot["mid"].iloc[i]
                T = t_for_day(d["day"], int(spot["ts"].iloc[i]))
                iv = smile_iv(S, k_strike, T)
                fair, _ = bs_call(S, k_strike, T, iv)
                all_signal.append(v["mid"].iloc[i] - fair)
    arr = np.array(all_signal)
    summary["mispricing_symmetry"] = {
        "mean_mid_minus_fair": round(float(np.mean(arr)), 3),
        "median_mid_minus_fair": round(float(np.median(arr)), 3),
        "std": round(float(np.std(arr)), 3),
        "frac_positive": round(float((arr > 0).mean()), 3),
        "frac_negative": round(float((arr < 0).mean()), 3),
    }
    print(f"  mid-fair: mean={summary['mispricing_symmetry']['mean_mid_minus_fair']:.2f} "
          f"median={summary['mispricing_symmetry']['median_mid_minus_fair']:.2f} "
          f"frac>0={summary['mispricing_symmetry']['frac_positive']:.2%}")

    # ===== TASK 7: Hedge cost analysis =====
    print()
    print("=" * 60)
    print("TASK 7: Hedge spread-cost analysis")
    print("=" * 60)
    # Spot bid-ask
    spot_spreads = []
    for d in days_data:
        spot_spreads.extend((d["spot"]["ask"] - d["spot"]["bid"]).tolist())
    avg_spot_spread = float(np.mean(spot_spreads))
    # Sum total notional voucher position
    book_size = sum(VOUCHER_LIMIT for _ in SHORT_STRIKES)  # 1200 if full short on 4 strikes
    avg_delta_per_unit = 0.0
    avg_S = float(np.mean([m for d in days_data for m in d["spot"]["mid"]]))
    for k in SHORT_STRIKES:
        # Use mid-T (~5 days remaining)
        T_mid = 5.0 / DAYS_PER_YEAR
        iv = smile_iv(avg_S, k, T_mid)
        _, delta = bs_call(avg_S, k, T_mid, iv)
        avg_delta_per_unit += delta * VOUCHER_LIMIT  # delta-equivalent shares
    summary["hedge_cost_analysis"] = {
        "avg_spot_spread": round(avg_spot_spread, 2),
        "voucher_book_size": book_size,
        "avg_total_delta_at_full_short": round(avg_delta_per_unit, 1),
        "spot_limit": SPOT_LIMIT,
        "delta_capped_by_spot_limit": avg_delta_per_unit > SPOT_LIMIT,
    }
    print(f"  Avg spot spread       : {avg_spot_spread:.2f} ticks")
    print(f"  Voucher book size     : {book_size} contracts")
    print(f"  Total delta @ full short: {avg_delta_per_unit:.1f}")
    print(f"  Spot limit            : {SPOT_LIMIT}")

    # ===== TASK 8: Vega exposure =====
    print()
    print("=" * 60)
    print("TASK 8: Residual vega exposure")
    print("=" * 60)
    total_vega_short = 0.0
    avg_S = float(np.mean([m for d in days_data for m in d["spot"]["mid"]]))
    for k in SHORT_STRIKES:
        T_mid = 5.0 / DAYS_PER_YEAR
        iv = smile_iv(avg_S, k, T_mid)
        v = bs_vega(avg_S, k, T_mid, iv)
        total_vega_short += v * VOUCHER_LIMIT
    # 1% (=0.01) vol move impact
    vega_1pct = total_vega_short * 0.01
    summary["vega_exposure"] = {
        "total_vega_per_unit_vol": round(total_vega_short, 1),
        "pnl_impact_per_1pct_vol_move": round(vega_1pct, 1),
        "pnl_impact_per_residual_smile_std": round(total_vega_short * RESID_STD_IV, 1),
        "residual_smile_std_iv": round(RESID_STD_IV, 4),
    }
    print(f"  Total vega @ full short (4 strikes × {VOUCHER_LIMIT}): "
          f"{total_vega_short:.0f} per 1.0 vol unit")
    print(f"  PnL impact per 1% vol move : {vega_1pct:.0f} XIRECs")
    print(f"  PnL impact per residual smile sigma ({RESID_STD_IV:.4f}): "
          f"{total_vega_short * RESID_STD_IV:.0f} XIRECs")

    # ===== Passive-MM fill (mid) sensitivity =====
    print()
    print("=" * 60)
    print("Passive-MM fill (entry at mid, not bid) sensitivity")
    print("=" * 60)
    passive_table = []
    for size in [VOUCHER_LIMIT, 100]:
        rh = simulate(
            days_data, 1000, SHORT_STRIKES, size,
            do_hedge=True, signal_threshold_sigma=0.0, direction="short",
            fill_at="mid",
        )
        ru = simulate(
            days_data, 1000, SHORT_STRIKES, size,
            do_hedge=False, signal_threshold_sigma=0.0, direction="short",
            fill_at="mid",
        )
        passive_table.append({
            "size": size,
            "hedged_pnl_per_day": round(rh.net_pnl / n_days),
            "unhedged_pnl_per_day": round(ru.net_pnl / n_days),
            "hedge_spread_cost_per_day": round(rh.hedge_spread_cost / n_days),
        })
        print(f"  Size={size:3d} (mid-fill): hedged={rh.net_pnl/n_days:+8.0f}/day  "
              f"unhedged={ru.net_pnl/n_days:+8.0f}/day  "
              f"hedge_spread={rh.hedge_spread_cost/n_days:6.0f}/day")
    summary["passive_mid_fill"] = passive_table

    # ===== Per-strike contribution =====
    print()
    print("=" * 60)
    print("Per-strike PnL contribution (always-on short, hedge=False, full size)")
    print("=" * 60)
    per_strike_pnl = {}
    for k_strike in SHORT_STRIKES:
        res = simulate(
            days_data, 1000, [k_strike], VOUCHER_LIMIT,
            do_hedge=False, signal_threshold_sigma=0.0, direction="short",
        )
        per_strike_pnl[k_strike] = round(res.net_pnl / n_days)
        print(f"  K={k_strike}: net={res.net_pnl / n_days:+8.0f}/day  "
              f"opt_spread_cost={res.option_spread_cost / n_days:6.0f}/day")
    summary["per_strike_pnl_unhedged"] = per_strike_pnl

    # ===== Per-day stability check =====
    print()
    print("=" * 60)
    print("Per-day stability check (signal=0, freq=100, hedged short)")
    print("=" * 60)
    per_day_stability = []
    for d in days_data:
        res = simulate(
            [d], 100, SHORT_STRIKES, VOUCHER_LIMIT,
            do_hedge=True, signal_threshold_sigma=0.0, direction="short",
        )
        per_day_stability.append({
            "day": d["day"],
            "net_pnl": round(res.net_pnl),
            "hedge_spread_cost": round(res.hedge_spread_cost),
        })
        print(f"  Day {d['day']}: PnL={res.net_pnl:+8.0f}  "
              f"hedge_spread={res.hedge_spread_cost:7.0f}")
    summary["per_day_stability"] = per_day_stability

    # ===== Headline numbers =====
    best_signal_short = max(signal_table_short, key=lambda r: r["net_pnl_per_day"])
    best_signal_long = max(signal_table_long, key=lambda r: r["net_pnl_per_day"])
    best_freq_row = max(freq_table_small, key=lambda r: r["net_pnl_per_day"])
    summary["headline"] = {
        "best_rebalance_freq_ticks": best_freq_row["rebalance_every"],
        "best_rebalance_pnl_per_day": best_freq_row["net_pnl_per_day"],
        "best_signal_threshold_sigma_short": best_signal_short["k_sigma"],
        "best_signal_pnl_per_day_short": best_signal_short["net_pnl_per_day"],
        "best_signal_threshold_sigma_long": best_signal_long["k_sigma"],
        "best_signal_pnl_per_day_long": best_signal_long["net_pnl_per_day"],
        "hedged_minus_unhedged_per_day_full_book": hedge_compare[0]["delta_per_day"],
        "hedged_minus_unhedged_per_day_small_book": hedge_compare[1]["delta_per_day"],
        "recommendation": (
            "DELTA HEDGE WORTHWHILE" if max(r["delta_per_day"] for r in hedge_compare) > 500
            else "SKIP DELTA HEDGE - Chris's critique holds"
        ),
    }

    out_path = OUT_DIR / "delta_hedged_options.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
