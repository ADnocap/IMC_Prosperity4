"""Objective functions — reduce per-session PnL arrays to a scalar score.

Keeps a registry of primitive metrics (mean_pnl, std_pnl, sharpe, cvar_5, ...)
that each take a `TrialResult` and return a float. An `Objective` is either a
single metric or a linear combination (`Composite`), declared in the study
YAML and always maximized by the optimizer — so use negative weights for
costs (e.g. CVaR).

Design note: metrics operate on the per-session distribution because anything
worth caring about (risk-adjusted return, tail loss, stability) requires the
full sample, not a pre-aggregated mean. The runner keeps arrays so this
module can evaluate any metric, including ones added later, without rerunning
the sim.

Adding a metric: write a function `(TrialResult) -> float` and register it in
`METRIC_REGISTRY`. YAML users reference it by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from optimizer.runner import TrialResult


MetricFn = Callable[[TrialResult], float]


def mean_pnl(r: TrialResult) -> float:
    return float(np.mean(r.total_pnl))


def std_pnl(r: TrialResult) -> float:
    # Population std; single-session runs return 0.
    if r.total_pnl.size < 2:
        return 0.0
    return float(np.std(r.total_pnl, ddof=1))


def median_pnl(r: TrialResult) -> float:
    return float(np.median(r.total_pnl))


def sharpe(r: TrialResult) -> float:
    """Per-session Sharpe = mean / std. Not annualized — sessions are the unit."""
    if r.total_pnl.size < 2:
        return 0.0
    mu = float(np.mean(r.total_pnl))
    sd = float(np.std(r.total_pnl, ddof=1))
    return mu / sd if sd > 1e-12 else 0.0


def _cvar_at(r: TrialResult, alpha: float) -> float:
    """Expected PnL conditional on being in the bottom `alpha` quantile.

    For a loss-averse objective, combine with weight < 0 so the optimizer is
    penalized for large negative tails.
    """
    if r.total_pnl.size == 0:
        return 0.0
    k = max(1, int(np.ceil(alpha * r.total_pnl.size)))
    sorted_pnl = np.sort(r.total_pnl)
    return float(np.mean(sorted_pnl[:k]))


def cvar_5(r: TrialResult) -> float:
    return _cvar_at(r, 0.05)


def cvar_10(r: TrialResult) -> float:
    return _cvar_at(r, 0.10)


def min_pnl(r: TrialResult) -> float:
    return float(np.min(r.total_pnl)) if r.total_pnl.size else 0.0


def p05_pnl(r: TrialResult) -> float:
    return float(np.quantile(r.total_pnl, 0.05)) if r.total_pnl.size else 0.0


def per_symbol(symbol: str) -> MetricFn:
    """Factory: returns a metric that reports mean PnL for a specific symbol."""

    def fn(r: TrialResult) -> float:
        series = r.symbol_pnl.get(symbol)
        return float(np.mean(series)) if series is not None and series.size else 0.0

    fn.__name__ = f"mean_pnl[{symbol}]"
    return fn


METRIC_REGISTRY: dict[str, MetricFn] = {
    "mean_pnl": mean_pnl,
    "std_pnl": std_pnl,
    "median_pnl": median_pnl,
    "sharpe": sharpe,
    "cvar_5": cvar_5,
    "cvar_10": cvar_10,
    "min_pnl": min_pnl,
    "p05_pnl": p05_pnl,
}


@dataclass(frozen=True)
class Term:
    name: str
    weight: float
    fn: MetricFn


@dataclass
class Composite:
    """Weighted sum of metrics. Optimizer maximizes this scalar.

    Pair negative weights with loss metrics: a `cvar_5` term with weight -0.2
    says "I prefer +1 mean PnL over avoiding 5 XIRECs of tail loss at the 5%
    quantile". The weight scale is entirely up to you — it multiplies raw
    metric values, so mean_pnl (~10000s of XIRECs) and sharpe (O(1)) live on
    very different scales. Either normalize or pick weights with the scales
    in mind.
    """

    terms: list[Term]

    def evaluate(self, r: TrialResult) -> tuple[float, dict[str, float]]:
        parts: dict[str, float] = {}
        total = 0.0
        for term in self.terms:
            value = term.fn(r)
            parts[term.name] = value
            total += term.weight * value
        return total, parts


def parse_objective(raw: Mapping[str, object]) -> Composite:
    """Build a Composite from the `objective:` block of a study YAML.

    Shorthand forms:
        objective: mean_pnl
        objective: { metric: mean_pnl }

    Full form:
        objective:
          terms:
            - { name: mean_pnl, weight: 1.0 }
            - { name: "mean_pnl[OSMIUM]", weight: 0.0 }    # reported, not scored
            - { name: cvar_5,   weight: -0.2 }
    """
    if isinstance(raw, str):
        return Composite(terms=[Term(name=raw, weight=1.0, fn=_resolve_metric(raw))])

    if not isinstance(raw, Mapping):
        raise ValueError(f"objective must be string or mapping, got {type(raw).__name__}")

    if "metric" in raw and "terms" not in raw:
        name = str(raw["metric"])
        return Composite(terms=[Term(name=name, weight=1.0, fn=_resolve_metric(name))])

    terms_raw = raw.get("terms")
    if not isinstance(terms_raw, Sequence):
        raise ValueError("objective.terms must be a list")
    terms: list[Term] = []
    for entry in terms_raw:
        if not isinstance(entry, Mapping):
            raise ValueError(f"term must be a mapping, got {entry!r}")
        name = str(entry["name"])
        weight = float(entry.get("weight", 1.0))
        terms.append(Term(name=name, weight=weight, fn=_resolve_metric(name)))
    if not terms:
        raise ValueError("objective must declare at least one term")
    return Composite(terms=terms)


def _resolve_metric(name: str) -> MetricFn:
    # Accept "mean_pnl[SYMBOL]" to pull per-symbol PnL.
    if "[" in name and name.endswith("]"):
        base, rest = name.split("[", 1)
        symbol = rest[:-1]
        if base.strip() != "mean_pnl":
            raise ValueError(f"only mean_pnl[SYMBOL] is supported, got {name!r}")
        return per_symbol(symbol)
    fn = METRIC_REGISTRY.get(name)
    if fn is None:
        raise ValueError(f"unknown metric {name!r}. Known: {sorted(METRIC_REGISTRY)}")
    return fn
