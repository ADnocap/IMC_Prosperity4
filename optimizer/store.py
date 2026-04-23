"""Study storage — thin wrapper around Optuna's SQLite backend.

Each study gets its own `.db` file under `tmp/optimizer/<study_name>/`. The
file is the persistent log: runs are resumable, shareable, and browsable with
the `optuna-dashboard` CLI if desired.

We also write a Parquet export at the end of each run for ad-hoc analysis
(`results.parquet`), because reading Optuna's schema directly is awkward and
pandas users want a wide row-per-trial table with params flattened out.
"""

from __future__ import annotations

from pathlib import Path

import optuna


def default_storage_dir() -> Path:
    return Path.cwd() / "tmp" / "optimizer"


def study_paths(study_name: str, root: Path | None = None) -> dict[str, Path]:
    base = (root or default_storage_dir()) / study_name
    base.mkdir(parents=True, exist_ok=True)
    return {
        "base": base,
        "db": base / "study.db",
        "trials_dir": base / "trials",
        "results_parquet": base / "results.parquet",
        "top_csv": base / "top_trials.csv",
    }


def open_study(
    study_name: str,
    sampler: optuna.samplers.BaseSampler,
    direction: str = "maximize",
    root: Path | None = None,
    load_if_exists: bool = True,
) -> optuna.Study:
    paths = study_paths(study_name, root=root)
    storage = f"sqlite:///{paths['db'].as_posix()}"
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        sampler=sampler,
        direction=direction,
        load_if_exists=load_if_exists,
    )


def trial_work_dir(study_name: str, trial_number: int, root: Path | None = None) -> Path:
    base = study_paths(study_name, root=root)["trials_dir"]
    trial_dir = base / f"trial_{trial_number:05d}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    return trial_dir
