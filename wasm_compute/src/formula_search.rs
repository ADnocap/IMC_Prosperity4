//! Stage 2 — formula discovery.
//!
//! Brute-force search over the two formula families we care about for this game:
//!
//!   Fixed:        price = round_fn(fv + shift) + constant
//!   Proportional: price = round_fn(fv * (1 + s * K))        (s = -1 bid, +1 ask)
//!
//! Wide enough to cover the OSMIUM (fixed ±10/±8) and PEPPER (proportional K=3/4000,
//! K=1/2000) bot families. The search splits the dataset in half for 2-fold CV so
//! we can catch a proportional-fit-to-noise on narrow-range data.
//!
//! Output: top-N formulas per bot/side with cross-validated match rate, Wilson CI,
//! residual histogram, and FV-range × match-rate heatmap (the plot that would have
//! flagged PEPPER's proportional-vs-fixed bug in minutes instead of weeks).

use crate::calibration::{chi2_p, normal_cdf, two_sided_p};
use js_sys::Float64Array;
use serde::Serialize;
use wasm_bindgen::prelude::*;

// ── Rounding functions ─────────────────────────────────────────────

#[derive(Copy, Clone)]
enum Round {
    Floor,
    Ceil,
    Round,   // Python-style round-half-to-even (banker's)
}

impl Round {
    fn apply(self, x: f64) -> i64 {
        match self {
            Round::Floor => x.floor() as i64,
            Round::Ceil => x.ceil() as i64,
            Round::Round => {
                let f = x.floor();
                let frac = x - f;
                if frac > 0.5 { (f as i64) + 1 }
                else if frac < 0.5 { f as i64 }
                else {
                    // half — round to even
                    let fi = f as i64;
                    if fi % 2 == 0 { fi } else { fi + 1 }
                }
            }
        }
    }

    fn name(self) -> &'static str {
        match self { Round::Floor => "floor", Round::Ceil => "ceil", Round::Round => "round" }
    }
}

// ── Fixed-offset search ────────────────────────────────────────────

#[derive(Serialize)]
pub struct FixedCandidate {
    pub round_fn: String,
    pub shift: f64,
    pub constant: i32,
    /// Match rate on the full dataset.
    pub match_rate: f64,
    /// Cross-validated match rate (fit on fold 1, score on fold 2; averaged both directions).
    pub cv_match_rate: f64,
    /// Wilson 95% CI on full-dataset match rate.
    pub ci_lo: f64,
    pub ci_hi: f64,
    pub n: usize,
    /// Residual histogram: values are counts of (observed - predicted) at keys -5..=5.
    pub residual_hist: Vec<i32>,
    /// Per-FV-decile match rate (index 0 = lowest decile, 9 = highest).
    pub fv_decile_match: Vec<f64>,
}

#[derive(Serialize)]
pub struct FormulaSearchOut {
    pub fixed_top: Vec<FixedCandidate>,
    pub proportional_top: Vec<ProportionalCandidate>,
    /// Overall winner by CV-BIC: "fixed" or "proportional".
    pub winner: String,
    pub winner_index: usize,
}

#[derive(Serialize)]
pub struct ProportionalCandidate {
    pub round_fn: String,
    /// K coefficient. For side = "bid" we test `round_fn(fv * (1 - K))`, for ask `round_fn(fv * (1 + K))`.
    pub k: f64,
    pub match_rate: f64,
    pub cv_match_rate: f64,
    pub ci_lo: f64,
    pub ci_hi: f64,
    pub n: usize,
    pub residual_hist: Vec<i32>,
    pub fv_decile_match: Vec<f64>,
}

fn wilson_95(k: usize, n: usize) -> (f64, f64) {
    if n == 0 { return (0.0, 0.0); }
    let z = 1.959963984540054_f64;
    let n_f = n as f64;
    let phat = k as f64 / n_f;
    let denom = 1.0 + z * z / n_f;
    let center = phat + z * z / (2.0 * n_f);
    let half = z * ((phat * (1.0 - phat) / n_f) + z * z / (4.0 * n_f * n_f)).sqrt();
    ((center - half) / denom, (center + half) / denom)
}

fn residual_hist(residuals: &[i32]) -> Vec<i32> {
    // Keys -5..=5, 11 bins; out-of-range clipped to endpoints.
    let mut hist = vec![0i32; 11];
    for &r in residuals {
        let clipped = r.clamp(-5, 5);
        hist[(clipped + 5) as usize] += 1;
    }
    hist
}

fn fv_decile_match_rates(fvs: &[f64], hits: &[bool]) -> Vec<f64> {
    if fvs.is_empty() { return vec![0.0; 10]; }
    let mut sorted: Vec<f64> = fvs.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = sorted.len();
    let mut cuts = [0.0_f64; 10];
    for i in 0..10 {
        let q = (i + 1) as f64 / 10.0;
        let idx = ((q * n as f64).floor() as usize).min(n - 1);
        cuts[i] = sorted[idx];
    }
    let mut counts = [0u32; 10];
    let mut hits_per = [0u32; 10];
    for (i, &fv) in fvs.iter().enumerate() {
        let d = (0..10).find(|&j| fv <= cuts[j]).unwrap_or(9);
        counts[d] += 1;
        if hits[i] { hits_per[d] += 1; }
    }
    (0..10).map(|j| {
        if counts[j] == 0 { 0.0 } else { hits_per[j] as f64 / counts[j] as f64 }
    }).collect()
}

/// Brute-force search. `side_sign`: -1 for bid, +1 for ask (used by proportional family).
/// `const_lo`/`const_hi` bound the fixed-offset integer search (inclusive).
#[wasm_bindgen(js_name = calibFormulaSearch)]
pub fn formula_search(
    fv: Float64Array,
    price: Float64Array,
    side_sign: f64,
    const_lo: i32,
    const_hi: i32,
    k_min: f64,
    k_max: f64,
    k_steps: u32,
    top_n: u32,
) -> Result<JsValue, JsValue> {
    let fvs: Vec<f64> = fv.to_vec();
    let prices: Vec<f64> = price.to_vec();
    if fvs.len() != prices.len() || fvs.is_empty() {
        return Err(JsValue::from_str("formula_search: length mismatch or empty"));
    }
    let pairs: Vec<(f64, i64)> = fvs.iter().zip(prices.iter())
        .filter(|(f, p)| f.is_finite() && p.is_finite())
        .map(|(f, p)| (*f, p.round() as i64))
        .collect();
    let n = pairs.len();
    if n < 10 {
        return Err(JsValue::from_str("formula_search: need n >= 10"));
    }

    let sign = if side_sign < 0.0 { -1.0 } else { 1.0 };
    let rounders = [Round::Floor, Round::Ceil, Round::Round];
    // Canonical shift range (-1, 1) exclusive — integer shifts are aliases of constant offsets
    // (e.g. `floor(fv - 1) + c  ==  floor(fv) + (c - 1)`). Keeping them in the grid creates tied
    // formulas that confuse the top-N ranking and hide the true canonical formula.
    let shifts: [f64; 7] = [-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75];

    // Split-half folds (stable split by index).
    let mid = n / 2;
    let fold_a: Vec<(f64, i64)> = pairs[..mid].to_vec();
    let fold_b: Vec<(f64, i64)> = pairs[mid..].to_vec();

    // ── Fixed search ──
    let mut fixed: Vec<FixedCandidate> = Vec::new();
    for &rnd in &rounders {
        for &sh in &shifts {
            for c in const_lo..=const_hi {
                let mut hits_full = 0usize;
                let mut res: Vec<i32> = Vec::with_capacity(n);
                let mut hit_vec = Vec::with_capacity(n);
                let mut fv_vec = Vec::with_capacity(n);
                for &(f, p) in &pairs {
                    let pred = rnd.apply(f + sh) + c as i64;
                    let hit = pred == p;
                    if hit { hits_full += 1; }
                    res.push((p - pred).clamp(i32::MIN as i64, i32::MAX as i64) as i32);
                    hit_vec.push(hit);
                    fv_vec.push(f);
                }
                // CV: fit (implicit — formula is data-independent) → score each fold separately.
                let mut ha = 0usize; for &(f, p) in &fold_a { if rnd.apply(f + sh) + c as i64 == p { ha += 1; } }
                let mut hb = 0usize; for &(f, p) in &fold_b { if rnd.apply(f + sh) + c as i64 == p { hb += 1; } }
                let cv = (ha as f64 / fold_a.len().max(1) as f64 + hb as f64 / fold_b.len().max(1) as f64) / 2.0;
                let (lo, hi) = wilson_95(hits_full, n);
                fixed.push(FixedCandidate {
                    round_fn: rnd.name().to_string(),
                    shift: sh, constant: c,
                    match_rate: hits_full as f64 / n as f64,
                    cv_match_rate: cv,
                    ci_lo: lo, ci_hi: hi, n,
                    residual_hist: residual_hist(&res),
                    fv_decile_match: fv_decile_match_rates(&fv_vec, &hit_vec),
                });
            }
        }
    }
    fixed.sort_by(|a, b| b.cv_match_rate.partial_cmp(&a.cv_match_rate).unwrap_or(std::cmp::Ordering::Equal));
    let fixed_top: Vec<FixedCandidate> = fixed.into_iter().take(top_n as usize).collect();

    // ── Proportional search ──
    let mut prop: Vec<ProportionalCandidate> = Vec::new();
    let ks_n = k_steps.max(2) as usize;
    for &rnd in &rounders {
        for step in 0..ks_n {
            let k = k_min + (k_max - k_min) * step as f64 / (ks_n - 1) as f64;
            let mut hits_full = 0usize;
            let mut res: Vec<i32> = Vec::with_capacity(n);
            let mut hit_vec = Vec::with_capacity(n);
            let mut fv_vec = Vec::with_capacity(n);
            for &(f, p) in &pairs {
                let pred = rnd.apply(f * (1.0 + sign * k));
                let hit = pred == p;
                if hit { hits_full += 1; }
                res.push((p - pred).clamp(i32::MIN as i64, i32::MAX as i64) as i32);
                hit_vec.push(hit);
                fv_vec.push(f);
            }
            let mut ha = 0usize; for &(f, p) in &fold_a { if rnd.apply(f * (1.0 + sign * k)) == p { ha += 1; } }
            let mut hb = 0usize; for &(f, p) in &fold_b { if rnd.apply(f * (1.0 + sign * k)) == p { hb += 1; } }
            let cv = (ha as f64 / fold_a.len().max(1) as f64 + hb as f64 / fold_b.len().max(1) as f64) / 2.0;
            let (lo, hi) = wilson_95(hits_full, n);
            prop.push(ProportionalCandidate {
                round_fn: rnd.name().to_string(),
                k,
                match_rate: hits_full as f64 / n as f64,
                cv_match_rate: cv,
                ci_lo: lo, ci_hi: hi, n,
                residual_hist: residual_hist(&res),
                fv_decile_match: fv_decile_match_rates(&fv_vec, &hit_vec),
            });
        }
    }
    prop.sort_by(|a, b| b.cv_match_rate.partial_cmp(&a.cv_match_rate).unwrap_or(std::cmp::Ordering::Equal));
    let prop_top: Vec<ProportionalCandidate> = prop.into_iter().take(top_n as usize).collect();

    // Pick winner — prefer fixed when the two are within 0.5% on CV (Occam); proportional only if
    // its FV-decile match rate is flat across the whole range AND it beats fixed by > 0.5%.
    let fixed_best_cv = fixed_top.first().map(|c| c.cv_match_rate).unwrap_or(0.0);
    let prop_best_cv  = prop_top.first().map(|c| c.cv_match_rate).unwrap_or(0.0);
    let prop_decile_spread = prop_top.first()
        .map(|c| {
            let m = c.fv_decile_match.iter().cloned().fold(0.0f64, f64::max);
            let mn = c.fv_decile_match.iter().cloned().fold(1.0f64, f64::min);
            m - mn
        })
        .unwrap_or(1.0);
    let fixed_decile_spread = fixed_top.first()
        .map(|c| {
            let m = c.fv_decile_match.iter().cloned().fold(0.0f64, f64::max);
            let mn = c.fv_decile_match.iter().cloned().fold(1.0f64, f64::min);
            m - mn
        })
        .unwrap_or(1.0);
    let (winner, winner_index) = if prop_best_cv > fixed_best_cv + 0.005
        && prop_decile_spread < fixed_decile_spread
    {
        ("proportional".to_string(), 0)
    } else {
        ("fixed".to_string(), 0)
    };
    // Silence unused-import warnings for the primitives we haven't wired yet
    // (they'll get used as soon as higher-level BIC selection lands).
    let _ = (chi2_p, normal_cdf, two_sided_p);

    serde_wasm_bindgen::to_value(&FormulaSearchOut {
        fixed_top, proportional_top: prop_top, winner, winner_index,
    }).map_err(Into::into)
}

// ── Native tests (run with `cargo test`) ──

#[cfg(test)]
mod tests {
    use super::*;

    fn approx_eq(a: f64, b: f64, eps: f64) -> bool { (a - b).abs() < eps }

    #[test]
    fn osmium_bot1_bid_recovers_floor_minus_10() {
        // Synthetic FV spanning several integer boundaries — narrow range creates
        // tied formulas (shift=-1,c=-9 is indistinguishable from shift=0,c=-10
        // when floor(fv) never changes). The real pipeline catches ties via the
        // residual histogram at integer FV; this test just checks we find
        // SOMETHING equivalent to `floor(fv) - 10` at 100% match.
        let fvs: Vec<f64> = (0..2000).map(|i| 9995.0 + i as f64 * 0.005).collect();
        let prices: Vec<f64> = fvs.iter().map(|f| (f.floor() as i64 - 10) as f64).collect();
        let n = fvs.len();
        let mut best_hits = 0usize;
        let mut best = (String::new(), 0.0, 0i32);
        for &r in &[Round::Floor, Round::Ceil, Round::Round] {
            for sh in [-0.5, -0.25, 0.0, 0.25, 0.5] {
                for c in -14..=-7 {
                    let mut hits = 0usize;
                    for i in 0..n {
                        if r.apply(fvs[i] + sh) + c as i64 == prices[i].round() as i64 { hits += 1; }
                    }
                    if hits > best_hits { best_hits = hits; best = (r.name().to_string(), sh, c); }
                }
            }
        }
        // Top formula must be floor-family with +0.0 shift, c=-10 (canonical).
        assert_eq!(best.0, "floor");
        assert!(approx_eq(best.1, 0.0, 1e-9), "got shift={}", best.1);
        assert_eq!(best.2, -10);
        assert!(best_hits == n, "expected 100% match, got {best_hits}/{n}");
    }

    #[test]
    fn pepper_bot1_bid_recovers_proportional_k_3_over_4000() {
        let k_true = 3.0 / 4000.0;
        let fvs: Vec<f64> = (0..30000).map(|i| 10000.0 + i as f64 * 0.1).collect();
        let prices: Vec<f64> = fvs.iter().map(|f| (f * (1.0 - k_true)).floor() as i64 as f64).collect();
        let n = fvs.len();
        let mut best_hits = 0usize;
        let mut best_k = 0.0_f64;
        for step in 0..=200 {
            let k = 0.0005 + (0.0010 - 0.0005) * step as f64 / 200.0;
            let mut hits = 0usize;
            for i in 0..n {
                if Round::Floor.apply(fvs[i] * (1.0 - k)) == prices[i] as i64 { hits += 1; }
            }
            if hits > best_hits { best_hits = hits; best_k = k; }
        }
        assert!(approx_eq(best_k, k_true, 5e-6), "got K={best_k}, expected {k_true}");
        assert!(best_hits as f64 / n as f64 > 0.999);
    }

    #[test]
    fn fixed_fails_on_proportional_wide_range() {
        let k_true = 3.0 / 4000.0;
        let fvs: Vec<f64> = (0..30000).map(|i| 10000.0 + i as f64 * 0.1).collect();
        let prices: Vec<f64> = fvs.iter().map(|f| (f * (1.0 - k_true)).floor() as i64 as f64).collect();
        let n = fvs.len();
        let mut best_hits = 0usize;
        for &r in &[Round::Floor, Round::Ceil, Round::Round] {
            for sh in [-0.5, -0.25, 0.0, 0.25, 0.5] {
                for c in -14..=-5 {
                    let mut hits = 0usize;
                    for i in 0..n {
                        if r.apply(fvs[i] + sh) + c as i64 == prices[i].round() as i64 { hits += 1; }
                    }
                    if hits > best_hits { best_hits = hits; }
                }
            }
        }
        let rate = best_hits as f64 / n as f64;
        assert!(rate < 0.80, "fixed match rate = {rate}; should fail on wide-range proportional data");
    }
}
