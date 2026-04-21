"""
Search for the optimal FV starting value for each day by maximizing Bot 2 bid match rate.
This also tests whether the formulas are consistent across all FV ranges.
"""

import csv, math
from pathlib import Path
from collections import Counter

DATA_DIR = Path(__file__).parents[3] / "data" / "prosperity4" / "round1"


def load_csv_product(day, product):
    fname = DATA_DIR / f"prices_round_1_day_{day}.csv"
    rows = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != product:
                continue
            ts = int(row["timestamp"])
            bids, asks = [], []
            bid_vols, ask_vols = {}, {}
            for i in [1, 2, 3]:
                bp = row[f"bid_price_{i}"]
                if bp:
                    bp = int(bp)
                    bids.append(bp)
                    bid_vols[bp] = int(row[f"bid_volume_{i}"])
                ap = row[f"ask_price_{i}"]
                if ap:
                    ap = int(ap)
                    asks.append(ap)
                    ask_vols[ap] = int(row[f"ask_volume_{i}"])
            rows.append({"ts": ts, "bids": sorted(bids, reverse=True),
                         "asks": sorted(asks), "bid_vols": bid_vols, "ask_vols": ask_vols})
    return rows


def score_formulas(rows, fv_start, drift=0.1):
    """Count matches for our calibrated formulas given a FV start."""
    b1_bid_m, b1_bid_t = 0, 0
    b1_ask_m, b1_ask_t = 0, 0
    b2_bid_m, b2_bid_t = 0, 0
    b2_ask_m, b2_ask_t = 0, 0

    for r in rows:
        fv = fv_start + drift * (r["ts"] / 100)

        b1_bid_exp = math.ceil(fv) - 10
        b1_ask_exp = math.floor(fv) + 10
        b2_bid_exp = math.ceil(fv) - 7
        b2_ask_exp = math.floor(fv) + 7

        for bp in r["bids"]:
            off = bp - fv
            vol = r["bid_vols"].get(bp, 0)
            if vol >= 15 and off < -5:  # Bot 1 by volume
                b1_bid_t += 1
                if bp == b1_bid_exp:
                    b1_bid_m += 1
            elif 5 <= vol <= 12 and off < -3:  # Bot 2 by volume
                b2_bid_t += 1
                if bp == b2_bid_exp:
                    b2_bid_m += 1

        for ap in r["asks"]:
            off = ap - fv
            vol = r["ask_vols"].get(ap, 0)
            if vol >= 15 and off > 5:
                b1_ask_t += 1
                if ap == b1_ask_exp:
                    b1_ask_m += 1
            elif 5 <= vol <= 12 and off > 3:
                b2_ask_t += 1
                if ap == b2_ask_exp:
                    b2_ask_m += 1

    return {
        "b1_bid": (b1_bid_m, b1_bid_t),
        "b1_ask": (b1_ask_m, b1_ask_t),
        "b2_bid": (b2_bid_m, b2_bid_t),
        "b2_ask": (b2_ask_m, b2_ask_t),
    }


print("=" * 80)
print("  SEARCHING FOR OPTIMAL FV START (PEPPER)")
print("=" * 80)

for day in [-2, -1, 0]:
    rows = load_csv_product(day, "INTARIAN_PEPPER_ROOT")
    n = len(rows)
    print(f"\n  ── Day {day} ({n} ticks) ──")

    # Get mid at t=0 as starting point
    t0 = [r for r in rows if r["ts"] == 0][0]
    if t0["bids"] and t0["asks"]:
        mid0 = (max(t0["bids"]) + min(t0["asks"])) / 2
    elif t0["asks"]:
        mid0 = min(t0["asks"])
    else:
        mid0 = 10000 + day * 1000
    print(f"  Mid at t=0: {mid0}")

    # Search around mid0
    best_score = 0
    best_start = mid0
    for start_offset in range(-15, 16):
        start = mid0 + start_offset * 0.5
        scores = score_formulas(rows, start)
        total_match = sum(s[0] for s in scores.values())
        total_obs = sum(s[1] for s in scores.values())
        if total_match > best_score:
            best_score = total_match
            best_start = start
            best_scores = scores

    print(f"  Best FV start: {best_start}")
    print(f"  Total matches: {best_score}")
    for k, (m, t) in best_scores.items():
        pct = m / t * 100 if t > 0 else 0
        print(f"    {k}: {m}/{t} ({pct:.1f}%)")

    # Also try with offset-based separation instead of volume-based
    print(f"\n  -- Offset-based separation with best start --")
    fv_start = best_start
    b2_bid_m, b2_bid_t = 0, 0
    b2_ask_m, b2_ask_t = 0, 0
    b1_bid_m, b1_bid_t = 0, 0
    b1_ask_m, b1_ask_t = 0, 0

    for r in rows:
        fv = fv_start + 0.1 * (r["ts"] / 100)
        for bp in r["bids"]:
            off = bp - fv
            if off < -8:
                b1_bid_t += 1
                if bp == math.ceil(fv) - 10:
                    b1_bid_m += 1
            elif off < -4:
                b2_bid_t += 1
                if bp == math.ceil(fv) - 7:
                    b2_bid_m += 1
        for ap in r["asks"]:
            off = ap - fv
            if off > 8:
                b1_ask_t += 1
                if ap == math.floor(fv) + 10:
                    b1_ask_m += 1
            elif off > 4:
                b2_ask_t += 1
                if ap == math.floor(fv) + 7:
                    b2_ask_m += 1

    for name, m, t in [("B1 bid", b1_bid_m, b1_bid_t), ("B1 ask", b1_ask_m, b1_ask_t),
                         ("B2 bid", b2_bid_m, b2_bid_t), ("B2 ask", b2_ask_m, b2_ask_t)]:
        pct = m / t * 100 if t > 0 else 0
        print(f"    {name}: {m}/{t} ({pct:.1f}%)")


# ── Also check: does the drift vary by day? ──
print(f"\n\n{'=' * 80}")
print("  CHECKING IF DRIFT VARIES BY DAY")
print("=" * 80)

for day in [-2, -1, 0]:
    rows = load_csv_product(day, "INTARIAN_PEPPER_ROOT")
    # Use the best-bid level to estimate FV at each tick
    # If Bot 2 bid = ceil(FV) - 7, then FV ≈ bid + 7 (roughly)
    # More precisely, mid of best bid and best ask gives FV estimate
    fv_estimates = []
    for r in rows:
        if r["bids"] and r["asks"]:
            mid = (max(r["bids"]) + min(r["asks"])) / 2
            fv_estimates.append((r["ts"], mid))

    if len(fv_estimates) > 100:
        # Linear regression: mid = a + b * ts
        xs = [e[0] for e in fv_estimates]
        ys = [e[1] for e in fv_estimates]
        n_pts = len(xs)
        mx = sum(xs) / n_pts
        my = sum(ys) / n_pts
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs)
        slope = cov / vx if vx > 0 else 0
        intercept = my - slope * mx
        drift_per_tick = slope * 100  # convert from per-ts-unit to per-tick
        print(f"  Day {day}: drift_per_tick = {drift_per_tick:.6f}, intercept = {intercept:.2f}")
        print(f"    Mid-price at t=0: {ys[0]:.1f}, at t=last: {ys[-1]:.1f}")
