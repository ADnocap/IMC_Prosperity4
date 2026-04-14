"""
Analyze the FV generating process for both Round 1 products.
- ASH_COATED_OSMIUM: appears to be a random walk
- INTARIAN_PEPPER_ROOT: appears to be a deterministic linear drift

Tests: normality of increments, autocorrelation, quantization, stationarity.
"""

import json, math, statistics
from pathlib import Path
from collections import Counter

DATA_DIR = Path(__file__).parent.parent / "data"


def analyze_product(name, fname):
    with open(DATA_DIR / fname) as f:
        data = json.load(f)

    rows = [r for r in data["rows"] if r["fv"] is not None]
    fvs = [r["fv"] for r in rows]
    n = len(fvs)

    print(f"\n{'=' * 80}")
    print(f"  FV PROCESS ANALYSIS: {name}")
    print(f"{'=' * 80}")
    print(f"\n  N = {n} timestamps (t=100 to t={rows[-1]['ts']})")
    print(f"  FV range: [{min(fvs):.6f}, {max(fvs):.6f}]")
    print(f"  FV start: {fvs[0]:.6f}  end: {fvs[-1]:.6f}")

    # ── Step changes ──
    steps = [fvs[i] - fvs[i - 1] for i in range(1, n)]
    mean_s = statistics.mean(steps)
    std_s = statistics.stdev(steps)
    print(f"\n  Step changes (n={len(steps)}):")
    print(f"    mean  = {mean_s:.8f}")
    print(f"    std   = {std_s:.8f}")
    print(f"    min   = {min(steps):.8f}")
    print(f"    max   = {max(steps):.8f}")
    print(f"    median= {statistics.median(steps):.8f}")

    # ── Quantization check ──
    # Check if values are quantized to 1/2048
    print(f"\n  Quantization check:")
    diffs_from_grid = []
    for fv in fvs:
        frac = fv - math.floor(fv)
        nearest_2048 = round(frac * 2048) / 2048
        diffs_from_grid.append(abs(frac - nearest_2048))
    max_diff = max(diffs_from_grid)
    print(f"    Max distance from 1/2048 grid: {max_diff:.10f}")
    print(f"    Quantized to 1/2048? {'YES' if max_diff < 1e-6 else 'NO'}")

    # ── Check if deterministic or stochastic ──
    # If std of steps is tiny relative to mean, it's deterministic
    if std_s > 0 and abs(mean_s) > 0:
        cv = std_s / abs(mean_s)
        print(f"\n  Coefficient of variation (std/|mean|): {cv:.4f}")
        if cv < 0.01:
            print(f"    → DETERMINISTIC DRIFT (CV < 0.01)")
            # Check exact drift rate
            print(f"    Drift per tick: {mean_s:.8f}")
            print(f"    Drift per 100 ticks: {mean_s * 100:.6f}")
            # Check if it's exactly 0.1 per tick
            print(f"    Is drift ≈ 0.1/tick? diff = {abs(mean_s - 0.1):.10f}")
            # Check residuals after removing drift
            residuals = [steps[i] - mean_s for i in range(len(steps))]
            print(f"    Residual std: {statistics.stdev(residuals):.10f}")
            print(f"    Residual max: {max(abs(r) for r in residuals):.10f}")
            # The residuals are just quantization noise
            return "deterministic", mean_s

    # ── For random walk: test normality ──
    if std_s > 0.01:
        print(f"\n  Normality test (step distribution):")
        # Compute skewness and kurtosis
        z_steps = [(s - mean_s) / std_s for s in steps]
        skew = statistics.mean([z ** 3 for z in z_steps])
        kurt = statistics.mean([z ** 4 for z in z_steps]) - 3  # excess kurtosis
        print(f"    Skewness: {skew:.4f} (0 for normal)")
        print(f"    Excess kurtosis: {kurt:.4f} (0 for normal)")
        # SE of skewness ≈ sqrt(6/n), SE of kurtosis ≈ sqrt(24/n)
        se_skew = math.sqrt(6 / len(steps))
        se_kurt = math.sqrt(24 / len(steps))
        print(f"    Skewness z-score: {skew / se_skew:.2f} (|z|<2 = consistent with normal)")
        print(f"    Kurtosis z-score: {kurt / se_kurt:.2f} (|z|<2 = consistent with normal)")

        # ── Autocorrelation ──
        print(f"\n  Autocorrelation of steps:")
        for lag in [1, 2, 3, 5, 10]:
            if lag >= len(steps):
                break
            pairs = [(steps[i], steps[i + lag]) for i in range(len(steps) - lag)]
            mx = statistics.mean([p[0] for p in pairs])
            my = statistics.mean([p[1] for p in pairs])
            cov = statistics.mean([(p[0] - mx) * (p[1] - my) for p in pairs])
            sx = statistics.stdev([p[0] for p in pairs])
            sy = statistics.stdev([p[1] for p in pairs])
            if sx > 0 and sy > 0:
                corr = cov / (sx * sy)
            else:
                corr = 0
            se = 1 / math.sqrt(len(pairs))
            print(f"    lag={lag:>2}: r={corr:>+.4f}  (SE={se:.4f}, z={corr/se:>+.2f})")

        # ── Step size histogram ──
        print(f"\n  Step histogram (binned to 0.05):")
        binned = Counter(round(s / 0.05) * 0.05 for s in steps)
        total = len(steps)
        for b in sorted(binned):
            if binned[b] / total > 0.005:
                bar = '#' * int(binned[b] / total * 100)
                print(f"    {b:>+7.3f}: {binned[b]:>4} ({binned[b]/total*100:>5.1f}%) {bar}")

        return "random_walk", std_s

    return "unknown", 0


print("=" * 80)
print("  ROUND 1 FAIR VALUE PROCESS ANALYSIS")
print("=" * 80)

osm_type, osm_param = analyze_product("ASH_COATED_OSMIUM", "ash_coated_osmium_fv_and_book.json")
pep_type, pep_param = analyze_product("INTARIAN_PEPPER_ROOT", "intarian_pepper_root_fv_and_book.json")

print(f"\n{'=' * 80}")
print(f"  SUMMARY")
print(f"{'=' * 80}")
print(f"  ASH_COATED_OSMIUM:    {osm_type}, σ={osm_param:.6f}" if osm_type == "random_walk" else f"  ASH_COATED_OSMIUM:    {osm_type}, param={osm_param:.8f}")
print(f"  INTARIAN_PEPPER_ROOT: {pep_type}, drift={pep_param:.8f}" if pep_type == "deterministic" else f"  INTARIAN_PEPPER_ROOT: {pep_type}, param={pep_param:.8f}")
