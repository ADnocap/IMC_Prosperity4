"""
Cross-validate calibrated bot models against the 3-day CSV data.

For PEPPER_ROOT, FV is deterministic: FV(t) = start + 0.1 * (t/100).
For OSMIUM, we use mid-price as FV proxy (less precise but enough for structural validation).

The CSV data has 10,000 ticks per product per day (vs 1,000 in the portal submission).
"""

import csv, math, statistics
from pathlib import Path
from collections import Counter, defaultdict

DATA_DIR = Path(__file__).parents[3] / "data" / "prosperity4" / "round1"

# ─── Known FV starts for PEPPER ───
PEPPER_FV_START = {-2: 10000, -1: 11000, 0: 12000}
PEPPER_DRIFT = 0.1  # per tick


def load_csv(day):
    fname = DATA_DIR / f"prices_round_1_day_{day}.csv"
    rows = {"ASH_COATED_OSMIUM": [], "INTARIAN_PEPPER_ROOT": []}
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prod = row["product"]
            ts = int(row["timestamp"])
            bids, asks = [], []
            bid_vols, ask_vols = {}, {}
            for i in [1, 2, 3]:
                bp = row[f"bid_price_{i}"]
                if bp:
                    bp = int(bp)
                    bv = int(row[f"bid_volume_{i}"])
                    bids.append(bp)
                    bid_vols[bp] = bv
                ap = row[f"ask_price_{i}"]
                if ap:
                    ap = int(ap)
                    av = int(row[f"ask_volume_{i}"])
                    asks.append(ap)
                    ask_vols[ap] = av
            mid = float(row["mid_price"]) if row["mid_price"] else None
            rows[prod].append({
                "ts": ts, "bids": sorted(bids, reverse=True), "asks": sorted(asks),
                "bid_vols": bid_vols, "ask_vols": ask_vols, "mid": mid
            })
    return rows


def validate_pepper(day, rows):
    """Validate PEPPER_ROOT bot models using known deterministic FV."""
    fv_start = PEPPER_FV_START[day]
    n = len(rows)

    print(f"\n  ── PEPPER_ROOT Day {day} ({n} ticks) ──")
    print(f"  FV start: {fv_start}, FV end: {fv_start + PEPPER_DRIFT * (n-1):.1f}")

    b1_bid_match, b1_bid_total = 0, 0
    b1_ask_match, b1_ask_total = 0, 0
    b2_bid_match, b2_bid_total = 0, 0
    b2_ask_match, b2_ask_total = 0, 0

    b1_bid_present, b1_ask_present = 0, 0
    b2_bid_present, b2_ask_present = 0, 0

    b1_bid_vols, b1_ask_vols = [], []
    b2_bid_vols, b2_ask_vols = [], []

    for r in rows:
        fv = fv_start + PEPPER_DRIFT * (r["ts"] / 100)

        # Expected quotes
        b1_bid_exp = math.ceil(fv) - 10
        b1_ask_exp = math.floor(fv) + 10
        b2_bid_exp = math.ceil(fv) - 7
        b2_ask_exp = math.floor(fv) + 7

        for bp in r["bids"]:
            off = bp - fv
            vol = r["bid_vols"].get(bp, 0)
            if off < -8:
                b1_bid_total += 1
                b1_bid_present += 1
                if bp == b1_bid_exp:
                    b1_bid_match += 1
                b1_bid_vols.append(vol)
            elif off < -4:
                b2_bid_total += 1
                b2_bid_present += 1
                if bp == b2_bid_exp:
                    b2_bid_match += 1
                b2_bid_vols.append(vol)

        for ap in r["asks"]:
            off = ap - fv
            vol = r["ask_vols"].get(ap, 0)
            if off > 8:
                b1_ask_total += 1
                b1_ask_present += 1
                if ap == b1_ask_exp:
                    b1_ask_match += 1
                b1_ask_vols.append(vol)
            elif off > 4:
                b2_ask_total += 1
                b2_ask_present += 1
                if ap == b2_ask_exp:
                    b2_ask_match += 1
                b2_ask_vols.append(vol)

    print(f"\n  Bot 1:")
    if b1_bid_total:
        print(f"    Bid: {b1_bid_match}/{b1_bid_total} ({b1_bid_match/b1_bid_total*100:.1f}%)  ceil(FV)-10")
    if b1_ask_total:
        print(f"    Ask: {b1_ask_match}/{b1_ask_total} ({b1_ask_match/b1_ask_total*100:.1f}%)  floor(FV)+10")
    print(f"    Bid presence: {b1_bid_present}/{n} ({b1_bid_present/n*100:.1f}%)")
    print(f"    Ask presence: {b1_ask_present}/{n} ({b1_ask_present/n*100:.1f}%)")
    if b1_bid_vols:
        vc = Counter(b1_bid_vols)
        print(f"    Bid vol: [{min(b1_bid_vols)},{max(b1_bid_vols)}] mean={statistics.mean(b1_bid_vols):.1f}")

    print(f"\n  Bot 2:")
    if b2_bid_total:
        print(f"    Bid: {b2_bid_match}/{b2_bid_total} ({b2_bid_match/b2_bid_total*100:.1f}%)  ceil(FV)-7")
    if b2_ask_total:
        print(f"    Ask: {b2_ask_match}/{b2_ask_total} ({b2_ask_match/b2_ask_total*100:.1f}%)  floor(FV)+7")
    print(f"    Bid presence: {b2_bid_present}/{n} ({b2_bid_present/n*100:.1f}%)")
    print(f"    Ask presence: {b2_ask_present}/{n} ({b2_ask_present/n*100:.1f}%)")
    if b2_bid_vols:
        print(f"    Bid vol: [{min(b2_bid_vols)},{max(b2_bid_vols)}] mean={statistics.mean(b2_bid_vols):.1f}")


def validate_osmium(day, rows):
    """Validate OSMIUM bot models using mid-price as FV proxy."""
    n = len(rows)
    print(f"\n  ── OSMIUM Day {day} ({n} ticks) ──")

    # Use mid as rough FV proxy
    # Check structural properties: volume ranges, spread distribution
    bbo_spreads = []
    outer_spreads = []
    best_vols = []
    worst_vols = []

    for r in rows:
        if r["bids"] and r["asks"]:
            bbo_spreads.append(min(r["asks"]) - max(r["bids"]))
            outer_spreads.append(max(r["asks"]) - min(r["bids"]))

            # Best level volumes
            bb_vol = r["bid_vols"].get(max(r["bids"]), 0)
            ba_vol = r["ask_vols"].get(min(r["asks"]), 0)
            best_vols.append((bb_vol, ba_vol))

            # Worst level volumes (when 2+ levels)
            if len(r["bids"]) >= 2:
                wb_vol = r["bid_vols"].get(min(r["bids"]), 0)
                wa_vol = r["ask_vols"].get(max(r["asks"]), 0) if len(r["asks"]) >= 2 else None
                if wa_vol is not None:
                    worst_vols.append((wb_vol, wa_vol))

    print(f"\n  BBO spread distribution:")
    sc = Counter(bbo_spreads)
    for s in sorted(sc):
        if sc[s] > 10:
            print(f"    {s:>4}: {sc[s]:>6} ({sc[s]/len(bbo_spreads)*100:.1f}%)")
    if bbo_spreads:
        print(f"    mean={statistics.mean(bbo_spreads):.2f}")

    print(f"\n  Outer spread distribution:")
    oc = Counter(outer_spreads)
    for s in sorted(oc):
        if oc[s] > 10:
            print(f"    {s:>4}: {oc[s]:>6} ({oc[s]/len(outer_spreads)*100:.1f}%)")
    if outer_spreads:
        print(f"    mean={statistics.mean(outer_spreads):.2f}")

    # Volume ranges at best level (should be Bot 2: U(10,15))
    bb = [v[0] for v in best_vols if 0 < v[0] <= 20]
    ba = [v[1] for v in best_vols if 0 < v[1] <= 20]
    if bb:
        print(f"\n  Best bid vol (Bot 2 proxy): [{min(bb)},{max(bb)}] mean={statistics.mean(bb):.1f}")
    if ba:
        print(f"  Best ask vol (Bot 2 proxy): [{min(ba)},{max(ba)}] mean={statistics.mean(ba):.1f}")

    # Volume at worst level when 2+ levels (should be Bot 1: U(20,30))
    if worst_vols:
        wb = [v[0] for v in worst_vols]
        wa = [v[1] for v in worst_vols]
        print(f"\n  Worst bid vol (Bot 1 proxy): [{min(wb)},{max(wb)}] mean={statistics.mean(wb):.1f}")
        print(f"  Worst ask vol (Bot 1 proxy): [{min(wa)},{max(wa)}] mean={statistics.mean(wa):.1f}")
        same = sum(1 for w in worst_vols if w[0] == w[1])
        print(f"  Worst bid=ask vol: {same}/{len(worst_vols)} ({same/len(worst_vols)*100:.1f}%)")

    # Level count distribution
    bid_levels = Counter(len(r["bids"]) for r in rows)
    ask_levels = Counter(len(r["asks"]) for r in rows)
    print(f"\n  Bid levels: {dict(sorted(bid_levels.items()))}")
    print(f"  Ask levels: {dict(sorted(ask_levels.items()))}")


# ═══════════════════════════════════════════════════════════
# Run validation across all 3 days
# ═══════════════════════════════════════════════════════════

print("=" * 80)
print("  CROSS-VALIDATION: PEPPER_ROOT (deterministic FV)")
print("=" * 80)

for day in [-2, -1, 0]:
    data = load_csv(day)
    validate_pepper(day, data["INTARIAN_PEPPER_ROOT"])

print(f"\n\n{'=' * 80}")
print("  CROSS-VALIDATION: OSMIUM (structural consistency)")
print("=" * 80)

for day in [-2, -1, 0]:
    data = load_csv(day)
    validate_osmium(day, data["ASH_COATED_OSMIUM"])
