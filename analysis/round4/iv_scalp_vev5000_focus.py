"""Final probe: focused grid search on VEV_5000 alone (THR_OPEN x SIZE) to
confirm the per-strike ceiling on the only strike that responds."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict


REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "traders" / "round4" / "submission_perstrike_tunable.py"


V2_UNIFORM = {
    "THR_OPEN":            0.536,
    "THR_CLOSE":          -0.4,
    "IV_SCALPING_THR":     1.0865,
    "SCALP_MAX_PER_TICK":  35,
    "THEO_NORM_WINDOW":    100,
    "IV_SCALPING_WINDOW":  200,
    "LOW_VEGA_THR_ADJ":    0.653,
    "LOW_VEGA_CUTOFF":     4.0984,
    "SMILE_A_ALPHA":       0.0052,
}


def run_trial(thr: float, size: int) -> Dict:
    payload = dict(V2_UNIFORM)
    payload["THR_OPEN_5000"] = thr
    payload["SCALP_MAX_PER_TICK_5000"] = size
    env = dict(os.environ)
    env["PROSPERITY_PARAMS"] = json.dumps(payload)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        "prosperity3bt", str(TRADER), "4",
        "--merge-pnl", "--no-out", "--no-progress",
    ]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                       timeout=120, check=False)
    out = r.stdout
    days = {1: 0, 2: 0, 3: 0}
    cur = 0
    pnl5000 = {1: 0, 2: 0, 3: 0}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^Backtesting .* day (\d)$", line)
        if m:
            cur = int(m.group(1)); continue
        m = re.match(r"^Round 4 day (\d):\s+(-?[\d,]+)$", line)
        if m:
            days[int(m.group(1))] = int(m.group(2).replace(",", "")); continue
        if cur in (1, 2, 3):
            m = re.match(r"^VEV_5000:\s+(-?[\d,]+)$", line)
            if m:
                pnl5000[cur] = int(m.group(1).replace(",", ""))
    total = days[1] + days[2] + days[3]
    return {
        "thr": thr, "size": size,
        "total": total, "d1": days[1], "d2": days[2], "d3": days[3],
        "vev5000_total": sum(pnl5000.values()),
        "vev5000_d3": pnl5000[3],
    }


def main():
    out_dir = REPO / "tmp" / "optimizer" / "iv_scalp_vev5000_grid"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"

    # 6 x 5 grid = 30 trials
    THRS = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1]
    SIZES = [20, 35, 50, 75, 100]

    rows = []
    print(f"V2 baseline VEV_5000 = 2,653; total = 29,934")
    for thr in THRS:
        for size in SIZES:
            r = run_trial(thr, size)
            rows.append(r)
            print(f"  thr={thr:.2f} size={size:3d}: total={r['total']:>6,}  "
                  f"VEV_5000_total={r['vev5000_total']:>5d}  "
                  f"VEV_5000_d3={r['vev5000_d3']:>5d}")

    rows.sort(key=lambda r: r["total"], reverse=True)
    print()
    print("Top 5 by total:")
    for r in rows[:5]:
        print(f"  thr={r['thr']:.2f} size={r['size']:3d}  total={r['total']:>6,} "
              f"VEV_5000={r['vev5000_total']}")

    # Write CSV
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thr_5000", "size_5000", "total", "d1", "d2", "d3",
                    "vev5000_total", "vev5000_d3"])
        for r in rows:
            w.writerow([r["thr"], r["size"], r["total"], r["d1"], r["d2"],
                         r["d3"], r["vev5000_total"], r["vev5000_d3"]])
    print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
