//! Calibration pipeline kernels.
//!
//! Discovery + validation statistics for the Workshop's Calibration tab.
//! Stats-primitive layer — higher-level pipeline stages (formula search,
//! layer detection) live in `formula_search.rs` and call into here.

use js_sys::Float64Array;
use serde::Serialize;
use wasm_bindgen::prelude::*;

// ── Math helpers ────────────────────────────────────────────────────

/// erf(x) via Abramowitz-Stegun 7.1.26 (max abs error ~1.5e-7).
fn erf(x: f64) -> f64 {
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let x = x.abs();
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let y = 1.0
        - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
            + 0.254829592)
            * t
            * (-x * x).exp();
    sign * y
}

/// Φ(z) — standard-normal CDF.
pub fn normal_cdf(z: f64) -> f64 {
    0.5 * (1.0 + erf(z / std::f64::consts::SQRT_2))
}

/// Two-sided p-value from a normal z-statistic.
pub fn two_sided_p(z: f64) -> f64 {
    2.0 * (1.0 - normal_cdf(z.abs()))
}

/// Chi-squared CDF via Wilson-Hilferty (accurate for df ≥ 3, tolerable for df ≥ 1).
/// Returns P(X ≤ chi2) under a chi2(df) distribution.
pub fn chi2_cdf(chi2: f64, df: f64) -> f64 {
    if df <= 0.0 || chi2 <= 0.0 {
        return 0.0;
    }
    let h = 2.0 / (9.0 * df);
    let z = ((chi2 / df).cbrt() - (1.0 - h)) / h.sqrt();
    normal_cdf(z)
}

/// Chi-squared survival p-value.
pub fn chi2_p(chi2: f64, df: f64) -> f64 {
    1.0 - chi2_cdf(chi2, df)
}

// ── Descriptive stats ──────────────────────────────────────────────

#[derive(Serialize)]
pub struct DescribeOut {
    pub n: usize,
    pub mean: f64,
    pub std: f64,
    pub min: f64,
    pub max: f64,
    pub skewness: f64,
    pub excess_kurtosis: f64,
    pub p01: f64, pub p05: f64, pub p25: f64, pub p50: f64, pub p75: f64, pub p95: f64, pub p99: f64,
}

fn quantile_sorted(sorted: &[f64], q: f64) -> f64 {
    if sorted.is_empty() { return 0.0; }
    let pos = q * (sorted.len() - 1) as f64;
    let lo = pos.floor() as usize;
    let hi = (lo + 1).min(sorted.len() - 1);
    let frac = pos - lo as f64;
    sorted[lo] * (1.0 - frac) + sorted[hi] * frac
}

#[wasm_bindgen(js_name = calibDescribe)]
pub fn describe(x: Float64Array) -> Result<JsValue, JsValue> {
    let v: Vec<f64> = x.to_vec().into_iter().filter(|v| v.is_finite()).collect();
    if v.is_empty() {
        return serde_wasm_bindgen::to_value(&DescribeOut {
            n: 0, mean: 0.0, std: 0.0, min: 0.0, max: 0.0,
            skewness: 0.0, excess_kurtosis: 0.0,
            p01: 0.0, p05: 0.0, p25: 0.0, p50: 0.0, p75: 0.0, p95: 0.0, p99: 0.0,
        }).map_err(Into::into);
    }
    let n = v.len();
    let mean: f64 = v.iter().sum::<f64>() / n as f64;
    let mut m2 = 0.0; let mut m3 = 0.0; let mut m4 = 0.0;
    for &x in &v {
        let d = x - mean;
        m2 += d * d; m3 += d * d * d; m4 += d * d * d * d;
    }
    let variance = if n > 1 { m2 / (n - 1) as f64 } else { 0.0 };
    let std = variance.sqrt();
    let skew = if std > 0.0 { (m3 / n as f64) / std.powi(3) } else { 0.0 };
    let ek = if std > 0.0 { (m4 / n as f64) / std.powi(4) - 3.0 } else { 0.0 };
    let mut sorted = v.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let out = DescribeOut {
        n, mean, std,
        min: sorted[0], max: sorted[n - 1],
        skewness: skew, excess_kurtosis: ek,
        p01: quantile_sorted(&sorted, 0.01),
        p05: quantile_sorted(&sorted, 0.05),
        p25: quantile_sorted(&sorted, 0.25),
        p50: quantile_sorted(&sorted, 0.50),
        p75: quantile_sorted(&sorted, 0.75),
        p95: quantile_sorted(&sorted, 0.95),
        p99: quantile_sorted(&sorted, 0.99),
    };
    serde_wasm_bindgen::to_value(&out).map_err(Into::into)
}

// ── Binomial / proportion tests ────────────────────────────────────

#[derive(Serialize)]
pub struct WilsonCI {
    pub phat: f64,
    pub lo: f64,
    pub hi: f64,
    pub z: f64,
    pub p_value: f64,
}

/// Wilson score interval for a binomial proportion + two-sided z-test vs p0.
/// If p0 < 0 the z/p_value fields are NaN (CI only).
#[wasm_bindgen(js_name = calibWilson)]
pub fn wilson(k: u32, n: u32, p0: f64, alpha: f64) -> Result<JsValue, JsValue> {
    if n == 0 {
        return serde_wasm_bindgen::to_value(&WilsonCI {
            phat: 0.0, lo: 0.0, hi: 0.0, z: f64::NAN, p_value: f64::NAN,
        }).map_err(Into::into);
    }
    let n_f = n as f64;
    let phat = k as f64 / n_f;
    // inverse-normal approximation for alpha/2
    let z_crit = inv_normal(1.0 - alpha / 2.0);
    let denom = 1.0 + z_crit * z_crit / n_f;
    let center = phat + z_crit * z_crit / (2.0 * n_f);
    let half = z_crit * ((phat * (1.0 - phat) / n_f) + z_crit * z_crit / (4.0 * n_f * n_f)).sqrt();
    let lo = (center - half) / denom;
    let hi = (center + half) / denom;
    let (z, p_value) = if p0 >= 0.0 && p0 <= 1.0 {
        let se = (p0 * (1.0 - p0) / n_f).sqrt();
        let z = if se > 0.0 { (phat - p0) / se } else { 0.0 };
        (z, two_sided_p(z))
    } else {
        (f64::NAN, f64::NAN)
    };
    serde_wasm_bindgen::to_value(&WilsonCI { phat, lo, hi, z, p_value }).map_err(Into::into)
}

/// Beasley-Springer-Moro rational approximation of the standard-normal quantile.
fn inv_normal(p: f64) -> f64 {
    let p = p.clamp(1e-12, 1.0 - 1e-12);
    // Acklam (2003) rational approximation — max error ~1.15e-9.
    const A: [f64; 6] = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
                         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    const B: [f64; 5] = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
                         6.680131188771972e+01, -1.328068155288572e+01];
    const C: [f64; 6] = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
                         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    const D: [f64; 4] = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
                         3.754408661907416e+00];
    let plow = 0.02425_f64;
    let phigh = 1.0 - plow;
    if p < plow {
        let q = (-2.0 * p.ln()).sqrt();
        (((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
            ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0)
    } else if p <= phigh {
        let q = p - 0.5;
        let r = q * q;
        (((((A[0]*r + A[1])*r + A[2])*r + A[3])*r + A[4])*r + A[5])*q /
            (((((B[0]*r + B[1])*r + B[2])*r + B[3])*r + B[4])*r + 1.0)
    } else {
        let q = (-2.0 * (1.0 - p).ln()).sqrt();
        -(((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
            ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0)
    }
}

// ── Chi-squared goodness-of-fit ────────────────────────────────────

#[derive(Serialize)]
pub struct Chi2Result {
    pub chi2: f64,
    pub df: f64,
    pub p_value: f64,
    pub n: usize,
    /// Observed counts aligned with expected[] for easy plotting.
    pub observed: Vec<u32>,
    pub expected: Vec<f64>,
}

/// χ² GoF vs a discrete uniform on integer bins [lo, hi] inclusive.
/// Counts integer-rounded values in `samples` within the bin range.
#[wasm_bindgen(js_name = calibChi2Uniform)]
pub fn chi2_uniform(samples: Float64Array, lo: i32, hi: i32) -> Result<JsValue, JsValue> {
    if hi < lo {
        return Err(JsValue::from_str("chi2_uniform: hi < lo"));
    }
    let n_bins = (hi - lo + 1) as usize;
    let mut observed = vec![0u32; n_bins];
    let mut n_total = 0usize;
    for v in samples.to_vec() {
        if !v.is_finite() { continue; }
        let k = v.round() as i32;
        if k >= lo && k <= hi {
            observed[(k - lo) as usize] += 1;
            n_total += 1;
        }
    }
    let expected_each = if n_total == 0 { 0.0 } else { n_total as f64 / n_bins as f64 };
    let expected = vec![expected_each; n_bins];
    let mut chi2 = 0.0;
    if expected_each > 0.0 {
        for (i, &o) in observed.iter().enumerate() {
            let d = o as f64 - expected[i];
            chi2 += d * d / expected[i];
        }
    }
    let df = (n_bins - 1) as f64;
    let p_value = chi2_p(chi2, df);
    serde_wasm_bindgen::to_value(&Chi2Result {
        chi2, df, p_value, n: n_total, observed, expected,
    }).map_err(Into::into)
}

/// Generic χ² GoF against user-supplied expected probabilities (must sum to 1).
/// `observed_counts` aligns with `expected_probs`.
#[wasm_bindgen(js_name = calibChi2Gof)]
pub fn chi2_gof(observed_counts: Float64Array, expected_probs: Float64Array) -> Result<JsValue, JsValue> {
    let obs_f: Vec<f64> = observed_counts.to_vec();
    let probs: Vec<f64> = expected_probs.to_vec();
    if obs_f.len() != probs.len() {
        return Err(JsValue::from_str("chi2_gof: length mismatch"));
    }
    let n_total: f64 = obs_f.iter().sum();
    let observed: Vec<u32> = obs_f.iter().map(|v| v.round().max(0.0) as u32).collect();
    let expected: Vec<f64> = probs.iter().map(|&p| p * n_total).collect();
    let mut chi2 = 0.0;
    for (i, &o) in observed.iter().enumerate() {
        if expected[i] > 0.0 {
            let d = o as f64 - expected[i];
            chi2 += d * d / expected[i];
        }
    }
    let df = (obs_f.len() - 1) as f64;
    let p_value = chi2_p(chi2, df);
    serde_wasm_bindgen::to_value(&Chi2Result {
        chi2, df, p_value, n: n_total as usize, observed, expected,
    }).map_err(Into::into)
}

// ── 2×2 independence (chi-squared 1 df) ────────────────────────────

#[derive(Serialize)]
pub struct Indep2x2Result {
    pub observed: [[u32; 2]; 2],
    pub expected: [[f64; 2]; 2],
    pub chi2: f64,
    pub p_value: f64,
    pub phi: f64,   // correlation coefficient (±1 range)
}

#[wasm_bindgen(js_name = calibIndep2x2)]
pub fn indep_2x2(both: u32, a_only: u32, b_only: u32, neither: u32) -> Result<JsValue, JsValue> {
    let n = both + a_only + b_only + neither;
    if n == 0 {
        return Err(JsValue::from_str("indep_2x2: empty table"));
    }
    let n_f = n as f64;
    let p_a = (both + a_only) as f64 / n_f;
    let p_b = (both + b_only) as f64 / n_f;
    let expected = [
        [p_a * p_b * n_f,           p_a * (1.0 - p_b) * n_f],
        [(1.0 - p_a) * p_b * n_f,   (1.0 - p_a) * (1.0 - p_b) * n_f],
    ];
    let observed = [[both, a_only], [b_only, neither]];
    let mut chi2 = 0.0;
    for i in 0..2 {
        for j in 0..2 {
            if expected[i][j] > 0.0 {
                let d = observed[i][j] as f64 - expected[i][j];
                chi2 += d * d / expected[i][j];
            }
        }
    }
    let p_value = chi2_p(chi2, 1.0);
    // Phi coefficient (for 2x2, phi^2 = chi2/n, signed by cross-product)
    let cross = (both as f64) * (neither as f64) - (a_only as f64) * (b_only as f64);
    let phi_sign = if cross >= 0.0 { 1.0 } else { -1.0 };
    let phi = phi_sign * (chi2 / n_f).sqrt();
    serde_wasm_bindgen::to_value(&Indep2x2Result {
        observed, expected, chi2, p_value, phi,
    }).map_err(Into::into)
}

// ── Ljung-Box on a binary / numeric series ─────────────────────────

#[derive(Serialize)]
pub struct LjungBoxResult {
    pub q: f64,
    pub df: f64,
    pub p_value: f64,
    /// Autocorrelation at lags 1..=max_lag.
    pub autocorr: Vec<f64>,
}

#[wasm_bindgen(js_name = calibLjungBox)]
pub fn ljung_box(x: Float64Array, max_lag: u32) -> Result<JsValue, JsValue> {
    let v: Vec<f64> = x.to_vec().into_iter().filter(|v| v.is_finite()).collect();
    let n = v.len();
    let max_lag = (max_lag as usize).min(n.saturating_sub(1));
    if n < 2 || max_lag == 0 {
        return serde_wasm_bindgen::to_value(&LjungBoxResult {
            q: 0.0, df: 0.0, p_value: 1.0, autocorr: vec![],
        }).map_err(Into::into);
    }
    let mean: f64 = v.iter().sum::<f64>() / n as f64;
    let denom: f64 = v.iter().map(|&x| (x - mean) * (x - mean)).sum();
    let mut ac = Vec::with_capacity(max_lag);
    let mut q = 0.0;
    let n_f = n as f64;
    for k in 1..=max_lag {
        let mut num = 0.0;
        for i in k..n {
            num += (v[i] - mean) * (v[i - k] - mean);
        }
        let rk = if denom > 0.0 { num / denom } else { 0.0 };
        ac.push(rk);
        if n > k {
            q += rk * rk / (n_f - k as f64);
        }
    }
    q *= n_f * (n_f + 2.0);
    let df = max_lag as f64;
    let p_value = chi2_p(q, df);
    serde_wasm_bindgen::to_value(&LjungBoxResult {
        q, df, p_value, autocorr: ac,
    }).map_err(Into::into)
}

// ── Wald-Wolfowitz runs test on a binary series ────────────────────

#[derive(Serialize)]
pub struct RunsTestResult {
    pub runs: u32,
    pub n1: u32,
    pub n2: u32,
    pub expected: f64,
    pub variance: f64,
    pub z: f64,
    pub p_value: f64,
}

#[wasm_bindgen(js_name = calibRunsTest)]
pub fn runs_test(series: Float64Array) -> Result<JsValue, JsValue> {
    let v: Vec<u8> = series.to_vec().into_iter()
        .filter_map(|x| if x.is_finite() { Some(if x > 0.5 { 1u8 } else { 0u8 }) } else { None })
        .collect();
    if v.len() < 2 {
        return Err(JsValue::from_str("runs_test: need n >= 2"));
    }
    let n1: u32 = v.iter().filter(|&&x| x == 1).count() as u32;
    let n2: u32 = v.iter().filter(|&&x| x == 0).count() as u32;
    let mut runs: u32 = 1;
    for i in 1..v.len() {
        if v[i] != v[i - 1] {
            runs += 1;
        }
    }
    let n = (n1 + n2) as f64;
    let n1f = n1 as f64;
    let n2f = n2 as f64;
    let expected = if n > 0.0 { 2.0 * n1f * n2f / n + 1.0 } else { 0.0 };
    let variance = if n > 1.0 {
        2.0 * n1f * n2f * (2.0 * n1f * n2f - n) / (n * n * (n - 1.0))
    } else { 0.0 };
    let z = if variance > 0.0 { (runs as f64 - expected) / variance.sqrt() } else { 0.0 };
    let p_value = two_sided_p(z);
    serde_wasm_bindgen::to_value(&RunsTestResult {
        runs, n1, n2, expected, variance, z, p_value,
    }).map_err(Into::into)
}

// ── Run-length distribution + Geometric KS ─────────────────────────

#[derive(Serialize)]
pub struct RunLengthResult {
    /// Lengths of consecutive 1-runs (sorted ascending).
    pub run_lengths: Vec<u32>,
    /// Empirical PMF at 1..=max observed.
    pub empirical_pmf: Vec<f64>,
    /// Geometric PMF with p = 1/mean_length.
    pub fitted_pmf: Vec<f64>,
    /// Kolmogorov-Smirnov statistic against Geometric(p).
    pub ks_stat: f64,
    pub ks_p: f64,
    pub mean_length: f64,
    pub n_runs: u32,
}

/// Approximate 2-sided KS p-value via the Kolmogorov distribution series.
fn ks_p_value(d: f64, n: f64) -> f64 {
    if d <= 0.0 || n <= 0.0 { return 1.0; }
    let lambda = (n.sqrt() + 0.12 + 0.11 / n.sqrt()) * d;
    let mut sum = 0.0;
    for j in 1..=100 {
        let term = 2.0 * (-1.0f64).powi(j - 1) * (-2.0 * lambda * lambda * (j as f64).powi(2)).exp();
        sum += term;
        if term.abs() < 1e-10 { break; }
    }
    sum.clamp(0.0, 1.0)
}

#[wasm_bindgen(js_name = calibRunLengthGeom)]
pub fn run_length_geom(series: Float64Array) -> Result<JsValue, JsValue> {
    let v: Vec<u8> = series.to_vec().into_iter()
        .filter_map(|x| if x.is_finite() { Some(if x > 0.5 { 1u8 } else { 0u8 }) } else { None })
        .collect();
    let mut lengths = Vec::new();
    let mut cur = 0u32;
    for &x in &v {
        if x == 1 { cur += 1; }
        else if cur > 0 { lengths.push(cur); cur = 0; }
    }
    if cur > 0 { lengths.push(cur); }
    lengths.sort();
    let n_runs = lengths.len() as u32;
    let mean = if n_runs > 0 { lengths.iter().sum::<u32>() as f64 / n_runs as f64 } else { 0.0 };
    let p = if mean > 0.0 { 1.0 / mean } else { 1.0 };
    let max_l = lengths.last().copied().unwrap_or(0) as usize;
    let mut emp = vec![0.0; max_l];
    let mut fit = vec![0.0; max_l];
    for &l in &lengths {
        if l >= 1 { emp[(l - 1) as usize] += 1.0 / n_runs.max(1) as f64; }
    }
    let mut geom_cdf_prev = 0.0;
    let mut emp_cdf = 0.0;
    let mut ks_stat = 0.0f64;
    for i in 0..max_l {
        let k = i + 1;
        let fit_pmf = p * (1.0 - p).powi((k - 1) as i32);
        fit[i] = fit_pmf;
        geom_cdf_prev += fit_pmf;
        emp_cdf += emp[i];
        ks_stat = ks_stat.max((emp_cdf - geom_cdf_prev).abs());
    }
    let ks_p = ks_p_value(ks_stat, n_runs as f64);
    serde_wasm_bindgen::to_value(&RunLengthResult {
        run_lengths: lengths,
        empirical_pmf: emp,
        fitted_pmf: fit,
        ks_stat, ks_p, mean_length: mean, n_runs,
    }).map_err(Into::into)
}

// ── Two-sample KS ──────────────────────────────────────────────────

#[derive(Serialize)]
pub struct Ks2Result {
    pub d: f64,
    pub p_value: f64,
    pub n1: usize,
    pub n2: usize,
}

#[wasm_bindgen(js_name = calibKs2)]
pub fn ks_2sample(a: Float64Array, b: Float64Array) -> Result<JsValue, JsValue> {
    let mut va: Vec<f64> = a.to_vec().into_iter().filter(|v| v.is_finite()).collect();
    let mut vb: Vec<f64> = b.to_vec().into_iter().filter(|v| v.is_finite()).collect();
    if va.is_empty() || vb.is_empty() {
        return Err(JsValue::from_str("ks_2sample: empty sample"));
    }
    va.sort_by(|x, y| x.partial_cmp(y).unwrap());
    vb.sort_by(|x, y| x.partial_cmp(y).unwrap());
    let (mut i, mut j) = (0usize, 0usize);
    let mut d = 0.0f64;
    let (n1, n2) = (va.len() as f64, vb.len() as f64);
    while i < va.len() && j < vb.len() {
        if va[i] <= vb[j] {
            let x = va[i]; while i < va.len() && va[i] == x { i += 1; }
        } else {
            let x = vb[j]; while j < vb.len() && vb[j] == x { j += 1; }
        }
        let f1 = i as f64 / n1;
        let f2 = j as f64 / n2;
        d = d.max((f1 - f2).abs());
    }
    let n_eff = n1 * n2 / (n1 + n2);
    let p_value = ks_p_value(d, n_eff);
    serde_wasm_bindgen::to_value(&Ks2Result {
        d, p_value, n1: va.len(), n2: vb.len(),
    }).map_err(Into::into)
}

// ── OLS linear regression with t-stat ──────────────────────────────

#[derive(Serialize)]
pub struct OlsResult {
    pub alpha: f64,   // intercept
    pub beta: f64,    // slope
    pub se_alpha: f64,
    pub se_beta: f64,
    pub t_beta: f64,
    pub p_beta: f64,  // two-sided p of H0: beta = 0 (normal approximation)
    pub r_squared: f64,
    pub residual_std: f64,
    pub n: usize,
}

#[wasm_bindgen(js_name = calibOls)]
pub fn ols_regress(x: Float64Array, y: Float64Array) -> Result<JsValue, JsValue> {
    let xv: Vec<f64> = x.to_vec();
    let yv: Vec<f64> = y.to_vec();
    if xv.len() != yv.len() || xv.len() < 3 {
        return Err(JsValue::from_str("ols: length mismatch or n < 3"));
    }
    let pairs: Vec<(f64, f64)> = xv.iter().zip(yv.iter())
        .filter(|(a, b)| a.is_finite() && b.is_finite())
        .map(|(a, b)| (*a, *b))
        .collect();
    let n = pairs.len();
    if n < 3 {
        return Err(JsValue::from_str("ols: need n >= 3 finite pairs"));
    }
    let n_f = n as f64;
    let mx: f64 = pairs.iter().map(|(x, _)| x).sum::<f64>() / n_f;
    let my: f64 = pairs.iter().map(|(_, y)| y).sum::<f64>() / n_f;
    let mut sxx = 0.0; let mut syy = 0.0; let mut sxy = 0.0;
    for (x, y) in &pairs {
        let dx = x - mx;
        let dy = y - my;
        sxx += dx * dx;
        syy += dy * dy;
        sxy += dx * dy;
    }
    if sxx == 0.0 {
        return Err(JsValue::from_str("ols: zero variance in x"));
    }
    let beta = sxy / sxx;
    let alpha = my - beta * mx;
    let mut ss_res = 0.0;
    for (x, y) in &pairs {
        let yh = alpha + beta * x;
        ss_res += (y - yh) * (y - yh);
    }
    let dof = (n - 2) as f64;
    let sigma2 = if dof > 0.0 { ss_res / dof } else { 0.0 };
    let se_beta = (sigma2 / sxx).sqrt();
    let se_alpha = (sigma2 * (1.0 / n_f + mx * mx / sxx)).sqrt();
    let t_beta = if se_beta > 0.0 { beta / se_beta } else { 0.0 };
    let p_beta = two_sided_p(t_beta);  // normal approx; accurate for n > ~30
    let r_squared = if syy > 0.0 { 1.0 - ss_res / syy } else { 0.0 };
    let residual_std = sigma2.sqrt();
    serde_wasm_bindgen::to_value(&OlsResult {
        alpha, beta, se_alpha, se_beta, t_beta, p_beta, r_squared, residual_std, n,
    }).map_err(Into::into)
}

// ── KDE + peak detection (1-D) ─────────────────────────────────────

#[derive(Serialize)]
pub struct KdeResult {
    pub grid: Vec<f64>,
    pub density: Vec<f64>,
    /// Indices (into grid/density) of detected local maxima, sorted by density desc.
    pub peaks: Vec<usize>,
    /// Bandwidth used (Silverman's rule).
    pub bandwidth: f64,
}

#[wasm_bindgen(js_name = calibKdePeaks)]
pub fn kde_peaks(samples: Float64Array, n_grid: u32, bandwidth: f64) -> Result<JsValue, JsValue> {
    let v: Vec<f64> = samples.to_vec().into_iter().filter(|v| v.is_finite()).collect();
    let n = v.len();
    if n < 3 {
        return Err(JsValue::from_str("kde_peaks: need n >= 3"));
    }
    let mean = v.iter().sum::<f64>() / n as f64;
    let std = (v.iter().map(|&x| (x - mean) * (x - mean)).sum::<f64>() / (n - 1) as f64).sqrt();
    let h = if bandwidth > 0.0 {
        bandwidth
    } else if std > 0.0 {
        1.06 * std * (n as f64).powf(-0.2)  // Silverman's rule
    } else {
        1.0
    };
    let min = *v.iter().fold(&v[0], |a, b| if b < a { b } else { a });
    let max = *v.iter().fold(&v[0], |a, b| if b > a { b } else { a });
    let pad = 3.0 * h;
    let lo = min - pad;
    let hi = max + pad;
    let g = n_grid.max(32) as usize;
    let step = (hi - lo) / (g - 1) as f64;
    let mut grid = vec![0.0; g];
    let mut density = vec![0.0; g];
    for i in 0..g { grid[i] = lo + step * i as f64; }
    let norm = 1.0 / (n as f64 * h * (2.0 * std::f64::consts::PI).sqrt());
    for &x in &v {
        // Only spread ±4h for speed.
        let lo_i = (((x - 4.0 * h - lo) / step).floor() as isize).max(0) as usize;
        let hi_i = (((x + 4.0 * h - lo) / step).ceil() as isize).min(g as isize - 1).max(0) as usize;
        for i in lo_i..=hi_i {
            let d = (grid[i] - x) / h;
            density[i] += norm * (-0.5 * d * d).exp();
        }
    }
    // Peak detection: strict local maximum within ±2 grid points, density > 10% of global max.
    let max_d = density.iter().cloned().fold(0.0f64, f64::max);
    let thresh = max_d * 0.10;
    let mut peaks: Vec<usize> = Vec::new();
    for i in 2..g.saturating_sub(2) {
        let d = density[i];
        if d > thresh
            && d > density[i - 1] && d > density[i - 2]
            && d > density[i + 1] && d > density[i + 2] {
            peaks.push(i);
        }
    }
    peaks.sort_by(|a, b| density[*b].partial_cmp(&density[*a]).unwrap());
    serde_wasm_bindgen::to_value(&KdeResult {
        grid, density, peaks, bandwidth: h,
    }).map_err(Into::into)
}

// ── Fisher combined + BH-FDR correction ────────────────────────────

#[derive(Serialize)]
pub struct FisherResult {
    pub chi2: f64,
    pub df: f64,
    pub p_value: f64,
}

#[wasm_bindgen(js_name = calibFisherCombined)]
pub fn fisher_combined(p_values: Float64Array) -> Result<JsValue, JsValue> {
    let ps: Vec<f64> = p_values.to_vec().into_iter()
        .filter(|p| p.is_finite() && *p > 0.0 && *p <= 1.0)
        .collect();
    if ps.is_empty() {
        return Err(JsValue::from_str("fisher: no valid p-values"));
    }
    let chi2: f64 = -2.0 * ps.iter().map(|p| p.ln()).sum::<f64>();
    let df = 2.0 * ps.len() as f64;
    let p_value = chi2_p(chi2, df);
    serde_wasm_bindgen::to_value(&FisherResult {
        chi2, df, p_value,
    }).map_err(Into::into)
}

/// Benjamini-Hochberg adjusted p-values (monotone step-up).
#[wasm_bindgen(js_name = calibBhAdjust)]
pub fn bh_adjust(p_values: Float64Array) -> Result<JsValue, JsValue> {
    let ps: Vec<f64> = p_values.to_vec();
    let n = ps.len();
    if n == 0 {
        return serde_wasm_bindgen::to_value(&Vec::<f64>::new()).map_err(Into::into);
    }
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|a, b| ps[*a].partial_cmp(&ps[*b]).unwrap_or(std::cmp::Ordering::Equal));
    let mut adj = vec![0.0_f64; n];
    let mut prev = 1.0_f64;
    for rank in (0..n).rev() {
        let idx = order[rank];
        let k = rank + 1;
        let raw = ps[idx] * n as f64 / k as f64;
        let a = raw.min(prev).min(1.0);
        adj[idx] = a;
        prev = a;
    }
    serde_wasm_bindgen::to_value(&adj).map_err(Into::into)
}
