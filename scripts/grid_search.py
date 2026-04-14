"""
Grid search over OSMIUM MM parameters to find the optimal combination.
Tests: soft_limit, max_skew, EMA alpha, penny-jump size, min_fv_distance.
Runs the backtester for each parameter combination.
"""
import subprocess
import csv
import json
import statistics
import itertools
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
TRADER_TEMPLATE = REPO / "traders" / "round1" / "a.py"
TRADER_TMP = REPO / "tmp" / "grid_trader.py"
RESULTS_DIR = REPO / "tmp" / "grid_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Read the base trader
with open(TRADER_TEMPLATE) as f:
    base_code = f.read()

# Parameter grid
GRID = {
    "soft_limit": [20, 35, 50, 65],
    "max_skew": [1, 2, 3],
    "penny_jump": [1, 2],  # how many ticks inside the reference level
    "ema_alpha": [0.5, 0.7, 1.0],  # 1.0 = no smoothing
}

SESSIONS = 300  # enough for stable estimates
TICKS = 1000

def make_trader(soft_limit, max_skew, penny_jump, ema_alpha):
    """Patch the trader code with specific parameters."""
    code = base_code
    # Patch soft_limit
    code = re.sub(r'"soft_limit": \d+', f'"soft_limit": {soft_limit}', code)
    # Patch max_skew
    code = re.sub(r'min\(round\(\(excess / max_excess\) \* \d+\), \d+\)',
                  f'min(round((excess / max_excess) * {max_skew}), {max_skew})', code)
    # Patch penny_jump (ref_bid + 1 → ref_bid + N, ref_ask - 1 → ref_ask - N)
    code = re.sub(r'our_bid = min\(ref_bid \+ \d+,', f'our_bid = min(ref_bid + {penny_jump},', code)
    code = re.sub(r'our_ask = max\(ref_ask - \d+,', f'our_ask = max(ref_ask - {penny_jump},', code)
    # Patch EMA alpha
    code = re.sub(r'alpha = [\d.]+', f'alpha = {ema_alpha}', code)
    return code


results = []
combos = list(itertools.product(
    GRID["soft_limit"], GRID["max_skew"], GRID["penny_jump"], GRID["ema_alpha"]
))

print(f"Grid search: {len(combos)} combinations × {SESSIONS} sessions")

for i, (soft, skew, pj, alpha) in enumerate(combos):
    # Write patched trader
    code = make_trader(soft, skew, pj, alpha)
    with open(TRADER_TMP, "w") as f:
        f.write(code)

    # Run backtester
    out_file = RESULTS_DIR / f"grid_{i}.json"
    cmd = [
        "prosperity4mcbt", str(TRADER_TMP),
        "--sessions", str(SESSIONS),
        "--ticks-per-day", str(TICKS),
        "--out", str(out_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    # Parse mean PnL from output
    mean_match = re.search(r"Mean total PnL: ([\d,.-]+)", result.stdout)
    if mean_match:
        mean_pnl = float(mean_match.group(1).replace(",", ""))
    else:
        mean_pnl = 0
        print(f"  FAILED: {result.stderr[:100]}")

    # Also get per-product breakdown
    summary_path = RESULTS_DIR.parent / "results" / "session_summary.csv"
    ash_mean = 0
    if summary_path.exists():
        with open(summary_path) as f:
            reader = csv.DictReader(f)
            ash_vals = [float(r["ash_pnl"]) for r in reader]
            if ash_vals:
                ash_mean = statistics.mean(ash_vals)

    results.append({
        "soft": soft, "skew": skew, "pj": pj, "alpha": alpha,
        "total": mean_pnl, "ash": ash_mean,
    })

    marker = " ←" if mean_pnl > 10900 else ""
    print(f"  [{i+1:>3}/{len(combos)}] soft={soft:>2} skew={skew} pj={pj} α={alpha:.1f} → total={mean_pnl:>8,.0f}  ash={ash_mean:>6,.0f}{marker}")

# Sort and show top results
results.sort(key=lambda x: -x["total"])
print(f"\n{'=' * 70}")
print(f"  TOP 10 COMBINATIONS")
print(f"{'=' * 70}")
print(f"  {'soft':>4} {'skew':>4} {'pj':>2} {'alpha':>5} {'total':>9} {'ash':>7}")
for r in results[:10]:
    print(f"  {r['soft']:>4} {r['skew']:>4} {r['pj']:>2} {r['alpha']:>5.1f} {r['total']:>9,.0f} {r['ash']:>7,.0f}")

print(f"\n  WORST 3:")
for r in results[-3:]:
    print(f"  {r['soft']:>4} {r['skew']:>4} {r['pj']:>2} {r['alpha']:>5.1f} {r['total']:>9,.0f} {r['ash']:>7,.0f}")
