"""IV-scalp idle-phase diagnostic.

Question 1: On 10K-tick days, what fraction of ticks per voucher have
            switch_mean < IV_SCALPING_THR (i.e. IV-scalp is gated off)?
Question 2: How long are the idle stretches and where do they fall?
Question 3: Do all 6 vouchers idle simultaneously, or are some still active?

Re-uses the same online-state computation as iv_scalp_diagnostic.py but
with the V2-tuned constants from traders/round4/submission.py and writes
per-voucher per-day idle stats.

Outputs:
  analysis/round4/iv_scalp_idle_diagnostic.json
  analysis/round4/iv_scalp_idle_diagnostic.md
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
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNDERLYING = "VELVETFRUIT_EXTRACT"
SCALP_STRIKES = {5000: "VEV_5000", 5100: "VEV_5100", 5200: "VEV_5200",
                 5300: "VEV_5300", 5400: "VEV_5400", 5500: "VEV_5500"}

# === V2-tuned constants (mirrors traders/round4/submission.py) ===
SMILE_A_INIT = 0.580261
SMILE_B = 0.033704
SMILE_C = 0.089775
SMILE_A_ALPHA = 0.0052       # V2
THEO_NORM_WINDOW = 100
IV_SCALPING_WINDOW = 200     # V2
THR_OPEN = 0.536             # V2
IV_SCALPING_THR = 1.0865     # V2
LOW_VEGA_THR_ADJ = 0.653     # V2
LOW_VEGA_CUTOFF = 4.0984     # V2

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


def diagnose_day(day: int) -> dict:
    pv_mid, pv_bid, pv_ask = load_day(day)
    needed = [UNDERLYING] + list(SCALP_STRIKES.values())
    panel = pv_mid.dropna(subset=needed)
    panel_bid = pv_bid.loc[panel.index]
    panel_ask = pv_ask.loc[panel.index]
    n = len(panel)
    print(f"day {day}: panel rows {n}")

    smile_a = SMILE_A_INIT
    mean_dev = {sym: None for sym in SCALP_STRIKES.values()}
    switch_mean = {sym: 0.0 for sym in SCALP_STRIKES.values()}
    a_m = 2.0 / (THEO_NORM_WINDOW + 1)
    a_s = 2.0 / (IV_SCALPING_WINDOW + 1)

    timestamps = panel.index.to_list()
    mids_arr = {sym: panel[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    bids_arr = {sym: panel_bid[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    asks_arr = {sym: panel_ask[sym].to_numpy() for sym in SCALP_STRIKES.values()}
    S_arr = panel[UNDERLYING].to_numpy()

    # Per-voucher per-tick: gate_active boolean, plus did the trigger fire
    gate_active = {sym: [False] * n for sym in SCALP_STRIKES.values()}
    trigger_fired = {sym: [False] * n for sym in SCALP_STRIKES.values()}
    switch_trace = {sym: [0.0] * n for sym in SCALP_STRIKES.values()}

    for i, ts in enumerate(timestamps):
        S = float(S_arr[i])
        T = t_years(int(ts))

        observed_ivs = {}
        for K, sym in SCALP_STRIKES.items():
            mid = float(mids_arr[sym][i])
            iv = implied_vol(mid, S, K, T)
            if iv is not None and 0.05 < iv < 4.5:
                observed_ivs[K] = iv
        if observed_ivs:
            residuals = []
            for K, iv_obs in observed_ivs.items():
                residuals.append(iv_obs - smile_iv(K, S, T, smile_a))
            avg_res = sum(residuals) / len(residuals)
            smile_a = max(0.05, min(3.0, smile_a + SMILE_A_ALPHA * avg_res))

        for K, sym in SCALP_STRIKES.items():
            mid = float(mids_arr[sym][i])
            best_bid = float(bids_arr[sym][i])
            best_ask = float(asks_arr[sym][i])
            if math.isnan(mid) or math.isnan(best_bid) or math.isnan(best_ask):
                continue
            fair = smile_fair(K, S, T, smile_a)
            iv_use = max(0.05, smile_iv(K, S, T, smile_a))
            vega = bs_vega(S, K, iv_use, T)
            dev = mid - fair
            md_prev = mean_dev[sym] if mean_dev[sym] is not None else dev
            md_new = a_m * dev + (1 - a_m) * md_prev
            mean_dev[sym] = md_new
            sw_prev = switch_mean[sym]
            sw_new = a_s * abs(dev - md_new) + (1 - a_s) * sw_prev
            switch_mean[sym] = sw_new
            switch_trace[sym][i] = sw_new

            if sw_new < IV_SCALPING_THR:
                continue
            gate_active[sym][i] = True

            thr = THR_OPEN + (LOW_VEGA_THR_ADJ if vega <= LOW_VEGA_CUTOFF else 0.0)
            sell_dev = (best_bid - fair) - md_new
            buy_dev = (best_ask - fair) - md_new
            if sell_dev >= thr or buy_dev <= -thr:
                trigger_fired[sym][i] = True

    # Aggregate per voucher
    per_voucher = {}
    all_gates = []  # all-vouchers-idle = no gate active anywhere
    for sym in SCALP_STRIKES.values():
        ga = gate_active[sym]
        tf = trigger_fired[sym]
        st = switch_trace[sym]
        n_active = sum(ga)
        n_fire = sum(tf)
        # Longest idle run
        longest_idle = 0
        cur = 0
        idle_runs = []
        for v in ga:
            if not v:
                cur += 1
            else:
                if cur > 0:
                    idle_runs.append(cur)
                    if cur > longest_idle:
                        longest_idle = cur
                    cur = 0
        if cur > 0:
            idle_runs.append(cur)
            if cur > longest_idle:
                longest_idle = cur
        # Where does idle concentrate? bucket by 1000-tick chunks (10 buckets per day)
        bucket_size = max(1, n // 10)
        bucket_idle_pct = []
        for b in range(10):
            lo = b * bucket_size
            hi = min(n, (b + 1) * bucket_size)
            if hi <= lo:
                bucket_idle_pct.append(None)
                continue
            n_idle_b = sum(1 for v in ga[lo:hi] if not v)
            bucket_idle_pct.append(round(n_idle_b / (hi - lo), 3))

        per_voucher[sym] = {
            "n_panel": n,
            "n_active": int(n_active),
            "n_idle": int(n - n_active),
            "active_pct": round(n_active / n, 4) if n > 0 else 0,
            "idle_pct": round((n - n_active) / n, 4) if n > 0 else 0,
            "n_trigger_fired": int(n_fire),
            "longest_idle_run": int(longest_idle),
            "n_idle_runs": len(idle_runs),
            "mean_idle_run": round(sum(idle_runs) / len(idle_runs), 1) if idle_runs else 0,
            "max_switch_mean": round(max(st) if st else 0.0, 4),
            "first_active_idx": next((i for i, v in enumerate(ga) if v), None),
            "last_active_idx": next((n - 1 - i for i, v in enumerate(reversed(ga)) if v), None),
            "idle_pct_per_decile": bucket_idle_pct,
        }
        all_gates.append(ga)

    # All-vouchers-idle stats
    n_all_idle = 0
    n_any_active = 0
    for i in range(n):
        any_active = any(all_gates[v][i] for v in range(len(all_gates)))
        if any_active:
            n_any_active += 1
        else:
            n_all_idle += 1

    return {
        "day": day,
        "n_panel": n,
        "per_voucher": per_voucher,
        "n_ticks_any_voucher_active": n_any_active,
        "n_ticks_all_vouchers_idle": n_all_idle,
        "pct_ticks_all_idle": round(n_all_idle / n, 4) if n > 0 else 0,
    }


def main():
    diags = []
    for day in (1, 2, 3):
        diags.append(diagnose_day(day))

    out_json = OUT_DIR / "iv_scalp_idle_diagnostic.json"
    out_json.write_text(json.dumps(diags, indent=2))
    print(f"Wrote {out_json}")

    # Markdown summary
    md = ["# IV-Scalp Idle-Phase Diagnostic (V2 params, 10K-tick replay)\n"]
    md.append("**Question:** is the IV-scalp gate (`switch_mean >= 1.0865`) "
              "frequently OFF on full 10K-tick days? If yes, a subordinate "
              "Mark-counterparty fallback could pick up PnL during idle stretches.\n")
    md.append("Source data: `data/prosperity4/round4/prices_round_4_day_{1,2,3}.csv`. "
              "Re-uses the exact V2 tuned constants from `traders/round4/submission.py` "
              "and computes online state in lock-step.\n")

    for d in diags:
        day = d["day"]
        n = d["n_panel"]
        md.append(f"\n## Day {day} ({n} ticks)\n")
        md.append("| Voucher | Active% | Idle% | Trigger fires | Longest idle | "
                  "#idle runs | Mean idle run | Max switch_mean |\n")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for sym in ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
            pv = d["per_voucher"][sym]
            md.append(f"| {sym} | {pv['active_pct']*100:.1f}% | "
                      f"{pv['idle_pct']*100:.1f}% | {pv['n_trigger_fired']} | "
                      f"{pv['longest_idle_run']} | {pv['n_idle_runs']} | "
                      f"{pv['mean_idle_run']:.1f} | {pv['max_switch_mean']:.3f} |\n")

        md.append(f"\n**All-vouchers-idle ticks**: {d['n_ticks_all_vouchers_idle']} "
                  f"of {n} ({d['pct_ticks_all_idle']*100:.1f}%) — "
                  f"i.e. for that fraction of the day, NO voucher has the gate "
                  f"open, so a subordinate Mark fallback could fire freely.\n")

        md.append("\n**Idle % per decile of the day** (tick range divided into 10 "
                  "equal buckets, % of bucket where gate is OFF):\n\n")
        md.append("| Voucher | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |\n")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for sym in ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
            buckets = d["per_voucher"][sym]["idle_pct_per_decile"]
            row = " | ".join(
                "—" if b is None else f"{int(b*100)}%" for b in buckets
            )
            md.append(f"| {sym} | {row} |\n")

    md.append("\n## Verdict\n\n")
    # Compute overall stats
    total_ticks = sum(d["n_panel"] for d in diags)
    total_all_idle = sum(d["n_ticks_all_vouchers_idle"] for d in diags)
    md.append(f"- Across all 3 days: **{total_all_idle}/{total_ticks} = "
              f"{100*total_all_idle/total_ticks:.1f}% of ticks have ALL six vouchers "
              f"idle simultaneously**.\n")
    for sym in ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
        idle_total = sum(d["per_voucher"][sym]["n_idle"] for d in diags)
        md.append(f"- `{sym}`: idle {idle_total}/{total_ticks} = "
                  f"{100*idle_total/total_ticks:.1f}% of all ticks.\n")

    out_md = OUT_DIR / "iv_scalp_idle_diagnostic.md"
    out_md.write_text("".join(md))
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
