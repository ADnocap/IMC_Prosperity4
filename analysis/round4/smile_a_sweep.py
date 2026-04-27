"""SMILE_A_ALPHA / SMILE_A_INIT sweep for round4 IV-scalp.

Anchored at V2 (all other 8 IV-scalp params held at V2's tuned values), this
sweeps:

  Phase 1: SMILE_A_ALPHA  in {0, 0.0005, 0.001, 0.002, 0.0052 (V2),
                              0.01 (V1), 0.02, 0.05}
  Phase 2: SMILE_A_INIT   in {0.4, 0.5, 0.58 (V2), 0.7, 0.88}, at best alpha
  Phase 3: combined grid IF either phase 1 or 2 improved
  Phase 4 (optional): IV_SCALPING_THR ramp at the best (alpha, init)

Honest holdout: train = D1+D2, holdout = D3. Ship gate:
  total >= V2_total + 1000  AND  holdout >= V2_holdout

Output: tmp/optimizer/smile_a_sweep_<ts>/
   - results.csv  (trial, phase, params, per-day per-asset PnL, totals)
   - log.txt
   - winners.json (best per phase)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "traders" / "round4" / "submission_tunable.py"


# V2 baseline (from traders/round4/submission.py).
V2_PARAMS: Dict[str, float] = {
    "THR_OPEN": 0.536,
    "THR_CLOSE": -0.4,
    "IV_SCALPING_THR": 1.0865,
    "SCALP_MAX_PER_TICK": 35,
    "THEO_NORM_WINDOW": 100,
    "IV_SCALPING_WINDOW": 200,
    "LOW_VEGA_THR_ADJ": 0.653,
    "LOW_VEGA_CUTOFF": 4.0984,
    "SMILE_A_ALPHA": 0.0052,
    "SMILE_A_INIT": 0.580261,
}

# Reported V2 numbers (from CLAUDE.md and submission.py docstring).
# Used as comparison baseline for the writeup; recomputed at trial 0.
V2_TOTAL_REPORTED = 29934
V2_HOLDOUT_REPORTED = 12312  # D3 component (reported in the prompt)


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
        s = line.strip()
        if s.startswith("Backtesting") and "day" in s:
            m = re.search(r"day (\d)", s)
            if m:
                cur_day = int(m.group(1))
                in_summary = False
            continue
        if s.startswith("Profit summary"):
            in_summary = True
            cur_day = 0
            continue
        if in_summary:
            md = LINE_DAY_RE.match(s)
            if md:
                d = int(md.group(1))
                per_day_total[d] = int(md.group(2).replace(",", ""))
                continue
            mt = LINE_TOTAL_RE.match(s)
            if mt:
                total = int(mt.group(1).replace(",", ""))
            continue
        if cur_day in (1, 2, 3):
            ma = LINE_ASSET_RE.match(s)
            if ma:
                asset = ma.group(1)
                if asset in PER_ASSET:
                    per_day_assets[cur_day][asset] = int(
                        ma.group(2).replace(",", "")
                    )
                continue
            mt = LINE_TOTAL_RE.match(s)
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


def csv_columns() -> List[str]:
    cols = ["trial", "phase", "label"]
    for k in V2_PARAMS:
        cols.append(k)
    cols += ["d1_total", "d2_total", "d3_total",
             "train", "holdout", "total", "elapsed", "ok"]
    for asset in PER_ASSET:
        for d in (1, 2, 3):
            cols.append(f"d{d}_{asset}")
    return cols


def append_csv_row(path: Path, cols: List[str], row: Dict) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([row.get(c, "") for c in cols])


def make_params(**overrides: float) -> Dict[str, float]:
    p = dict(V2_PARAMS)
    p.update(overrides)
    return p


def execute(trials: List[Dict], cols: List[str], csv_path: Path,
            log_f, start_trial: int = 0) -> List[Dict]:
    """Run trials and write each result. Returns list of result dicts."""
    results = []
    best_total = -10**12
    for i, t in enumerate(trials):
        idx = start_trial + i
        params = t["params"]
        res = run_trial(params)
        row = {"trial": idx, "phase": t["phase"], "label": t["label"]}
        for k, v in params.items():
            row[k] = v
        if not res["ok"]:
            row["ok"] = 0
            row["elapsed"] = round(res.get("elapsed", 0), 2)
            msg = (f"trial {idx:3d} [{t['phase']}/{t['label']}]: "
                   f"FAIL ({res.get('error')})")
            print(msg)
            log_f.write(msg + "\n")
            if res.get("stderr"):
                log_f.write(res["stderr"] + "\n")
            append_csv_row(csv_path, cols, row)
            results.append({"row": row, "params": params, "trial": idx,
                            "ok": False, "label": t["label"],
                            "phase": t["phase"]})
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
            tag = " <-- best in run"
        line = (f"trial {idx:3d} [{t['phase']}/{t['label']}]: "
                f"total={total:7d}  train={train:7d}  hold={holdout:7d}  "
                f"({res['elapsed']:.1f}s){tag}")
        print(line)
        log_f.write(line + "\n")
        log_f.flush()
        results.append({"row": row, "params": params, "trial": idx,
                        "ok": True, "label": t["label"],
                        "phase": t["phase"], "total": total,
                        "train": train, "holdout": holdout,
                        "d1": d1, "d2": d2, "d3": d3})
    return results


def best(results: List[Dict], key: str = "total") -> Optional[Dict]:
    ok = [r for r in results if r["ok"]]
    if not ok:
        return None
    return max(ok, key=lambda r: r[key])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--phase", type=str, default="all",
                    choices=["all", "1", "2", "3", "4"])
    args = ap.parse_args()

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = REPO / "tmp" / "optimizer" / f"smile_a_sweep_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"
    log_path = out_dir / "log.txt"
    winners_path = out_dir / "winners.json"

    cols = csv_columns()
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)

    print(f"[smile_a_sweep] out_dir={out_dir}")

    log_f = log_path.open("w", encoding="utf-8")
    winners: Dict[str, Dict] = {}

    # === PHASE 1: SMILE_A_ALPHA sweep =====================================
    alpha_grid = [0.0, 0.0005, 0.001, 0.002, 0.0052, 0.01, 0.02, 0.05]
    phase1_trials: List[Dict] = []
    # First trial = V2 baseline (alpha=0.0052) for sanity-check vs reported.
    phase1_trials.append({
        "phase": "1",
        "label": "V2_baseline",
        "params": make_params(),
    })
    for a in alpha_grid:
        if abs(a - 0.0052) < 1e-9:
            continue  # already covered by V2_baseline
        phase1_trials.append({
            "phase": "1",
            "label": f"alpha={a}",
            "params": make_params(SMILE_A_ALPHA=a),
        })

    print(f"\n=== PHASE 1: SMILE_A_ALPHA sweep ({len(phase1_trials)} trials) ===")
    log_f.write(f"\n=== PHASE 1 ({len(phase1_trials)} trials) ===\n")
    p1_results = execute(phase1_trials, cols, csv_path, log_f, start_trial=0)
    p1_best = best(p1_results, "total")
    if p1_best:
        winners["phase1_best_total"] = {
            "trial": p1_best["trial"],
            "label": p1_best["label"],
            "total": p1_best["total"],
            "train": p1_best["train"],
            "holdout": p1_best["holdout"],
            "params": p1_best["params"],
        }

    # === PHASE 2: SMILE_A_INIT sweep at best alpha ========================
    if args.phase in ("all", "2", "3", "4") and p1_best:
        best_alpha = p1_best["params"]["SMILE_A_ALPHA"]
        init_grid = [0.4, 0.5, 0.580261, 0.7, 0.88]
        phase2_trials: List[Dict] = []
        for ini in init_grid:
            phase2_trials.append({
                "phase": "2",
                "label": f"alpha={best_alpha},init={ini}",
                "params": make_params(SMILE_A_ALPHA=best_alpha,
                                       SMILE_A_INIT=ini),
            })
        print(f"\n=== PHASE 2: SMILE_A_INIT sweep at alpha={best_alpha} "
              f"({len(phase2_trials)} trials) ===")
        log_f.write(f"\n=== PHASE 2 alpha={best_alpha} "
                    f"({len(phase2_trials)} trials) ===\n")
        p2_results = execute(phase2_trials, cols, csv_path, log_f,
                             start_trial=len(p1_results))
        p2_best = best(p2_results, "total")
        if p2_best:
            winners["phase2_best_total"] = {
                "trial": p2_best["trial"],
                "label": p2_best["label"],
                "total": p2_best["total"],
                "train": p2_best["train"],
                "holdout": p2_best["holdout"],
                "params": p2_best["params"],
            }
    else:
        p2_results = []

    # === PHASE 3: combined grid IF either phase 1 OR 2 improved over V2 ===
    v2_total_actual = next(
        (r["total"] for r in p1_results
         if r["ok"] and r["label"] == "V2_baseline"), V2_TOTAL_REPORTED
    )
    v2_holdout_actual = next(
        (r["holdout"] for r in p1_results
         if r["ok"] and r["label"] == "V2_baseline"), V2_HOLDOUT_REPORTED
    )
    print(f"\n[v2_actual] total={v2_total_actual}, holdout={v2_holdout_actual}")
    log_f.write(f"\n[v2_actual] total={v2_total_actual}, "
                f"holdout={v2_holdout_actual}\n")

    do_phase3 = False
    if args.phase == "all":
        if p1_best and p1_best["total"] > v2_total_actual:
            do_phase3 = True
        if "phase2_best_total" in winners and \
                winners["phase2_best_total"]["total"] > v2_total_actual:
            do_phase3 = True
    elif args.phase == "3":
        do_phase3 = True

    p3_results: List[Dict] = []
    if do_phase3 and p1_best:
        # Cross-product of top-3 alphas and top-3 inits (excluding the already-
        # tested center). Keep size modest.
        alpha_top = sorted(
            [r for r in p1_results if r["ok"]],
            key=lambda r: -r["total"])[:3]
        if p2_results:
            init_top = sorted(
                [r for r in p2_results if r["ok"]],
                key=lambda r: -r["total"])[:3]
            init_vals = [r["params"]["SMILE_A_INIT"] for r in init_top]
        else:
            init_vals = [0.5, 0.58, 0.7]
        alpha_vals = [r["params"]["SMILE_A_ALPHA"] for r in alpha_top]
        seen = set()
        phase3_trials: List[Dict] = []
        for a in alpha_vals:
            for ini in init_vals:
                key = (round(a, 6), round(ini, 6))
                if key in seen:
                    continue
                seen.add(key)
                phase3_trials.append({
                    "phase": "3",
                    "label": f"alpha={a},init={ini}",
                    "params": make_params(SMILE_A_ALPHA=a, SMILE_A_INIT=ini),
                })
        print(f"\n=== PHASE 3: combined (alpha, init) grid "
              f"({len(phase3_trials)} trials) ===")
        log_f.write(f"\n=== PHASE 3 ({len(phase3_trials)} trials) ===\n")
        p3_results = execute(phase3_trials, cols, csv_path, log_f,
                             start_trial=len(p1_results) + len(p2_results))
        p3_best = best(p3_results, "total")
        if p3_best:
            winners["phase3_best_total"] = {
                "trial": p3_best["trial"],
                "label": p3_best["label"],
                "total": p3_best["total"],
                "train": p3_best["train"],
                "holdout": p3_best["holdout"],
                "params": p3_best["params"],
            }

    # === PHASE 4: IV_SCALPING_THR sweep at best (alpha, init), only if a
    # better-than-V2 winner emerged.
    p4_results: List[Dict] = []
    overall_best = best(p1_results + p2_results + p3_results, "total")
    if args.phase in ("all", "4") and overall_best and \
            overall_best["total"] > v2_total_actual:
        best_a = overall_best["params"]["SMILE_A_ALPHA"]
        best_i = overall_best["params"]["SMILE_A_INIT"]
        thr_grid = [0.7, 1.0865, 1.5, 2.0]
        phase4_trials: List[Dict] = []
        for thr in thr_grid:
            if abs(thr - 1.0865) < 1e-9 and abs(best_a - V2_PARAMS["SMILE_A_ALPHA"]) < 1e-9 \
                    and abs(best_i - V2_PARAMS["SMILE_A_INIT"]) < 1e-9:
                continue  # already V2
            phase4_trials.append({
                "phase": "4",
                "label": f"alpha={best_a},init={best_i},thr={thr}",
                "params": make_params(SMILE_A_ALPHA=best_a,
                                       SMILE_A_INIT=best_i,
                                       IV_SCALPING_THR=thr),
            })
        print(f"\n=== PHASE 4: IV_SCALPING_THR sweep at best (alpha, init) "
              f"({len(phase4_trials)} trials) ===")
        log_f.write(f"\n=== PHASE 4 ({len(phase4_trials)} trials) ===\n")
        p4_results = execute(phase4_trials, cols, csv_path, log_f,
                             start_trial=len(p1_results) + len(p2_results)
                                          + len(p3_results))
        p4_best = best(p4_results, "total")
        if p4_best:
            winners["phase4_best_total"] = {
                "trial": p4_best["trial"],
                "label": p4_best["label"],
                "total": p4_best["total"],
                "train": p4_best["train"],
                "holdout": p4_best["holdout"],
                "params": p4_best["params"],
            }

    # === Summary =========================================================
    all_results = p1_results + p2_results + p3_results + p4_results
    overall = best(all_results, "total")
    if overall:
        winners["overall_best"] = {
            "trial": overall["trial"],
            "phase": overall["phase"],
            "label": overall["label"],
            "total": overall["total"],
            "train": overall["train"],
            "holdout": overall["holdout"],
            "params": overall["params"],
        }
        # Ship gate evaluation
        gate_total = overall["total"] >= v2_total_actual + 1000
        gate_holdout = overall["holdout"] >= v2_holdout_actual
        winners["ship_gate"] = {
            "v2_total_actual": v2_total_actual,
            "v2_holdout_actual": v2_holdout_actual,
            "best_total": overall["total"],
            "best_holdout": overall["holdout"],
            "delta_total": overall["total"] - v2_total_actual,
            "delta_holdout": overall["holdout"] - v2_holdout_actual,
            "gate_total_pass": gate_total,
            "gate_holdout_pass": gate_holdout,
            "ship": gate_total and gate_holdout,
        }

    winners_path.write_text(json.dumps(winners, indent=2), encoding="utf-8")
    log_f.write("\n=== WINNERS ===\n")
    log_f.write(json.dumps(winners, indent=2) + "\n")
    log_f.close()

    print("\n=== SUMMARY ===")
    print(json.dumps(winners, indent=2))
    print(f"\nResults: {csv_path}")
    print(f"Winners: {winners_path}")


if __name__ == "__main__":
    main()
