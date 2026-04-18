"""Cross-product signal and trade-through analysis for Round 1."""
import csv
import math
from collections import defaultdict

DATA = "data/prosperity4/round1"
DAYS = [-2, -1, 0]

# --- Load prices ---
prices = defaultdict(dict)  # (day, timestamp) -> product -> row
for d in DAYS:
    with open(f"{DATA}/prices_round_1_day_{d}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            prod = row["product"]
            mid = row["mid_price"]
            if mid:
                prices[(d, ts)][prod] = {
                    "mid": float(mid),
                    "bid1": float(row["bid_price_1"]) if row["bid_price_1"] else None,
                    "ask1": float(row["ask_price_1"]) if row["ask_price_1"] else None,
                    "bid_vol1": int(row["bid_volume_1"]) if row["bid_volume_1"] else 0,
                    "ask_vol1": int(row["ask_volume_1"]) if row["ask_volume_1"] else 0,
                }

# --- Load trades ---
trades = defaultdict(list)  # (day, timestamp) -> list of trade dicts
for d in DAYS:
    with open(f"{DATA}/trades_round_1_day_{d}.csv") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            trades[(d, ts)].append({
                "symbol": row["symbol"],
                "price": float(row["price"]),
                "quantity": int(row["quantity"]),
                "buyer": row.get("buyer", ""),
                "seller": row.get("seller", ""),
            })

# ============================================================
# 1. CROSS-PRODUCT CORRELATION
# ============================================================
print("=" * 60)
print("1. CROSS-PRODUCT RETURN CORRELATION")
print("=" * 60)

for d in DAYS:
    # Get sorted timestamps where both products exist
    all_ts = sorted(set(ts for (dd, ts) in prices if dd == d))
    both_ts = [ts for ts in all_ts if "ASH_COATED_OSMIUM" in prices[(d, ts)] and "INTARIAN_PEPPER_ROOT" in prices[(d, ts)]]

    aco_ret = []
    ipr_ret = []
    for i in range(1, len(both_ts)):
        t0, t1 = both_ts[i - 1], both_ts[i]
        aco_r = prices[(d, t1)]["ASH_COATED_OSMIUM"]["mid"] - prices[(d, t0)]["ASH_COATED_OSMIUM"]["mid"]
        ipr_r = prices[(d, t1)]["INTARIAN_PEPPER_ROOT"]["mid"] - prices[(d, t0)]["INTARIAN_PEPPER_ROOT"]["mid"]
        # Detrend IPR: remove +0.1/tick drift
        dt = (t1 - t0) / 100.0
        ipr_r -= 0.1 * dt
        aco_ret.append(aco_r)
        ipr_ret.append(ipr_r)

    n = len(aco_ret)
    if n < 2:
        continue
    ma = sum(aco_ret) / n
    mi = sum(ipr_ret) / n
    cov = sum((a - ma) * (i - mi) for a, i in zip(aco_ret, ipr_ret)) / n
    sa = math.sqrt(sum((a - ma) ** 2 for a in aco_ret) / n)
    si = math.sqrt(sum((i - mi) ** 2 for i in ipr_ret) / n)
    corr = cov / (sa * si) if sa > 0 and si > 0 else 0
    print(f"  Day {d}: n={n}, corr(ACO_ret, IPR_detrended_ret) = {corr:.4f}")

    # Lead-lag: ACO[t] -> IPR[t+1] and vice versa
    if n > 2:
        # ACO leads IPR
        cov_lead = sum((aco_ret[i] - ma) * (ipr_ret[i + 1] - mi) for i in range(n - 1)) / (n - 1)
        corr_lead = cov_lead / (sa * si) if sa > 0 and si > 0 else 0
        # IPR leads ACO
        cov_lead2 = sum((ipr_ret[i] - mi) * (aco_ret[i + 1] - ma) for i in range(n - 1)) / (n - 1)
        corr_lead2 = cov_lead2 / (sa * si) if sa > 0 and si > 0 else 0
        print(f"         ACO[t]->IPR[t+1] = {corr_lead:.4f},  IPR[t]->ACO[t+1] = {corr_lead2:.4f}")

# ============================================================
# 2. TRADE-THROUGH ANALYSIS FOR ACO
# ============================================================
print()
print("=" * 60)
print("2. ACO TRADE-THROUGH ANALYSIS")
print("=" * 60)

total_ticks_with_trades = 0
tradethrough_ticks = 0
total_vol = 0
tradethrough_vol = 0

for d in DAYS:
    for (dd, ts), tlist in trades.items():
        if dd != d:
            continue
        aco_trades = [t for t in tlist if t["symbol"] == "ASH_COATED_OSMIUM"]
        if not aco_trades:
            continue
        total_ticks_with_trades += 1
        prices_seen = set(t["price"] for t in aco_trades)
        vol = sum(t["quantity"] for t in aco_trades)
        total_vol += vol
        if len(prices_seen) > 1:
            tradethrough_ticks += 1
            tradethrough_vol += vol

print(f"  Ticks with ACO trades: {total_ticks_with_trades}")
print(f"  Trade-through ticks (multiple prices): {tradethrough_ticks} ({100*tradethrough_ticks/max(total_ticks_with_trades,1):.1f}%)")
print(f"  Total ACO volume: {total_vol}")
print(f"  Trade-through volume: {tradethrough_vol} ({100*tradethrough_vol/max(total_vol,1):.1f}%)")

# Also look at IPR
ipr_tt_ticks = 0
ipr_total_ticks = 0
for (dd, ts), tlist in trades.items():
    ipr_trades = [t for t in tlist if t["symbol"] == "INTARIAN_PEPPER_ROOT"]
    if not ipr_trades:
        continue
    ipr_total_ticks += 1
    if len(set(t["price"] for t in ipr_trades)) > 1:
        ipr_tt_ticks += 1
print(f"\n  IPR trade-through ticks: {ipr_tt_ticks}/{ipr_total_ticks} ({100*ipr_tt_ticks/max(ipr_total_ticks,1):.1f}%)")

# ============================================================
# 3. SPREAD -> NEXT RETURN FOR ACO
# ============================================================
print()
print("=" * 60)
print("3. ACO SPREAD -> NEXT-TICK RETURN")
print("=" * 60)

for d in DAYS:
    all_ts = sorted(ts for (dd, ts) in prices if dd == d and "ASH_COATED_OSMIUM" in prices[(dd, ts)])
    spreads = []
    next_rets = []
    for i in range(len(all_ts) - 1):
        t0, t1 = all_ts[i], all_ts[i + 1]
        p0 = prices[(d, t0)]["ASH_COATED_OSMIUM"]
        p1 = prices[(d, t1)]["ASH_COATED_OSMIUM"]
        if p0["bid1"] is not None and p0["ask1"] is not None:
            spread = p0["ask1"] - p0["bid1"]
            ret = p1["mid"] - p0["mid"]
            spreads.append(spread)
            next_rets.append(ret)

    if not spreads:
        continue

    # Bucket by spread
    spread_buckets = defaultdict(list)
    for s, r in zip(spreads, next_rets):
        bucket = round(s)
        spread_buckets[bucket].append(r)

    print(f"  Day {d}:")
    for bucket in sorted(spread_buckets.keys()):
        rets = spread_buckets[bucket]
        avg = sum(rets) / len(rets)
        std = math.sqrt(sum((r - avg) ** 2 for r in rets) / len(rets)) if len(rets) > 1 else 0
        print(f"    Spread={bucket:4.0f}: n={len(rets):5d}, avg_next_ret={avg:+.3f}, std={std:.3f}")

    # Overall correlation
    n = len(spreads)
    ms = sum(spreads) / n
    mr = sum(next_rets) / n
    cov = sum((s - ms) * (r - mr) for s, r in zip(spreads, next_rets)) / n
    ss = math.sqrt(sum((s - ms) ** 2 for s in spreads) / n)
    sr = math.sqrt(sum((r - mr) ** 2 for r in next_rets) / n)
    corr = cov / (ss * sr) if ss > 0 and sr > 0 else 0
    print(f"    Spread-Return corr = {corr:.4f}")

# Also for ACO: does |mid - 10000| predict reversion?
print()
print("  ACO DEVIATION FROM 10000 -> NEXT RETURN:")
for d in DAYS:
    all_ts = sorted(ts for (dd, ts) in prices if dd == d and "ASH_COATED_OSMIUM" in prices[(dd, ts)])
    devs = []
    rets = []
    for i in range(len(all_ts) - 1):
        t0, t1 = all_ts[i], all_ts[i + 1]
        p0 = prices[(d, t0)]["ASH_COATED_OSMIUM"]
        p1 = prices[(d, t1)]["ASH_COATED_OSMIUM"]
        dev = p0["mid"] - 10000
        ret = p1["mid"] - p0["mid"]
        devs.append(dev)
        rets.append(ret)
    if not devs:
        continue
    n = len(devs)
    md = sum(devs) / n
    mr = sum(rets) / n
    cov = sum((dd - md) * (r - mr) for dd, r in zip(devs, rets)) / n
    sd = math.sqrt(sum((dd - md) ** 2 for dd in devs) / n)
    sr = math.sqrt(sum((r - mr) ** 2 for r in rets) / n)
    corr = cov / (sd * sr) if sd > 0 and sr > 0 else 0
    print(f"    Day {d}: corr(deviation, next_ret) = {corr:.4f}")

# ============================================================
# 4. VOLUME / SPREAD TIME-OF-DAY PATTERNS
# ============================================================
print()
print("=" * 60)
print("4. TIME-OF-DAY PATTERNS (binned by 10k timestamp = ~1/10 of day)")
print("=" * 60)

for prod in ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]:
    print(f"\n  {prod}:")
    vol_by_bin = defaultdict(int)
    spread_by_bin = defaultdict(list)
    count_by_bin = defaultdict(int)

    for d in DAYS:
        # Volume from trades
        for (dd, ts), tlist in trades.items():
            if dd != d:
                continue
            for t in tlist:
                if t["symbol"] == prod:
                    b = ts // 100000
                    vol_by_bin[b] += t["quantity"]

        # Spread from prices
        all_ts = sorted(ts for (dd, ts) in prices if dd == d and prod in prices[(dd, ts)])
        for ts in all_ts:
            p = prices[(d, ts)][prod]
            b = ts // 100000
            count_by_bin[b] += 1
            if p["bid1"] is not None and p["ask1"] is not None:
                spread_by_bin[b].append(p["ask1"] - p["bid1"])

    bins = sorted(set(list(vol_by_bin.keys()) + list(count_by_bin.keys())))
    print(f"    {'Bin':>4s} {'Ticks':>6s} {'Volume':>7s} {'Avg Spread':>11s}")
    for b in bins:
        avg_spr = sum(spread_by_bin[b]) / len(spread_by_bin[b]) if spread_by_bin[b] else float("nan")
        print(f"    {b:4d} {count_by_bin[b]:6d} {vol_by_bin[b]:7d} {avg_spr:11.1f}")

print("\nDone.")
