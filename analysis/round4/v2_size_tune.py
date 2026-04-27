"""V2 size-knob joint tuner via R4 historical replay.

V2's size knobs (VEV_BASE_SIZE, MR_MM_LEVEL_SIZE, HY_MM_BASE_SIZE,
BASE_MM_SIZE, OBI tier sizes) were tuned in pieces (search-2 / search-4)
and never retuned post the V2 IV-scalp shipping. This searches them
jointly with proper train/holdout audit.
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
TRADER = REPO / "traders" / "round4" / "submission_size_tunable.py"

# (name, kind, lo, hi)  kind in {"int", "float"}
# Centered around V2's defaults; range +/- 2x. Train/holdout audit will
# detect overfit (same negative correlation tell as v7_optimp_tune).
PARAM_SPACE: List[Tuple[str, str, float, float]] = [
    ("VEV_BASE_SIZE",          "int",   1,    20),    # V2: 3
    ("MR_MM_LEVEL_SIZE",       "int",   8,    40),    # V2: 13
    ("HY_MM_BASE_SIZE",        "int",   30,   120),   # V2: 54
    ("BASE_MM_SIZE",           "int",   15,   80),    # V2: 37
    ("MR_K",                   "float", 0.02, 0.10),  # V2: 0.045
    ("MR_MAX_FRAC",            "float", 0.30, 0.70),  # V2: 0.49
    ("VEV_SOFT_POS_FRAC",      "float", 0.40, 0.85),  # V2: 0.6
    ("HY_SOFT_POS_FRAC",       "float", 0.30, 0.65),  # V2: 0.43
    ("VEV_SIZES_MILD_BIG",     "int",   12,   40),    # V2: 22
    ("VEV_SIZES_MILD_SMALL",   "int",   3,    18),    # V2: 8
    ("VEV_SIZES_STRONG_BIG",   "int",   18,   55),    # V2: 30
    ("VEV_SIZES_STRONG_SMALL", "int",   1,    10),    # V2: 2
    ("VEV_SIZES_EXTREME_BIG",  "int",   25,   75),    # V2: 40
    ("VEV_SIZES_EXTREME_SMALL","int",   1,    10),    # V2: 3
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
    """V2 size defaults — should reproduce 29,934."""
    return {
        "VEV_BASE_SIZE": 3,
        "MR_MM_LEVEL_SIZE": 13,
        "HY_MM_BASE_SIZE": 54,
        "BASE_MM_SIZE": 37,
        "MR_K": 0.04481152690538941,
        "MR_MAX_FRAC": 0.4925933073268412,
        "VEV_SOFT_POS_FRAC": 0.6,
        "HY_SOFT_POS_FRAC": 0.43174743324315,
        "VEV_SIZES_MILD_BIG": 22,
        "VEV_SIZES_MILD_SMALL": 8,
        "VEV_SIZES_STRONG_BIG": 30,
        "VEV_SIZES_STRONG_SMALL": 2,
        "VEV_SIZES_EXTREME_BIG": 40,
        "VEV_SIZES_EXTREME_SMALL": 3,
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
        out_dir = REPO / "tmp" / "optimizer" / f"v2_size_tune_{ts}"
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

    print(f"[v2_size_tune] out_dir={out_dir}")
    print(f"[v2_size_tune] running {len(trials)} trials")

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
