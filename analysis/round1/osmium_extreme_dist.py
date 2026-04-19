"""How often does OSMIUM center_dist exceed various thresholds?

If |center_dist| >= 15 is common enough (say 1% of ticks), a deep-crossing
strategy might cover its per-unit spread cost.
"""
import csv
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent.parent
R1 = ROOT / "data" / "prosperity4" / "round1"
R2 = ROOT / "data" / "prosperity4" / "round2"
DAYS = [(R1, 1, -2), (R1, 1, -1), (R1, 1, 0),
        (R2, 2, -1), (R2, 2, 0), (R2, 2, 1)]

buckets = Counter()
total = 0
for dir_, rnd, day in DAYS:
    path = dir_ / f"prices_round_{rnd}_day_{day}.csv"
    with path.open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["product"] != "ASH_COATED_OSMIUM":
                continue
            mid = float(r["mid_price"])
            # mid is a reasonable proxy for FV; for asymmetric ticks it's noisy
            # but for distribution stats it's fine
            d = int(round(mid - 10000))
            ad = abs(d)
            total += 1
            for th in (5, 8, 10, 12, 15, 20, 25):
                if ad >= th:
                    buckets[th] += 1
            # bucket by range
            b = min(ad // 5 * 5, 40)
            buckets[f"bucket_{b}"] += 1

print(f"Total ticks across 6 days: {total}")
print("\nTail probabilities:")
for th in (5, 8, 10, 12, 15, 20, 25):
    n = buckets.get(th, 0)
    print(f"  |center_dist| >= {th:>2}: {n:>5} ticks ({n/total:.2%})")

print("\nBuckets (|center_dist|):")
for b in range(0, 45, 5):
    k = f"bucket_{b}"
    n = buckets.get(k, 0)
    print(f"  [{b},{b+5}): {n:>5} ticks ({n/total:.2%})")
