"""Per-strike IV-scalp parameter tuner via R4 historical replay.

Workflow per trial:
  1. Sample per-strike params from a sane range (uniform random).
  2. Spawn `prosperity3bt traders/round4/submission_perstrike_tunable.py 4
     --merge-pnl --no-out --no-progress` with PROSPERITY_PARAMS=<json> in env.
     Uniform V2 params are passed through every trial (so the only thing that
     changes between trials is the per-strike overrides).
  3. Parse per-day per-asset PnL from stdout.
  4. Score: total D1+D2+D3 PnL; track TRAIN=D1+D2 / HOLDOUT=D3 separately.

Output: tmp/optimizer/iv_scalp_perstrike_<timestamp>/
   - results.csv  one row per trial: trial, params (one column each),
                  total_d1, total_d2, total_d3, train, holdout, total,
                  per-asset PnL columns.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple


REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "traders" / "round4" / "submission_perstrike_tunable.py"

STRIKES = (5000, 5100, 5200, 5300, 5400, 5500)

# Uniform V2 anchor — kept fixed across the search.
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


def sample_thr_open_per_strike(rng: random.Random) -> Dict[str, float]:
    """6 per-strike THR_OPEN in [0.20, 1.50]."""
    return {f"THR_OPEN_{K}": round(rng.uniform(0.20, 1.50), 4) for K in STRIKES}


def sample_thr_open_and_size(rng: random.Random) -> Dict[str, float]:
    """6 THR_OPEN + 6 SCALP_MAX_PER_TICK per-strike."""
    p: Dict[str, float] = {}
    for K in STRIKES:
        p[f"THR_OPEN_{K}"] = round(rng.uniform(0.20, 1.50), 4)
        p[f"SCALP_MAX_PER_TICK_{K}"] = rng.randint(10, 100)
    return p


def baseline_uniform_v2() -> Dict[str, float]:
    """Trial 0: uniform V2 = no per-strike overrides."""
    return dict(V2_UNIFORM)


def run_trial(params_per_strike: Dict[str, float],
              timeout: int = 240) -> Dict:
    """params_per_strike are *just* the per-strike overrides. We always pass
    V2_UNIFORM as the uniform baseline so the trader uses V2 thresholds for
    any strike not overridden. (This is identical behavior since the file's
    class defaults are also V2 — we pass V2 explicitly for clarity.)"""
    payload = dict(V2_UNIFORM)
    payload.update(params_per_strike)
    env = dict(os.environ)
    env["PROSPERITY_PARAMS"] = json.dumps(payload)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        "prosperity3bt", str(TRADER), "4",
        "--merge-pnl", "--no-out", "--no-progress",
    ]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "elapsed": time.time() - t0}
    elapsed = time.time() - t0
    if r.returncode != 0:
        return {"ok": False, "error": f"rc={r.returncode}",
                "stderr": r.stderr[-2000:], "elapsed": elapsed}
    parsed = parse_output(r.stdout)
    parsed["ok"] = True
    parsed["elapsed"] = elapsed
    return parsed


PER_ASSET = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500",
    "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500",
]
LINE_ASSET_RE = re.compile(r"^([A-Z_0-9]+):\s+(-?[\d,]+)$")
LINE_TOTAL_RE = re.compile(r"^Total profit:\s+(-?[\d,]+)$")
LINE_DAY_RE = re.compile(r"^Round 4 day (\d):\s+(-?[\d,]+)$")


def parse_output(stdout: str) -> Dict:
    per_day_assets: Dict[int, Dict[str, int]] = {1: {}, 2: {}, 3: {}}
    per_day_total: Dict[int, int] = {1: 0, 2: 0, 3: 0}
    total = 0
    cur_day = 0
    in_summary = False
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Backtesting") and "day" in line:
            m = re.search(r"day (\d)", line)
            if m:
                cur_day = int(m.group(1))
                in_summary = False
            continue
        if line.startswith("Profit summary"):
            in_summary = True
            cur_day = 0
            continue
        if in_summary:
            md = LINE_DAY_RE.match(line)
            if md:
                d = int(md.group(1))
                per_day_total[d] = int(md.group(2).replace(",", ""))
                continue
            mt = LINE_TOTAL_RE.match(line)
            if mt:
                total = int(mt.group(1).replace(",", ""))
            continue
        if cur_day in (1, 2, 3):
            ma = LINE_ASSET_RE.match(line)
            if ma:
                asset = ma.group(1)
                if asset in PER_ASSET:
                    per_day_assets[cur_day][asset] = int(ma.group(2).replace(",", ""))
                continue
            mt = LINE_TOTAL_RE.match(line)
            if mt:
                per_day_total[cur_day] = int(mt.group(1).replace(",", ""))
                continue
    return {
        "per_day_total": per_day_total,
        "per_day_assets": per_day_assets,
        "total": total,
    }


def trial_param_columns(mode: str) -> List[str]:
    cols = [f"THR_OPEN_{K}" for K in STRIKES]
    if mode == "thr_open_size":
        cols += [f"SCALP_MAX_PER_TICK_{K}" for K in STRIKES]
    return cols


def write_csv_header(path: Path, mode: str) -> List[str]:
    cols = ["trial"] + trial_param_columns(mode)
    cols += ["d1_total", "d2_total", "d3_total", "train", "holdout", "total",
             "elapsed", "ok"]
    for asset in PER_ASSET:
        for d in (1, 2, 3):
            cols.append(f"d{d}_{asset}")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
    return cols


def append_csv_row(path: Path, cols: List[str], row: Dict):
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([row.get(c, "") for c in cols])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="Number of random trials")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--mode", choices=("thr_open", "thr_open_size"),
                    default="thr_open",
                    help="thr_open: 6 params; thr_open_size: 12 params")
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--include-baseline", action="store_true", default=True)
    ap.add_argument("--extra-trials-json", type=str, default=None,
                    help="Path to JSON list of extra param dicts (per-strike "
                         "keys only).")
    args = ap.parse_args()

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = REPO / "tmp" / "optimizer" / f"iv_scalp_perstrike_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"
    log_path = out_dir / "log.txt"
    cols = write_csv_header(csv_path, args.mode)

    rng = random.Random(args.seed)
    trials: List[Dict[str, float]] = []
    if args.include_baseline:
        trials.append({})  # uniform V2 = no per-strike overrides
    sampler = (sample_thr_open_per_strike if args.mode == "thr_open"
               else sample_thr_open_and_size)
    for _ in range(args.n):
        trials.append(sampler(rng))
    if args.extra_trials_json:
        extra = json.loads(Path(args.extra_trials_json).read_text(encoding="utf-8"))
        for p in extra:
            trials.append(p)

    print(f"[iv_scalp_perstrike] mode={args.mode}")
    print(f"[iv_scalp_perstrike] out_dir={out_dir}")
    print(f"[iv_scalp_perstrike] running {len(trials)} trials")

    best_total = -10**12
    best_row = None
    best_holdout = -10**12
    best_holdout_row = None
    with log_path.open("w", encoding="utf-8") as logf:
        for i, params in enumerate(trials):
            res = run_trial(params)
            row = {"trial": i}
            row.update(params)
            if not res["ok"]:
                row["ok"] = 0
                row["d1_total"] = row["d2_total"] = row["d3_total"] = ""
                row["train"] = row["holdout"] = row["total"] = ""
                row["elapsed"] = round(res.get("elapsed", 0), 2)
                msg = f"trial {i}: FAIL ({res.get('error')}) params={params}"
                print(msg)
                logf.write(msg + "\n")
                if res.get("stderr"):
                    logf.write(res["stderr"] + "\n")
                append_csv_row(csv_path, cols, row)
                continue
            d1 = res["per_day_total"][1]
            d2 = res["per_day_total"][2]
            d3 = res["per_day_total"][3]
            train = d1 + d2
            holdout = d3
            total = res["total"]
            row.update({
                "d1_total": d1, "d2_total": d2, "d3_total": d3,
                "train": train, "holdout": holdout, "total": total,
                "elapsed": round(res["elapsed"], 2), "ok": 1,
            })
            for asset in PER_ASSET:
                for d in (1, 2, 3):
                    row[f"d{d}_{asset}"] = res["per_day_assets"][d].get(asset, 0)
            append_csv_row(csv_path, cols, row)

            tag = ""
            if total > best_total:
                best_total = total
                best_row = (i, params, total, train, holdout)
                tag = " <-- best total"
            if holdout > best_holdout:
                best_holdout = holdout
                best_holdout_row = (i, params, total, train, holdout)
                tag += " <-- best holdout" if "holdout" not in tag else ""
            line = (f"trial {i:3d}: total={total:7d}  "
                    f"train={train:7d}  hold={holdout:7d}  "
                    f"({res['elapsed']:.1f}s){tag}")
            print(line)
            logf.write(line + "\n")
            logf.flush()

    print()
    if best_row:
        print(f"Best total: trial {best_row[0]}, total={best_row[2]}, "
              f"train={best_row[3]}, holdout={best_row[4]}")
        print(f"  params: {json.dumps(best_row[1], sort_keys=True)}")
    if best_holdout_row:
        print(f"Best holdout: trial {best_holdout_row[0]}, total={best_holdout_row[2]}, "
              f"train={best_holdout_row[3]}, holdout={best_holdout_row[4]}")
        print(f"  params: {json.dumps(best_holdout_row[1], sort_keys=True)}")
    print(f"Results: {csv_path}")


if __name__ == "__main__":
    main()
