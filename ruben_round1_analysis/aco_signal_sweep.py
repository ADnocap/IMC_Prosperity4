#!/usr/bin/env python3
"""Sweep ACO signal constants for traders/a.py and report best settings.

Staged sweep:
1) Broad quick scan for OBI and mid-dev controls.
2) Volatility-widen refinement on top candidates.
3) Heavy confirmation on finalists.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "traders" / "a.py"
TMP_STRATEGY_PATH = ROOT / "traders" / "_aco_sweep_tmp.py"
RESULTS_DIR = ROOT / "tmp" / "aco_sweep"
TMP_OUT = RESULTS_DIR / "tmp_dashboard.json"

MEAN_PNL_PATTERN = re.compile(r"Mean total PnL:\s*([\d,.-]+)")


@dataclass(frozen=True)
class Params:
    obi_trigger: float
    mid_alpha: float
    mid_dev_trigger: float
    vol_widen: float
    vol_widen_strong: float


@dataclass
class Result:
    params: Params
    mode: str
    mean_pnl: float
    raw_output: str


def _replace_constant(code: str, name: str, value: float) -> str:
    pattern = re.compile(rf"^(\s*{name}\s*=\s*).*$", re.MULTILINE)
    if isinstance(value, float):
        value_str = f"{value:.2f}"
    else:
        value_str = str(value)
    next_code, n = pattern.subn(rf"\g<1>{value_str}", code, count=1)
    if n != 1:
        raise RuntimeError(f"failed to replace constant {name}")
    return next_code


def build_strategy(base_code: str, params: Params) -> str:
    code = base_code
    code = _replace_constant(code, "ACO_OBI_TRIGGER", params.obi_trigger)
    code = _replace_constant(code, "ACO_MID_ALPHA", params.mid_alpha)
    code = _replace_constant(code, "ACO_MID_DEV_TRIGGER", params.mid_dev_trigger)
    code = _replace_constant(code, "ACO_VOL_WIDEN", params.vol_widen)
    code = _replace_constant(code, "ACO_VOL_WIDEN_STRONG", params.vol_widen_strong)
    return code


def parse_mean_pnl(output: str) -> float:
    match = MEAN_PNL_PATTERN.search(output)
    if not match:
        raise RuntimeError("could not parse Mean total PnL from backtest output")
    return float(match.group(1).replace(",", ""))


def run_backtest(strategy_path: Path, mode: str) -> tuple[float, str]:
    if mode == "quick":
        cmd = [
            "prosperity4mcbt",
            strategy_path.name,
            "--quick",
            "--out",
            str(TMP_OUT),
        ]
        timeout = 180
    elif mode == "heavy":
        cmd = [
            "prosperity4mcbt",
            strategy_path.name,
            "--heavy",
            "--out",
            str(TMP_OUT),
        ]
        timeout = 480
    else:
        raise ValueError(f"unsupported mode {mode}")

    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"backtest failed ({proc.returncode}): {output[:1000]}")
    return parse_mean_pnl(output), output


def evaluate(base_code: str, params: Params, mode: str) -> Result:
    strategy_code = build_strategy(base_code, params)
    TMP_STRATEGY_PATH.write_text(strategy_code, encoding="utf-8")
    mean, raw_output = run_backtest(TMP_STRATEGY_PATH, mode=mode)
    return Result(params=params, mode=mode, mean_pnl=mean, raw_output=raw_output)


def stage1_grid() -> Iterable[Params]:
    obi_values = [0.20, 0.25, 0.30, 0.35, 0.40]
    mid_alphas = [0.08, 0.12, 0.16, 0.20]
    mid_dev_values = [0.80, 1.20, 1.60]
    for obi, alpha, dev in itertools.product(obi_values, mid_alphas, mid_dev_values):
        yield Params(
            obi_trigger=obi,
            mid_alpha=alpha,
            mid_dev_trigger=dev,
            vol_widen=1.35,
            vol_widen_strong=1.80,
        )


def stage2_grid(base: Params) -> Iterable[Params]:
    vol_widen_values = [1.20, 1.30, 1.40, 1.50]
    vol_strong_values = [1.60, 1.80, 2.00]
    for vw, vws in itertools.product(vol_widen_values, vol_strong_values):
        if vws <= vw + 0.10:
            continue
        yield Params(
            obi_trigger=base.obi_trigger,
            mid_alpha=base.mid_alpha,
            mid_dev_trigger=base.mid_dev_trigger,
            vol_widen=vw,
            vol_widen_strong=vws,
        )


def print_result(prefix: str, result: Result):
    p = result.params
    print(
        f"{prefix} "
        f"obi={p.obi_trigger:.2f} "
        f"alpha={p.mid_alpha:.2f} "
        f"mid_dev={p.mid_dev_trigger:.2f} "
        f"vw={p.vol_widen:.2f} "
        f"vws={p.vol_widen_strong:.2f} "
        f"mean={result.mean_pnl:,.2f}"
    )


def run():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    base_code = TEMPLATE_PATH.read_text(encoding="utf-8")

    all_stage1: list[Result] = []
    s1 = list(stage1_grid())
    print(f"Stage 1: {len(s1)} quick runs")
    for i, params in enumerate(s1, start=1):
        result = evaluate(base_code, params, mode="quick")
        all_stage1.append(result)
        print_result(f"[S1 {i}/{len(s1)}]", result)

    all_stage1.sort(key=lambda r: r.mean_pnl, reverse=True)
    top_stage1 = all_stage1[:5]
    print("\nTop Stage 1:")
    for i, r in enumerate(top_stage1, start=1):
        print_result(f"#{i}", r)

    all_stage2: list[Result] = []
    stage2_params: list[Params] = []
    for base in top_stage1:
        stage2_params.extend(stage2_grid(base.params))

    print(f"\nStage 2: {len(stage2_params)} quick runs (vol refine)")
    for i, params in enumerate(stage2_params, start=1):
        result = evaluate(base_code, params, mode="quick")
        all_stage2.append(result)
        print_result(f"[S2 {i}/{len(stage2_params)}]", result)

    all_stage2.sort(key=lambda r: r.mean_pnl, reverse=True)
    top_stage2 = all_stage2[:3]
    print("\nTop Stage 2 (quick):")
    for i, r in enumerate(top_stage2, start=1):
        print_result(f"#{i}", r)

    heavy_results: list[Result] = []
    print(f"\nStage 3: {len(top_stage2)} heavy runs")
    for i, candidate in enumerate(top_stage2, start=1):
        result = evaluate(base_code, candidate.params, mode="heavy")
        heavy_results.append(result)
        print_result(f"[S3 {i}/{len(top_stage2)}]", result)

    heavy_results.sort(key=lambda r: r.mean_pnl, reverse=True)
    winner = heavy_results[0]

    summary = {
        "winner": asdict(winner.params),
        "winner_heavy_mean_pnl": winner.mean_pnl,
        "stage1_top5": [
            {"params": asdict(r.params), "quick_mean_pnl": r.mean_pnl} for r in top_stage1
        ],
        "stage2_top3_quick": [
            {"params": asdict(r.params), "quick_mean_pnl": r.mean_pnl} for r in top_stage2
        ],
        "stage3_heavy": [
            {"params": asdict(r.params), "heavy_mean_pnl": r.mean_pnl} for r in heavy_results
        ],
    }

    summary_path = RESULTS_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nWinner:")
    print_result("#1", winner)
    print(f"\nSaved summary to {summary_path}")

    if TMP_STRATEGY_PATH.exists():
        TMP_STRATEGY_PATH.unlink()


if __name__ == "__main__":
    run()
