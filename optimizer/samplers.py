"""Optuna sampler construction.

Thin layer that maps the YAML `search.sampler` key to an Optuna sampler
instance. Sampler-specific options (e.g. `n_startup_trials` for TPE) live in
the `search.sampler_options` sub-block.

Supported samplers:
    random    — RandomSampler. Good baseline, embarrassingly parallel.
    tpe       — TPESampler. Multivariate Tree-structured Parzen Estimator,
                the sensible default for mixed continuous/discrete spaces.
    cmaes     — CmaEsSampler. Gradient-free continuous optimization; strong
                on smooth landscapes but ignores categorical params.
    qmc       — QMCSampler. Quasi-Monte Carlo (Sobol by default) — good for
                initial space-filling. Use as a warmup, then switch to TPE.

LHS / Sobol for initial exploration is achieved by setting `n_startup_trials`
on TPE: those trials are drawn from a space-filling design before the model
kicks in. No separate "LHS sampler" is required.
"""

from __future__ import annotations

from typing import Any, Mapping

import optuna
from optuna.samplers import (
    BaseSampler,
    CmaEsSampler,
    QMCSampler,
    RandomSampler,
    TPESampler,
)


def build_sampler(name: str, seed: int | None, options: Mapping[str, Any]) -> BaseSampler:
    key = (name or "tpe").lower()
    opts = dict(options or {})
    if key == "random":
        return RandomSampler(seed=seed)
    if key in ("tpe", "bayesian"):
        return TPESampler(
            seed=seed,
            multivariate=bool(opts.get("multivariate", True)),
            group=bool(opts.get("group", True)),
            n_startup_trials=int(opts.get("n_startup_trials", 20)),
            n_ei_candidates=int(opts.get("n_ei_candidates", 24)),
            warn_independent_sampling=False,
        )
    if key == "cmaes":
        return CmaEsSampler(
            seed=seed,
            n_startup_trials=int(opts.get("n_startup_trials", 1)),
            sigma0=opts.get("sigma0"),
        )
    if key in ("qmc", "sobol"):
        return QMCSampler(
            seed=seed,
            qmc_type=str(opts.get("qmc_type", "sobol")),
            scramble=bool(opts.get("scramble", True)),
        )
    raise ValueError(f"unknown sampler {name!r}. Known: random, tpe, cmaes, qmc")


def suppress_optuna_info_logs() -> None:
    """Quiet Optuna's per-trial log chatter and experimental-feature warnings.

    We drive our own progress output, so Optuna's default INFO-level trial
    notifications are redundant and slow tight sweeps via stderr flushing.
    The `multivariate` / `group` options on TPESampler are stable in practice
    but still flagged experimental — the warning is noise for our use case.
    """
    import warnings

    from optuna.exceptions import ExperimentalWarning

    warnings.filterwarnings("ignore", category=ExperimentalWarning)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
