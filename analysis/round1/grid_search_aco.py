"""Grid search over ACO parameters using Monte Carlo backtester."""
import subprocess
import json
import os
import re
import itertools
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(PROJECT_DIR, "traders", "a.py")
TMP_TRADER = os.path.join(PROJECT_DIR, "traders", "_grid_tmp.py")
RESULTS_DIR = os.path.join(PROJECT_DIR, "tmp", "grid_search")

# Grid parameters
ALPHAS = [0.1, 0.2, 0.3, 0.5, 1.0]       # 1.0 = no EMA (raw FV)
SOFT_LIMITS = [40, 50, 60, 70]
QUOTE_OFFSETS = [1, 2, 3]                   # distance from FV for passive quotes

os.makedirs(RESULTS_DIR, exist_ok=True)

# Read template
with open(TEMPLATE_PATH) as f:
    template = f.read()


def make_trader(alpha, soft_limit, quote_offset):
    """Generate a modified trader with the given parameters."""
    code = template

    # Replace soft_limit
    code = code.replace(
        '"soft_limit": 50,',
        f'"soft_limit": {soft_limit},'
    )

    # Replace EMA alpha block
    if alpha >= 1.0:
        # No EMA — use raw FV
        code = code.replace(
            """        raw_fv = self._estimate_ash_fv(od, td)
        if raw_fv is None:
            return orders

        # EMA-smooth FV
        prev_fv = td.get("ash_ema_fv")
        if prev_fv is not None:
            fv = 0.2 * raw_fv + 0.8 * prev_fv
        else:
            fv = raw_fv
        td["ash_ema_fv"] = fv""",
            """        fv = self._estimate_ash_fv(od, td)
        if fv is None:
            return orders"""
        )
    else:
        # Replace alpha value
        code = code.replace(
            f"fv = 0.2 * raw_fv + 0.8 * prev_fv",
            f"fv = {alpha} * raw_fv + {1-alpha} * prev_fv"
        )

    # Replace quote offset (fv_r - 1 -> fv_r - offset, fv_r + 1 -> fv_r + offset)
    code = code.replace(
        "our_bid = min(ref_bid + 1, fv_r - 1) + skew",
        f"our_bid = min(ref_bid + 1, fv_r - {quote_offset}) + skew"
    )
    code = code.replace(
        "our_ask = max(ref_ask - 1, fv_r + 1) + skew",
        f"our_ask = max(ref_ask - 1, fv_r + {quote_offset}) + skew"
    )
    # Also fix the fallback when bid >= ask
    code = code.replace(
        "our_bid = fv_r - 1\n            our_ask = fv_r + 1",
        f"our_bid = fv_r - {quote_offset}\n            our_ask = fv_r + {quote_offset}"
    )

    return code


def run_backtest(trader_path):
    """Run MC backtest and return mean PnL."""
    cmd = [
        "prosperity4mcbt", trader_path,
        "--quick",
        "--out", os.path.join(RESULTS_DIR, "tmp.json")
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=PROJECT_DIR, timeout=120
    )
    output = result.stdout + result.stderr
    match = re.search(r"Mean total PnL:\s*([\d,.-]+)", output)
    if match:
        return float(match.group(1).replace(",", ""))
    print(f"  FAILED: {output[:200]}")
    return None


def main():
    combos = list(itertools.product(ALPHAS, SOFT_LIMITS, QUOTE_OFFSETS))
    print(f"Grid search: {len(combos)} combinations")
    print(f"  Alphas: {ALPHAS}")
    print(f"  Soft limits: {SOFT_LIMITS}")
    print(f"  Quote offsets: {QUOTE_OFFSETS}")
    print()

    results = []
    for i, (alpha, soft, offset) in enumerate(combos):
        label = f"a={alpha:.1f} s={soft} q={offset}"
        sys.stdout.write(f"[{i+1}/{len(combos)}] {label} ... ")
        sys.stdout.flush()

        code = make_trader(alpha, soft, offset)
        with open(TMP_TRADER, "w") as f:
            f.write(code)

        pnl = run_backtest(TMP_TRADER)
        if pnl is not None:
            results.append((alpha, soft, offset, pnl))
            print(f"PnL = {pnl:,.0f}")
        else:
            print("FAILED")

    # Clean up
    if os.path.exists(TMP_TRADER):
        os.remove(TMP_TRADER)

    # Sort and display
    print(f"\n{'='*60}")
    print(f"  GRID SEARCH RESULTS (top 20)")
    print(f"{'='*60}")
    results.sort(key=lambda x: -x[3])
    for rank, (alpha, soft, offset, pnl) in enumerate(results[:20], 1):
        portal_est = pnl / 2
        ema_label = "raw" if alpha >= 1.0 else f"{alpha:.1f}"
        print(f"  #{rank:2d}  alpha={ema_label:>4s}  soft={soft:2d}  quote_off={offset}  "
              f"PnL={pnl:>10,.0f}  (portal ~{portal_est:>8,.0f})")

    # Save full results
    results_path = os.path.join(RESULTS_DIR, "grid_results.json")
    with open(results_path, "w") as f:
        json.dump([{"alpha": a, "soft_limit": s, "quote_offset": o, "mean_pnl": p}
                    for a, s, o, p in results], f, indent=2)
    print(f"\nFull results saved to {results_path}")


if __name__ == "__main__":
    main()
