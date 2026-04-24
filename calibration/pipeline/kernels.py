"""Port of wasm_compute/src/calibration.rs and formula_search.rs.

All approximations match the Rust originals byte-for-byte (Abramowitz-Stegun
erf, Wilson-Hilferty chi2, Acklam inv_normal) so the CLI pipeline produces
identical p-values to the visualizer's WASM kernels.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence


# ── Math helpers ────────────────────────────────────────────────────


def erf(x: float) -> float:
    """Abramowitz-Stegun 7.1.26 (max abs error ~1.5e-7)."""
    sign = -1.0 if x < 0 else 1.0
    a = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * math.exp(-a * a)
    return sign * y


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / math.sqrt(2.0)))


def two_sided_p(z: float) -> float:
    return 2.0 * (1.0 - normal_cdf(abs(z)))


def chi2_cdf(chi2: float, df: float) -> float:
    """Wilson-Hilferty (acceptable for df ≥ 3, tolerable for df 1-2)."""
    if df <= 0.0 or chi2 <= 0.0:
        return 0.0
    h = 2.0 / (9.0 * df)
    z = ((chi2 / df) ** (1.0 / 3.0) - (1.0 - h)) / math.sqrt(h)
    return normal_cdf(z)


def chi2_p(chi2: float, df: float) -> float:
    return 1.0 - chi2_cdf(chi2, df)


def inv_normal(p: float) -> float:
    """Acklam (2003) rational approximation, max error ~1.15e-9."""
    p = max(1e-12, min(1.0 - 1e-12, p))
    A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
          1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
          6.680131188771972e+01, -1.328068155288572e+01]
    C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
          3.754408661907416e+00]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) / \
               ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((A[0]*r + A[1])*r + A[2])*r + A[3])*r + A[4])*r + A[5])*q / \
               (((((B[0]*r + B[1])*r + B[2])*r + B[3])*r + B[4])*r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) / \
            ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0)


# ── Descriptive stats ──────────────────────────────────────────────


@dataclass
class DescribeOut:
    n: int
    mean: float
    std: float
    min: float
    max: float
    skewness: float
    excess_kurtosis: float
    p01: float; p05: float; p25: float; p50: float; p75: float; p95: float; p99: float


def _quantile_sorted(sorted_v: Sequence[float], q: float) -> float:
    if not sorted_v:
        return 0.0
    pos = q * (len(sorted_v) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = pos - lo
    return sorted_v[lo] * (1.0 - frac) + sorted_v[hi] * frac


def describe(x: Sequence[float]) -> DescribeOut:
    v = [float(t) for t in x if math.isfinite(t)]
    if not v:
        return DescribeOut(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    n = len(v)
    mean = sum(v) / n
    m2 = m3 = m4 = 0.0
    for t in v:
        d = t - mean
        m2 += d * d; m3 += d * d * d; m4 += d * d * d * d
    var = m2 / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    skew = (m3 / n) / std**3 if std > 0 else 0.0
    ek = (m4 / n) / std**4 - 3.0 if std > 0 else 0.0
    s = sorted(v)
    return DescribeOut(
        n, mean, std, s[0], s[-1], skew, ek,
        _quantile_sorted(s, 0.01), _quantile_sorted(s, 0.05),
        _quantile_sorted(s, 0.25), _quantile_sorted(s, 0.50),
        _quantile_sorted(s, 0.75), _quantile_sorted(s, 0.95),
        _quantile_sorted(s, 0.99),
    )


# ── Wilson CI + proportion z-test ──────────────────────────────────


@dataclass
class WilsonOut:
    phat: float
    lo: float
    hi: float
    z: float
    p_value: float


def wilson(k: int, n: int, p0: float = -1.0, alpha: float = 0.05) -> WilsonOut:
    if n == 0:
        return WilsonOut(0.0, 0.0, 0.0, float('nan'), float('nan'))
    n_f = float(n)
    phat = k / n_f
    z_crit = inv_normal(1.0 - alpha / 2.0)
    denom = 1.0 + z_crit * z_crit / n_f
    center = phat + z_crit * z_crit / (2.0 * n_f)
    half = z_crit * math.sqrt((phat * (1.0 - phat) / n_f) + z_crit * z_crit / (4.0 * n_f * n_f))
    lo = (center - half) / denom
    hi = (center + half) / denom
    if 0.0 <= p0 <= 1.0:
        se = math.sqrt(p0 * (1.0 - p0) / n_f)
        z = (phat - p0) / se if se > 0 else 0.0
        p_value = two_sided_p(z)
    else:
        z = float('nan')
        p_value = float('nan')
    return WilsonOut(phat, lo, hi, z, p_value)


# ── χ² uniform GoF ─────────────────────────────────────────────────


@dataclass
class Chi2Out:
    chi2: float
    df: float
    p_value: float
    n: int
    observed: list
    expected: list


def chi2_uniform(samples: Sequence[float], lo: int, hi: int) -> Chi2Out:
    if hi < lo:
        raise ValueError("chi2_uniform: hi < lo")
    n_bins = hi - lo + 1
    observed = [0] * n_bins
    n_total = 0
    for v in samples:
        if not math.isfinite(v):
            continue
        k = int(round(v))
        if lo <= k <= hi:
            observed[k - lo] += 1
            n_total += 1
    expected_each = n_total / n_bins if n_total else 0.0
    expected = [expected_each] * n_bins
    chi2 = 0.0
    if expected_each > 0.0:
        for i, o in enumerate(observed):
            d = o - expected[i]
            chi2 += d * d / expected[i]
    df = float(n_bins - 1)
    p_value = chi2_p(chi2, df)
    return Chi2Out(chi2, df, p_value, n_total, observed, expected)


def chi2_gof(observed_counts: Sequence[float], expected_probs: Sequence[float]) -> Chi2Out:
    obs_f = list(observed_counts)
    probs = list(expected_probs)
    if len(obs_f) != len(probs):
        raise ValueError("chi2_gof: length mismatch")
    n_total = sum(obs_f)
    observed = [int(max(0, round(v))) for v in obs_f]
    expected = [p * n_total for p in probs]
    chi2 = 0.0
    for i, o in enumerate(observed):
        if expected[i] > 0:
            d = o - expected[i]
            chi2 += d * d / expected[i]
    df = float(len(obs_f) - 1)
    return Chi2Out(chi2, df, chi2_p(chi2, df), int(n_total), observed, expected)


# ── 2×2 independence ───────────────────────────────────────────────


@dataclass
class Indep2x2Out:
    observed: list
    expected: list
    chi2: float
    p_value: float
    phi: float


def indep_2x2(both: int, a_only: int, b_only: int, neither: int) -> Indep2x2Out:
    n = both + a_only + b_only + neither
    if n == 0:
        raise ValueError("indep_2x2: empty table")
    n_f = float(n)
    p_a = (both + a_only) / n_f
    p_b = (both + b_only) / n_f
    expected = [
        [p_a * p_b * n_f, p_a * (1.0 - p_b) * n_f],
        [(1.0 - p_a) * p_b * n_f, (1.0 - p_a) * (1.0 - p_b) * n_f],
    ]
    observed = [[both, a_only], [b_only, neither]]
    chi2 = 0.0
    for i in range(2):
        for j in range(2):
            if expected[i][j] > 0:
                d = observed[i][j] - expected[i][j]
                chi2 += d * d / expected[i][j]
    p_value = chi2_p(chi2, 1.0)
    cross = both * neither - a_only * b_only
    phi_sign = 1.0 if cross >= 0 else -1.0
    phi = phi_sign * math.sqrt(chi2 / n_f)
    return Indep2x2Out(observed, expected, chi2, p_value, phi)


# ── Ljung-Box ──────────────────────────────────────────────────────


@dataclass
class LjungOut:
    q: float
    df: float
    p_value: float
    autocorr: list


def ljung_box(x: Sequence[float], max_lag: int) -> LjungOut:
    v = [float(t) for t in x if math.isfinite(t)]
    n = len(v)
    max_lag = min(max_lag, n - 1) if n > 0 else 0
    if n < 2 or max_lag <= 0:
        return LjungOut(0.0, 0.0, 1.0, [])
    mean_v = sum(v) / n
    denom = sum((t - mean_v) ** 2 for t in v)
    ac: list = []
    q = 0.0
    n_f = float(n)
    for k in range(1, max_lag + 1):
        num = 0.0
        for i in range(k, n):
            num += (v[i] - mean_v) * (v[i - k] - mean_v)
        rk = num / denom if denom > 0 else 0.0
        ac.append(rk)
        if n > k:
            q += rk * rk / (n_f - k)
    q *= n_f * (n_f + 2.0)
    df = float(max_lag)
    return LjungOut(q, df, chi2_p(q, df), ac)


# ── Wald-Wolfowitz runs test ───────────────────────────────────────


@dataclass
class RunsOut:
    runs: int
    n1: int
    n2: int
    expected: float
    variance: float
    z: float
    p_value: float


def runs_test(series: Sequence[float]) -> RunsOut:
    v = [(1 if t > 0.5 else 0) for t in series if math.isfinite(t)]
    if len(v) < 2:
        raise ValueError("runs_test: need n >= 2")
    n1 = sum(v)
    n2 = len(v) - n1
    runs = 1
    for i in range(1, len(v)):
        if v[i] != v[i - 1]:
            runs += 1
    n = float(n1 + n2)
    n1f, n2f = float(n1), float(n2)
    expected = 2.0 * n1f * n2f / n + 1.0 if n > 0 else 0.0
    variance = (2.0 * n1f * n2f * (2.0 * n1f * n2f - n)) / (n * n * (n - 1.0)) if n > 1 else 0.0
    z = (runs - expected) / math.sqrt(variance) if variance > 0 else 0.0
    return RunsOut(runs, n1, n2, expected, variance, z, two_sided_p(z))


# ── Run-length geometric ───────────────────────────────────────────


def _ks_p_value(d: float, n: float) -> float:
    if d <= 0.0 or n <= 0.0:
        return 1.0
    lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    s = 0.0
    for j in range(1, 101):
        term = 2.0 * ((-1.0) ** (j - 1)) * math.exp(-2.0 * lam * lam * j * j)
        s += term
        if abs(term) < 1e-10:
            break
    return max(0.0, min(1.0, s))


@dataclass
class RunLenOut:
    run_lengths: list
    empirical_pmf: list
    fitted_pmf: list
    ks_stat: float
    ks_p: float
    mean_length: float
    n_runs: int


def run_length_geom(series: Sequence[float]) -> RunLenOut:
    v = [(1 if t > 0.5 else 0) for t in series if math.isfinite(t)]
    lengths = []
    cur = 0
    for x in v:
        if x == 1:
            cur += 1
        elif cur > 0:
            lengths.append(cur)
            cur = 0
    if cur > 0:
        lengths.append(cur)
    lengths.sort()
    n_runs = len(lengths)
    mean_l = sum(lengths) / n_runs if n_runs else 0.0
    p = 1.0 / mean_l if mean_l > 0 else 1.0
    max_l = lengths[-1] if lengths else 0
    emp = [0.0] * max_l
    fit = [0.0] * max_l
    for l in lengths:
        if l >= 1:
            emp[l - 1] += 1.0 / max(1, n_runs)
    geom_cdf = 0.0
    emp_cdf = 0.0
    ks_stat = 0.0
    for i in range(max_l):
        k = i + 1
        fit_pmf = p * (1.0 - p) ** (k - 1)
        fit[i] = fit_pmf
        geom_cdf += fit_pmf
        emp_cdf += emp[i]
        ks_stat = max(ks_stat, abs(emp_cdf - geom_cdf))
    return RunLenOut(lengths, emp, fit, ks_stat, _ks_p_value(ks_stat, float(n_runs)), mean_l, n_runs)


# ── 2-sample KS ────────────────────────────────────────────────────


@dataclass
class Ks2Out:
    d: float
    p_value: float
    n1: int
    n2: int


def ks_2sample(a: Sequence[float], b: Sequence[float]) -> Ks2Out:
    va = sorted(t for t in a if math.isfinite(t))
    vb = sorted(t for t in b if math.isfinite(t))
    if not va or not vb:
        raise ValueError("ks_2sample: empty sample")
    i = j = 0
    d = 0.0
    n1, n2 = float(len(va)), float(len(vb))
    while i < len(va) and j < len(vb):
        if va[i] <= vb[j]:
            x = va[i]
            while i < len(va) and va[i] == x:
                i += 1
        else:
            x = vb[j]
            while j < len(vb) and vb[j] == x:
                j += 1
        f1 = i / n1
        f2 = j / n2
        d = max(d, abs(f1 - f2))
    n_eff = n1 * n2 / (n1 + n2)
    return Ks2Out(d, _ks_p_value(d, n_eff), len(va), len(vb))


# ── OLS ────────────────────────────────────────────────────────────


@dataclass
class OlsOut:
    alpha: float
    beta: float
    se_alpha: float
    se_beta: float
    t_beta: float
    p_beta: float
    r_squared: float
    residual_std: float
    n: int
    residuals: list = field(default_factory=list)


def ols_regress(x: Sequence[float], y: Sequence[float]) -> OlsOut:
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("ols: length mismatch or n < 3")
    pairs = [(float(a), float(b)) for a, b in zip(x, y) if math.isfinite(a) and math.isfinite(b)]
    n = len(pairs)
    if n < 3:
        raise ValueError("ols: need n >= 3 finite pairs")
    n_f = float(n)
    mx = sum(p[0] for p in pairs) / n_f
    my = sum(p[1] for p in pairs) / n_f
    sxx = syy = sxy = 0.0
    for a, b in pairs:
        dx = a - mx
        dy = b - my
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    if sxx == 0:
        raise ValueError("ols: zero variance in x")
    beta = sxy / sxx
    alpha = my - beta * mx
    ss_res = 0.0
    residuals = []
    for a, b in pairs:
        yh = alpha + beta * a
        r = b - yh
        residuals.append(r)
        ss_res += r * r
    dof = float(n - 2)
    sigma2 = ss_res / dof if dof > 0 else 0.0
    se_beta = math.sqrt(sigma2 / sxx) if sxx > 0 else 0.0
    se_alpha = math.sqrt(sigma2 * (1.0 / n_f + mx * mx / sxx)) if sxx > 0 else 0.0
    t_beta = beta / se_beta if se_beta > 0 else 0.0
    p_beta = two_sided_p(t_beta)
    r_squared = 1.0 - ss_res / syy if syy > 0 else 0.0
    return OlsOut(alpha, beta, se_alpha, se_beta, t_beta, p_beta, r_squared, math.sqrt(sigma2), n, residuals)


# ── KDE + peak detection ───────────────────────────────────────────


@dataclass
class KdeOut:
    grid: list
    density: list
    peaks: list
    bandwidth: float


def kde_peaks(samples: Sequence[float], n_grid: int = 400, bandwidth: float = 0.0) -> KdeOut:
    v = [float(t) for t in samples if math.isfinite(t)]
    n = len(v)
    if n < 3:
        raise ValueError("kde_peaks: need n >= 3")
    mean_v = sum(v) / n
    std = math.sqrt(sum((x - mean_v) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    if bandwidth > 0:
        h = bandwidth
    elif std > 0:
        h = 1.06 * std * n ** (-0.2)
    else:
        h = 1.0
    mn = min(v); mx = max(v)
    pad = 3.0 * h
    lo = mn - pad; hi = mx + pad
    g = max(32, int(n_grid))
    step = (hi - lo) / (g - 1)
    grid = [lo + step * i for i in range(g)]
    density = [0.0] * g
    norm = 1.0 / (n * h * math.sqrt(2.0 * math.pi))
    for x in v:
        lo_i = max(0, int(math.floor((x - 4.0 * h - lo) / step)))
        hi_i = max(0, min(g - 1, int(math.ceil((x + 4.0 * h - lo) / step))))
        for i in range(lo_i, hi_i + 1):
            d = (grid[i] - x) / h
            density[i] += norm * math.exp(-0.5 * d * d)
    max_d = max(density) if density else 0.0
    thresh = max_d * 0.10
    peaks: list = []
    for i in range(2, g - 2):
        d_ = density[i]
        if d_ > thresh and d_ > density[i - 1] and d_ > density[i - 2] and d_ > density[i + 1] and d_ > density[i + 2]:
            peaks.append(i)
    peaks.sort(key=lambda i: -density[i])
    return KdeOut(grid, density, peaks, h)


# ── Fisher combined + Benjamini-Hochberg FDR ──────────────────────


@dataclass
class FisherOut:
    chi2: float
    df: float
    p_value: float


def fisher_combined(p_values: Sequence[float]) -> FisherOut:
    ps = [p for p in p_values if math.isfinite(p) and 0.0 < p <= 1.0]
    if not ps:
        raise ValueError("fisher: no valid p-values")
    chi2 = -2.0 * sum(math.log(p) for p in ps)
    df = 2.0 * len(ps)
    return FisherOut(chi2, df, chi2_p(chi2, df))


def bh_adjust(p_values: Sequence[float]) -> list:
    ps = list(p_values)
    n = len(ps)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: ps[i] if math.isfinite(ps[i]) else 1.0)
    adj = [0.0] * n
    prev = 1.0
    for rank in range(n - 1, -1, -1):
        idx = order[rank]
        k = rank + 1
        raw = ps[idx] * n / k
        a = min(min(raw, prev), 1.0)
        adj[idx] = a
        prev = a
    return adj


# ── Formula search (port of formula_search.rs) ─────────────────────


def _python_round_half_to_even(x: float) -> int:
    """Banker's rounding (matches Rust implementation)."""
    f = math.floor(x)
    frac = x - f
    if frac > 0.5:
        return int(f) + 1
    if frac < 0.5:
        return int(f)
    fi = int(f)
    return fi if fi % 2 == 0 else fi + 1


_ROUND_FNS = {
    "floor": lambda x: int(math.floor(x)),
    "ceil":  lambda x: int(math.ceil(x)),
    "round": _python_round_half_to_even,
}


def _wilson_95(k: int, n: int) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    n_f = float(n)
    phat = k / n_f
    denom = 1.0 + z * z / n_f
    center = phat + z * z / (2.0 * n_f)
    half = z * math.sqrt((phat * (1.0 - phat) / n_f) + z * z / (4.0 * n_f * n_f))
    return ((center - half) / denom, (center + half) / denom)


def _residual_hist(residuals: list) -> list:
    hist = [0] * 11
    for r in residuals:
        c = max(-5, min(5, int(r)))
        hist[c + 5] += 1
    return hist


def _fv_decile_match_rates(fvs: list, hits: list) -> list:
    if not fvs:
        return [0.0] * 10
    sorted_fv = sorted(fvs)
    n = len(sorted_fv)
    cuts = [sorted_fv[min(int((q + 1) / 10 * n), n - 1)] for q in range(10)]
    counts = [0] * 10
    hits_per = [0] * 10
    for i, fv in enumerate(fvs):
        d = next((j for j in range(10) if fv <= cuts[j]), 9)
        counts[d] += 1
        if hits[i]:
            hits_per[d] += 1
    return [(hits_per[j] / counts[j]) if counts[j] else 0.0 for j in range(10)]


@dataclass
class FixedCandidate:
    round_fn: str
    shift: float
    constant: int
    match_rate: float
    cv_match_rate: float
    ci_lo: float
    ci_hi: float
    n: int
    residual_hist: list
    fv_decile_match: list


@dataclass
class PropCandidate:
    round_fn: str
    k: float
    match_rate: float
    cv_match_rate: float
    ci_lo: float
    ci_hi: float
    n: int
    residual_hist: list
    fv_decile_match: list


@dataclass
class FormulaSearchOut:
    fixed_top: list
    proportional_top: list
    winner: str
    winner_index: int


def formula_search(
    fv: Sequence[float],
    price: Sequence[float],
    side_sign: float,
    const_lo: int,
    const_hi: int,
    k_min: float,
    k_max: float,
    k_steps: int,
    top_n: int = 5,
) -> FormulaSearchOut:
    if len(fv) != len(price) or not fv:
        raise ValueError("formula_search: length mismatch or empty")
    pairs = [(float(f), int(round(float(p))))
             for f, p in zip(fv, price)
             if math.isfinite(f) and math.isfinite(p)]
    n = len(pairs)
    if n < 10:
        raise ValueError("formula_search: need n >= 10")
    sign = -1.0 if side_sign < 0 else 1.0
    rounders = ["floor", "ceil", "round"]
    shifts = [-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75]
    mid = n // 2
    fold_a = pairs[:mid]
    fold_b = pairs[mid:]

    fixed: list = []
    for r_name in rounders:
        rfn = _ROUND_FNS[r_name]
        for sh in shifts:
            for c in range(const_lo, const_hi + 1):
                hits_full = 0
                res = []
                hit_vec = []
                fv_vec = []
                for f, p in pairs:
                    pred = rfn(f + sh) + c
                    hit = pred == p
                    if hit:
                        hits_full += 1
                    res.append(p - pred)
                    hit_vec.append(hit)
                    fv_vec.append(f)
                ha = sum(1 for f, p in fold_a if rfn(f + sh) + c == p)
                hb = sum(1 for f, p in fold_b if rfn(f + sh) + c == p)
                cv = (ha / max(1, len(fold_a)) + hb / max(1, len(fold_b))) / 2.0
                lo, hi = _wilson_95(hits_full, n)
                fixed.append(FixedCandidate(
                    r_name, sh, c, hits_full / n, cv, lo, hi, n,
                    _residual_hist(res), _fv_decile_match_rates(fv_vec, hit_vec),
                ))
    fixed.sort(key=lambda c: -c.cv_match_rate)
    fixed_top = fixed[:top_n]

    prop: list = []
    ks_n = max(2, k_steps)
    for r_name in rounders:
        rfn = _ROUND_FNS[r_name]
        for step in range(ks_n):
            k = k_min + (k_max - k_min) * step / (ks_n - 1)
            hits_full = 0
            res = []
            hit_vec = []
            fv_vec = []
            for f, p in pairs:
                pred = rfn(f * (1.0 + sign * k))
                hit = pred == p
                if hit:
                    hits_full += 1
                res.append(p - pred)
                hit_vec.append(hit)
                fv_vec.append(f)
            ha = sum(1 for f, p in fold_a if rfn(f * (1.0 + sign * k)) == p)
            hb = sum(1 for f, p in fold_b if rfn(f * (1.0 + sign * k)) == p)
            cv = (ha / max(1, len(fold_a)) + hb / max(1, len(fold_b))) / 2.0
            lo, hi = _wilson_95(hits_full, n)
            prop.append(PropCandidate(
                r_name, k, hits_full / n, cv, lo, hi, n,
                _residual_hist(res), _fv_decile_match_rates(fv_vec, hit_vec),
            ))
    prop.sort(key=lambda c: -c.cv_match_rate)
    prop_top = prop[:top_n]

    fixed_best_cv = fixed_top[0].cv_match_rate if fixed_top else 0.0
    prop_best_cv = prop_top[0].cv_match_rate if prop_top else 0.0
    if prop_top:
        prop_dec = max(prop_top[0].fv_decile_match) - min(prop_top[0].fv_decile_match)
    else:
        prop_dec = 1.0
    if fixed_top:
        fixed_dec = max(fixed_top[0].fv_decile_match) - min(fixed_top[0].fv_decile_match)
    else:
        fixed_dec = 1.0
    if prop_best_cv > fixed_best_cv + 0.005 and prop_dec < fixed_dec:
        winner = "proportional"
    else:
        winner = "fixed"
    return FormulaSearchOut(fixed_top, prop_top, winner, 0)
