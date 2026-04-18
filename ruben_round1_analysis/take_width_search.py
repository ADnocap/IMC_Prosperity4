"""
Grid search: ASH_COATED_OSMIUM take_width parameter.

take_width=N means:
  - Buy asks at price <= fv_r + N
  - Sell bids at price >= fv_r - N

Tests take_width in [0, 1, 2, 3, 4, 5] with soft_limit=70.
"""

import subprocess
import re
import os
import sys
import json
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADER_SRC = os.path.join(ROOT, "traders", "a.py")
TMP_TRADER = os.path.join(ROOT, "traders", "_take_tmp.py")
OUT_DIR = os.path.join(ROOT, "tmp", "grid_search")
os.makedirs(OUT_DIR, exist_ok=True)

TAKE_WIDTHS = [0, 1, 2, 3, 4, 5]


def make_trader(take_width: int) -> str:
    """Read base trader and patch the taking thresholds."""
    with open(TRADER_SRC, "r") as f:
        code = f.read()

    # Patch the buy-side taking threshold:
    #   Original:  if ask_price > fv_r:
    #   Patched:   if ask_price > fv_r + N:
    if take_width == 0:
        buy_new = "if ask_price > fv_r:"
    else:
        buy_new = f"if ask_price > fv_r + {take_width}:"
    code = code.replace("if ask_price > fv_r:", buy_new, 1)

    # Patch the sell-side taking threshold:
    #   Original:  if bid_price < fv_r:
    #   Patched:   if bid_price < fv_r - N:
    if take_width == 0:
        sell_new = "if bid_price < fv_r:"
    else:
        sell_new = f"if bid_price < fv_r - {take_width}:"
    code = code.replace("if bid_price < fv_r:", sell_new, 1)

    return code


def run_backtest(take_width: int) -> dict:
    """Create patched trader, run backtester, parse results."""
    code = make_trader(take_width)
    with open(TMP_TRADER, "w") as f:
        f.write(code)

    out_file = os.path.join(OUT_DIR, f"take_w{take_width}.json")
    cmd = [
        "prosperity4mcbt",
        TMP_TRADER,
        "--quick",
        "--out", out_file,
    ]

    print(f"\n{'='*60}")
    print(f"  Running take_width={take_width}")
    print(f"{'='*60}")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    stdout = proc.stdout
    stderr = proc.stderr
    output = stdout + "\n" + stderr

    # Print the output for monitoring
    print(output[-1500:] if len(output) > 1500 else output)

    # Try to parse results from the JSON output
    result = {"take_width": take_width}

    # Parse from the JSON file if available
    if os.path.exists(out_file):
        try:
            with open(out_file, "r") as f:
                data = json.load(f)
            # Extract PnL stats from overall.totalPnl
            stats = data.get("overall", {}).get("totalPnl", {})
            if stats:
                result["mean_pnl"] = stats.get("mean")
                result["std_pnl"] = stats.get("std")
                result["p5"] = stats.get("p05") or stats.get("p5")
                result["p25"] = stats.get("p25")
                result["p50"] = stats.get("p50")
                result["p75"] = stats.get("p75")
                result["p95"] = stats.get("p95")
                result["min_pnl"] = stats.get("min")
                result["max_pnl"] = stats.get("max")
            # Also get per-product breakdown
            products = data.get("products", {})
            for prod, pdata in products.items():
                prod_stats = pdata.get("totalPnl", {})
                if prod_stats:
                    result[f"{prod}_mean"] = prod_stats.get("mean")
        except Exception as e:
            print(f"  Warning: could not parse {out_file}: {e}")

    # Also try to parse from stdout (the backtester prints summary stats)
    # Look for patterns like "Mean PnL: 1234" etc.
    for line in output.split("\n"):
        line_s = line.strip()
        if "mean" in line_s.lower() and "pnl" in line_s.lower():
            m = re.search(r"[-+]?\d+\.?\d*", line_s.split(":")[-1] if ":" in line_s else line_s)
            if m and "mean_pnl" not in result:
                result["mean_pnl"] = float(m.group())

    # Store raw output for debugging
    result["raw_tail"] = output[-500:]

    return result


def main():
    results = []
    for tw in TAKE_WIDTHS:
        r = run_backtest(tw)
        results.append(r)

    # Cleanup temp trader
    if os.path.exists(TMP_TRADER):
        os.remove(TMP_TRADER)

    # Print results table
    print("\n\n" + "=" * 80)
    print("GRID SEARCH RESULTS: ASH_COATED_OSMIUM take_width")
    print("=" * 80)

    # Sort by mean PnL descending
    results_with_pnl = [r for r in results if r.get("mean_pnl") is not None]
    results_no_pnl = [r for r in results if r.get("mean_pnl") is None]
    results_with_pnl.sort(key=lambda x: x["mean_pnl"], reverse=True)
    sorted_results = results_with_pnl + results_no_pnl

    header = f"{'take_w':>6} | {'Mean PnL':>10} | {'Std':>8} | {'P5':>10} | {'P50':>10} | {'P95':>10} | {'ACO Mean':>10} | {'IPR Mean':>10}"
    print(header)
    print("-" * len(header))

    def fmt(v):
        if isinstance(v, (int, float)):
            return f"{v:>10.1f}"
        return f"{str(v):>10}"

    for r in sorted_results:
        tw = r["take_width"]
        mean = r.get("mean_pnl", "N/A")
        std = r.get("std_pnl", "N/A")
        p5 = r.get("p5", "N/A")
        p50 = r.get("p50", "N/A")
        p95 = r.get("p95", "N/A")
        aco = r.get("ASH_COATED_OSMIUM_mean", "N/A")
        ipr = r.get("INTARIAN_PEPPER_ROOT_mean", "N/A")

        print(f"{tw:>6} | {fmt(mean)} | {fmt(std):>8} | {fmt(p5)} | {fmt(p50)} | {fmt(p95)} | {fmt(aco)} | {fmt(ipr)}")

    print("\nBest take_width:", sorted_results[0]["take_width"] if sorted_results else "N/A")


if __name__ == "__main__":
    main()
