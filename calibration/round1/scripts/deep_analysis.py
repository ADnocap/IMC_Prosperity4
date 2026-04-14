"""
Deep analysis to resolve remaining questions:
1. OSMIUM Bot 1: is it floor(FV)-10 / ceil(FV)+10, or something else?
2. Presence model: what determines whether a bot quotes on a given tick?
3. PEPPER Bot 1 ask miss: what's happening at the 1 miss?
4. Cross-product pattern: are the bots using the same code with different params?
"""

import json, math, statistics
from pathlib import Path
from collections import Counter, defaultdict
from scipy import stats as sp_stats

DATA_DIR = Path(__file__).parent.parent / "data"

def load(fname):
    with open(DATA_DIR / fname) as f:
        data = json.load(f)
    return [r for r in data["rows"] if r["fv"] is not None]


# ═══════════════════════════════════════════════════════════════
# 1. OSMIUM Bot 1: FV fraction analysis
# ═══════════════════════════════════════════════════════════════

print("=" * 80)
print("  1. OSMIUM BOT 1: FV FRACTION DEEP DIVE")
print("=" * 80)

rows = load("ash_coated_osmium_fv_and_book.json")

# Extract Bot 1 (offset > 9 or < -9)
b1_bid_data = []
b1_ask_data = []
for r in rows:
    fv = r["fv"]
    for bp in r["bids"]:
        off = bp - fv
        if off < -9:
            vol = r["bid_vols"].get(bp, r["bid_vols"].get(str(bp), 0))
            b1_bid_data.append({"fv": fv, "price": bp, "vol": vol, "off": off})
    for ap in r["asks"]:
        off = ap - fv
        if off > 9:
            vol = r["ask_vols"].get(ap, r["ask_vols"].get(str(ap), 0))
            b1_ask_data.append({"fv": fv, "price": ap, "vol": vol, "off": off})

print(f"\n  Bot 1 bid data points: {len(b1_bid_data)}")
print(f"  Bot 1 ask data points: {len(b1_ask_data)}")

# Bid: price - floor(FV) by fine FV fraction
print(f"\n  BID: price - floor(FV) by FV fraction (1/20 bins):")
frac_bid = defaultdict(list)
for d in b1_bid_data:
    frac = round((d["fv"] - math.floor(d["fv"])) * 20) / 20
    if frac >= 1.0: frac = 0.0
    frac_bid[frac].append(d["price"] - math.floor(d["fv"]))

for f in sorted(frac_bid):
    c = Counter(frac_bid[f])
    print(f"  {f:>6.2f} {len(frac_bid[f]):>4} {dict(sorted(c.items()))}")

# Ask: price - floor(FV) by fine FV fraction
print(f"\n  ASK: price - floor(FV) by FV fraction (1/20 bins):")
frac_ask = defaultdict(list)
for d in b1_ask_data:
    frac = round((d["fv"] - math.floor(d["fv"])) * 20) / 20
    if frac >= 1.0: frac = 0.0
    frac_ask[frac].append(d["price"] - math.floor(d["fv"]))

for f in sorted(frac_ask):
    c = Counter(frac_ask[f])
    print(f"  {f:>6.2f} {len(frac_ask[f]):>4} {dict(sorted(c.items()))}")

# Test: bid = floor(FV) - 10 misses
print(f"\n  BID misses for floor(FV) - 10:")
for d in b1_bid_data:
    pred = math.floor(d["fv"]) - 10
    if pred != d["price"]:
        frac = d["fv"] - math.floor(d["fv"])
        print(f"    fv={d['fv']:.6f} frac={frac:.6f} actual={d['price']} predicted={pred} err={d['price']-pred:+d}")

# Test: ask = ceil(FV) + 10 misses
print(f"\n  ASK misses for ceil(FV) + 10:")
for d in b1_ask_data:
    pred = math.ceil(d["fv"]) + 10
    if pred != d["price"]:
        frac = d["fv"] - math.floor(d["fv"])
        print(f"    fv={d['fv']:.6f} frac={frac:.6f} actual={d['price']} predicted={pred} err={d['price']-pred:+d}")

# Also test: bid = ceil(FV) - 11
print(f"\n  BID misses for ceil(FV) - 11:")
for d in b1_bid_data:
    pred = math.ceil(d["fv"]) - 11
    if pred != d["price"]:
        frac = d["fv"] - math.floor(d["fv"])
        print(f"    fv={d['fv']:.6f} frac={frac:.6f} actual={d['price']} predicted={pred} err={d['price']-pred:+d}")


# ═══════════════════════════════════════════════════════════════
# 2. PRESENCE ANALYSIS: both products
# ═══════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  2. PRESENCE PATTERN ANALYSIS")
print("=" * 80)

for name, fname in [("OSMIUM", "ash_coated_osmium_fv_and_book.json"),
                     ("PEPPER", "intarian_pepper_root_fv_and_book.json")]:
    rows = load(fname)
    n = len(rows)

    # Determine thresholds based on product
    if "osmium" in fname:
        b1_thresh, b2_lo, b2_hi = 9, 5, 9
    else:
        b1_thresh, b2_lo, b2_hi = 8, 4, 8

    print(f"\n  ── {name} ──")

    # Per-side presence
    b1_bid_present = []
    b1_ask_present = []
    b2_bid_present = []
    b2_ask_present = []

    for r in rows:
        fv = r["fv"]
        b1b = any(bp - fv < -b1_thresh for bp in r["bids"])
        b1a = any(ap - fv > b1_thresh for ap in r["asks"])
        b2b = any(-b2_hi < bp - fv < -b2_lo for bp in r["bids"])
        b2a = any(b2_lo < ap - fv < b2_hi for ap in r["asks"])
        b1_bid_present.append(b1b)
        b1_ask_present.append(b1a)
        b2_bid_present.append(b2b)
        b2_ask_present.append(b2a)

    # Presence rates
    rates = {
        "B1_bid": sum(b1_bid_present) / n,
        "B1_ask": sum(b1_ask_present) / n,
        "B2_bid": sum(b2_bid_present) / n,
        "B2_ask": sum(b2_ask_present) / n,
    }
    for k, v in rates.items():
        se = math.sqrt(v * (1-v) / n)
        print(f"    {k}: {v:.4f} ± {se:.4f} ({sum([b1_bid_present, b1_ask_present, b2_bid_present, b2_ask_present][[*rates.keys()].index(k)])})")

    # Are bid and ask of same bot independent?
    for bot_name, bid_p, ask_p in [("Bot1", b1_bid_present, b1_ask_present),
                                     ("Bot2", b2_bid_present, b2_ask_present)]:
        both = sum(b and a for b, a in zip(bid_p, ask_p))
        p_bid = sum(bid_p) / n
        p_ask = sum(ask_p) / n
        p_both_actual = both / n
        p_both_expected = p_bid * p_ask
        # Chi-squared 2x2 independence test
        observed = [[both, sum(bid_p) - both],
                     [sum(ask_p) - both, n - sum(bid_p) - sum(ask_p) + both]]
        chi2, p, dof, expected = sp_stats.chi2_contingency(observed)
        print(f"    {bot_name} bid/ask independence: actual_both={p_both_actual:.4f} expected={p_both_expected:.4f} χ²={chi2:.2f} p={p:.4f}")

    # Are Bot1 and Bot2 presence independent?
    b1_both = [b and a for b, a in zip(b1_bid_present, b1_ask_present)]
    b2_both = [b and a for b, a in zip(b2_bid_present, b2_ask_present)]
    joint = sum(b1 and b2 for b1, b2 in zip(b1_both, b2_both))
    p_b1 = sum(b1_both) / n
    p_b2 = sum(b2_both) / n
    observed = [[joint, sum(b1_both) - joint],
                 [sum(b2_both) - joint, n - sum(b1_both) - sum(b2_both) + joint]]
    chi2, p, dof, expected = sp_stats.chi2_contingency(observed)
    print(f"    Bot1/Bot2 independence: actual_joint={joint/n:.4f} expected={p_b1*p_b2:.4f} χ²={chi2:.2f} p={p:.4f}")

    # Autocorrelation of presence (run length)
    for bot_name, present_flags in [("Bot1_bid", b1_bid_present),
                                      ("Bot2_bid", b2_bid_present)]:
        # lag-1 autocorrelation
        pairs = [(1 if present_flags[i] else 0, 1 if present_flags[i+1] else 0) for i in range(n-1)]
        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        corr, p_corr = sp_stats.pearsonr(x, y)
        print(f"    {bot_name} lag-1 autocorrelation: r={corr:.4f} p={p_corr:.6f}")

    # Run length distribution
    for bot_name, present_flags in [("Bot1_bid", b1_bid_present),
                                      ("Bot2_bid", b2_bid_present)]:
        present_runs = []
        absent_runs = []
        cur = present_flags[0]
        rl = 1
        for i in range(1, n):
            if present_flags[i] == cur:
                rl += 1
            else:
                if cur:
                    present_runs.append(rl)
                else:
                    absent_runs.append(rl)
                cur = present_flags[i]
                rl = 1
        if cur:
            present_runs.append(rl)
        else:
            absent_runs.append(rl)

        print(f"\n    {bot_name} present runs: n={len(present_runs)}")
        if present_runs:
            print(f"      mean={statistics.mean(present_runs):.1f}  min={min(present_runs)}  max={max(present_runs)}")
            rc = Counter(present_runs)
            # Expected geometric distribution with p=0.2 (if 80% presence, 20% absence)
            for rl_val in sorted(rc)[:10]:
                pct = rc[rl_val] / len(present_runs) * 100
                print(f"      len={rl_val:>3}: {rc[rl_val]:>4} ({pct:>5.1f}%)")

        print(f"    {bot_name} absent runs: n={len(absent_runs)}")
        if absent_runs:
            print(f"      mean={statistics.mean(absent_runs):.1f}  min={min(absent_runs)}  max={max(absent_runs)}")
            rc = Counter(absent_runs)
            for rl_val in sorted(rc)[:10]:
                pct = rc[rl_val] / len(absent_runs) * 100
                print(f"      len={rl_val:>3}: {rc[rl_val]:>4} ({pct:>5.1f}%)")


# ═══════════════════════════════════════════════════════════════
# 3. PEPPER Bot 1 ask miss
# ═══════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  3. PEPPER BOT 1 ASK MISS DETAIL")
print("=" * 80)

rows = load("intarian_pepper_root_fv_and_book.json")
for r in rows:
    fv = r["fv"]
    for ap in r["asks"]:
        off = ap - fv
        if off > 8:
            pred = math.floor(fv) + 10
            if pred != ap:
                print(f"  ts={r['ts']} fv={fv:.6f} frac={fv-math.floor(fv):.6f} ask={ap} pred={pred} err={ap-pred:+d}")

# Also PEPPER Bot 2 ask miss
print(f"\n  PEPPER BOT 2 ASK MISS:")
for r in rows:
    fv = r["fv"]
    for ap in r["asks"]:
        off = ap - fv
        if 4 < off < 8:
            pred = math.floor(fv) + 7
            if pred != ap:
                print(f"  ts={r['ts']} fv={fv:.6f} frac={fv-math.floor(fv):.6f} ask={ap} pred={pred} err={ap-pred:+d}")


# ═══════════════════════════════════════════════════════════════
# 4. CROSS-PRODUCT COMPARISON
# ═══════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  4. CROSS-PRODUCT COMPARISON SUMMARY")
print("=" * 80)

print("""
  ┌─────────────────────┬──────────────────────────────┬──────────────────────────────┐
  │                     │ ASH_COATED_OSMIUM            │ INTARIAN_PEPPER_ROOT         │
  ├─────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ FV process          │ RW, σ=0.312                  │ Deterministic +0.1/tick      │
  │ FV start            │ ~10002                       │ ~12000                       │
  │ FV quantization     │ 1/2048                       │ 1/2048                       │
  ├─────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Bot 1 bid           │ floor(FV) - 10               │ ceil(FV) - 10                │
  │ Bot 1 ask           │ ceil(FV) + 10                │ floor(FV) + 10               │
  │ Bot 1 vol           │ U(20,30)                     │ U(15,25)                     │
  │ Bot 1 spread        │ 21 (non-int), 20 (int)       │ 19 (non-int), 20 (int)       │
  ├─────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Bot 2 bid           │ round(FV) - 8                │ ceil(FV) - 7                 │
  │ Bot 2 ask           │ round(FV) + 8                │ floor(FV) + 7                │
  │ Bot 2 vol           │ U(10,15)                     │ U(8,12)                      │
  │ Bot 2 spread        │ 16 (normal), 15/17 (bnd)     │ 13 (non-int), 14 (int)       │
  ├─────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Bot 3 rate          │ 7.6%                         │ 4.7%                         │
  │ Bot 3 pattern       │ Single-sided, near FV        │ Single-sided, near FV        │
  │ Per-side presence   │ ~80%                         │ ~80%                         │
  └─────────────────────┴──────────────────────────────┴──────────────────────────────┘
""")
