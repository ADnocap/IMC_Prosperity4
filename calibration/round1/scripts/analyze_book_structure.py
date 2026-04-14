"""
Analyze order book structure for both Round 1 products.
Identify bot layers by offset from FV, volume distributions, and presence patterns.
Following the calibration philosophy: condition on everything, never look at marginals.
"""

import json, math, statistics
from pathlib import Path
from collections import Counter, defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"


def analyze_product(name, fname):
    with open(DATA_DIR / fname) as f:
        data = json.load(f)

    rows = [r for r in data["rows"] if r["fv"] is not None]
    n = len(rows)

    print(f"\n{'=' * 80}")
    print(f"  ORDER BOOK STRUCTURE: {name}")
    print(f"{'=' * 80}")

    # ── Step 1: Catalog all levels by offset from FV ──
    all_bid_offsets = []
    all_ask_offsets = []
    bid_level_counts = Counter()
    ask_level_counts = Counter()

    for r in rows:
        fv = r["fv"]
        bid_level_counts[len(r["bids"])] += 1
        ask_level_counts[len(r["asks"])] += 1
        for bp in r["bids"]:
            all_bid_offsets.append(bp - fv)
        for ap in r["asks"]:
            all_ask_offsets.append(ap - fv)

    print(f"\n  Number of bid levels per tick:")
    for k in sorted(bid_level_counts):
        print(f"    {k} levels: {bid_level_counts[k]:>5} ({bid_level_counts[k]/n*100:.1f}%)")
    print(f"\n  Number of ask levels per tick:")
    for k in sorted(ask_level_counts):
        print(f"    {k} levels: {ask_level_counts[k]:>5} ({ask_level_counts[k]/n*100:.1f}%)")

    # ── Step 2: Offset histogram to identify clusters ──
    print(f"\n  {'─' * 70}")
    print(f"  BID OFFSET HISTOGRAM (binned to 0.5)")
    bid_hist = Counter(round(o * 2) / 2 for o in all_bid_offsets)
    for b in sorted(bid_hist):
        if bid_hist[b] > 3:
            bar = '#' * min(50, int(bid_hist[b] / n * 100))
            print(f"    {b:>+7.1f}: {bid_hist[b]:>5} ({bid_hist[b]/len(all_bid_offsets)*100:>5.1f}%) {bar}")

    print(f"\n  ASK OFFSET HISTOGRAM (binned to 0.5)")
    ask_hist = Counter(round(o * 2) / 2 for o in all_ask_offsets)
    for b in sorted(ask_hist):
        if ask_hist[b] > 3:
            bar = '#' * min(50, int(ask_hist[b] / n * 100))
            print(f"    {b:>+7.1f}: {ask_hist[b]:>5} ({ask_hist[b]/len(all_ask_offsets)*100:>5.1f}%) {bar}")

    # ── Step 3: Per-level analysis (separate the layers) ──
    # For each tick, categorize each level by its offset range
    print(f"\n  {'─' * 70}")
    print(f"  PER-TICK LEVEL ANALYSIS")

    for r in rows[:5]:
        fv = r["fv"]
        print(f"\n  ts={r['ts']:>6} fv={fv:.4f}")
        for bp in sorted(r["bids"], reverse=True):
            vol = r["bid_vols"].get(bp, r["bid_vols"].get(str(bp), 0))
            print(f"    BID {bp:>7} (off={bp-fv:>+8.4f}) vol={vol}")
        for ap in sorted(r["asks"]):
            vol = r["ask_vols"].get(ap, r["ask_vols"].get(str(ap), 0))
            print(f"    ASK {ap:>7} (off={ap-fv:>+8.4f}) vol={vol}")

    # ── Step 4: Identify layers by offset clustering ──
    # Collect (offset, volume) for each level
    print(f"\n  {'─' * 70}")
    print(f"  LAYER IDENTIFICATION")

    # Group offsets into coarse bins and check volume per bin
    bid_by_offset = defaultdict(list)  # offset_bin -> [(vol, fv_frac)]
    ask_by_offset = defaultdict(list)

    for r in rows:
        fv = r["fv"]
        for bp in r["bids"]:
            off = bp - fv
            vol = r["bid_vols"].get(bp, r["bid_vols"].get(str(bp), 0))
            bid_by_offset[round(off)].append((vol, fv - math.floor(fv)))
        for ap in r["asks"]:
            off = ap - fv
            vol = r["ask_vols"].get(ap, r["ask_vols"].get(str(ap), 0))
            ask_by_offset[round(off)].append((vol, fv - math.floor(fv)))

    print(f"\n  BID levels by integer offset:")
    print(f"  {'offset':>7} {'count':>6} {'freq%':>6} {'vol_min':>8} {'vol_max':>8} {'vol_mean':>9} {'vol_dist':>30}")
    for off in sorted(bid_by_offset):
        entries = bid_by_offset[off]
        vols = [e[0] for e in entries]
        vc = Counter(vols)
        top3 = vc.most_common(3)
        dist_str = ", ".join(f"{v}:{c}" for v, c in top3)
        freq = len(entries) / n * 100
        print(f"  {off:>+7} {len(entries):>6} {freq:>5.1f}% {min(vols):>8} {max(vols):>8} {statistics.mean(vols):>9.1f} {dist_str:>30}")

    print(f"\n  ASK levels by integer offset:")
    print(f"  {'offset':>7} {'count':>6} {'freq%':>6} {'vol_min':>8} {'vol_max':>8} {'vol_mean':>9} {'vol_dist':>30}")
    for off in sorted(ask_by_offset):
        entries = ask_by_offset[off]
        vols = [e[0] for e in entries]
        vc = Counter(vols)
        top3 = vc.most_common(3)
        dist_str = ", ".join(f"{v}:{c}" for v, c in top3)
        freq = len(entries) / n * 100
        print(f"  {off:>+7} {len(entries):>6} {freq:>5.1f}% {min(vols):>8} {max(vols):>8} {statistics.mean(vols):>9.1f} {dist_str:>30}")

    # ── Step 5: Cross-side volume correlation ──
    print(f"\n  {'─' * 70}")
    print(f"  CROSS-LEVEL VOLUME CORRELATION")

    # For each tick, check if bid and ask volumes at equivalent layers match
    # First: worst (deepest) level
    worst_same = 0
    best_same = 0
    worst_n = 0
    best_n = 0

    for r in rows:
        if r["bids"] and r["asks"]:
            worst_bid = min(r["bids"])
            worst_ask = max(r["asks"])
            wb_vol = r["bid_vols"].get(worst_bid, r["bid_vols"].get(str(worst_bid), 0))
            wa_vol = r["ask_vols"].get(worst_ask, r["ask_vols"].get(str(worst_ask), 0))
            worst_n += 1
            if wb_vol == wa_vol:
                worst_same += 1

            best_bid = max(r["bids"])
            best_ask = min(r["asks"])
            bb_vol = r["bid_vols"].get(best_bid, r["bid_vols"].get(str(best_bid), 0))
            ba_vol = r["ask_vols"].get(best_ask, r["ask_vols"].get(str(best_ask), 0))
            best_n += 1
            if bb_vol == ba_vol:
                best_same += 1

    if worst_n > 0:
        print(f"  Deepest level: bid_vol == ask_vol? {worst_same}/{worst_n} ({worst_same/worst_n*100:.1f}%)")
    if best_n > 0:
        print(f"  Best level:    bid_vol == ask_vol? {best_same}/{best_n} ({best_same/best_n*100:.1f}%)")

    # When 2+ levels on each side, check layer-specific correlation
    multi_level = [(r, len(r["bids"]), len(r["asks"])) for r in rows if len(r["bids"]) >= 2 and len(r["asks"]) >= 2]
    if multi_level:
        layer1_same = 0
        layer2_same = 0
        cross_same = 0
        ml_n = len(multi_level)
        for r, nb, na in multi_level:
            # Layer 1 = deepest, Layer 2 = best
            worst_bid = min(r["bids"])
            worst_ask = max(r["asks"])
            best_bid = max(r["bids"])
            best_ask = min(r["asks"])

            wbv = r["bid_vols"].get(worst_bid, r["bid_vols"].get(str(worst_bid), 0))
            wav = r["ask_vols"].get(worst_ask, r["ask_vols"].get(str(worst_ask), 0))
            bbv = r["bid_vols"].get(best_bid, r["bid_vols"].get(str(best_bid), 0))
            bav = r["ask_vols"].get(best_ask, r["ask_vols"].get(str(best_ask), 0))

            if wbv == wav:
                layer1_same += 1
            if bbv == bav:
                layer2_same += 1
            if wbv == bbv:
                cross_same += 1

        print(f"\n  When 2+ levels on each side (n={ml_n}):")
        print(f"    Deepest bid_vol == deepest ask_vol: {layer1_same}/{ml_n} ({layer1_same/ml_n*100:.1f}%)")
        print(f"    Best bid_vol == best ask_vol:       {layer2_same}/{ml_n} ({layer2_same/ml_n*100:.1f}%)")
        print(f"    Deepest bid_vol == best bid_vol:    {cross_same}/{ml_n} ({cross_same/ml_n*100:.1f}%)")

    # ── Step 6: Spread analysis ──
    print(f"\n  {'─' * 70}")
    print(f"  SPREAD ANALYSIS")

    bbo_spreads = []
    outer_spreads = []
    for r in rows:
        if r["bids"] and r["asks"]:
            bbo_spreads.append(min(r["asks"]) - max(r["bids"]))
            outer_spreads.append(max(r["asks"]) - min(r["bids"]))

    print(f"\n  BBO spread (best ask - best bid):")
    sc = Counter(bbo_spreads)
    for s in sorted(sc):
        print(f"    {s:>4}: {sc[s]:>5} ({sc[s]/len(bbo_spreads)*100:.1f}%)")
    print(f"    mean={statistics.mean(bbo_spreads):.2f}")

    print(f"\n  Outer spread (worst ask - worst bid):")
    oc = Counter(outer_spreads)
    for s in sorted(oc):
        if oc[s] > 2:
            print(f"    {s:>4}: {oc[s]:>5} ({oc[s]/len(outer_spreads)*100:.1f}%)")
    print(f"    mean={statistics.mean(outer_spreads):.2f}")


analyze_product("ASH_COATED_OSMIUM", "ash_coated_osmium_fv_and_book.json")
analyze_product("INTARIAN_PEPPER_ROOT", "intarian_pepper_root_fv_and_book.json")
