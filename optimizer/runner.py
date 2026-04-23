"""Monte Carlo runner — one trial = one `prosperity4mcbt` subprocess.

Takes a resolved param dict, serializes it to the `PROSPERITY_PARAMS` env var,
spawns `prosperity4mcbt` with a dedicated output directory so parallel trials
never collide, and parses `session_summary.csv` for per-session total + per-
symbol PnL arrays.

The arrays — not the aggregated mean — are what the objective module consumes,
because metrics like Sharpe / CVaR / DSR need the full per-session
distribution. Reducing to a scalar is the objective's job.

Parallelism: the runner is thread-safe per call (each call gets its own
`--out` dir and its own env). Optuna's `study.optimize(n_jobs=N)` runs trials
on N threads; each thread calls `run_trial` which spawns one MC subprocess.
The Rust MC internally threads across sessions, so the outer N is the
concurrent-trial width. Keep `n_jobs * rust_threads` below your physical cores
or you'll thrash.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from optimizer.trader_api import ENV_VAR, encode_overrides


@dataclass
class SimConfig:
    """Static MC-run configuration applied to every trial in a study.

    Session budget is either a single `sessions` value (no splits) or a
    `train_sessions + val_sessions` split that gets run in one MC subprocess
    and sliced post-hoc. `test_sessions` is NOT run per-trial — it is
    deferred to the end-of-study retest on top-K trials using `test_seed`,
    which gives an honest out-of-sample number the sampler never saw.

    The split design keeps per-trial cost to one subprocess. An alternative
    would be three separate subprocesses, but that triples runtime for no
    statistical gain — sessions are IID draws, and a within-run slice is as
    valid as a cross-run partition for the OOS diagnostic we want.
    """

    trader_path: Path
    sessions: int = 100
    ticks_per_day: int | None = None
    seed: int | None = None
    quote_fraction: float | None = None
    maf_bid: int | None = None
    fv_mode: str | None = None
    trade_mode: str | None = None
    extra_flags: dict[str, Any] | None = None  # per-asset flags by full name
    workdir_root: Path | None = None
    keep_output: bool = False  # default False: clean per-trial dirs to save disk

    # Split-aware budget. When both train_sessions and val_sessions are > 0,
    # `sessions` is ignored and the per-trial MC runs train+val sessions. The
    # caller is expected to slice the result via TrialResult.slice.
    train_sessions: int = 0
    val_sessions: int = 0
    test_sessions: int = 0          # used only by end-of-study retest
    test_seed: int | None = None    # disjoint from training `seed`

    def uses_splits(self) -> bool:
        return self.train_sessions > 0 and self.val_sessions > 0

    def per_trial_sessions(self) -> int:
        if self.uses_splits():
            return self.train_sessions + self.val_sessions
        return self.sessions

    def to_cli_args(self) -> list[str]:
        args: list[str] = ["--sessions", str(self.per_trial_sessions())]
        if self.ticks_per_day is not None:
            args += ["--ticks-per-day", str(self.ticks_per_day)]
        if self.seed is not None:
            args += ["--seed", str(self.seed)]
        if self.quote_fraction is not None:
            args += ["--quote-fraction", str(self.quote_fraction)]
        if self.maf_bid is not None:
            args += ["--maf-bid", str(self.maf_bid)]
        if self.fv_mode is not None:
            args += ["--fv-mode", str(self.fv_mode)]
        if self.trade_mode is not None:
            args += ["--trade-mode", str(self.trade_mode)]
        for key, value in (self.extra_flags or {}).items():
            # canonicalize: `intarian-pepper-root-start-fv` → `--intarian-pepper-root-start-fv`
            flag = key if key.startswith("--") else f"--{key}"
            args += [flag, str(value)]
        return args


@dataclass
class TrialResult:
    """Raw per-session metrics from one MC run.

    `total_pnl` is a 1-D array of length `sessions`. `symbol_pnl` maps each
    product symbol to a same-length array. Metadata is used by the objective
    module and for logging.
    """

    total_pnl: np.ndarray
    symbol_pnl: dict[str, np.ndarray]
    sessions: int
    output_dir: Path
    returncode: int

    def slice(self, start: int, end: int) -> "TrialResult":
        """Return a view over a contiguous session range.

        Used to split a single MC run's output into train / val partitions —
        sessions are IID draws so index-based slicing is statistically sound
        (sessions 0..n_train and n_train..total are both valid subsamples of
        the same distribution).
        """
        if start < 0 or end > self.sessions or start >= end:
            raise ValueError(f"bad slice [{start}, {end}) for {self.sessions} sessions")
        sliced_symbol = {sym: arr[start:end].copy() for sym, arr in self.symbol_pnl.items()}
        return TrialResult(
            total_pnl=self.total_pnl[start:end].copy(),
            symbol_pnl=sliced_symbol,
            sessions=end - start,
            output_dir=self.output_dir,
            returncode=self.returncode,
        )


_SYMBOL_PNL_SUFFIX = "_pnl"


class RunnerError(RuntimeError):
    """Raised when the MC subprocess fails or produces unusable output."""


def run_trial(
    params: Mapping[str, Any],
    sim: SimConfig,
    trial_dir: Path,
    seed_override: int | None = None,
) -> TrialResult:
    """Execute one MC run with the given param overrides.

    `trial_dir` must be unique per concurrent trial to keep outputs separated.
    `seed_override` lets the caller drive a seed without mutating the shared
    SimConfig — used by validators (train/val/test splits).
    """
    trial_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env[ENV_VAR] = encode_overrides(dict(params))

    args = [sys.executable, "-m", "backtester.cli_mc", str(sim.trader_path)]
    args += sim.to_cli_args()
    if seed_override is not None:
        # If the config also sets a seed, the later flag wins (argparse semantics).
        args += ["--seed", str(seed_override)]
    args += ["--out", str(trial_dir)]

    log_path = trial_dir / "stdout.log"
    with log_path.open("w", encoding="utf-8") as log_f:
        proc = subprocess.run(
            args,
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True,
        )

    if proc.returncode != 0:
        tail = _tail(log_path, 40)
        raise RunnerError(
            f"prosperity4mcbt failed (exit {proc.returncode}) for params={dict(params)!r}\n"
            f"--- last log lines ---\n{tail}"
        )

    summary_path = trial_dir / "session_summary.csv"
    if not summary_path.is_file():
        # Some runs emit the JSON + summary in a timestamped subdir. Walk for it.
        matches = list(trial_dir.rglob("session_summary.csv"))
        if not matches:
            raise RunnerError(f"session_summary.csv missing under {trial_dir}")
        summary_path = matches[0]

    total, symbol = _parse_session_summary(summary_path)
    if total.size == 0:
        raise RunnerError(f"session_summary.csv empty at {summary_path}")

    result = TrialResult(
        total_pnl=total,
        symbol_pnl=symbol,
        sessions=int(total.size),
        output_dir=trial_dir,
        returncode=proc.returncode,
    )

    if not sim.keep_output:
        # Keep only the summary CSV + log — dashboard.json and per-session dumps are heavy.
        _prune_trial_dir(trial_dir)

    return result


def _parse_session_summary(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        symbol_cols = [c for c in fields if c.endswith(_SYMBOL_PNL_SUFFIX) and c != "total_pnl"]
        total: list[float] = []
        by_symbol: dict[str, list[float]] = {c: [] for c in symbol_cols}
        for row in reader:
            total.append(float(row["total_pnl"]))
            for c in symbol_cols:
                by_symbol[c].append(float(row[c]))
    total_arr = np.asarray(total, dtype=np.float64)
    symbol_arr = {
        c[: -len(_SYMBOL_PNL_SUFFIX)]: np.asarray(vs, dtype=np.float64)
        for c, vs in by_symbol.items()
    }
    return total_arr, symbol_arr


def _prune_trial_dir(trial_dir: Path) -> None:
    keep = {"session_summary.csv", "run_summary.csv", "stdout.log"}
    for entry in trial_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        elif entry.name not in keep:
            try:
                entry.unlink()
            except OSError:
                pass


def _tail(path: Path, n: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "<log unavailable>"
    return "\n".join(lines[-n:])
