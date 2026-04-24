"""Stage 0 — FV process identification.

Port of visualizer/src/pages/calibration/stages/fv_process.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import kernels as K
from .data import FvAndBook


KNOWN_GRIDS = [
    ("1/1024", 1.0 / 1024),
    ("1/100",  1.0 / 100),
    ("1/256",  1.0 / 256),
    ("1/500",  1.0 / 500),
    ("1/10000", 1.0 / 10000),
]


def _detect_quantization(steps: list) -> dict:
    min_abs = float("inf")
    for s in steps:
        a = abs(s)
        if a > 1e-12 and a < min_abs:
            min_abs = a
    if not math.isfinite(min_abs):
        min_abs = 0.0
    best_name, best_val = KNOWN_GRIDS[0]
    best_err = float("inf")
    for name, val in KNOWN_GRIDS:
        err = abs(min_abs - val)
        if err < best_err:
            best_err = err; best_name = name; best_val = val
    tol = best_val * 0.05
    grid = best_name if best_err <= tol else "unknown"
    return {"grid": grid, "value": best_val, "min_abs": min_abs}


@dataclass
class FvFitResult:
    picked_type: str
    diagnostics: dict
    residuals: list
    fitted: list
    delta_fv: list
    fv_series: list = field(default_factory=list)


def run_stage0(data: FvAndBook) -> FvFitResult:
    rows = sorted([r for r in data.rows if r.fv is not None], key=lambda r: r.ts)
    fvs = [r.fv for r in rows]
    n = len(fvs)
    if n < 3:
        raise ValueError("Stage 0: need >= 3 ticks with FV")
    mu_fv = sum(fvs) / n
    s_fv = math.sqrt(sum((v - mu_fv) ** 2 for v in fvs) / max(1, n - 1))

    steps = [fvs[i] - fvs[i - 1] for i in range(1, n)]
    mu_step = sum(steps) / len(steps)
    s_step = math.sqrt(sum((s - mu_step) ** 2 for s in steps) / max(1, len(steps) - 1))
    se_step = s_step / math.sqrt(len(steps))
    z_step = mu_step / se_step if se_step > 0 else 0.0

    idx = list(range(n))
    lin = K.ols_regress(idx, fvs)

    # AC(1) of ΔFV
    num = sum((steps[i] - mu_step) * (steps[i - 1] - mu_step) for i in range(1, len(steps)))
    den = sum((s - mu_step) ** 2 for s in steps)
    ac1 = num / den if den > 0 else 0.0
    ac1_se = 1.0 / math.sqrt(len(steps))
    ac1_z = ac1 / ac1_se
    ac1_p = K.two_sided_p(ac1_z)

    quant = _detect_quantization(steps)
    quant_scale = quant["value"] if quant["value"] > 0 else 1e-6

    if s_fv < quant_scale * 3:
        picked = "constant"
        fitted = [mu_fv] * n
        residuals = [v - mu_fv for v in fvs]
    elif lin.p_beta < 1e-3 and lin.r_squared > 0.9:
        picked = "linear_drift"
        fitted = [lin.alpha + lin.beta * t for t in idx]
        residuals = lin.residuals
    elif ac1_p < 1e-3 and abs(ac1) > 0.1:
        picked = "ar1"
        residuals = [steps[i] - ac1 * steps[i - 1] for i in range(1, len(steps))]
        fitted = [0.0] * n
        fitted[0] = fvs[0]
        for i in range(1, n):
            pred_step = ac1 * steps[i - 2] if i >= 2 else mu_step
            fitted[i] = fitted[i - 1] + pred_step
    else:
        picked = "random_walk"
        residuals = [s - mu_step for s in steps]
        fitted = [0.0] * n
        fitted[0] = fvs[0]
        for i in range(1, n):
            fitted[i] = fitted[i - 1] + mu_step

    max_lag = min(10, max(2, len(residuals) // 4))
    lb = K.ljung_box(residuals, max_lag)

    n_r = len(residuals)
    r_mu = sum(residuals) / n_r
    r_var = sum((r - r_mu) ** 2 for r in residuals) / max(1, n_r - 1)
    r_std = math.sqrt(r_var)
    m3 = sum((r - r_mu) ** 3 for r in residuals)
    m4 = sum((r - r_mu) ** 4 for r in residuals)
    skew = (m3 / n_r) / r_std ** 3 if r_std > 0 else 0.0
    ek = (m4 / n_r) / r_std ** 4 - 3.0 if r_std > 0 else 0.0
    se_skew = math.sqrt(6 / n_r)
    se_kurt = math.sqrt(24 / n_r)
    skew_z = skew / se_skew
    kurt_z = ek / se_kurt

    diag = {
        "n_ticks": n,
        "mean_fv": mu_fv, "std_fv": s_fv,
        "mean_step": mu_step, "std_step": s_step,
        "mean_step_z": z_step, "mean_step_p": K.two_sided_p(z_step),
        "linear_fit": {
            "alpha": lin.alpha, "beta": lin.beta,
            "se_beta": lin.se_beta, "t_beta": lin.t_beta, "p_beta": lin.p_beta,
            "r_squared": lin.r_squared, "residual_std": lin.residual_std,
        },
        "residual_ljung": {"q": lb.q, "df": lb.df, "p": lb.p_value, "ac": lb.autocorr},
        "skewness": skew, "excess_kurtosis": ek,
        "skew_z": skew_z, "skew_p": K.two_sided_p(skew_z),
        "kurt_z": kurt_z, "kurt_p": K.two_sided_p(kurt_z),
        "quantization": quant,
        "delta_ac1": ac1, "delta_ac1_z": ac1_z, "delta_ac1_p": ac1_p,
    }
    return FvFitResult(
        picked_type=picked,
        diagnostics=diag,
        residuals=residuals,
        fitted=fitted,
        delta_fv=steps,
        fv_series=[{"ts": r.ts, "fv": r.fv} for r in rows],
    )
