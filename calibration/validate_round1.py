"""
Rigorous calibration validation for Round 1 products.
Follows ANALYSIS_PHILOSOPHY.md: condition every variable, run stat tests, never eyeball.
"""
import json, math
from collections import Counter, defaultdict
from pathlib import Path


def chi2_uniform(counts_dict, lo, hi):
    """Chi-squared test for discrete uniform on [lo, hi]."""
    n_bins = hi - lo + 1
    n = sum(counts_dict.values())
    expected = n / n_bins
    chi2 = sum((counts_dict.get(v, 0) - expected) ** 2 / expected for v in range(lo, hi + 1))
    df = n_bins - 1
    # Wilson-Hilferty approximation for chi2 CDF
    if df > 0:
        z = (chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))
        z /= math.sqrt(2 / (9 * df))
        p = 0.5 * (1 + math.erf(-z / math.sqrt(2)))
    else:
        p = 1.0
    return chi2, df, p


def z_test_prop(k, n, p0):
    """Two-sided z-test for proportion."""
    p_hat = k / n
    se = math.sqrt(p0 * (1 - p0) / n) if n > 0 else 1
    z = (p_hat - p0) / se
    p = 2 * 0.5 * (1 + math.erf(-abs(z) / math.sqrt(2)))
    return z, p, p_hat


def pass_fail(p, alpha=0.05):
    return "PASS" if p > alpha else f"FAIL (p={p:.4f})"


PRODUCTS = [
    ("ASH_COATED_OSMIUM", Path("calibration/ash_coated_osmium/data/fv_and_book.json")),
    ("INTARIAN_PEPPER_ROOT", Path("calibration/intarian_pepper_root/data/fv_and_book.json")),
]

for product, path in PRODUCTS:
    with open(path) as f:
        data = json.load(f)

    rows = [r for r in data["rows"] if r["fv"] is not None]
    n_total = len(rows)

    print("=" * 70)
    print(f"  {product} - RIGOROUS CALIBRATION VALIDATION")
    print(f"  n = {n_total} ticks with FV")
    print("=" * 70)

    # ── Separate bots by offset from FV ────────────────────────
    bot1_bids = []
    bot1_asks = []
    bot2_bids = []
    bot2_asks = []
    bot3_events = []

    bot1_both = bot1_bid_only = bot1_ask_only = bot1_absent = 0
    bot2_both = bot2_bid_only = bot2_ask_only = bot2_absent = 0
    bot1_same_vol = bot1_both_n = 0
    bot2_same_vol = bot2_both_n = 0

    for r in rows:
        fv = r["fv"]
        b1b = b1a = b2b = b2a = None
        b1bv = b1av = b2bv = b2av = 0

        for bp in r["bids"]:
            off = abs(bp - fv)
            vol = r["bid_vols"].get(str(bp), r["bid_vols"].get(bp, 0))
            if off > 8.5:
                bot1_bids.append((bp, vol, fv))
                b1b = bp
                b1bv = vol
            elif off > 4.5:
                bot2_bids.append((bp, vol, fv))
                b2b = bp
                b2bv = vol
            else:
                bot3_events.append(("bid", bp, vol, fv))

        for ap in r["asks"]:
            off = abs(ap - fv)
            vol = r["ask_vols"].get(str(ap), r["ask_vols"].get(ap, 0))
            if off > 8.5:
                bot1_asks.append((ap, vol, fv))
                b1a = ap
                b1av = vol
            elif off > 4.5:
                bot2_asks.append((ap, vol, fv))
                b2a = ap
                b2av = vol
            else:
                bot3_events.append(("ask", ap, vol, fv))

        if b1b is not None and b1a is not None:
            bot1_both += 1
            bot1_both_n += 1
            if b1bv == b1av:
                bot1_same_vol += 1
        elif b1b is not None:
            bot1_bid_only += 1
        elif b1a is not None:
            bot1_ask_only += 1
        else:
            bot1_absent += 1

        if b2b is not None and b2a is not None:
            bot2_both += 1
            bot2_both_n += 1
            if b2bv == b2av:
                bot2_same_vol += 1
        elif b2b is not None:
            bot2_bid_only += 1
        elif b2a is not None:
            bot2_ask_only += 1
        else:
            bot2_absent += 1

    # ═══════════════════════════════════════════════════════════
    # TEST 1: Price formula accuracy
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 1: PRICE FORMULA ACCURACY ---")

    if product == "ASH_COATED_OSMIUM":
        b1bm = sum(1 for p, v, fv in bot1_bids if math.floor(fv) - 10 == p)
        b1am = sum(1 for p, v, fv in bot1_asks if math.ceil(fv) + 10 == p)
        b2bm = sum(1 for p, v, fv in bot2_bids if math.floor(fv - 0.5) - 7 == p)
        b2am = sum(1 for p, v, fv in bot2_asks if math.floor(fv - 0.5) + 9 == p)
    else:
        b1bm = sum(1 for p, v, fv in bot1_bids if math.ceil(fv) - 10 == p)
        b1am = sum(1 for p, v, fv in bot1_asks if math.floor(fv) + 10 == p)
        b2bm = sum(1 for p, v, fv in bot2_bids if math.ceil(fv) - 7 == p)
        b2am = sum(1 for p, v, fv in bot2_asks if math.floor(fv) + 7 == p)

    for label, match, total in [
        ("Bot1 bid", b1bm, len(bot1_bids)),
        ("Bot1 ask", b1am, len(bot1_asks)),
        ("Bot2 bid", b2bm, len(bot2_bids)),
        ("Bot2 ask", b2am, len(bot2_asks)),
    ]:
        pct = match / total * 100 if total else 0
        miss = total - match
        print(f"  {label}: {match}/{total} ({pct:.1f}%) -- {miss} misses")

    # Analyze misses
    for label, recs, formula_fn in [
        (
            "Bot1 bid",
            bot1_bids,
            (lambda fv: math.floor(fv) - 10) if product == "ASH_COATED_OSMIUM" else (lambda fv: math.ceil(fv) - 10),
        ),
        (
            "Bot1 ask",
            bot1_asks,
            (lambda fv: math.ceil(fv) + 10) if product == "ASH_COATED_OSMIUM" else (lambda fv: math.floor(fv) + 10),
        ),
    ]:
        misses = [(p, v, fv, p - formula_fn(fv)) for p, v, fv in recs if formula_fn(fv) != p]
        if misses:
            miss_diffs = Counter(m[3] for m in misses)
            frac_at_miss = [fv - math.floor(fv) for _, _, fv, _ in misses]
            print(f"    {label} misses: diffs={dict(miss_diffs)}")
            print(f"      FV fracs at miss: {[round(f, 4) for f in frac_at_miss[:10]]}")

    # ═══════════════════════════════════════════════════════════
    # TEST 2: Volume distributions (chi-squared for uniformity)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 2: VOLUME DISTRIBUTIONS (chi-squared uniformity) ---")

    if product == "ASH_COATED_OSMIUM":
        vol_tests = [
            ("Bot1 vol", [v for _, v, _ in bot1_bids + bot1_asks], 20, 30),
            ("Bot2 vol", [v for _, v, _ in bot2_bids + bot2_asks], 10, 15),
        ]
    else:
        vol_tests = [
            ("Bot1 vol", [v for _, v, _ in bot1_bids + bot1_asks], 15, 25),
            ("Bot2 vol", [v for _, v, _ in bot2_bids + bot2_asks], 8, 12),
        ]

    for label, vols, lo, hi in vol_tests:
        vc = Counter(vols)
        chi2, df, p = chi2_uniform(vc, lo, hi)
        print(f"  {label}: U({lo},{hi})? n={len(vols)} chi2={chi2:.2f} df={df} p={p:.4f} => {pass_fail(p)}")
        # Show distribution
        for v in range(lo, hi + 1):
            expected_pct = 100 / (hi - lo + 1)
            actual_pct = vc.get(v, 0) / len(vols) * 100
            print(f"    vol={v:>3}: {vc.get(v, 0):>5} ({actual_pct:.1f}%) expected={expected_pct:.1f}%")

    # ═══════════════════════════════════════════════════════════
    # TEST 3: Volume | side (bid vs ask same distribution?)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 3: VOLUME | SIDE (bid vs ask same?) ---")

    for label, b_recs, a_recs, lo, hi in [
        ("Bot1", bot1_bids, bot1_asks, 20 if product == "ASH_COATED_OSMIUM" else 15, 30 if product == "ASH_COATED_OSMIUM" else 25),
        ("Bot2", bot2_bids, bot2_asks, 10 if product == "ASH_COATED_OSMIUM" else 8, 15 if product == "ASH_COATED_OSMIUM" else 12),
    ]:
        bv = [v for _, v, _ in b_recs]
        av = [v for _, v, _ in a_recs]
        bvc = Counter(bv)
        avc = Counter(av)
        bchi2, _, bp = chi2_uniform(bvc, lo, hi)
        achi2, _, ap = chi2_uniform(avc, lo, hi)
        print(f"  {label} bid: n={len(bv)} chi2={bchi2:.2f} p={bp:.4f} {pass_fail(bp)}")
        print(f"  {label} ask: n={len(av)} chi2={achi2:.2f} p={ap:.4f} {pass_fail(ap)}")
        print(f"  {label} bid mean={sum(bv)/len(bv):.2f} ask mean={sum(av)/len(av):.2f}")

    # ═══════════════════════════════════════════════════════════
    # TEST 4: Same bid/ask volume per tick
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 4: SAME BID/ASK VOLUME PER TICK ---")
    print(f"  Bot 1: {bot1_same_vol}/{bot1_both_n} ({bot1_same_vol / bot1_both_n * 100:.1f}%) same")
    print(f"  Bot 2: {bot2_same_vol}/{bot2_both_n} ({bot2_same_vol / bot2_both_n * 100:.1f}%) same")

    # ═══════════════════════════════════════════════════════════
    # TEST 5: Presence independence (chi-squared 2x2)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 5: BOT PRESENCE - BID/ASK INDEPENDENCE ---")

    for label, both, b_only, a_only, absent in [
        ("Bot 1", bot1_both, bot1_bid_only, bot1_ask_only, bot1_absent),
        ("Bot 2", bot2_both, bot2_bid_only, bot2_ask_only, bot2_absent),
    ]:
        total = both + b_only + a_only + absent
        p_bid = (both + b_only) / total
        p_ask = (both + a_only) / total
        exp = [p_bid * p_ask * total, p_bid * (1 - p_ask) * total, (1 - p_bid) * p_ask * total, (1 - p_bid) * (1 - p_ask) * total]
        obs = [both, b_only, a_only, absent]
        chi2 = sum((o - e) ** 2 / e for o, e in zip(obs, exp) if e > 0)
        # df=1 for 2x2 independence
        z = math.sqrt(chi2) if chi2 > 0 else 0
        p_val = 2 * 0.5 * (1 + math.erf(-z / math.sqrt(2)))

        print(f"  {label}: p(bid)={p_bid:.3f} p(ask)={p_ask:.3f}")
        print(f"    Obs:  both={both} bid_only={b_only} ask_only={a_only} absent={absent}")
        print(f"    Exp:  both={exp[0]:.0f} bid_only={exp[1]:.0f} ask_only={exp[2]:.0f} absent={exp[3]:.0f}")
        print(f"    chi2={chi2:.3f} p={p_val:.4f} => {pass_fail(p_val)}")

    # ═══════════════════════════════════════════════════════════
    # TEST 6: Volume | price offset (conditioning check)
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 6: VOLUME | PRICE OFFSET (no hidden structure?) ---")

    for label, recs, lo, hi in [
        ("Bot1 bid", bot1_bids, 20 if product == "ASH_COATED_OSMIUM" else 15, 30 if product == "ASH_COATED_OSMIUM" else 25),
        ("Bot1 ask", bot1_asks, 20 if product == "ASH_COATED_OSMIUM" else 15, 30 if product == "ASH_COATED_OSMIUM" else 25),
        ("Bot2 bid", bot2_bids, 10 if product == "ASH_COATED_OSMIUM" else 8, 15 if product == "ASH_COATED_OSMIUM" else 12),
        ("Bot2 ask", bot2_asks, 10 if product == "ASH_COATED_OSMIUM" else 8, 15 if product == "ASH_COATED_OSMIUM" else 12),
    ]:
        vol_by_offset = defaultdict(list)
        for p, v, fv in recs:
            off = round(p - fv)
            vol_by_offset[off].append(v)

        print(f"  {label}:")
        for off in sorted(vol_by_offset):
            vols = vol_by_offset[off]
            vc = Counter(vols)
            if len(vols) >= 20:
                chi2, df, p = chi2_uniform(vc, lo, hi)
                print(f"    offset={off:+3d}: n={len(vols):>4} mean={sum(vols)/len(vols):.1f} chi2={chi2:.1f} p={p:.3f} {pass_fail(p)}")
            else:
                print(f"    offset={off:+3d}: n={len(vols):>4} mean={sum(vols)/len(vols):.1f} (too few for test)")

    # ═══════════════════════════════════════════════════════════
    # TEST 7: FV dynamics
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 7: FV DYNAMICS ---")

    fvs = [r["fv"] for r in rows]
    steps = [fvs[i] - fvs[i - 1] for i in range(1, len(fvs))]
    mean_s = sum(steps) / len(steps)
    std_s = math.sqrt(sum((s - mean_s) ** 2 for s in steps) / len(steps))

    # Excess kurtosis (normal = 0)
    if std_s > 0:
        kurt = sum(((s - mean_s) / std_s) ** 4 for s in steps) / len(steps) - 3
    else:
        kurt = 0

    # AC(1)
    num = sum((steps[i] - mean_s) * (steps[i - 1] - mean_s) for i in range(1, len(steps)))
    den = sum((s - mean_s) ** 2 for s in steps)
    ac1 = num / den if den > 0 else 0
    se_ac = 1 / math.sqrt(len(steps))
    ac_z = ac1 / se_ac
    ac_p = 2 * 0.5 * (1 + math.erf(-abs(ac_z) / math.sqrt(2)))

    # Skewness
    if std_s > 0:
        skew = sum(((s - mean_s) / std_s) ** 3 for s in steps) / len(steps)
    else:
        skew = 0

    print(f"  Mean step:  {mean_s:.6f}")
    print(f"  Std step:   {std_s:.6f}")
    print(f"  Skewness:   {skew:.4f} (normal=0)")
    print(f"  Ex.kurtosis:{kurt:.4f} (normal=0)")
    print(f"  AC(1):      {ac1:.4f} (z={ac_z:.2f}, p={ac_p:.4f}) {pass_fail(ac_p)}")

    # Quantization check
    min_abs_step = min((abs(s) for s in steps if abs(s) > 1e-10), default=0)
    print(f"  Min |step|: {min_abs_step:.8f}")
    print(f"  1/1024:     {1/1024:.8f}")
    close_to_1024 = abs(min_abs_step - 1 / 1024) < 1e-6
    print(f"  Quantized to 1/1024? {'YES' if close_to_1024 else 'NO'}")

    # ═══════════════════════════════════════════════════════════
    # TEST 8: Bot 3 conditioned analysis
    # ═══════════════════════════════════════════════════════════
    print(f"\n  --- TEST 8: BOT 3 CONDITIONED ANALYSIS ---")
    n_b3 = len(bot3_events)
    presence_rate = n_b3 / n_total
    print(f"  Presence: {n_b3}/{n_total} ({presence_rate * 100:.1f}%)")

    if n_b3 >= 10:
        # Side
        sides = Counter(e[0] for e in bot3_events)
        z_s, p_s, ph_s = z_test_prop(sides.get("bid", 0), n_b3, 0.5)
        print(f"  Side 50/50: bid={sides.get('bid', 0)} ask={sides.get('ask', 0)} z={z_s:.2f} p={p_s:.4f} {pass_fail(p_s)}")

        # Crossing vs passive
        crossing = [(s, p, v, fv) for s, p, v, fv in bot3_events if (s == "bid" and p > fv) or (s == "ask" and p < fv)]
        passive = [e for e in bot3_events if e not in crossing]
        print(f"  Crossing: {len(crossing)}/{n_b3} ({len(crossing)/n_b3*100:.1f}%)")
        print(f"  Passive:  {len(passive)}/{n_b3} ({len(passive)/n_b3*100:.1f}%)")

        if crossing:
            cv = [v for _, _, v, _ in crossing]
            print(f"    Crossing vol: mean={sum(cv)/len(cv):.1f} range=[{min(cv)},{max(cv)}] dist={dict(sorted(Counter(cv).items()))}")
        if passive:
            pv = [v for _, _, v, _ in passive]
            print(f"    Passive vol:  mean={sum(pv)/len(pv):.1f} range=[{min(pv)},{max(pv)}] dist={dict(sorted(Counter(pv).items()))}")

        # Price offsets | side
        for side in ["bid", "ask"]:
            offs = [round(p - fv) for s, p, _, fv in bot3_events if s == side]
            print(f"  Offsets | {side}: {dict(sorted(Counter(offs).items()))}")

        # Volume | (side, crossing)
        for side in ["bid", "ask"]:
            for cross_label, events in [("crossing", crossing), ("passive", passive)]:
                sv = [v for s, p, v, fv in events if s == side]
                if sv:
                    print(f"  Vol | ({side}, {cross_label}): n={len(sv)} mean={sum(sv)/len(sv):.1f} range=[{min(sv)},{max(sv)}]")
    else:
        print("  Too few events for statistical analysis")

    print()
