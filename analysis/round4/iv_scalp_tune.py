"""IV-scalp parameter tuner via R4 historical replay.

Workflow per trial:
  1. Sample params from a sane range (uniform random or coarse grid).
  2. Spawn `prosperity3bt traders/round4/submission_tunable.py 4 --merge-pnl
     --no-out --no-progress` with PROSPERITY_PARAMS=<json> in env.
  3. Parse per-day per-asset PnL from stdout.
  4. Score: total D1+D2+D3 PnL; track TRAIN=D1+D2 / HOLDOUT=D3 separately.

Output: tmp/optimizer/iv_scalp_tune_<timestamp>/
   - results.csv  one row per trial: trial, params (one column each),
                  total_d1, total_d2, total_d3, train, holdout, total,
                  per-asset PnL columns
   - log.txt      stdout from each trial (just the profit summary)
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
from typing import Dict, List, Optional, Tuple


REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "traders" / "round4" / "submission_tunable.py"

# (name, kind, lo, hi)  kind in {"int", "float"}
PARAM_SPACE: List[Tuple[str, str, float, float]] = [
    ("THR_OPEN",            "float", 0.30, 1.50),
    ("THR_CLOSE",           "float", -0.50, 0.50),
    ("IV_SCALPING_THR",     "float", 0.40, 1.50),
    ("SCALP_MAX_PER_TICK",  "int",   20,   150),
    ("THEO_NORM_WINDOW",    "int",   50,   300),
    ("IV_SCALPING_WINDOW",  "int",   50,   300),
    ("LOW_VEGA_THR_ADJ",    "float", 0.0,  1.0),
    ("LOW_VEGA_CUTOFF",     "float", 0.5,  5.0),
    ("SMILE_A_ALPHA",       "float", 0.001, 0.05),
]

# Per-asset columns we care about
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


def sample_params(rng: random.Random) -> Dict[str, float]:
    p: Dict[str, float] = {}
    for name, kind, lo, hi in PARAM_SPACE:
        if kind == "int":
            p[name] = rng.randint(int(lo), int(hi))
        else:
            p[name] = round(rng.uniform(lo, hi), 4)
    return p


def baseline_params() -> Dict[str, float]:
    return {
        "THR_OPEN": 0.5,
        "THR_CLOSE": 0.0,
        "IV_SCALPING_THR": 0.7,
        "SCALP_MAX_PER_TICK": 60,
        "THEO_NORM_WINDOW": 100,
        "IV_SCALPING_WINDOW": 100,
        "LOW_VEGA_THR_ADJ": 0.5,
        "LOW_VEGA_CUTOFF": 1.0,
        "SMILE_A_ALPHA": 0.01,
    }


def parse_output(stdout: str) -> Dict:
    """Parse prosperity3bt --merge-pnl output. Schema:
       For each of 3 days, per-asset lines + 'Total profit: X'
       Then a 'Profit summary:' block with 'Round 4 day N: X' and
       a final 'Total profit: X'.
    """
    per_day_assets: Dict[int, Dict[str, int]] = {1: {}, 2: {}, 3: {}}
    per_day_total: Dict[int, int] = {1: 0, 2: 0, 3: 0}
    total = 0

    cur_day = 0
    in_summary = False
    last_total_for_day = None
    seen_day_in_block = 0
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("Backtesting") and "day" in line:
            m = re.search(r"day (\d)", line)
            if m:
                seen_day_in_block += 1
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


def run_trial(params: Dict[str, float], timeout: int = 240) -> Dict:
    env = dict(os.environ)
    env["PROSPERITY_PARAMS"] = json.dumps(params)
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


def write_csv_header(path: Path) -> List[str]:
    cols = ["trial"]
    for name, *_ in PARAM_SPACE:
        cols.append(name)
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
    ap.add_argument("--n", type=int, default=80, help="Number of random trials")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", type=str, default=None,
                    help="Output dir; default tmp/optimizer/iv_scalp_tune_<ts>/")
    ap.add_argument("--include-baseline", action="store_true", default=True)
    ap.add_argument("--extra-trials-json", type=str, default=None,
                    help="Path to JSON list of extra param dicts to run "
                         "(e.g. neighborhood probes after random search).")
    args = ap.parse_args()

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = REPO / "tmp" / "optimizer" / f"iv_scalp_tune_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"
    log_path = out_dir / "log.txt"
    cols = write_csv_header(csv_path)

    rng = random.Random(args.seed)
    trials: List[Dict[str, float]] = []
    if args.include_baseline:
        trials.append(baseline_params())
    for _ in range(args.n):
        trials.append(sample_params(rng))
    if args.extra_trials_json:
        extra = json.loads(Path(args.extra_trials_json).read_text(encoding="utf-8"))
        for p in extra:
            trials.append(p)

    print(f"[iv_scalp_tune] out_dir={out_dir}")
    print(f"[iv_scalp_tune] running {len(trials)} trials")

    best_total = -10**12
    best_row = None
    with log_path.open("w", encoding="utf-8") as logf:
        for i, params in enumerate(trials):
            res = run_trial(params)
            row = {"trial": i}
            row.update({k: params[k] for k in params})
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
                tag = " <-- best"
            line = (f"trial {i:3d}: total={total:7d}  "
                    f"train={train:7d}  hold={holdout:7d}  "
                    f"({res['elapsed']:.1f}s){tag}")
            print(line)
            logf.write(line + "\n")
            logf.flush()

    print()
    print(f"Best so far: trial {best_row[0]}, total={best_row[2]}, "
          f"train={best_row[3]}, holdout={best_row[4]}")
    print(f"Best params: {json.dumps(best_row[1], sort_keys=True)}")
    print(f"Results: {csv_path}")


if __name__ == "__main__":
    main()
