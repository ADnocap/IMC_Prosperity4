"""
Full calibration of ASH_COATED_OSMIUM bot quoting rules.

Structure from initial analysis:
  - Bot 1 (outer wall): offset ≈ ±10-11 from FV, vol 20-30
  - Bot 2 (inner wall): offset ≈ ±8 from FV, vol 10-15
  - Bot 3 (noise): offset ≈ 0-3 from FV, very rare

Methodology: brute-force formula search, then statistical validation.
"""

import json, math, statistics
from pathlib import Path
from collections import Counter, defaultdict
from scipy import stats as sp_stats

DATA = Path(__file__).parent.parent / "data" / "ash_coated_osmium_fv_and_book.json"
with open(DATA) as f:
    data = json.load(f)

rows = [r for r in data["rows"] if r["fv"] is not None]
n = len(rows)

# ═════════════════════════════════════════════════════════════════════
# HELPER: extract bot layers from each tick
# ═════════════════════════════════════════════════════════════════════

def get_layers(r):
    """Separate order book into Bot 1 (outer), Bot 2 (inner), Bot 3 (noise)."""
    fv = r["fv"]
    layers = {"b1_bids": [], "b1_asks": [], "b2_bids": [], "b2_asks": [],
              "b3_bids": [], "b3_asks": []}

    for bp in r["bids"]:
        off = bp - fv
        vol = r["bid_vols"].get(bp, r["bid_vols"].get(str(bp), 0))
        if off < -9:
            layers["b1_bids"].append((bp, vol, off))
        elif off < -5:
            layers["b2_bids"].append((bp, vol, off))
        else:
            layers["b3_bids"].append((bp, vol, off))

    for ap in r["asks"]:
        off = ap - fv
        vol = r["ask_vols"].get(ap, r["ask_vols"].get(str(ap), 0))
        if off > 9:
            layers["b1_asks"].append((ap, vol, off))
        elif off > 5:
            layers["b2_asks"].append((ap, vol, off))
        else:
            layers["b3_asks"].append((ap, vol, off))

    return layers


# ═════════════════════════════════════════════════════════════════════
# BOT 1 CALIBRATION (OUTER WALL)
# ═════════════════════════════════════════════════════════════════════

print("=" * 80)
print("  BOT 1 (OUTER WALL) CALIBRATION — ASH_COATED_OSMIUM")
print("=" * 80)

b1_records = []
for r in rows:
    L = get_layers(r)
    b1_bid = L["b1_bids"][0] if L["b1_bids"] else None
    b1_ask = L["b1_asks"][0] if L["b1_asks"] else None
    b1_records.append({
        "fv": r["fv"], "ts": r["ts"],
        "bid": b1_bid, "ask": b1_ask,
        "both": b1_bid is not None and b1_ask is not None
    })

b1_present = sum(1 for r in b1_records if r["both"])
b1_bid_only = sum(1 for r in b1_records if r["bid"] is not None and r["ask"] is None)
b1_ask_only = sum(1 for r in b1_records if r["bid"] is None and r["ask"] is not None)
b1_absent = sum(1 for r in b1_records if r["bid"] is None and r["ask"] is None)

print(f"\n  Presence:")
print(f"    Both sides:  {b1_present}/{n} ({b1_present/n*100:.1f}%)")
print(f"    Bid only:    {b1_bid_only}/{n} ({b1_bid_only/n*100:.1f}%)")
print(f"    Ask only:    {b1_ask_only}/{n} ({b1_ask_only/n*100:.1f}%)")
print(f"    Absent:      {b1_absent}/{n} ({b1_absent/n*100:.1f}%)")

# ── Brute-force formula search for Bot 1 ──
print(f"\n  {'─' * 70}")
print(f"  BRUTE-FORCE FORMULA SEARCH (Bot 1)")

b1_with_bid = [(r["fv"], r["bid"][0]) for r in b1_records if r["bid"]]
b1_with_ask = [(r["fv"], r["ask"][0]) for r in b1_records if r["ask"]]

best_bid = (0, "", 0)
best_ask = (0, "", 0)

for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(-14, -7):
            matches = sum(1 for fv, actual in b1_with_bid if rnd_func(fv + shift) + offset == actual)
            if matches > best_bid[0]:
                best_bid = (matches, f"{rnd_name}(FV + {shift}) + {offset}", offset)
        for offset in range(7, 15):
            matches = sum(1 for fv, actual in b1_with_ask if rnd_func(fv + shift) + offset == actual)
            if matches > best_ask[0]:
                best_ask = (matches, f"{rnd_name}(FV + {shift}) + {offset}", offset)

nb = len(b1_with_bid)
na = len(b1_with_ask)
print(f"\n  Best BID formula: {best_bid[1]}")
print(f"    Match: {best_bid[0]}/{nb} ({best_bid[0]/nb*100:.1f}%)")
print(f"  Best ASK formula: {best_ask[1]}")
print(f"    Match: {best_ask[0]}/{na} ({best_ask[0]/na*100:.1f}%)")

# ── Check top 5 formulas for each ──
print(f"\n  Top BID formulas:")
results = []
for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(-14, -7):
            matches = sum(1 for fv, actual in b1_with_bid if rnd_func(fv + shift) + offset == actual)
            results.append((matches, f"{rnd_name}(FV + {shift}) + {offset}"))
results.sort(reverse=True)
for m, f in results[:8]:
    print(f"    {f:<35} {m}/{nb} ({m/nb*100:.1f}%)")

print(f"\n  Top ASK formulas:")
results = []
for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(7, 15):
            matches = sum(1 for fv, actual in b1_with_ask if rnd_func(fv + shift) + offset == actual)
            results.append((matches, f"{rnd_name}(FV + {shift}) + {offset}"))
results.sort(reverse=True)
for m, f in results[:8]:
    print(f"    {f:<35} {m}/{na} ({m/na*100:.1f}%)")

# ── Miss analysis ──
print(f"\n  {'─' * 70}")
print(f"  MISS ANALYSIS (Bot 1)")

# Use the best formula: parse it
# Let's just hardcode the check for the top formula and show misses
bid_misses = []
ask_misses = []

for fv, actual in b1_with_bid:
    predicted = round(fv) - 11  # assuming best is round(FV) - 11
    if predicted != actual:
        bid_misses.append((fv, actual, predicted, actual - predicted))

for fv, actual in b1_with_ask:
    predicted = round(fv) + 11
    if predicted != actual:
        ask_misses.append((fv, actual, predicted, actual - predicted))

print(f"\n  Bid misses (round(FV)-11): {len(bid_misses)}/{nb}")
if bid_misses:
    err_dist = Counter(m[3] for m in bid_misses)
    print(f"    Error distribution: {dict(err_dist)}")
    print(f"    FV fractions at misses:")
    frac_at_miss = [m[0] - math.floor(m[0]) for m in bid_misses]
    print(f"      mean={statistics.mean(frac_at_miss):.4f}  min={min(frac_at_miss):.4f}  max={max(frac_at_miss):.4f}")
    # Check if misses cluster near 0.5
    near_half = sum(1 for f in frac_at_miss if abs(f - 0.5) < 0.05)
    print(f"      Near 0.5 boundary: {near_half}/{len(frac_at_miss)}")

print(f"\n  Ask misses (round(FV)+11): {len(ask_misses)}/{na}")
if ask_misses:
    err_dist = Counter(m[3] for m in ask_misses)
    print(f"    Error distribution: {dict(err_dist)}")
    frac_at_miss = [m[0] - math.floor(m[0]) for m in ask_misses]
    print(f"      mean={statistics.mean(frac_at_miss):.4f}  min={min(frac_at_miss):.4f}  max={max(frac_at_miss):.4f}")
    near_half = sum(1 for f in frac_at_miss if abs(f - 0.5) < 0.05)
    print(f"      Near 0.5 boundary: {near_half}/{len(frac_at_miss)}")

# ── Volume analysis ──
print(f"\n  {'─' * 70}")
print(f"  VOLUME ANALYSIS (Bot 1)")

b1_bid_vols = [r["bid"][1] for r in b1_records if r["bid"]]
b1_ask_vols = [r["ask"][1] for r in b1_records if r["ask"]]

print(f"\n  Bid volumes: min={min(b1_bid_vols)} max={max(b1_bid_vols)} mean={statistics.mean(b1_bid_vols):.1f}")
print(f"  Ask volumes: min={min(b1_ask_vols)} max={max(b1_ask_vols)} mean={statistics.mean(b1_ask_vols):.1f}")

# Uniformity test
vc = Counter(b1_bid_vols)
vol_range = list(range(min(b1_bid_vols), max(b1_bid_vols) + 1))
expected = len(b1_bid_vols) / len(vol_range)
chi2_bid = sum((vc.get(v, 0) - expected) ** 2 / expected for v in vol_range)
df = len(vol_range) - 1
p_bid = 1 - sp_stats.chi2.cdf(chi2_bid, df)
print(f"\n  Bid vol chi-squared (uniform [{min(b1_bid_vols)},{max(b1_bid_vols)}]): χ²={chi2_bid:.2f}, df={df}, p={p_bid:.4f}")
print(f"    Uniform? {'YES' if p_bid > 0.05 else 'NO'}")

print(f"\n  Bid vol distribution:")
for v in vol_range:
    c = vc.get(v, 0)
    pct = c / len(b1_bid_vols) * 100
    print(f"    {v:>3}: {c:>4} ({pct:>5.1f}%)")

vc_a = Counter(b1_ask_vols)
expected_a = len(b1_ask_vols) / len(vol_range)
chi2_ask = sum((vc_a.get(v, 0) - expected_a) ** 2 / expected_a for v in vol_range)
p_ask = 1 - sp_stats.chi2.cdf(chi2_ask, df)
print(f"\n  Ask vol chi-squared (uniform [{min(b1_ask_vols)},{max(b1_ask_vols)}]): χ²={chi2_ask:.2f}, df={df}, p={p_ask:.4f}")
print(f"    Uniform? {'YES' if p_ask > 0.05 else 'NO'}")

# Same-tick bid/ask vol correlation
same_vol = sum(1 for r in b1_records if r["both"] and r["bid"][1] == r["ask"][1])
print(f"\n  Same bid/ask volume on same tick: {same_vol}/{b1_present} ({same_vol/b1_present*100:.1f}%)")

# Volume independence from FV
print(f"\n  Volume vs FV fraction (independence check):")
vol_by_frac = defaultdict(list)
for r in b1_records:
    if r["bid"]:
        frac = round((r["fv"] - math.floor(r["fv"])) * 10) / 10
        vol_by_frac[frac].append(r["bid"][1])

for f in sorted(vol_by_frac):
    vs = vol_by_frac[f]
    print(f"    frac={f:.1f}: mean={statistics.mean(vs):.1f} std={statistics.stdev(vs) if len(vs)>1 else 0:.1f} n={len(vs)}")


# ═════════════════════════════════════════════════════════════════════
# BOT 2 CALIBRATION (INNER WALL)
# ═════════════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  BOT 2 (INNER WALL) CALIBRATION — ASH_COATED_OSMIUM")
print("=" * 80)

b2_records = []
for r in rows:
    L = get_layers(r)
    b2_bid = L["b2_bids"][0] if L["b2_bids"] else None
    b2_ask = L["b2_asks"][0] if L["b2_asks"] else None
    b2_records.append({
        "fv": r["fv"], "ts": r["ts"],
        "bid": b2_bid, "ask": b2_ask,
        "both": b2_bid is not None and b2_ask is not None
    })

b2_present = sum(1 for r in b2_records if r["both"])
b2_bid_only = sum(1 for r in b2_records if r["bid"] is not None and r["ask"] is None)
b2_ask_only = sum(1 for r in b2_records if r["bid"] is None and r["ask"] is not None)
b2_absent = sum(1 for r in b2_records if r["bid"] is None and r["ask"] is None)

print(f"\n  Presence:")
print(f"    Both sides:  {b2_present}/{n} ({b2_present/n*100:.1f}%)")
print(f"    Bid only:    {b2_bid_only}/{n} ({b2_bid_only/n*100:.1f}%)")
print(f"    Ask only:    {b2_ask_only}/{n} ({b2_ask_only/n*100:.1f}%)")
print(f"    Absent:      {b2_absent}/{n} ({b2_absent/n*100:.1f}%)")

# ── Brute-force formula search for Bot 2 ──
print(f"\n  {'─' * 70}")
print(f"  BRUTE-FORCE FORMULA SEARCH (Bot 2)")

b2_with_bid = [(r["fv"], r["bid"][0]) for r in b2_records if r["bid"]]
b2_with_ask = [(r["fv"], r["ask"][0]) for r in b2_records if r["ask"]]

# Search over more formulas, including asymmetric rounding (like TOMATOES Bot 2)
best_bid = (0, "")
best_ask = (0, "")

for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(-10, -5):
            matches = sum(1 for fv, actual in b2_with_bid if rnd_func(fv + shift) + offset == actual)
            if matches > best_bid[0]:
                best_bid = (matches, f"{rnd_name}(FV + {shift}) + {offset}")
        for offset in range(5, 11):
            matches = sum(1 for fv, actual in b2_with_ask if rnd_func(fv + shift) + offset == actual)
            if matches > best_ask[0]:
                best_ask = (matches, f"{rnd_name}(FV + {shift}) + {offset}")

nb2 = len(b2_with_bid)
na2 = len(b2_with_ask)
print(f"\n  Best BID formula: {best_bid[1]}")
print(f"    Match: {best_bid[0]}/{nb2} ({best_bid[0]/nb2*100:.1f}%)")
print(f"  Best ASK formula: {best_ask[1]}")
print(f"    Match: {best_ask[0]}/{na2} ({best_ask[0]/na2*100:.1f}%)")

# Top 8 formulas
print(f"\n  Top BID formulas:")
results = []
for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(-10, -5):
            matches = sum(1 for fv, actual in b2_with_bid if rnd_func(fv + shift) + offset == actual)
            results.append((matches, f"{rnd_name}(FV + {shift}) + {offset}"))
results.sort(reverse=True)
for m, f in results[:8]:
    print(f"    {f:<35} {m}/{nb2} ({m/nb2*100:.1f}%)")

print(f"\n  Top ASK formulas:")
results = []
for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil), ("round", round)]:
    for shift in [x * 0.25 for x in range(-4, 5)]:
        for offset in range(5, 11):
            matches = sum(1 for fv, actual in b2_with_ask if rnd_func(fv + shift) + offset == actual)
            results.append((matches, f"{rnd_name}(FV + {shift}) + {offset}"))
results.sort(reverse=True)
for m, f in results[:8]:
    print(f"    {f:<35} {m}/{na2} ({m/na2*100:.1f}%)")

# ── Offset vs FV fraction (to detect asymmetric rounding) ──
print(f"\n  {'─' * 70}")
print(f"  OFFSET vs FV FRACTIONAL PART (Bot 2)")

frac_bid = defaultdict(list)
frac_ask = defaultdict(list)
for r in b2_records:
    frac = round((r["fv"] - math.floor(r["fv"])) * 20) / 20
    if frac >= 1.0:
        frac = 0.0
    if r["bid"]:
        frac_bid[frac].append(r["bid"][0] - math.floor(r["fv"]))
    if r["ask"]:
        frac_ask[frac].append(r["ask"][0] - math.floor(r["fv"]))

print(f"\n  Bid price - floor(FV) by FV fraction:")
print(f"  {'frac':>6} {'n':>4} {'values (Counter)'}")
for f in sorted(frac_bid):
    c = Counter(frac_bid[f])
    print(f"  {f:>6.2f} {len(frac_bid[f]):>4} {dict(sorted(c.items()))}")

print(f"\n  Ask price - floor(FV) by FV fraction:")
print(f"  {'frac':>6} {'n':>4} {'values (Counter)'}")
for f in sorted(frac_ask):
    c = Counter(frac_ask[f])
    print(f"  {f:>6.2f} {len(frac_ask[f]):>4} {dict(sorted(c.items()))}")

# ── Volume analysis ──
print(f"\n  {'─' * 70}")
print(f"  VOLUME ANALYSIS (Bot 2)")

b2_bid_vols = [r["bid"][1] for r in b2_records if r["bid"]]
b2_ask_vols = [r["ask"][1] for r in b2_records if r["ask"]]

print(f"\n  Bid volumes: min={min(b2_bid_vols)} max={max(b2_bid_vols)} mean={statistics.mean(b2_bid_vols):.1f}")
print(f"  Ask volumes: min={min(b2_ask_vols)} max={max(b2_ask_vols)} mean={statistics.mean(b2_ask_vols):.1f}")

vc2 = Counter(b2_bid_vols)
vol_range2 = list(range(min(b2_bid_vols), max(b2_bid_vols) + 1))
expected2 = len(b2_bid_vols) / len(vol_range2)
chi2_b2 = sum((vc2.get(v, 0) - expected2) ** 2 / expected2 for v in vol_range2)
df2 = len(vol_range2) - 1
p_b2 = 1 - sp_stats.chi2.cdf(chi2_b2, df2)
print(f"\n  Bid vol chi-squared (uniform [{min(b2_bid_vols)},{max(b2_bid_vols)}]): χ²={chi2_b2:.2f}, df={df2}, p={p_b2:.4f}")
print(f"    Uniform? {'YES' if p_b2 > 0.05 else 'NO'}")

print(f"\n  Bid vol distribution:")
for v in vol_range2:
    c = vc2.get(v, 0)
    print(f"    {v:>3}: {c:>4} ({c/len(b2_bid_vols)*100:>5.1f}%)")

same_b2 = sum(1 for r in b2_records if r["both"] and r["bid"][1] == r["ask"][1])
print(f"\n  Same bid/ask volume on same tick: {same_b2}/{b2_present} ({same_b2/b2_present*100:.1f}%)")


# ═════════════════════════════════════════════════════════════════════
# BOT 3 CALIBRATION (NOISE)
# ═════════════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  BOT 3 (NOISE) CALIBRATION — ASH_COATED_OSMIUM")
print("=" * 80)

b3_events = []
for r in rows:
    L = get_layers(r)
    has_bid = len(L["b3_bids"]) > 0
    has_ask = len(L["b3_asks"]) > 0
    if has_bid or has_ask:
        b3_events.append({
            "fv": r["fv"], "ts": r["ts"],
            "bids": L["b3_bids"], "asks": L["b3_asks"],
            "bid_only": has_bid and not has_ask,
            "ask_only": not has_bid and has_ask,
            "both": has_bid and has_ask,
        })

print(f"\n  Timestamps with Bot 3 activity: {len(b3_events)}/{n} ({len(b3_events)/n*100:.1f}%)")
bid_only_3 = sum(1 for e in b3_events if e["bid_only"])
ask_only_3 = sum(1 for e in b3_events if e["ask_only"])
both_3 = sum(1 for e in b3_events if e["both"])
print(f"    Bid only: {bid_only_3}  Ask only: {ask_only_3}  Both: {both_3}")

# Collect all bot 3 quotes
b3_quotes = []
for e in b3_events:
    for bp, vol, off in e["bids"]:
        crossing = bp > e["fv"]
        b3_quotes.append({"side": "bid", "price": bp, "vol": vol, "off": off,
                          "fv": e["fv"], "crossing": crossing})
    for ap, vol, off in e["asks"]:
        crossing = ap < e["fv"]
        b3_quotes.append({"side": "ask", "price": ap, "vol": vol, "off": off,
                          "fv": e["fv"], "crossing": crossing})

print(f"\n  Total Bot 3 quotes: {len(b3_quotes)}")
if b3_quotes:
    sides = Counter(q["side"] for q in b3_quotes)
    print(f"  Side split: bid={sides.get('bid',0)} ask={sides.get('ask',0)}")

    # Side split test
    n_b3 = len(b3_quotes)
    n_bid = sides.get("bid", 0)
    p_hat = n_bid / n_b3
    z_side = (p_hat - 0.5) / math.sqrt(0.5 * 0.5 / n_b3)
    p_side = 2 * (1 - sp_stats.norm.cdf(abs(z_side)))
    print(f"  50/50 test: z={z_side:.2f}, p={p_side:.4f} {'(not significant)' if p_side > 0.05 else '(SIGNIFICANT)'}")

    # Offset distribution
    print(f"\n  Offset (price - round(FV)) distribution:")
    deltas = Counter(q["price"] - round(q["fv"]) for q in b3_quotes)
    for d in sorted(deltas):
        print(f"    delta={d:>+3}: {deltas[d]:>4} ({deltas[d]/len(b3_quotes)*100:.1f}%)")

    # Crossing vs passive
    crossing = sum(1 for q in b3_quotes if q["crossing"])
    passive = len(b3_quotes) - crossing
    print(f"\n  Crossing (aggressive): {crossing}/{len(b3_quotes)} ({crossing/len(b3_quotes)*100:.1f}%)")
    print(f"  Passive:               {passive}/{len(b3_quotes)} ({passive/len(b3_quotes)*100:.1f}%)")

    # Volume | crossing
    cross_vols = [q["vol"] for q in b3_quotes if q["crossing"]]
    pass_vols = [q["vol"] for q in b3_quotes if not q["crossing"]]
    if cross_vols:
        print(f"\n  Crossing vol: min={min(cross_vols)} max={max(cross_vols)} mean={statistics.mean(cross_vols):.1f}")
        print(f"    Distribution: {dict(Counter(cross_vols))}")
    if pass_vols:
        print(f"  Passive vol:  min={min(pass_vols)} max={max(pass_vols)} mean={statistics.mean(pass_vols):.1f}")
        print(f"    Distribution: {dict(Counter(pass_vols))}")

    # Run length (duration)
    b3_ts = set()
    for e in b3_events:
        b3_ts.add(e["ts"])
    all_ts = sorted(r["ts"] for r in rows)
    runs = []
    in_run = False
    run_len = 0
    for ts in all_ts:
        if ts in b3_ts:
            run_len += 1
            in_run = True
        else:
            if in_run:
                runs.append(run_len)
                run_len = 0
                in_run = False
    if in_run:
        runs.append(run_len)

    print(f"\n  Run lengths (consecutive ticks with Bot 3):")
    rc = Counter(runs)
    for rl in sorted(rc):
        print(f"    len={rl}: {rc[rl]}")

# ═════════════════════════════════════════════════════════════════════
# SPREAD ANALYSIS (combining all bots)
# ═════════════════════════════════════════════════════════════════════

print(f"\n\n{'=' * 80}")
print("  OVERALL SPREAD / PRESENCE PATTERN")
print("=" * 80)

# When do we see which configurations?
configs = Counter()
for r in rows:
    L = get_layers(r)
    b1 = len(L["b1_bids"]) > 0 and len(L["b1_asks"]) > 0
    b2 = len(L["b2_bids"]) > 0 and len(L["b2_asks"]) > 0
    b3 = len(L["b3_bids"]) > 0 or len(L["b3_asks"]) > 0
    configs[(b1, b2, b3)] += 1

print(f"\n  (Bot1, Bot2, Bot3) configuration frequency:")
for cfg in sorted(configs, key=configs.get, reverse=True):
    print(f"    {cfg}: {configs[cfg]:>5} ({configs[cfg]/n*100:.1f}%)")
