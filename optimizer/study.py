"""Study orchestration — ties YAML config, param space, sampler, runner, and
objective together behind one `run_study(config)` entry point.

Lifecycle of a single trial:
    1. Optuna's sampler proposes params (honouring the search strategy).
    2. ParamSpace.check_constraints filters infeasible samples — violations
       raise TrialPruned so Optuna does not record them as failures.
    3. The runner spawns `prosperity4mcbt` in a dedicated trial dir with the
       param dict injected as the PROSPERITY_PARAMS env var.
    4. The objective reduces the per-session PnL arrays to a scalar.
    5. Optuna stores the trial; we also attach per-metric values as
       `trial.user_attrs` so reports can show them later.

Parallelism: Optuna's `study.optimize(n_jobs=N)` runs N trials concurrently on
threads. Each thread has its own subprocess, its own trial dir, its own env
dict — safe. Physical-core budget is `n_jobs × rust_threads`; tune down if
you see CPU thrash.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import optuna
import pandas as pd

from optimizer.objective import Composite
from optimizer.runner import RunnerError, SimConfig, run_trial
from optimizer.samplers import build_sampler, suppress_optuna_info_logs
from optimizer.space import ParamSpace
from optimizer.store import default_storage_dir, open_study, study_paths, trial_work_dir
from optimizer.validators import (
    cluster_stability,
    deflated_sharpe_ratio,
    load_trial_pnl_matrix,
    param_importance,
    probability_of_backtest_overfitting,
    trial_param_matrix,
)


_TEST_SEED_OFFSET = 10_000_019  # Prime offset so (train seed) + offset is unlikely to collide
                                # with any session-seed the sampler saw during training.


@dataclass
class StudyConfig:
    name: str
    space: ParamSpace
    objective: Composite
    sim: SimConfig
    n_trials: int = 100
    n_jobs: int = 1
    sampler: str = "tpe"
    sampler_options: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    storage_root: Path | None = None
    resume: bool = True
    top_k: int = 10


def run_study(cfg: StudyConfig) -> optuna.Study:
    suppress_optuna_info_logs()
    sampler = build_sampler(cfg.sampler, seed=cfg.seed, options=cfg.sampler_options)
    study = open_study(
        study_name=cfg.name,
        sampler=sampler,
        direction="maximize",
        root=cfg.storage_root,
        load_if_exists=cfg.resume,
    )

    existing = len([t for t in study.trials if t.state.is_finished()])
    remaining = max(cfg.n_trials - existing, 0)
    if remaining == 0:
        print(f"[study:{cfg.name}] already has {existing} finished trials — nothing to run.")
    else:
        if existing:
            print(f"[study:{cfg.name}] resuming: {existing} trials on disk, {remaining} to go.")
        else:
            print(f"[study:{cfg.name}] starting fresh: {remaining} trials.")

        t0 = time.time()
        study.optimize(
            _build_objective(cfg),
            n_trials=remaining,
            n_jobs=cfg.n_jobs,
            show_progress_bar=True,
            catch=(RunnerError,),
        )
        print(f"[study:{cfg.name}] finished in {time.time() - t0:.1f}s.")

    retest_results: dict[int, dict[str, Any]] = {}
    if cfg.sim.test_sessions > 0:
        retest_results = _retest_top_k(study, cfg)

    diag = _run_validators(study, cfg)
    _write_reports(study, cfg, diag, retest_results)
    return study


def _retest_top_k(study: optuna.Study, cfg: "StudyConfig") -> dict[int, dict[str, Any]]:
    """Re-run the top-K trials on fresh test seeds and record OOS scores.

    Results are written to a sidecar `retest.json` in the study dir because
    Optuna forbids mutating `user_attrs` on finished trials (its SQLite
    backend raises `UpdateFinishedTrialError`). The report layer merges this
    file back against the trials dataframe at print time.

    Returns the {trial_number: metrics} dict so callers can use it in-process
    without re-reading the file.
    """
    import json as _json

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        return {}

    top = sorted(completed, key=lambda t: t.value if t.value is not None else float("-inf"), reverse=True)
    top = top[: cfg.top_k]

    test_seed = cfg.sim.test_seed
    if test_seed is None:
        base = cfg.sim.seed if cfg.sim.seed is not None else 20260401
        test_seed = base + _TEST_SEED_OFFSET

    test_sim = replace(
        cfg.sim,
        sessions=cfg.sim.test_sessions,
        train_sessions=0,
        val_sessions=0,
        seed=test_seed,
    )

    print(f"\n[study:{cfg.name}] retesting top-{len(top)} on test_seed={test_seed}, sessions={cfg.sim.test_sessions}")

    def _score_one(trial: optuna.trial.FrozenTrial) -> tuple[int, dict[str, Any] | None, str | None]:
        trial_dir = trial_work_dir(cfg.name, trial.number, root=cfg.storage_root) / "test"
        trial_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = run_trial(params=trial.params, sim=test_sim, trial_dir=trial_dir)
        except RunnerError as exc:
            return trial.number, None, str(exc)
        score, parts = cfg.objective.evaluate(result)
        metrics: dict[str, Any] = {
            "score": float(score),
            "n_sessions": int(result.sessions),
            "pnl_mean": float(np.mean(result.total_pnl)),
            "pnl_std": float(np.std(result.total_pnl, ddof=1)) if result.sessions > 1 else 0.0,
            "parts": {k: float(v) for k, v in parts.items()},
            "symbol_means": {
                sym: float(np.mean(series)) for sym, series in result.symbol_pnl.items() if series.size
            },
        }
        return trial.number, metrics, None

    results: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    t0 = time.time()
    workers = max(1, cfg.n_jobs)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_score_one, t): t for t in top}
        for fut in as_completed(futures):
            n, metrics, err = fut.result()
            if err:
                errors.append(f"trial {n}: {err}")
            elif metrics is not None:
                results[n] = metrics
    print(f"[study:{cfg.name}] retest done in {time.time() - t0:.1f}s")
    if errors:
        print(f"[study:{cfg.name}] retest errors ({len(errors)}):")
        for msg in errors[:5]:
            print(f"  - {msg}")

    paths = study_paths(cfg.name, root=cfg.storage_root)
    (paths["base"] / "retest.json").write_text(
        _json.dumps(
            {
                "test_seed": int(test_seed),
                "test_sessions": int(cfg.sim.test_sessions),
                "results": {str(k): v for k, v in results.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


def _build_objective(cfg: StudyConfig):
    """Closes over study config to produce the function Optuna calls per trial.

    When seed splits are active (cfg.sim.uses_splits()), the MC runs
    `train_sessions + val_sessions` in one subprocess and the result is
    sliced. The sampler only sees the train score, so the val slice is a
    genuine out-of-sample sanity check for every trial.
    """

    def objective(trial: optuna.Trial) -> float:
        params = cfg.space.sample(trial)
        failures = cfg.space.check_constraints(params)
        if failures:
            raise optuna.TrialPruned(f"constraints failed: {failures}")

        trial_dir = trial_work_dir(cfg.name, trial.number, root=cfg.storage_root)
        full = run_trial(params=params, sim=cfg.sim, trial_dir=trial_dir)

        if cfg.sim.uses_splits():
            n_train = cfg.sim.train_sessions
            n_val = cfg.sim.val_sessions
            if full.sessions < n_train + n_val:
                raise optuna.TrialPruned(
                    f"MC returned {full.sessions} sessions, expected at least {n_train + n_val}"
                )
            train = full.slice(0, n_train)
            val = full.slice(n_train, n_train + n_val)
            score, parts = cfg.objective.evaluate(train)
            _attach_trial_attrs(trial, train, parts, prefix="train")
            val_score, val_parts = cfg.objective.evaluate(val)
            _attach_trial_attrs(trial, val, val_parts, prefix="val")
            trial.set_user_attr("val_score", float(val_score))
            trial.set_user_attr("train_val_delta", float(score - val_score))
        else:
            score, parts = cfg.objective.evaluate(full)
            _attach_trial_attrs(trial, full, parts, prefix="train")

        trial.set_user_attr("params_hash", _params_hash(params))
        return score

    return objective


def _attach_trial_attrs(
    trial: optuna.Trial,
    result,
    metric_parts: dict[str, float],
    *,
    prefix: str,
) -> None:
    """Stash per-slice metrics in trial.user_attrs under a prefix.

    `prefix` is typically "train" or "val" so the same report renders both
    views. Keeping the PnL moments (mean/std) separate from the objective
    components makes it cheap to eyeball whether a high-scoring trial is
    scoring high because of the raw PnL or a favourable cvar/sharpe term.
    """
    import numpy as _np

    trial.set_user_attr(f"{prefix}/n_sessions", int(result.sessions))
    if result.sessions > 0:
        trial.set_user_attr(f"{prefix}/pnl_mean", float(_np.mean(result.total_pnl)))
    if result.sessions > 1:
        trial.set_user_attr(f"{prefix}/pnl_std", float(_np.std(result.total_pnl, ddof=1)))
    for metric_name, value in metric_parts.items():
        trial.set_user_attr(f"{prefix}/metric/{metric_name}", float(value))
    for symbol, series in result.symbol_pnl.items():
        if series.size:
            trial.set_user_attr(f"{prefix}/symbol/{symbol}/mean", float(_np.mean(series)))


def _params_hash(params: dict) -> str:
    import hashlib
    import json as _json

    blob = _json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _run_validators(study: optuna.Study, cfg: "StudyConfig") -> dict[str, Any]:
    """Compute end-of-study diagnostics. Output is a plain dict so it can be
    serialized to JSON alongside the Parquet/CSV reports."""
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if len(completed) < 5:
        return {"skipped": f"only {len(completed)} completed trials — need 5+ for validators"}

    storage_root = cfg.storage_root or default_storage_dir()
    pnl_matrix, loaded_numbers = load_trial_pnl_matrix(cfg.name, completed, root=storage_root)
    diag: dict[str, Any] = {
        "n_completed_trials": len(completed),
        "n_trials_with_pnl_matrix": len(loaded_numbers),
    }

    # Best trial by training value (what the sampler optimized on).
    best = max(completed, key=lambda t: t.value if t.value is not None else float("-inf"))
    diag["best_trial"] = {
        "number": best.number,
        "value": float(best.value) if best.value is not None else None,
        "params": dict(best.params),
    }

    if pnl_matrix.size and best.number in loaded_numbers:
        best_row = pnl_matrix[loaded_numbers.index(best.number)]
        sharpes = _per_trial_sharpes(pnl_matrix)
        dsr = deflated_sharpe_ratio(best_row, n_trials=len(loaded_numbers), sharpes_for_variance=sharpes)
        diag["dsr"] = {
            "sharpe": dsr.sharpe,
            "probability": dsr.deflated_sharpe_probability,
            "expected_max_sr_under_null": dsr.expected_max_sr_under_null,
            "n_trials": dsr.n_trials,
            "n_sessions": dsr.n_sessions,
            "skew": dsr.skew,
            "kurt_excess": dsr.kurt_excess,
            "reasoning": dsr.reasoning,
        }
        pbo = probability_of_backtest_overfitting(pnl_matrix, max_partitions=min(64, 2 ** max(1, len(loaded_numbers) // 4)))
        diag["pbo"] = {
            "pbo": pbo.pbo,
            "n_trials": pbo.n_trials,
            "n_sessions": pbo.n_sessions,
            "n_partitions_used": pbo.n_partitions_used,
            "reasoning": pbo.reasoning,
        }
    else:
        diag["dsr"] = {"skipped": "best trial has no session_summary.csv on disk"}
        diag["pbo"] = {"skipped": "no PnL matrix available"}

    # Clustering in param space. Only meaningful with at least 2×top_k trials
    # and numeric params.
    params_X, numeric_keys, param_trial_numbers = trial_param_matrix(completed)
    if params_X.size and numeric_keys:
        scores_aligned = [
            next(t.value for t in completed if t.number == n) or float("-inf")
            for n in param_trial_numbers
        ]
        cluster = cluster_stability(
            params_X,
            top_k=max(2, min(cfg.top_k, len(completed) // 2)),
            scores=scores_aligned,
        )
        diag["cluster"] = {
            "top_k": cluster.top_k,
            "median_top_dist": cluster.median_top_dist,
            "median_random_dist": cluster.median_random_dist,
            "ratio": cluster.ratio,
            "reasoning": cluster.reasoning,
            "numeric_params": numeric_keys,
        }
    else:
        diag["cluster"] = {"skipped": "no numeric params or too few trials"}

    imp = param_importance(study)
    diag["importance"] = {
        "importances": imp.importances,
        "reasoning": imp.reasoning,
    }

    # Persist.
    import json as _json

    paths = study_paths(cfg.name, root=cfg.storage_root)
    (paths["base"] / "validators.json").write_text(
        _json.dumps(diag, indent=2, default=_json_default), encoding="utf-8"
    )
    return diag


def _per_trial_sharpes(pnl_matrix: np.ndarray) -> list[float]:
    """Compute per-row Sharpe to seed DSR's variance-of-Sharpe estimate."""
    out: list[float] = []
    for row in pnl_matrix:
        if row.size < 2:
            out.append(0.0)
            continue
        mu = float(np.mean(row))
        sd = float(np.std(row, ddof=1))
        out.append(mu / sd if sd > 1e-12 else 0.0)
    return out


def _json_default(obj: Any) -> Any:
    import numpy as _np

    if isinstance(obj, (_np.integer, _np.floating)):
        return float(obj)
    if isinstance(obj, _np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def _write_reports(
    study: optuna.Study,
    cfg: StudyConfig,
    diagnostics: dict[str, Any] | None = None,
    retest: dict[int, dict[str, Any]] | None = None,
) -> None:
    paths = study_paths(cfg.name, root=cfg.storage_root)

    df = study.trials_dataframe(attrs=("number", "value", "params", "user_attrs", "state"))
    if df.empty:
        print(f"[study:{cfg.name}] no trials to report.")
        return

    # Merge retest metrics in as explicit columns — keeps the parquet / CSV
    # self-describing (no need to join retest.json at read time).
    if retest:
        df["test_score"] = df["number"].map(lambda n: _safe_get(retest, n, "score"))
        df["test_pnl_mean"] = df["number"].map(lambda n: _safe_get(retest, n, "pnl_mean"))
        df["test_pnl_std"] = df["number"].map(lambda n: _safe_get(retest, n, "pnl_std"))

    df.to_parquet(paths["results_parquet"], index=False)

    finished = df[df["state"] == "COMPLETE"].copy()
    if finished.empty:
        print(f"[study:{cfg.name}] no completed trials.")
        return

    # Prefer ranking by test score when it exists — that's the honest OOS number.
    rank_col = "test_score" if "test_score" in finished.columns and finished["test_score"].notna().any() else "value"
    finished.sort_values(rank_col, ascending=False, inplace=True, na_position="last")
    top = finished.head(cfg.top_k)
    top.to_csv(paths["top_csv"], index=False)

    print(f"\n[study:{cfg.name}] top {len(top)} trials (ranked by {rank_col}):")
    summary_cols = _report_columns(top)
    with pd.option_context("display.max_columns", None, "display.width", 220, "display.float_format", "{:,.1f}".format):
        print(top[summary_cols].to_string(index=False))

    if diagnostics:
        _print_diagnostics(diagnostics)

    print(f"\nArtifacts:")
    print(f"  SQLite     : {paths['db']}")
    print(f"  Parquet    : {paths['results_parquet']}")
    print(f"  Top-K CSV  : {paths['top_csv']}")
    print(f"  Validators : {paths['base'] / 'validators.json'}")
    print(f"  Trial logs : {paths['trials_dir']}")


def _print_diagnostics(diag: dict[str, Any]) -> None:
    if "skipped" in diag:
        print(f"\n[validators] skipped: {diag['skipped']}")
        return

    print("\n[validators] Anti-overfitting diagnostics")
    print("-" * 60)

    dsr = diag.get("dsr") or {}
    if "skipped" in dsr:
        print(f"  Deflated Sharpe Ratio : skipped ({dsr['skipped']})")
    else:
        prob = dsr.get("probability", float("nan"))
        verdict = "PASS" if isinstance(prob, float) and prob >= 0.95 else "FLAG"
        print(f"  Deflated Sharpe Ratio : P(true SR>0) = {prob:.3f}  [{verdict}]")
        print(f"      SR={dsr.get('sharpe'):.3f}, null-max SR={dsr.get('expected_max_sr_under_null'):.3f}, "
              f"n={dsr.get('n_sessions')}, trials={dsr.get('n_trials')}")

    pbo = diag.get("pbo") or {}
    if "skipped" in pbo:
        print(f"  Probability of Overfit: skipped ({pbo['skipped']})")
    else:
        p = pbo.get("pbo", float("nan"))
        verdict = "PASS" if isinstance(p, float) and p < 0.25 else ("CAUTION" if p < 0.5 else "FAIL")
        print(f"  Probability of Overfit: PBO = {p:.3f}  [{verdict}]  "
              f"({pbo.get('n_partitions_used')} partitions)")

    cluster = diag.get("cluster") or {}
    if "skipped" in cluster:
        print(f"  Cluster stability     : skipped ({cluster['skipped']})")
    else:
        r = cluster.get("ratio", float("nan"))
        verdict = "CLUSTERED" if r < 1.0 else "SCATTERED"
        print(f"  Cluster stability     : ratio = {r:.2f}  [{verdict}]  "
              f"(top-{cluster.get('top_k')} vs random)")

    imp = diag.get("importance") or {}
    importances = imp.get("importances") or {}
    if importances:
        top = sorted(importances.items(), key=lambda kv: -kv[1])
        print("  fANOVA importance     :")
        for name, value in top:
            print(f"      {name:<25s} {value:.3f}")


def _report_columns(df: pd.DataFrame) -> list[str]:
    """Pick the interesting columns for the top-K console printout."""
    cols: list[str] = ["number", "value"]
    for name in ("test_score", "user_attrs_val_score", "user_attrs_train_val_delta"):
        if name in df.columns:
            cols.append(name)
    cols.extend([c for c in df.columns if c.startswith("params_")])
    for name in ("user_attrs_train/pnl_mean", "user_attrs_val/pnl_mean", "test_pnl_mean"):
        if name in df.columns:
            cols.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for c in cols:
        if c in df.columns and c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _safe_get(retest: dict[int, dict[str, Any]], trial_number: Any, key: str) -> Any:
    try:
        num = int(trial_number)
    except (TypeError, ValueError):
        return None
    metrics = retest.get(num)
    if metrics is None:
        return None
    return metrics.get(key)


def config_from_yaml(raw: Mapping[str, Any], default_name: str | None = None) -> StudyConfig:
    """Build a StudyConfig from a parsed YAML mapping.

    Schema (see studies/*.yaml for examples):

        name: <str>                     # study id, also storage dir
        trader: <path>                  # single-file submission
        sim:
          sessions: <int>
          ticks_per_day: <int?>
          seed: <int?>
          quote_fraction: <float?>
          maf_bid: <int?>
          flags: { ... per-asset flags without leading -- ... }
        params: { ... }                 # parsed by space.parse_space
        constraints: [ ... ]            # parsed by space.parse_space
        objective: { ... }              # parsed by objective.parse_objective
        search:
          sampler: <tpe|random|cmaes|qmc>
          sampler_options: { ... }
          n_trials: <int>
          n_jobs: <int>
          seed: <int?>
        report:
          top_k: <int?>
    """
    from optimizer.objective import parse_objective
    from optimizer.space import parse_space

    name = str(raw.get("name", default_name or "study"))

    trader_raw = raw.get("trader")
    if not trader_raw:
        raise ValueError("study YAML must declare `trader`")
    trader_path = Path(str(trader_raw)).resolve()
    if not trader_path.is_file():
        raise FileNotFoundError(f"trader not found: {trader_path}")

    sim_raw = raw.get("sim") or {}
    sim = SimConfig(
        trader_path=trader_path,
        sessions=int(sim_raw.get("sessions", 100)),
        ticks_per_day=_as_int_or_none(sim_raw.get("ticks_per_day")),
        seed=_as_int_or_none(sim_raw.get("seed")),
        quote_fraction=_as_float_or_none(sim_raw.get("quote_fraction")),
        maf_bid=_as_int_or_none(sim_raw.get("maf_bid")),
        fv_mode=_as_str_or_none(sim_raw.get("fv_mode")),
        trade_mode=_as_str_or_none(sim_raw.get("trade_mode")),
        extra_flags=dict(sim_raw.get("flags") or {}),
        train_sessions=int(sim_raw.get("train_sessions", 0)),
        val_sessions=int(sim_raw.get("val_sessions", 0)),
        test_sessions=int(sim_raw.get("test_sessions", 0)),
        test_seed=_as_int_or_none(sim_raw.get("test_seed")),
    )

    space = parse_space(raw)
    objective = parse_objective(raw.get("objective") or "mean_pnl")

    search = raw.get("search") or {}
    report = raw.get("report") or {}
    return StudyConfig(
        name=name,
        space=space,
        objective=objective,
        sim=sim,
        n_trials=int(search.get("n_trials", 100)),
        n_jobs=int(search.get("n_jobs", 1)),
        sampler=str(search.get("sampler", "tpe")),
        sampler_options=dict(search.get("sampler_options") or {}),
        seed=_as_int_or_none(search.get("seed")),
        top_k=int(report.get("top_k", 10)),
    )


def _as_int_or_none(v: Any) -> int | None:
    return None if v is None else int(v)


def _as_float_or_none(v: Any) -> float | None:
    return None if v is None else float(v)


def _as_str_or_none(v: Any) -> str | None:
    return None if v is None else str(v)
