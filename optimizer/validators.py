"""Anti-overfitting diagnostics for finished studies.

Four independent checks, each answering a different question:

1. **Deflated Sharpe Ratio (DSR)** — Bailey & Lopez de Prado (2014). Adjusts
   the in-sample Sharpe of the best trial for multiple-testing bias. Output is
   the probability that the true Sharpe is > 0 after correcting for the number
   of configurations searched, the non-normality of returns, and sample size.
   DSR > 0.95 is the standard "pass" threshold.

2. **Probability of Backtest Overfitting (PBO)** via Combinatorially Symmetric
   Cross-Validation (Bailey, Borwein, Lopez de Prado, Zhu 2014). Splits the
   per-session PnL matrix into paired halves, measures how often the best
   trial on one half ranks below median on the other. PBO > 0.5 = overfit.

3. **Cluster stability** — do the top-K trials cluster in normalized param
   space? A tight cluster means the landscape has a single robust basin.
   Scattered winners mean each "best" is a different noisy local peak.

4. **fANOVA importance** via Optuna. Which params actually move the
   objective? Dimensions with near-zero importance are candidates for
   freezing in future studies.

None of these are decisions the optimizer acts on. They are warning lights
for the human reading the report.
"""

from __future__ import annotations

import csv
import itertools
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import optuna


# -------------------------------------------------------------------------
# Deflated Sharpe Ratio
# -------------------------------------------------------------------------


def _gaussian_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _gaussian_ppf(p: float) -> float:
    """Inverse standard-normal CDF via the Beasley-Springer-Moro approximation.

    Not meant for extreme tails (<1e-7) but adequate for the [0.5, 0.99999]
    range that DSR actually probes.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"ppf arg must be in (0,1), got {p}")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)


def _expected_max_sr(n_trials: int) -> float:
    """Expected max Sharpe of `n_trials` i.i.d. standard-normal samples.

    Uses the Bailey-Lopez de Prado approximation: a weighted mix of the (1-1/N)
    and (1 - 1/(N·e)) quantiles of the standard normal. Accurate for N >= 10.
    """
    if n_trials <= 1:
        return 0.0
    gamma = 0.5772156649015329  # Euler–Mascheroni
    return (
        (1.0 - gamma) * _gaussian_ppf(1.0 - 1.0 / n_trials)
        + gamma * _gaussian_ppf(1.0 - 1.0 / (n_trials * math.e))
    )


@dataclass
class DSRResult:
    sharpe: float
    deflated_sharpe_probability: float
    expected_max_sr_under_null: float
    n_trials: int
    n_sessions: int
    skew: float
    kurt_excess: float
    reasoning: str


def deflated_sharpe_ratio(
    best_pnl: np.ndarray,
    n_trials: int,
    sharpes_for_variance: Sequence[float] | None = None,
) -> DSRResult:
    """DSR of the best trial after multiple-testing correction.

    `best_pnl` is the per-session PnL array of the winner. `n_trials` is the
    number of strategies that were tested (the multiple-testing burden).
    `sharpes_for_variance` is the vector of in-sample Sharpes across all
    trials — used to estimate V[SR]. If omitted, we fall back to 1/sqrt(N-1)
    (the asymptotic variance of a single Sharpe).
    """
    x = np.asarray(best_pnl, dtype=np.float64)
    if x.size < 3:
        return DSRResult(
            sharpe=float("nan"),
            deflated_sharpe_probability=float("nan"),
            expected_max_sr_under_null=float("nan"),
            n_trials=n_trials,
            n_sessions=int(x.size),
            skew=float("nan"),
            kurt_excess=float("nan"),
            reasoning="fewer than 3 sessions — DSR undefined",
        )

    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd if sd > 1e-12 else 0.0

    # Higher moments
    z = (x - mu) / sd if sd > 1e-12 else np.zeros_like(x)
    skew = float(np.mean(z ** 3))
    kurt_excess = float(np.mean(z ** 4) - 3.0)

    # Variance of the Sharpe estimator under the sample moments.
    n = x.size
    denom = max(1 - skew * sr + ((kurt_excess) / 4.0) * (sr ** 2), 1e-12)

    # Benchmark Sharpe under null: expected max of n_trials standard-normal Sharpes
    # scaled by the empirical Sharpe std.
    if sharpes_for_variance is not None and len(sharpes_for_variance) > 1:
        sigma_sr = float(np.std(list(sharpes_for_variance), ddof=1))
    else:
        sigma_sr = 1.0 / math.sqrt(max(n - 1, 1))

    sr0 = sigma_sr * _expected_max_sr(max(n_trials, 2))

    z_stat = ((sr - sr0) * math.sqrt(max(n - 1, 1))) / math.sqrt(denom)
    psr = _gaussian_cdf(z_stat)

    reason = (
        f"SR={sr:.3f} vs null-max SR0={sr0:.3f}; z={z_stat:.2f}; P(true SR > 0)={psr:.3f}."
        + (" Pass." if psr >= 0.95 else " Below the 0.95 threshold — flag.")
    )
    return DSRResult(
        sharpe=sr,
        deflated_sharpe_probability=psr,
        expected_max_sr_under_null=sr0,
        n_trials=n_trials,
        n_sessions=n,
        skew=skew,
        kurt_excess=kurt_excess,
        reasoning=reason,
    )


# -------------------------------------------------------------------------
# Probability of Backtest Overfitting (CSCV)
# -------------------------------------------------------------------------


@dataclass
class PBOResult:
    pbo: float
    n_trials: int
    n_sessions: int
    n_partitions_used: int
    logits: list[float] = field(default_factory=list)
    reasoning: str = ""


def probability_of_backtest_overfitting(
    pnl_matrix: np.ndarray,
    max_partitions: int = 64,
    seed: int | None = 0,
) -> PBOResult:
    """CSCV / PBO on a (trials × sessions) PnL matrix.

    The core idea: partition sessions into two disjoint halves A and B. On A,
    find the best trial by mean PnL. On B, record where that trial's mean PnL
    ranks among all trials. If it's in the bottom half of B, the in-sample
    winner failed OOS — count as an "overfit" event. PBO is the fraction of
    partitions where this happens.

    Exhaustive enumeration over C(n, n/2) partitions is infeasible for n >
    ~20, so we sample `max_partitions` random partitions (with a fixed seed
    for reproducibility).
    """
    M = np.asarray(pnl_matrix, dtype=np.float64)
    if M.ndim != 2 or M.shape[0] < 2 or M.shape[1] < 4:
        return PBOResult(
            pbo=float("nan"),
            n_trials=int(M.shape[0]) if M.ndim == 2 else 0,
            n_sessions=int(M.shape[1]) if M.ndim == 2 else 0,
            n_partitions_used=0,
            reasoning="need at least 2 trials and 4 sessions to compute PBO",
        )
    n_trials, n_sessions = M.shape

    rng = random.Random(seed)
    half = n_sessions // 2
    all_idx = list(range(n_sessions))

    logits: list[float] = []
    overfit_count = 0
    partitions_used = 0

    for _ in range(max_partitions):
        # Sample a random half (order doesn't matter; A is "first half").
        shuffled = all_idx.copy()
        rng.shuffle(shuffled)
        idx_a = np.array(sorted(shuffled[:half]))
        idx_b = np.array(sorted(shuffled[half:2 * half]))

        mu_a = M[:, idx_a].mean(axis=1)
        mu_b = M[:, idx_b].mean(axis=1)

        best_a = int(np.argmax(mu_a))
        # Rank of that trial in B (0 = worst, n_trials-1 = best).
        rank_b = int(np.sum(mu_b <= mu_b[best_a]) - 1)
        relative_rank = rank_b / (n_trials - 1) if n_trials > 1 else 0.5
        # Logit of relative rank. < 0 → below median → overfit.
        eps = 1e-6
        q = max(eps, min(1.0 - eps, relative_rank))
        logit = math.log(q / (1.0 - q))
        logits.append(logit)
        if relative_rank < 0.5:
            overfit_count += 1
        partitions_used += 1

    pbo = overfit_count / partitions_used if partitions_used else float("nan")

    reason = (
        f"best-in-A below median in B: {overfit_count}/{partitions_used} "
        f"partitions → PBO = {pbo:.3f}."
    )
    if pbo > 0.5:
        reason += " Severe overfitting — your top trials don't generalize."
    elif pbo > 0.25:
        reason += " Mild overfitting — treat winners as one candidate, not the answer."
    else:
        reason += " Winners generalize."

    return PBOResult(
        pbo=pbo,
        n_trials=n_trials,
        n_sessions=n_sessions,
        n_partitions_used=partitions_used,
        logits=logits,
        reasoning=reason,
    )


# -------------------------------------------------------------------------
# Cluster stability
# -------------------------------------------------------------------------


@dataclass
class ClusterResult:
    top_k: int
    median_top_dist: float
    median_random_dist: float
    ratio: float
    reasoning: str


def cluster_stability(
    params_matrix: np.ndarray,
    top_k: int = 10,
    scores: Sequence[float] | None = None,
    seed: int | None = 0,
) -> ClusterResult:
    """Ratio of pairwise distance in top-K vs random-K sample of all trials.

    `params_matrix` is a (n_trials × n_params) array of numeric params. Each
    column is z-scored so no one dimension dominates the distance. We compute
    the median pairwise Euclidean distance in the top-K and compare it to the
    median for an equally-sized random sample from the full set. Ratio < 1 =
    top-K is tighter than random = clustered = robust. Ratio > 1 means the
    winners are more spread out than random — each one is a lucky local peak
    rather than a shared plateau.
    """
    X = np.asarray(params_matrix, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] < 2 * top_k or X.shape[1] == 0:
        return ClusterResult(
            top_k=top_k,
            median_top_dist=float("nan"),
            median_random_dist=float("nan"),
            ratio=float("nan"),
            reasoning="need at least 2×top_k trials with ≥1 numeric param",
        )

    # z-score per column; columns with zero variance collapse to zeros (their
    # contribution to pairwise distance is 0, which is the right thing —
    # they're not differentiating trials).
    col_mean = X.mean(axis=0, keepdims=True)
    col_std = X.std(axis=0, keepdims=True)
    col_std[col_std < 1e-12] = 1.0
    Z = (X - col_mean) / col_std

    # Rank trials. If scores omitted, use param-space centroid as a fallback —
    # but in practice the caller always has scores.
    if scores is None:
        raise ValueError("cluster_stability requires `scores` to identify top-K")
    order = np.argsort(-np.asarray(scores, dtype=np.float64))
    top_idx = order[:top_k]

    rng = random.Random(seed)
    n = X.shape[0]
    random_idx = rng.sample(range(n), top_k)

    top_dist = _median_pairwise(Z[top_idx])
    rand_dist = _median_pairwise(Z[random_idx])
    ratio = top_dist / rand_dist if rand_dist > 1e-12 else float("nan")

    if math.isnan(ratio):
        reason = "couldn't compute ratio (degenerate distances)"
    elif ratio < 0.7:
        reason = f"top-K is {ratio:.2f}× spread of random-K — tightly clustered, robust winner."
    elif ratio < 1.1:
        reason = f"top-K is {ratio:.2f}× spread of random-K — moderate clustering."
    else:
        reason = f"top-K is {ratio:.2f}× spread of random-K — scattered winners, results are likely noise."

    return ClusterResult(
        top_k=top_k,
        median_top_dist=top_dist,
        median_random_dist=rand_dist,
        ratio=ratio,
        reasoning=reason,
    )


def _median_pairwise(pts: np.ndarray) -> float:
    if pts.shape[0] < 2:
        return float("nan")
    diffs = pts[:, None, :] - pts[None, :, :]
    dists = np.sqrt((diffs ** 2).sum(axis=-1))
    i, j = np.triu_indices(pts.shape[0], k=1)
    return float(np.median(dists[i, j]))


# -------------------------------------------------------------------------
# fANOVA importance
# -------------------------------------------------------------------------


@dataclass
class ImportanceResult:
    importances: dict[str, float]
    reasoning: str


def param_importance(study: optuna.Study) -> ImportanceResult:
    """Wrap `optuna.importance.get_param_importances` with fallback handling.

    fANOVA needs at least two trials with numeric params and non-constant
    scores. When those conditions aren't met (e.g. only categorical params,
    or every trial returned the same value), it raises — we catch and
    return NaNs with a clear reason string.
    """
    try:
        raw = optuna.importance.get_param_importances(study)
    except Exception as exc:  # ValueError or RuntimeError depending on cause
        return ImportanceResult(importances={}, reasoning=f"fANOVA failed: {exc}")

    imp = {str(k): float(v) for k, v in raw.items()}
    if not imp:
        return ImportanceResult(importances={}, reasoning="no importances produced")

    top = sorted(imp.items(), key=lambda kv: -kv[1])
    lines = [f"  {name:<20s} {value:.3f}" for name, value in top]
    return ImportanceResult(
        importances=imp,
        reasoning="param importances (fANOVA, normalized to sum 1):\n" + "\n".join(lines),
    )


# -------------------------------------------------------------------------
# Loader: trial PnL matrix from on-disk session_summary.csv files
# -------------------------------------------------------------------------


def load_trial_pnl_matrix(
    study_name: str,
    trials: Sequence[optuna.trial.FrozenTrial],
    root: Path,
) -> tuple[np.ndarray, list[int]]:
    """Stack per-trial `session_summary.csv` files into a matrix.

    Returns `(matrix, trial_numbers)` where `matrix` is (n_trials × n_sessions)
    of total_pnl and `trial_numbers` is the corresponding trial IDs. Trials
    without a summary file are skipped (they'll be flagged in the output).
    """
    rows: list[list[float]] = []
    numbers: list[int] = []
    expected_len: int | None = None
    for trial in trials:
        trial_dir = root / study_name / "trials" / f"trial_{trial.number:05d}"
        summary = trial_dir / "session_summary.csv"
        if not summary.is_file():
            continue
        with summary.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            vals = [float(row["total_pnl"]) for row in reader]
        if not vals:
            continue
        if expected_len is None:
            expected_len = len(vals)
        if len(vals) != expected_len:
            # Trim to the shorter of the two — required for a rectangular matrix.
            vals = vals[:expected_len]
        rows.append(vals)
        numbers.append(trial.number)
    if not rows:
        return np.zeros((0, 0)), []
    return np.asarray(rows, dtype=np.float64), numbers


def trial_param_matrix(
    trials: Sequence[optuna.trial.FrozenTrial],
) -> tuple[np.ndarray, list[str], list[int]]:
    """Build a (n_trials × n_numeric_params) matrix from trial params.

    Categorical params are skipped — they can't participate in Euclidean
    distance without an encoding choice that would muddle the diagnostic.
    """
    numbers: list[int] = []
    rows: list[list[float]] = []
    numeric_keys: list[str] | None = None
    for trial in trials:
        row: list[float] = []
        keys: list[str] = []
        for name, value in sorted(trial.params.items()):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                keys.append(name)
                row.append(float(value))
        if numeric_keys is None:
            numeric_keys = keys
        if keys != numeric_keys:
            continue
        rows.append(row)
        numbers.append(trial.number)
    if numeric_keys is None:
        numeric_keys = []
    if not rows:
        return np.zeros((0, 0)), numeric_keys, []
    return np.asarray(rows, dtype=np.float64), numeric_keys, numbers
