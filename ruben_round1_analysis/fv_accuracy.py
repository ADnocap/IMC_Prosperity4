"""
Analyze wall-based FV estimation accuracy for ASH_COATED_OSMIUM.

Wall detection logic (from calibrated bot model):
- Inner wall: vol in [10,15] -> FV ~ bid_price + 8, or ask_price - 8
- Outer wall: vol in [20,30] -> FV ~ bid_price + 10.5, or ask_price - 10.5
- If both sides found, average them.

We compare estimated FV to future mid-prices (5 and 10 ticks ahead).
"""

import csv
import math
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "prosperity4" / "round1"
PRODUCT = "ASH_COATED_OSMIUM"

def load_ash_data():
    """Load all ASH_COATED_OSMIUM rows from all days, return list of dicts."""
    rows = []
    for day_suffix in ["-2", "-1", "0"]:
        fpath = DATA_DIR / f"prices_round_1_day_{day_suffix}.csv"
        if not fpath.exists():
            continue
        with open(fpath, "r") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row["product"] != PRODUCT:
                    continue
                rows.append(row)
    return rows


def parse_levels(row):
    """Extract bid/ask levels as list of (price, vol) tuples."""
    bids = []
    asks = []
    for i in range(1, 4):
        bp = row.get(f"bid_price_{i}", "")
        bv = row.get(f"bid_volume_{i}", "")
        if bp and bv:
            bids.append((float(bp), abs(float(bv))))
        ap = row.get(f"ask_price_{i}", "")
        av = row.get(f"ask_volume_{i}", "")
        if ap and av:
            asks.append((float(ap), abs(float(av))))
    return bids, asks


def estimate_fv(bids, asks):
    """Estimate FV from wall detection. Returns float or None."""
    estimates = []

    for price, vol in bids:
        if 10 <= vol <= 15:
            estimates.append(("bid_inner", price + 8))
        elif 20 <= vol <= 30:
            estimates.append(("bid_outer", price + 10.5))

    for price, vol in asks:
        if 10 <= vol <= 15:
            estimates.append(("ask_inner", price - 8))
        elif 20 <= vol <= 30:
            estimates.append(("ask_outer", price - 10.5))

    if not estimates:
        return None

    return sum(e[1] for e in estimates) / len(estimates)


def two_sided_mid(row):
    """Compute mid only from two-sided books. Returns None if one-sided."""
    bp = row.get("bid_price_1", "").strip()
    ap = row.get("ask_price_1", "").strip()
    if not bp or not ap:
        return None
    return (float(bp) + float(ap)) / 2


def main():
    rows = load_ash_data()
    print(f"Loaded {len(rows)} ASH_COATED_OSMIUM ticks across all days\n")

    # Group by day
    days = {}
    for row in rows:
        d = row["day"]
        days.setdefault(d, []).append(row)

    # Process each day separately to avoid cross-day forward lookups
    all_results = []

    for day_key in sorted(days.keys(), key=lambda x: int(x)):
        day_rows = days[day_key]
        mids = []
        fvs = []
        for row in day_rows:
            mid = two_sided_mid(row)
            mids.append(mid)

            bids, asks = parse_levels(row)
            fv = estimate_fv(bids, asks)
            fvs.append(fv)

        for i in range(len(day_rows)):
            if fvs[i] is None or mids[i] is None:
                continue
            mid_5 = mids[i + 5] if i + 5 < len(mids) and mids[i + 5] is not None else None
            mid_10 = mids[i + 10] if i + 10 < len(mids) and mids[i + 10] is not None else None
            all_results.append({
                "fv": fvs[i],
                "mid_now": mids[i],
                "mid_5": mid_5,
                "mid_10": mid_10,
                "day": day_key,
                "ts": day_rows[i]["timestamp"],
            })

    print(f"Ticks with valid FV estimate: {len(all_results)}")

    # --- 1. FV vs current mid ---
    diffs_now = [r["fv"] - r["mid_now"] for r in all_results]
    print(f"\n=== FV vs Current Mid ===")
    print(f"  Mean diff (FV - mid):  {sum(diffs_now)/len(diffs_now):.3f}")
    print(f"  Std diff:              {(sum((d - sum(diffs_now)/len(diffs_now))**2 for d in diffs_now)/len(diffs_now))**0.5:.3f}")

    # --- 2. Forward prediction accuracy ---
    for horizon, key in [(5, "mid_5"), (10, "mid_10")]:
        valid = [r for r in all_results if r[key] is not None]
        if not valid:
            continue
        errors_fv = [r["fv"] - r[key] for r in valid]
        errors_mid = [r["mid_now"] - r[key] for r in valid]

        mae_fv = sum(abs(e) for e in errors_fv) / len(errors_fv)
        mae_mid = sum(abs(e) for e in errors_mid) / len(errors_mid)
        rmse_fv = (sum(e**2 for e in errors_fv) / len(errors_fv)) ** 0.5
        rmse_mid = (sum(e**2 for e in errors_mid) / len(errors_mid)) ** 0.5
        bias_fv = sum(errors_fv) / len(errors_fv)
        bias_mid = sum(errors_mid) / len(errors_mid)

        wrong_1 = sum(1 for e in errors_fv if abs(e) > 1) / len(errors_fv) * 100
        wrong_2 = sum(1 for e in errors_fv if abs(e) > 2) / len(errors_fv) * 100

        print(f"\n=== Forward {horizon}-tick prediction (n={len(valid)}) ===")
        print(f"  Wall FV:   MAE={mae_fv:.3f}  RMSE={rmse_fv:.3f}  Bias={bias_fv:.3f}")
        print(f"  Raw Mid:   MAE={mae_mid:.3f}  RMSE={rmse_mid:.3f}  Bias={bias_mid:.3f}")
        print(f"  FV wrong >1: {wrong_1:.1f}%   >2: {wrong_2:.1f}%")

    # --- 3. EMA smoothing comparison ---
    print(f"\n=== EMA Smoothing Comparison ===")
    alphas = [0.1, 0.2, 0.3, 0.5, 1.0]  # 1.0 = raw FV

    for horizon, key in [(5, "mid_5"), (10, "mid_10")]:
        valid_indices = [i for i, r in enumerate(all_results) if r[key] is not None]
        if not valid_indices:
            continue

        print(f"\n  --- {horizon}-tick forward ---")
        print(f"  {'Alpha':<8} {'MAE':<10} {'RMSE':<10} {'Bias':<10} {'>1 tick%':<10} {'>2 tick%':<10}")

        for alpha in alphas:
            # Compute EMA per day
            ema_vals = []
            current_ema = None
            current_day = None

            for r in all_results:
                if r["day"] != current_day:
                    current_ema = r["fv"]
                    current_day = r["day"]
                else:
                    current_ema = alpha * r["fv"] + (1 - alpha) * current_ema
                ema_vals.append(current_ema)

            errors = [ema_vals[i] - all_results[i][key] for i in valid_indices]
            mae = sum(abs(e) for e in errors) / len(errors)
            rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
            bias = sum(errors) / len(errors)
            w1 = sum(1 for e in errors if abs(e) > 1) / len(errors) * 100
            w2 = sum(1 for e in errors if abs(e) > 2) / len(errors) * 100
            print(f"  {alpha:<8.1f} {mae:<10.3f} {rmse:<10.3f} {bias:<10.3f} {w1:<10.1f} {w2:<10.1f}")

    # --- 4. Also compare: raw mid as predictor with EMA ---
    print(f"\n=== Mid-price EMA as predictor (for reference) ===")
    for horizon, key in [(5, "mid_5"), (10, "mid_10")]:
        valid_indices = [i for i, r in enumerate(all_results) if r[key] is not None]
        if not valid_indices:
            continue

        print(f"\n  --- {horizon}-tick forward ---")
        print(f"  {'Alpha':<8} {'MAE':<10} {'RMSE':<10} {'Bias':<10}")

        for alpha in [0.1, 0.2, 0.3, 0.5, 1.0]:
            ema_vals = []
            current_ema = None
            current_day = None

            for r in all_results:
                if r["day"] != current_day:
                    current_ema = r["mid_now"]
                    current_day = r["day"]
                else:
                    current_ema = alpha * r["mid_now"] + (1 - alpha) * current_ema
                ema_vals.append(current_ema)

            errors = [ema_vals[i] - all_results[i][key] for i in valid_indices]
            mae = sum(abs(e) for e in errors) / len(errors)
            rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
            bias = sum(errors) / len(errors)
            print(f"  {alpha:<8.1f} {mae:<10.3f} {rmse:<10.3f} {bias:<10.3f}")

    # --- 5. Detection rate ---
    all_ticks = 0
    detected = 0
    for day_key in sorted(days.keys(), key=lambda x: int(x)):
        for row in days[day_key]:
            all_ticks += 1
            bids, asks = parse_levels(row)
            fv = estimate_fv(bids, asks)
            if fv is not None:
                detected += 1
    print(f"\n=== Wall Detection Rate ===")
    print(f"  {detected}/{all_ticks} ticks ({detected/all_ticks*100:.1f}%)")

    # --- 6. Wall type distribution ---
    type_counts = {}
    for day_key in sorted(days.keys(), key=lambda x: int(x)):
        for row in days[day_key]:
            bids, asks = parse_levels(row)
            types_found = []
            for price, vol in bids:
                if 10 <= vol <= 15:
                    types_found.append("bid_inner")
                elif 20 <= vol <= 30:
                    types_found.append("bid_outer")
            for price, vol in asks:
                if 10 <= vol <= 15:
                    types_found.append("ask_inner")
                elif 20 <= vol <= 30:
                    types_found.append("ask_outer")
            key = "+".join(sorted(types_found)) if types_found else "none"
            type_counts[key] = type_counts.get(key, 0) + 1

    print(f"\n=== Wall Type Distribution ===")
    for k, v in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<50} {v:>5} ({v/all_ticks*100:.1f}%)")


if __name__ == "__main__":
    main()
