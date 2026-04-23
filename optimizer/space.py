"""Parameter space definition.

A `ParamSpace` is a declarative description of the search space for a study.
Each parameter is either continuous (`FloatParam`), integer (`IntParam`), or
categorical (`CategoricalParam`). Float and int params support a `log` flag
that asks Optuna to sample in log space — standard when the sensible range
spans multiple orders of magnitude (e.g. a sample-count threshold from 50 to
5000).

`suggest(trial, name, spec)` translates a spec into the right `trial.suggest_*`
call so the rest of the code never imports Optuna directly.

Constraints are expressed as Python expressions evaluated over the sampled
param dict: `"IPR_ASK_OFFSET_1 < IPR_ASK_OFFSET_2"`. A trial that violates any
constraint is pruned — Optuna treats it as an infeasible sample without
polluting the study with a synthetic penalty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import optuna


@dataclass(frozen=True)
class FloatParam:
    low: float
    high: float
    log: bool = False
    step: float | None = None

    def suggest(self, trial: optuna.Trial, name: str) -> float:
        return trial.suggest_float(name, self.low, self.high, log=self.log, step=self.step)


@dataclass(frozen=True)
class IntParam:
    low: int
    high: int
    log: bool = False
    step: int = 1

    def suggest(self, trial: optuna.Trial, name: str) -> int:
        return trial.suggest_int(name, self.low, self.high, log=self.log, step=self.step)


@dataclass(frozen=True)
class CategoricalParam:
    choices: tuple[Any, ...]

    def suggest(self, trial: optuna.Trial, name: str) -> Any:
        return trial.suggest_categorical(name, list(self.choices))


ParamSpec = FloatParam | IntParam | CategoricalParam


@dataclass
class ParamSpace:
    params: dict[str, ParamSpec] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)

    def sample(self, trial: optuna.Trial) -> dict[str, Any]:
        return {name: spec.suggest(trial, name) for name, spec in self.params.items()}

    def check_constraints(self, values: Mapping[str, Any]) -> list[str]:
        failures: list[str] = []
        for expr in self.constraints:
            try:
                ok = bool(eval(expr, {"__builtins__": {}}, dict(values)))
            except Exception as exc:
                failures.append(f"{expr!r} raised {exc!r}")
                continue
            if not ok:
                failures.append(expr)
        return failures


def parse_param_spec(raw: Mapping[str, Any]) -> ParamSpec:
    """Translate a YAML-style dict into a typed `ParamSpec`.

    Canonical shapes:
        {type: float, low: 0.05, high: 0.30, log: false}
        {type: int,   low: 100,  high: 1000, log: true}
        {type: categorical, choices: [a, b, c]}
    """
    kind = str(raw.get("type", "")).lower()
    if kind == "float":
        return FloatParam(
            low=float(raw["low"]),
            high=float(raw["high"]),
            log=bool(raw.get("log", False)),
            step=float(raw["step"]) if raw.get("step") is not None else None,
        )
    if kind == "int":
        return IntParam(
            low=int(raw["low"]),
            high=int(raw["high"]),
            log=bool(raw.get("log", False)),
            step=int(raw.get("step", 1)),
        )
    if kind in ("categorical", "choice", "choices"):
        choices = raw.get("choices") or raw.get("values")
        if not isinstance(choices, Sequence) or not choices:
            raise ValueError(f"categorical param needs non-empty choices: {raw!r}")
        return CategoricalParam(choices=tuple(choices))
    raise ValueError(f"unknown param type {kind!r} in spec {raw!r}")


def parse_space(raw: Mapping[str, Any]) -> ParamSpace:
    params_raw = raw.get("params") or {}
    if not isinstance(params_raw, Mapping):
        raise ValueError("`params` must be a mapping")
    params = {str(name): parse_param_spec(spec) for name, spec in params_raw.items()}
    constraints_raw = raw.get("constraints") or []
    if not isinstance(constraints_raw, Sequence):
        raise ValueError("`constraints` must be a list of strings")
    return ParamSpace(params=params, constraints=[str(c) for c in constraints_raw])
