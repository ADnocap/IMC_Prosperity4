"""`prosperity4opt` entry point.

Loads a YAML study file, builds a StudyConfig, runs the study, and prints a
top-K summary. Progress goes to stderr via the Optuna progress bar; the
scoreboard goes to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import yaml
from typer import Argument, Option, Typer

from optimizer.study import config_from_yaml, run_study


app = Typer(context_settings={"help_option_names": ["--help", "-h"]})


@app.command()
def run(
    study_file: Annotated[
        Path,
        Argument(
            help="Path to the study YAML file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    n_trials: Annotated[
        Optional[int],
        Option("--n-trials", help="Override search.n_trials from the YAML."),
    ] = None,
    n_jobs: Annotated[
        Optional[int],
        Option("--n-jobs", help="Override search.n_jobs from the YAML."),
    ] = None,
    sessions: Annotated[
        Optional[int],
        Option("--sessions", help="Override sim.sessions from the YAML (quick dev iteration)."),
    ] = None,
    name: Annotated[
        Optional[str],
        Option("--name", help="Override the study name (and thus storage dir)."),
    ] = None,
    fresh: Annotated[
        bool,
        Option("--fresh", help="Don't resume prior trials — create a new storage location."),
    ] = False,
    storage_root: Annotated[
        Optional[Path],
        Option("--storage-root", help="Root directory for study storage. Default: tmp/optimizer/."),
    ] = None,
) -> None:
    with study_file.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        print(f"Error: {study_file} did not parse as a YAML mapping.", file=sys.stderr)
        raise SystemExit(1)

    cfg = config_from_yaml(raw, default_name=study_file.stem)

    if name is not None:
        cfg.name = name
    if n_trials is not None:
        cfg.n_trials = n_trials
    if n_jobs is not None:
        cfg.n_jobs = n_jobs
    if sessions is not None:
        cfg.sim.sessions = sessions
    if storage_root is not None:
        cfg.storage_root = storage_root.resolve()
    if fresh:
        cfg.resume = False
        # If the user wants a clean run but didn't bump the name, they'll hit
        # load_if_exists=True on the SQLite. Force a new name by appending a
        # timestamp so we don't silently resume.
        from datetime import datetime

        cfg.name = f"{cfg.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    run_study(cfg)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
