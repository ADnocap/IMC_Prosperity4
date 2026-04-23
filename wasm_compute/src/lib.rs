//! Compute kernels for the Prosperity Workshop visualizer.
//!
//! Design goals:
//! - All numeric columns arrive from JS as `Float64Array` and cross the FFI as
//!   `js_sys::Float64Array::to_vec()` (one memcpy into WASM linear memory).
//! - No per-row allocations; we gather per-product indices first, then stream
//!   the kernel in a single pass over the column arrays.
//! - Outputs are plain `Vec<[f64; 2]>` / small structs serialised back to JS via
//!   `serde-wasm-bindgen` — cheap for the scatter / binned sizes we emit.

use js_sys::Float64Array;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::collections::HashSet;
use wasm_bindgen::prelude::*;

mod calibration;
mod formula_search;

// ── Utilities ───────────────────────────────────────────────────────

fn group_indices(
    products: &[String],
    products_allowed: &Option<Vec<String>>,
) -> Vec<(String, Vec<usize>)> {
    let allowed: Option<std::collections::HashSet<&str>> = products_allowed
        .as_ref()
        .map(|list| list.iter().map(String::as_str).collect());
    let mut buckets: HashMap<String, Vec<usize>> = HashMap::new();
    for (i, product) in products.iter().enumerate() {
        if let Some(allow) = &allowed {
            if !allow.contains(product.as_str()) {
                continue;
            }
        }
        buckets.entry(product.clone()).or_default().push(i);
    }
    let mut pairs: Vec<(String, Vec<usize>)> = buckets.into_iter().collect();
    pairs.sort_by(|a, b| a.0.cmp(&b.0));
    pairs
}

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() { return 0.0; }
    values.iter().sum::<f64>() / values.len() as f64
}

fn stdev(values: &[f64], mu: f64) -> f64 {
    if values.len() < 2 { return 0.0; }
    let mut ss = 0.0;
    for &v in values {
        let d = v - mu;
        ss += d * d;
    }
    (ss / (values.len() as f64 - 1.0)).sqrt()
}

fn quantile_sorted(sorted: &[f64], q: f64) -> f64 {
    if sorted.is_empty() { return 0.0; }
    let idx = ((q * (sorted.len() as f64 - 1.0)).floor() as usize).min(sorted.len() - 1);
    sorted[idx]
}

fn pearson(xs: &[f64], ys: &[f64]) -> f64 {
    let n = xs.len();
    if n < 2 { return 0.0; }
    let (mut sx, mut sy) = (0.0, 0.0);
    for i in 0..n { sx += xs[i]; sy += ys[i]; }
    let mx = sx / n as f64;
    let my = sy / n as f64;
    let (mut num, mut dx2, mut dy2) = (0.0, 0.0, 0.0);
    for i in 0..n {
        let ax = xs[i] - mx;
        let ay = ys[i] - my;
        num += ax * ay;
        dx2 += ax * ax;
        dy2 += ay * ay;
    }
    let denom = (dx2 * dy2).sqrt();
    if denom == 0.0 { 0.0 } else { num / denom }
}

fn ols(xs: &[f64], ys: &[f64]) -> (f64, f64) {
    let n = xs.len();
    if n < 2 { return (0.0, 0.0); }
    let (mut sx, mut sy) = (0.0, 0.0);
    for i in 0..n { sx += xs[i]; sy += ys[i]; }
    let mx = sx / n as f64;
    let my = sy / n as f64;
    let (mut num, mut den) = (0.0, 0.0);
    for i in 0..n {
        let ax = xs[i] - mx;
        num += ax * (ys[i] - my);
        den += ax * ax;
    }
    let slope = if den == 0.0 { 0.0 } else { num / den };
    let intercept = my - slope * mx;
    (slope, intercept)
}

fn finite(v: f64) -> bool { v.is_finite() }

// ── Mid / microprice ────────────────────────────────────────────────

#[derive(Deserialize)]
struct MidInputJs {
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    products: Vec<String>,
}

#[derive(Serialize)]
struct MidOutputProduct {
    product: String,
    #[serde(rename = "midPoints")] mid_points: Vec<[f64; 2]>,
    #[serde(rename = "microPoints")] micro_points: Vec<[f64; 2]>,
}

#[wasm_bindgen(js_name = computeMid)]
pub fn compute_mid(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
    bid1: Option<Float64Array>,
    ask1: Option<Float64Array>,
    bid_vol1: Option<Float64Array>,
    ask_vol1: Option<Float64Array>,
) -> Result<JsValue, JsValue> {
    let meta: MidInputJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();
    let has_micro = bid1.is_some() && ask1.is_some() && bid_vol1.is_some() && ask_vol1.is_some();
    let bid1 = bid1.map(|a| a.to_vec());
    let ask1 = ask1.map(|a| a.to_vec());
    let bid_vol1 = bid_vol1.map(|a| a.to_vec());
    let ask_vol1 = ask_vol1.map(|a| a.to_vec());

    let groups = group_indices(&meta.products, &meta.products_allowed);
    let mut out: Vec<MidOutputProduct> = Vec::with_capacity(groups.len());
    for (product, indices) in groups {
        let mut mid_points: Vec<[f64; 2]> = Vec::with_capacity(indices.len());
        let mut micro_points: Vec<[f64; 2]> = Vec::new();
        for &i in &indices {
            let t = times[i];
            let m = mids[i];
            if finite(t) && finite(m) { mid_points.push([t, m]); }
            if has_micro && finite(t) {
                let bp = bid1.as_ref().unwrap()[i];
                let ap = ask1.as_ref().unwrap()[i];
                let bv = bid_vol1.as_ref().unwrap()[i];
                let av = ask_vol1.as_ref().unwrap()[i];
                let denom = bv + av;
                if finite(bp) && finite(ap) && finite(denom) && denom > 0.0 {
                    micro_points.push([t, (bp * av + ap * bv) / denom]);
                }
            }
        }
        out.push(MidOutputProduct { product, mid_points, micro_points });
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Spread ──────────────────────────────────────────────────────────

#[derive(Serialize)]
struct SpreadHistogram {
    centers: Vec<f64>,
    counts: Vec<u32>,
}

#[derive(Serialize)]
struct SpreadOutputProduct {
    product: String,
    n: u32,
    mean: f64,
    std: f64,
    p05: f64,
    p50: f64,
    p95: f64,
    #[serde(rename = "timeSeries")] time_series: Vec<[f64; 2]>,
    histogram: SpreadHistogram,
}

fn decimate<T: Clone>(arr: &[T], cap: usize) -> Vec<T> {
    if arr.len() <= cap { return arr.to_vec(); }
    let step = ((arr.len() as f64) / (cap as f64)).ceil() as usize;
    arr.iter().step_by(step).cloned().collect()
}

#[wasm_bindgen(js_name = computeSpread)]
pub fn compute_spread(
    meta: JsValue,
    times: Float64Array,
    bid1: Float64Array,
    ask1: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: MidInputJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let bid1 = bid1.to_vec();
    let ask1 = ask1.to_vec();
    let groups = group_indices(&meta.products, &meta.products_allowed);
    let mut out: Vec<SpreadOutputProduct> = Vec::with_capacity(groups.len());
    for (product, indices) in groups {
        let mut values: Vec<f64> = Vec::with_capacity(indices.len());
        let mut series: Vec<[f64; 2]> = Vec::with_capacity(indices.len());
        for &i in &indices {
            let bp = bid1[i]; let ap = ask1[i]; let t = times[i];
            if !finite(bp) || !finite(ap) || !finite(t) { continue; }
            let s = ap - bp;
            if !finite(s) { continue; }
            values.push(s);
            series.push([t, s]);
        }
        if values.is_empty() { continue; }
        let mu = mean(&values);
        let sd = stdev(&values, mu);
        let mut sorted = values.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let bins = ((values.len() as f64).sqrt() as usize).clamp(10, 30);
        let lo = sorted[0];
        let hi = sorted[sorted.len() - 1];
        let width = if lo == hi { 1.0 } else { (hi - lo) / bins as f64 };
        let mut centers = vec![0.0_f64; bins];
        let mut counts = vec![0_u32; bins];
        for i in 0..bins { centers[i] = lo + width * (i as f64 + 0.5); }
        for &v in &values {
            let mut idx = ((v - lo) / width).floor() as isize;
            if idx < 0 { idx = 0; }
            if idx >= bins as isize { idx = bins as isize - 1; }
            counts[idx as usize] += 1;
        }
        out.push(SpreadOutputProduct {
            product,
            n: values.len() as u32,
            mean: mu,
            std: sd,
            p05: quantile_sorted(&sorted, 0.05),
            p50: quantile_sorted(&sorted, 0.5),
            p95: quantile_sorted(&sorted, 0.95),
            time_series: decimate(&series, 5000),
            histogram: SpreadHistogram { centers, counts },
        });
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Depth (single product) ──────────────────────────────────────────

#[derive(Deserialize)]
struct DepthMetaJs {
    #[serde(rename = "productFilter")] product_filter: String,
    products: Vec<String>,
    #[serde(rename = "maxPoints", default = "default_depth_max_points")] max_points: usize,
}

fn default_depth_max_points() -> usize { 4000 }

#[derive(Serialize)]
struct DepthLevelOut {
    level: u32,
    #[serde(rename = "bidPoints")] bid_points: Vec<[f64; 2]>,
    #[serde(rename = "askPoints")] ask_points: Vec<[f64; 2]>,
}

#[wasm_bindgen(js_name = computeDepth)]
pub fn compute_depth(
    meta: JsValue,
    times: Float64Array,
    bid_volumes_flat: Option<Float64Array>,
    ask_volumes_flat: Option<Float64Array>,
    level_count: u32,
    has_bid_volume_mask: Vec<u8>,
    has_ask_volume_mask: Vec<u8>,
) -> Result<JsValue, JsValue> {
    let meta: DepthMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let row_count = meta.products.len();
    let levels = level_count as usize;
    let bv = bid_volumes_flat.map(|a| a.to_vec());
    let av = ask_volumes_flat.map(|a| a.to_vec());

    // First pass: count matching rows so we can pick a stride that caps total
    // points per series at `max_points`.
    let mut matching: Vec<usize> = Vec::new();
    for i in 0..row_count {
        if meta.products[i] == meta.product_filter && finite(times[i]) {
            matching.push(i);
        }
    }
    let stride = if matching.len() > meta.max_points {
        ((matching.len() as f64) / (meta.max_points as f64)).ceil() as usize
    } else {
        1
    };

    let mut out: Vec<DepthLevelOut> = (0..levels)
        .map(|l| DepthLevelOut { level: (l + 1) as u32, bid_points: Vec::new(), ask_points: Vec::new() })
        .collect();

    let mut step = 0;
    for &i in &matching {
        if step % stride != 0 { step += 1; continue; }
        step += 1;
        let t = times[i];
        for l in 0..levels {
            let offset = l * row_count + i;
            if has_bid_volume_mask[l] != 0 {
                if let Some(arr) = &bv {
                    let v = arr[offset];
                    if finite(v) { out[l].bid_points.push([t, -v]); }
                }
            }
            if has_ask_volume_mask[l] != 0 {
                if let Some(arr) = &av {
                    let v = arr[offset];
                    if finite(v) { out[l].ask_points.push([t, v]); }
                }
            }
        }
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Queue imbalance ─────────────────────────────────────────────────

#[derive(Deserialize)]
struct QueueMetaJs {
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    products: Vec<String>,
    horizon: usize,
    #[serde(rename = "maxScatter")] max_scatter: usize,
    bins: usize,
}

#[derive(Serialize)]
struct QueueOutputProduct {
    product: String,
    scatter: Vec<[f64; 2]>,
    binned: Vec<[f64; 2]>,
    correlation: f64,
    n: u32,
}

#[wasm_bindgen(js_name = computeQueueImbalance)]
pub fn compute_queue_imbalance(
    meta: JsValue,
    mids: Float64Array,
    bid_vol1: Float64Array,
    ask_vol1: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: QueueMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let mids = mids.to_vec();
    let bid_vol1 = bid_vol1.to_vec();
    let ask_vol1 = ask_vol1.to_vec();
    let groups = group_indices(&meta.products, &meta.products_allowed);

    let mut out: Vec<QueueOutputProduct> = Vec::new();
    for (product, indices) in groups {
        let mut i_vec: Vec<f64> = Vec::with_capacity(indices.len());
        let mut mid_vec: Vec<f64> = Vec::with_capacity(indices.len());
        for &idx in &indices {
            let bv = bid_vol1[idx];
            let av = ask_vol1[idx];
            let m = mids[idx];
            if !finite(bv) || !finite(av) || !finite(m) { continue; }
            let denom = bv + av;
            if denom <= 0.0 { continue; }
            i_vec.push((bv - av) / denom);
            mid_vec.push(m);
        }
        if mid_vec.len() <= meta.horizon + 10 { continue; }

        let limit = mid_vec.len() - meta.horizon;
        let mut xs: Vec<f64> = Vec::with_capacity(limit);
        let mut ys: Vec<f64> = Vec::with_capacity(limit);
        for i in 0..limit {
            xs.push(i_vec[i]);
            ys.push(mid_vec[i + meta.horizon] - mid_vec[i]);
        }

        let mut buckets: Vec<Vec<f64>> = vec![Vec::new(); meta.bins];
        for i in 0..xs.len() {
            let mut idx = (((xs[i] + 1.0) / 2.0) * meta.bins as f64).floor() as isize;
            if idx < 0 { idx = 0; }
            if idx >= meta.bins as isize { idx = meta.bins as isize - 1; }
            buckets[idx as usize].push(ys[i]);
        }
        let mut binned: Vec<[f64; 2]> = Vec::new();
        for b in 0..meta.bins {
            if buckets[b].is_empty() { continue; }
            let center = -1.0 + (2.0 * (b as f64 + 0.5)) / meta.bins as f64;
            binned.push([center, mean(&buckets[b])]);
        }

        let step = if xs.len() > meta.max_scatter { (xs.len() as f64 / meta.max_scatter as f64).ceil() as usize } else { 1 };
        let mut scatter: Vec<[f64; 2]> = Vec::with_capacity((xs.len() + step - 1) / step);
        let mut i = 0;
        while i < xs.len() { scatter.push([xs[i], ys[i]]); i += step; }

        out.push(QueueOutputProduct {
            product,
            scatter,
            binned,
            correlation: pearson(&xs, &ys),
            n: xs.len() as u32,
        });
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── OFI (Cont-Kukanov) ──────────────────────────────────────────────

#[derive(Deserialize)]
struct OfiMetaJs {
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    products: Vec<String>,
    #[serde(rename = "maxScatter")] max_scatter: usize,
}

#[derive(Serialize)]
struct OfiOutputProduct {
    product: String,
    scatter: Vec<[f64; 2]>,
    correlation: f64,
    slope: f64,
    intercept: f64,
    n: u32,
    #[serde(rename = "xMin")] x_min: f64,
    #[serde(rename = "xMax")] x_max: f64,
}

#[wasm_bindgen(js_name = computeOfi)]
pub fn compute_ofi(
    meta: JsValue,
    mids: Float64Array,
    bid1: Float64Array,
    bid_vol1: Float64Array,
    ask1: Float64Array,
    ask_vol1: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: OfiMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let mids = mids.to_vec();
    let bid1 = bid1.to_vec();
    let bid_vol1 = bid_vol1.to_vec();
    let ask1 = ask1.to_vec();
    let ask_vol1 = ask_vol1.to_vec();
    let groups = group_indices(&meta.products, &meta.products_allowed);

    let mut out: Vec<OfiOutputProduct> = Vec::new();
    for (product, indices) in groups {
        let mut bp: Vec<f64> = Vec::with_capacity(indices.len());
        let mut bv: Vec<f64> = Vec::with_capacity(indices.len());
        let mut ap: Vec<f64> = Vec::with_capacity(indices.len());
        let mut av: Vec<f64> = Vec::with_capacity(indices.len());
        let mut mid: Vec<f64> = Vec::with_capacity(indices.len());
        for &idx in &indices {
            let (ab, bv_, aa, av_, m) = (bid1[idx], bid_vol1[idx], ask1[idx], ask_vol1[idx], mids[idx]);
            if !finite(ab) || !finite(bv_) || !finite(aa) || !finite(av_) || !finite(m) { continue; }
            bp.push(ab); bv.push(bv_); ap.push(aa); av.push(av_); mid.push(m);
        }
        if mid.len() <= 10 { continue; }

        let mut xs: Vec<f64> = Vec::with_capacity(mid.len() - 1);
        let mut ys: Vec<f64> = Vec::with_capacity(mid.len() - 1);
        for i in 1..mid.len() {
            let e_b = if bp[i] > bp[i - 1] { bv[i] }
                      else if bp[i] < bp[i - 1] { -bv[i - 1] }
                      else { bv[i] - bv[i - 1] };
            let e_a = if ap[i] < ap[i - 1] { -av[i] }
                      else if ap[i] > ap[i - 1] { av[i - 1] }
                      else { av[i] - av[i - 1] };
            let ofi = e_b + e_a;
            let next_mid = if i + 1 < mid.len() { mid[i + 1] } else { mid[i] };
            xs.push(ofi);
            ys.push(next_mid - mid[i]);
        }
        if xs.len() < 10 { continue; }

        let (slope, intercept) = ols(&xs, &ys);
        let step = if xs.len() > meta.max_scatter { (xs.len() as f64 / meta.max_scatter as f64).ceil() as usize } else { 1 };
        let mut scatter: Vec<[f64; 2]> = Vec::with_capacity((xs.len() + step - 1) / step);
        let mut i = 0;
        while i < xs.len() { scatter.push([xs[i], ys[i]]); i += step; }

        let (mut x_min, mut x_max) = (f64::INFINITY, f64::NEG_INFINITY);
        for &x in &xs { if x < x_min { x_min = x; } if x > x_max { x_max = x; } }

        out.push(OfiOutputProduct {
            product,
            scatter,
            correlation: pearson(&xs, &ys),
            slope,
            intercept,
            n: xs.len() as u32,
            x_min: if x_min.is_finite() { x_min } else { 0.0 },
            x_max: if x_max.is_finite() { x_max } else { 0.0 },
        });
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Shared: per-product sorted (time, mid) index ────────────────────
//
// Both the trade-join kernels need the mid price at a given (product, time).
// We build once per kernel call: a product→indices map where each bucket's
// indices are sorted by time. Then a single binary search gives us O(log n)
// per lookup.

struct PriceIndex {
    product_buckets: HashMap<String, Vec<usize>>,
    times: Vec<f64>,
    mids: Vec<f64>,
}

impl PriceIndex {
    fn build(times: &[f64], products: &[String], mids: &[f64]) -> Self {
        let mut buckets: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, product) in products.iter().enumerate() {
            if !finite(times[i]) || !finite(mids[i]) { continue; }
            buckets.entry(product.clone()).or_default().push(i);
        }
        for indices in buckets.values_mut() {
            indices.sort_by(|&a, &b| times[a].partial_cmp(&times[b]).unwrap_or(std::cmp::Ordering::Equal));
        }
        Self { product_buckets: buckets, times: times.to_vec(), mids: mids.to_vec() }
    }

    /// Returns the mid at or before `t` for the given product, or `None` if no
    /// prior snapshot exists.
    fn mid_at(&self, product: &str, t: f64) -> Option<f64> {
        let bucket = self.product_buckets.get(product)?;
        if bucket.is_empty() { return None; }
        // Binary search on the bucket's times.
        let times = &self.times;
        let mut lo = 0usize;
        let mut hi = bucket.len();
        while lo < hi {
            let mid = (lo + hi) / 2;
            if times[bucket[mid]] <= t { lo = mid + 1; } else { hi = mid; }
        }
        if lo == 0 { return None; }
        let idx = bucket[lo - 1];
        Some(self.mids[idx])
    }
}

// ── Mark-out by counterparty ────────────────────────────────────────

#[derive(Deserialize)]
struct MarkoutMetaJs {
    #[serde(rename = "tradeProducts")] trade_products: Vec<String>,
    #[serde(rename = "tradeBuyers")] trade_buyers: Vec<String>,
    #[serde(rename = "tradeSellers")] trade_sellers: Vec<String>,
    #[serde(rename = "priceProducts")] price_products: Vec<String>,
    #[serde(rename = "horizonTimestamps")] horizon_timestamps: Vec<u32>,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    #[serde(rename = "counterpartiesAllowed")] counterparties_allowed: Option<Vec<String>>,
}

#[derive(Serialize)]
struct MarkoutRowOut {
    counterparty: String,
    side: String,
    trades: u32,
    #[serde(rename = "markoutMeans")] markout_means: Vec<f64>,
    #[serde(rename = "markoutCounts")] markout_counts: Vec<u32>,
}

#[wasm_bindgen(js_name = computeMarkout)]
pub fn compute_markout(
    meta: JsValue,
    trade_times: Float64Array,
    trade_prices: Float64Array,
    trade_quantities: Float64Array,
    price_times: Float64Array,
    price_mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: MarkoutMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let trade_times = trade_times.to_vec();
    let trade_prices = trade_prices.to_vec();
    let _ = trade_quantities; // not used in this kernel, kept in the API for symmetry
    let price_times = price_times.to_vec();
    let price_mids = price_mids.to_vec();
    let index = PriceIndex::build(&price_times, &meta.price_products, &price_mids);

    let product_allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());
    let cp_allow: Option<HashSet<&str>> = meta.counterparties_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());

    let horizons = &meta.horizon_timestamps;
    let h = horizons.len();

    // Accumulator: (counterparty, side) → (sum_per_horizon, count_per_horizon, trades)
    let mut buyer_acc: HashMap<String, (Vec<f64>, Vec<u32>, u32)> = HashMap::new();
    let mut seller_acc: HashMap<String, (Vec<f64>, Vec<u32>, u32)> = HashMap::new();

    for i in 0..trade_times.len() {
        let t = trade_times[i];
        let price = trade_prices[i];
        if !finite(t) || !finite(price) { continue; }
        let product = &meta.trade_products[i];
        if let Some(allow) = &product_allow {
            if !allow.contains(product.as_str()) { continue; }
        }

        let buyer = meta.trade_buyers.get(i).cloned().unwrap_or_default();
        let seller = meta.trade_sellers.get(i).cloned().unwrap_or_default();

        // For buyer: mark-out = mid_{t+Δ} − price. Positive ⇒ they profited.
        // For seller: mark-out = price − mid_{t+Δ}.
        if !buyer.is_empty() {
            if cp_allow.as_ref().map(|s| s.contains(buyer.as_str())).unwrap_or(true) {
                let slot = buyer_acc.entry(buyer).or_insert_with(|| (vec![0.0; h], vec![0; h], 0));
                slot.2 += 1;
                for (hi, dt) in horizons.iter().enumerate() {
                    let target = t + *dt as f64;
                    if let Some(future_mid) = index.mid_at(product, target) {
                        slot.0[hi] += future_mid - price;
                        slot.1[hi] += 1;
                    }
                }
            }
        }
        if !seller.is_empty() {
            if cp_allow.as_ref().map(|s| s.contains(seller.as_str())).unwrap_or(true) {
                let slot = seller_acc.entry(seller).or_insert_with(|| (vec![0.0; h], vec![0; h], 0));
                slot.2 += 1;
                for (hi, dt) in horizons.iter().enumerate() {
                    let target = t + *dt as f64;
                    if let Some(future_mid) = index.mid_at(product, target) {
                        slot.0[hi] += price - future_mid;
                        slot.1[hi] += 1;
                    }
                }
            }
        }
    }

    let mut out: Vec<MarkoutRowOut> = Vec::with_capacity(buyer_acc.len() + seller_acc.len());
    for (cp, (sums, counts, trades)) in buyer_acc.into_iter() {
        let means: Vec<f64> = sums.iter().zip(counts.iter())
            .map(|(s, c)| if *c == 0 { 0.0 } else { s / *c as f64 }).collect();
        out.push(MarkoutRowOut { counterparty: cp, side: "buyer".into(), trades, markout_means: means, markout_counts: counts });
    }
    for (cp, (sums, counts, trades)) in seller_acc.into_iter() {
        let means: Vec<f64> = sums.iter().zip(counts.iter())
            .map(|(s, c)| if *c == 0 { 0.0 } else { s / *c as f64 }).collect();
        out.push(MarkoutRowOut { counterparty: cp, side: "seller".into(), trades, markout_means: means, markout_counts: counts });
    }
    // Sort by |mean markout at the largest horizon| descending so the most
    // informative counterparties surface at the top.
    out.sort_by(|a, b| {
        let pick = |r: &MarkoutRowOut| r.markout_means.last().copied().unwrap_or(0.0).abs();
        pick(b).partial_cmp(&pick(a)).unwrap_or(std::cmp::Ordering::Equal)
    });
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Trade offset from mid, per counterparty ─────────────────────────

#[derive(Deserialize)]
struct OffsetMetaJs {
    #[serde(rename = "tradeProducts")] trade_products: Vec<String>,
    #[serde(rename = "tradeBuyers")] trade_buyers: Vec<String>,
    #[serde(rename = "tradeSellers")] trade_sellers: Vec<String>,
    #[serde(rename = "priceProducts")] price_products: Vec<String>,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
}

#[derive(Serialize)]
struct OffsetHistOut { centers: Vec<f64>, counts: Vec<u32> }

#[derive(Serialize)]
struct OffsetRowOut {
    counterparty: String,
    side: String,
    trades: u32,
    mean: f64,
    histogram: OffsetHistOut,
}

#[wasm_bindgen(js_name = computeOffset)]
pub fn compute_offset(
    meta: JsValue,
    trade_times: Float64Array,
    trade_prices: Float64Array,
    price_times: Float64Array,
    price_mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: OffsetMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let trade_times = trade_times.to_vec();
    let trade_prices = trade_prices.to_vec();
    let price_times = price_times.to_vec();
    let price_mids = price_mids.to_vec();
    let index = PriceIndex::build(&price_times, &meta.price_products, &price_mids);
    let product_allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());

    // Per (counterparty, side) → raw offsets list
    let mut buyer_vals: HashMap<String, Vec<f64>> = HashMap::new();
    let mut seller_vals: HashMap<String, Vec<f64>> = HashMap::new();

    for i in 0..trade_times.len() {
        let t = trade_times[i];
        let price = trade_prices[i];
        if !finite(t) || !finite(price) { continue; }
        let product = &meta.trade_products[i];
        if let Some(allow) = &product_allow {
            if !allow.contains(product.as_str()) { continue; }
        }
        let mid = match index.mid_at(product, t) { Some(v) => v, None => continue };
        let offset = price - mid;
        let buyer = meta.trade_buyers.get(i).cloned().unwrap_or_default();
        let seller = meta.trade_sellers.get(i).cloned().unwrap_or_default();
        if !buyer.is_empty() { buyer_vals.entry(buyer).or_default().push(offset); }
        if !seller.is_empty() { seller_vals.entry(seller).or_default().push(-offset); }
    }

    fn summarize(cp: String, side: &str, values: Vec<f64>) -> OffsetRowOut {
        let n = values.len();
        let mu = mean(&values);
        let bins = ((n as f64).sqrt() as usize).clamp(10, 30).max(1);
        let (lo, hi) = values.iter().fold((f64::INFINITY, f64::NEG_INFINITY),
            |(a, b), v| (a.min(*v), b.max(*v)));
        let width = if !lo.is_finite() || !hi.is_finite() || lo == hi { 1.0 } else { (hi - lo) / bins as f64 };
        let base = if lo.is_finite() { lo } else { 0.0 };
        let mut centers = vec![0.0_f64; bins];
        let mut counts = vec![0_u32; bins];
        for i in 0..bins { centers[i] = base + width * (i as f64 + 0.5); }
        for &v in &values {
            if !v.is_finite() { continue; }
            let mut idx = ((v - base) / width).floor() as isize;
            if idx < 0 { idx = 0; }
            if idx >= bins as isize { idx = bins as isize - 1; }
            counts[idx as usize] += 1;
        }
        OffsetRowOut { counterparty: cp, side: side.into(), trades: n as u32, mean: mu, histogram: OffsetHistOut { centers, counts } }
    }

    let mut out: Vec<OffsetRowOut> = Vec::new();
    for (cp, values) in buyer_vals.into_iter() { out.push(summarize(cp, "buyer", values)); }
    for (cp, values) in seller_vals.into_iter() { out.push(summarize(cp, "seller", values)); }
    out.sort_by(|a, b| b.trades.cmp(&a.trades));
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Effective vs realized spread ────────────────────────────────────
//
// Effective spread: 2 * |price - mid_t|    (taker cost round-trip)
// Realized spread: 2 * sign * (price - mid_{t+Δ}) where sign is the
//   Lee-Ready aggressor classification (+1 buyer-initiated, -1 seller).
// Adverse selection: effective - realized.

#[derive(Deserialize)]
struct EffMetaJs {
    #[serde(rename = "tradeProducts")] trade_products: Vec<String>,
    #[serde(rename = "priceProducts")] price_products: Vec<String>,
    #[serde(rename = "horizonTimestamp")] horizon_timestamp: u32,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
}

#[derive(Serialize)]
struct EffOutProduct {
    product: String,
    n: u32,
    #[serde(rename = "meanEffective")] mean_effective: f64,
    #[serde(rename = "meanRealized")] mean_realized: f64,
    #[serde(rename = "adverseSelection")] adverse_selection: f64,
    #[serde(rename = "meanSign")] mean_sign: f64,
}

#[wasm_bindgen(js_name = computeEffRealized)]
pub fn compute_eff_realized(
    meta: JsValue,
    trade_times: Float64Array,
    trade_prices: Float64Array,
    price_times: Float64Array,
    price_mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: EffMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let trade_times = trade_times.to_vec();
    let trade_prices = trade_prices.to_vec();
    let price_times = price_times.to_vec();
    let price_mids = price_mids.to_vec();
    let index = PriceIndex::build(&price_times, &meta.price_products, &price_mids);
    let product_allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());
    let dt = meta.horizon_timestamp as f64;

    // Per product: (sum_eff, sum_real, sum_sign, n)
    let mut acc: HashMap<String, (f64, f64, f64, u32)> = HashMap::new();

    for i in 0..trade_times.len() {
        let t = trade_times[i];
        let price = trade_prices[i];
        if !finite(t) || !finite(price) { continue; }
        let product = &meta.trade_products[i];
        if let Some(allow) = &product_allow {
            if !allow.contains(product.as_str()) { continue; }
        }
        let mid = match index.mid_at(product, t) { Some(v) => v, None => continue };
        let sign = if price > mid { 1.0 } else if price < mid { -1.0 } else { 0.0 };
        if sign == 0.0 { continue; }
        let future_mid = match index.mid_at(product, t + dt) { Some(v) => v, None => continue };
        let effective = 2.0 * (price - mid).abs();
        let realized = 2.0 * sign * (price - future_mid);
        let slot = acc.entry(product.clone()).or_insert((0.0, 0.0, 0.0, 0));
        slot.0 += effective;
        slot.1 += realized;
        slot.2 += sign;
        slot.3 += 1;
    }

    let mut out: Vec<EffOutProduct> = acc.into_iter().map(|(product, (eff, real, sign, n))| {
        let nf = n as f64;
        let mean_eff = if n == 0 { 0.0 } else { eff / nf };
        let mean_real = if n == 0 { 0.0 } else { real / nf };
        EffOutProduct {
            product,
            n,
            mean_effective: mean_eff,
            mean_realized: mean_real,
            adverse_selection: mean_eff - mean_real,
            mean_sign: if n == 0 { 0.0 } else { sign / nf },
        }
    }).collect();
    out.sort_by(|a, b| a.product.cmp(&b.product));
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Cross-asset: return correlation matrix ──────────────────────────

#[derive(Deserialize)]
struct CorrMetaJs {
    products: Vec<String>,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    #[serde(rename = "returnHorizon")] return_horizon: u32,
}

#[derive(Serialize)]
struct CorrMatrixOut {
    labels: Vec<String>,
    matrix: Vec<f64>,
    n: Vec<u32>,
}

/// Per-product tick-to-tick return correlation matrix.
///
/// Implementation notes:
/// - No dense (N_products × N_times) grid. For a round like P3 R7 (15 products,
///   580k rows, ~50k unique cumulative timestamps, partial per-product overlap)
///   that grid is ~20 MB of HashMap entries and bumps WASM memory limits.
/// - Instead: group rows by product, sort each group by time, diff consecutive
///   rows to get returns keyed by timestamp. Then for each pair of products,
///   two-pointer merge-join on timestamps to pick up the overlapping samples.
/// - Memory scales as O(rows), not O(products × times).
#[wasm_bindgen(js_name = computeCorrMatrix)]
pub fn compute_corr_matrix(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: CorrMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();
    let allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());

    // 1) Group (time, mid) pairs per product.
    let mut by_product: HashMap<String, Vec<(f64, f64)>> = HashMap::new();
    for i in 0..meta.products.len() {
        let p = &meta.products[i];
        if let Some(a) = &allow { if !a.contains(p.as_str()) { continue; } }
        let t = times[i];
        let m = mids[i];
        if !finite(t) || !finite(m) { continue; }
        by_product.entry(p.clone()).or_default().push((t, m));
    }

    let mut labels: Vec<String> = by_product.keys().cloned().collect();
    labels.sort();
    let n_products = labels.len();
    if n_products < 2 {
        return Ok(serde_wasm_bindgen::to_value(&CorrMatrixOut {
            labels, matrix: Vec::new(), n: Vec::new(),
        })?);
    }

    // 2) Per-product returns series: list of (time_end, Δmid) sorted by time.
    //    horizon_steps = 1 diff between consecutive same-product rows. Higher
    //    horizons would re-use the same series but pair i with i+h.
    let horizon_steps = meta.return_horizon.max(1) as usize;
    let mut returns: Vec<Vec<(f64, f64)>> = Vec::with_capacity(n_products);
    for label in &labels {
        let mut series = by_product.remove(label).unwrap_or_default();
        series.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut rets: Vec<(f64, f64)> = Vec::with_capacity(series.len().saturating_sub(horizon_steps));
        if series.len() > horizon_steps {
            for i in 0..(series.len() - horizon_steps) {
                let a = series[i].1;
                let b = series[i + horizon_steps].1;
                if finite(a) && finite(b) {
                    rets.push((series[i + horizon_steps].0, b - a));
                }
            }
        }
        returns.push(rets);
    }

    // 3) Pairwise merge-join + Pearson correlation.
    let mut matrix = vec![0.0_f64; n_products * n_products];
    let mut n_matrix = vec![0_u32; n_products * n_products];
    let mut xs: Vec<f64> = Vec::new();
    let mut ys: Vec<f64> = Vec::new();
    for i in 0..n_products {
        // Diagonal: autocorrelation with self = 1 when there's any data.
        matrix[i * n_products + i] = if returns[i].is_empty() { 0.0 } else { 1.0 };
        n_matrix[i * n_products + i] = returns[i].len() as u32;
        for j in (i + 1)..n_products {
            xs.clear();
            ys.clear();
            let a = &returns[i];
            let b = &returns[j];
            let (mut p, mut q) = (0usize, 0usize);
            while p < a.len() && q < b.len() {
                let ta = a[p].0;
                let tb = b[q].0;
                if ta < tb { p += 1; }
                else if ta > tb { q += 1; }
                else { xs.push(a[p].1); ys.push(b[q].1); p += 1; q += 1; }
            }
            let c = pearson(&xs, &ys);
            matrix[i * n_products + j] = c;
            matrix[j * n_products + i] = c;
            n_matrix[i * n_products + j] = xs.len() as u32;
            n_matrix[j * n_products + i] = xs.len() as u32;
        }
    }
    Ok(serde_wasm_bindgen::to_value(&CorrMatrixOut { labels, matrix, n: n_matrix })?)
}

// ── Cross-asset: lead-lag cross-correlation ─────────────────────────

#[derive(Deserialize)]
struct LeadLagMetaJs {
    products: Vec<String>,
    #[serde(rename = "productA")] product_a: String,
    #[serde(rename = "productB")] product_b: String,
    #[serde(rename = "maxLagSteps")] max_lag_steps: i32,
    #[serde(rename = "stepTimestamp")] step_timestamp: f64,
}

#[derive(Serialize)]
struct LeadLagOut {
    lags: Vec<i32>,
    correlations: Vec<f64>,
    n: Vec<u32>,
    #[serde(rename = "bestLag")] best_lag: i32,
    #[serde(rename = "bestCorr")] best_corr: f64,
}

#[wasm_bindgen(js_name = computeLeadLag)]
pub fn compute_lead_lag(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: LeadLagMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();

    // Gather (time → mid) for each product.
    let mut a_map: HashMap<u64, f64> = HashMap::new();
    let mut b_map: HashMap<u64, f64> = HashMap::new();
    let mut distinct_times_set: HashSet<u64> = HashSet::new();
    for i in 0..meta.products.len() {
        let t = times[i];
        let m = mids[i];
        if !finite(t) || !finite(m) { continue; }
        let k = t.to_bits();
        distinct_times_set.insert(k);
        if meta.products[i] == meta.product_a { a_map.insert(k, m); }
        if meta.products[i] == meta.product_b { b_map.insert(k, m); }
    }
    let mut distinct_times: Vec<f64> = distinct_times_set.iter().map(|&b| f64::from_bits(b)).collect();
    distinct_times.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    // Build parallel return series for A and B at the intersection of timestamps.
    let mut ra: Vec<f64> = Vec::with_capacity(distinct_times.len());
    let mut rb: Vec<f64> = Vec::with_capacity(distinct_times.len());
    for w in distinct_times.windows(2) {
        let t0 = w[0].to_bits(); let t1 = w[1].to_bits();
        let a0 = a_map.get(&t0).copied(); let a1 = a_map.get(&t1).copied();
        let b0 = b_map.get(&t0).copied(); let b1 = b_map.get(&t1).copied();
        ra.push(match (a0, a1) { (Some(x), Some(y)) => y - x, _ => f64::NAN });
        rb.push(match (b0, b1) { (Some(x), Some(y)) => y - x, _ => f64::NAN });
    }

    let max_lag = meta.max_lag_steps.max(1);
    let _ = meta.step_timestamp;
    let mut lags: Vec<i32> = Vec::with_capacity((2 * max_lag + 1) as usize);
    let mut correlations: Vec<f64> = Vec::with_capacity(lags.capacity());
    let mut ns: Vec<u32> = Vec::with_capacity(lags.capacity());
    let mut best_lag = 0_i32;
    let mut best_abs = -1.0_f64;
    let mut best = 0.0_f64;
    for lag in -max_lag..=max_lag {
        lags.push(lag);
        let mut xs: Vec<f64> = Vec::new();
        let mut ys: Vec<f64> = Vec::new();
        // Positive lag ⇒ compare ra[t] vs rb[t + lag] ⇒ A leads B by `lag`.
        let n = ra.len();
        for i in 0..n {
            let j = i as i32 + lag;
            if j < 0 || j as usize >= rb.len() { continue; }
            let a = ra[i]; let b = rb[j as usize];
            if finite(a) && finite(b) { xs.push(a); ys.push(b); }
        }
        let c = pearson(&xs, &ys);
        correlations.push(c);
        ns.push(xs.len() as u32);
        if c.abs() > best_abs { best_abs = c.abs(); best_lag = lag; best = c; }
    }
    Ok(serde_wasm_bindgen::to_value(&LeadLagOut { lags, correlations, n: ns, best_lag, best_corr: best })?)
}

// ── Cross-asset: pair spread + z-score (OLS) ────────────────────────

#[derive(Deserialize)]
struct PairMetaJs {
    products: Vec<String>,
    #[serde(rename = "productA")] product_a: String,
    #[serde(rename = "productB")] product_b: String,
    #[serde(rename = "zWindow")] z_window: usize,
}

#[derive(Serialize)]
struct PairOut {
    beta: f64,
    alpha: f64,
    r2: f64,
    spread: Vec<[f64; 2]>,
    zscore: Vec<[f64; 2]>,
    #[serde(rename = "meanReversionHalfLife")] mean_reversion_half_life: Option<f64>,
}

#[wasm_bindgen(js_name = computePairSpread)]
pub fn compute_pair_spread(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: PairMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();

    // Aligned (time, midA, midB) series.
    let mut a_map: HashMap<u64, f64> = HashMap::new();
    let mut b_map: HashMap<u64, f64> = HashMap::new();
    for i in 0..meta.products.len() {
        let t = times[i]; let m = mids[i];
        if !finite(t) || !finite(m) { continue; }
        let k = t.to_bits();
        if meta.products[i] == meta.product_a { a_map.insert(k, m); }
        if meta.products[i] == meta.product_b { b_map.insert(k, m); }
    }
    let mut aligned: Vec<(f64, f64, f64)> = a_map.iter()
        .filter_map(|(k, &va)| b_map.get(k).map(|&vb| (f64::from_bits(*k), va, vb)))
        .collect();
    aligned.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));

    if aligned.len() < 10 {
        return Ok(serde_wasm_bindgen::to_value(&PairOut {
            beta: 0.0, alpha: 0.0, r2: 0.0,
            spread: Vec::new(), zscore: Vec::new(), mean_reversion_half_life: None,
        })?);
    }

    // OLS: midA = α + β · midB
    let (b_vals, a_vals): (Vec<f64>, Vec<f64>) = aligned.iter().map(|&(_, a, b)| (b, a)).unzip();
    let (beta, alpha) = ols(&b_vals, &a_vals);
    let a_mean = mean(&a_vals);
    let mut ss_res = 0.0;
    let mut ss_tot = 0.0;
    for i in 0..a_vals.len() {
        let pred = alpha + beta * b_vals[i];
        let r = a_vals[i] - pred;
        ss_res += r * r;
        let dt = a_vals[i] - a_mean;
        ss_tot += dt * dt;
    }
    let r2 = if ss_tot == 0.0 { 0.0 } else { 1.0 - ss_res / ss_tot };

    // Residual series: r_t = midA − (α + β·midB)
    let residuals: Vec<f64> = aligned.iter().map(|&(_, a, b)| a - (alpha + beta * b)).collect();

    // Rolling z-score (window centered at right edge): z_t = (r_t − μ_w) / σ_w
    let w = meta.z_window.max(3);
    let mut z_series: Vec<[f64; 2]> = Vec::with_capacity(residuals.len());
    let mut spread_series: Vec<[f64; 2]> = Vec::with_capacity(residuals.len());
    for i in 0..residuals.len() {
        spread_series.push([aligned[i].0, residuals[i]]);
        if i + 1 < w { continue; }
        let start = i + 1 - w;
        let slice = &residuals[start..=i];
        let mu = mean(slice);
        let sd = stdev(slice, mu);
        let z = if sd == 0.0 { 0.0 } else { (residuals[i] - mu) / sd };
        z_series.push([aligned[i].0, z]);
    }

    // OU half-life: r_{t+1} = a + b·r_t + ε → half-life = −ln(2) / ln(1 + b) if b ∈ (−1, 0).
    let half_life = if residuals.len() < 20 {
        None
    } else {
        let x: Vec<f64> = residuals[..residuals.len() - 1].to_vec();
        let y: Vec<f64> = residuals[1..].iter().map(|v| v - 0.0).collect();
        // y = a + b*x. We fit diff form: r_{t+1} − r_t = a' + b'·r_t ⇒ b = b' + 1.
        let y_diff: Vec<f64> = x.iter().zip(y.iter()).map(|(xi, yi)| yi - xi).collect();
        let (b_diff, _a_diff) = ols(&x, &y_diff);
        let b = b_diff + 1.0;
        if b > 0.0 && b < 1.0 { Some(-(2.0_f64).ln() / b.ln()) } else { None }
    };

    Ok(serde_wasm_bindgen::to_value(&PairOut {
        beta, alpha, r2,
        spread: spread_series,
        zscore: z_series,
        mean_reversion_half_life: half_life,
    })?)
}

// ── Exogenous: observation → product return β table ────────────────

#[derive(Deserialize)]
struct ObsCol { name: String, values: Vec<f64> }

#[derive(Deserialize)]
struct ObsBetaMetaJs {
    #[serde(rename = "obsColumns")] obs_columns: Vec<ObsCol>,
    #[serde(rename = "priceProducts")] price_products: Vec<String>,
    #[serde(rename = "lagTimestamp")] lag_timestamp: f64,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
}

#[derive(Serialize)]
struct ObsBetaCellOut {
    observation: String,
    product: String,
    n: u32,
    beta: f64,
    correlation: f64,
    r2: f64,
}

#[wasm_bindgen(js_name = computeObsBeta)]
pub fn compute_obs_beta(
    meta: JsValue,
    obs_times: Float64Array,
    price_times: Float64Array,
    price_mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: ObsBetaMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let obs_times = obs_times.to_vec();
    let price_times = price_times.to_vec();
    let price_mids = price_mids.to_vec();
    let index = PriceIndex::build(&price_times, &meta.price_products, &price_mids);

    let mut products: Vec<String> = index.product_buckets.keys().cloned().collect();
    products.sort();
    let allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());
    let products: Vec<String> = products.into_iter().filter(|p| allow.as_ref().map(|s| s.contains(p.as_str())).unwrap_or(true)).collect();

    let mut out: Vec<ObsBetaCellOut> = Vec::new();
    for obs in &meta.obs_columns {
        for product in &products {
            let mut xs: Vec<f64> = Vec::new();
            let mut ys: Vec<f64> = Vec::new();
            for i in 0..obs_times.len() {
                let t = obs_times[i];
                if !finite(t) { continue; }
                let x = obs.values[i];
                if !finite(x) { continue; }
                let m_now = match index.mid_at(product, t) { Some(v) => v, None => continue };
                let m_future = match index.mid_at(product, t + meta.lag_timestamp) { Some(v) => v, None => continue };
                xs.push(x);
                ys.push(m_future - m_now);
            }
            if xs.len() < 10 { continue; }
            let (beta, _a) = ols(&xs, &ys);
            let c = pearson(&xs, &ys);
            out.push(ObsBetaCellOut {
                observation: obs.name.clone(),
                product: product.clone(),
                n: xs.len() as u32,
                beta,
                correlation: c,
                r2: c * c,
            });
        }
    }
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Realized volatility (rolling stdev of tick returns) ────────────

#[derive(Deserialize)]
struct RealizedVolMetaJs {
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    products: Vec<String>,
    window: usize,
}

#[derive(Serialize)]
struct RealizedVolOut {
    product: String,
    n: u32,
    mean: f64,
    p05: f64,
    p50: f64,
    p95: f64,
    #[serde(rename = "timeSeries")] time_series: Vec<[f64; 2]>,
}

#[wasm_bindgen(js_name = computeRealizedVol)]
pub fn compute_realized_vol(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: RealizedVolMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();
    let window = meta.window.max(2);
    let groups = group_indices(&meta.products, &meta.products_allowed);

    let mut out: Vec<RealizedVolOut> = Vec::new();
    for (product, indices) in groups {
        // Per-product return series: (time_at_row, Δmid vs previous same-product row).
        let mut returns: Vec<(f64, f64)> = Vec::with_capacity(indices.len());
        let mut prev_mid: Option<f64> = None;
        for &i in &indices {
            let t = times[i];
            let m = mids[i];
            if !finite(t) || !finite(m) { continue; }
            if let Some(p) = prev_mid {
                returns.push((t, m - p));
            }
            prev_mid = Some(m);
        }
        if returns.len() < window + 1 { continue; }

        // Rolling sum / sum-of-squares — O(N) with a single pass.
        let mut sum = 0.0_f64;
        let mut sum2 = 0.0_f64;
        for i in 0..window {
            let r = returns[i].1;
            sum += r;
            sum2 += r * r;
        }
        let mut sd_series: Vec<[f64; 2]> = Vec::with_capacity(returns.len() - window + 1);
        let mut sd_values: Vec<f64> = Vec::with_capacity(returns.len() - window + 1);
        let w = window as f64;
        // First window ends at index window-1.
        let emit = |t: f64, sum: f64, sum2: f64, bucket: &mut Vec<[f64; 2]>, bucket_v: &mut Vec<f64>| {
            let mu = sum / w;
            // Sample variance: (Σx² − n·μ²) / (n − 1). Guard against tiny negatives from FP drift.
            let var = ((sum2 - w * mu * mu) / (w - 1.0)).max(0.0);
            let sd = var.sqrt();
            bucket.push([t, sd]);
            bucket_v.push(sd);
        };
        emit(returns[window - 1].0, sum, sum2, &mut sd_series, &mut sd_values);
        for i in window..returns.len() {
            let add = returns[i].1;
            let drop = returns[i - window].1;
            sum += add - drop;
            sum2 += add * add - drop * drop;
            emit(returns[i].0, sum, sum2, &mut sd_series, &mut sd_values);
        }
        if sd_values.is_empty() { continue; }
        let mu = mean(&sd_values);
        let mut sorted = sd_values.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        out.push(RealizedVolOut {
            product,
            n: sd_values.len() as u32,
            mean: mu,
            p05: quantile_sorted(&sorted, 0.05),
            p50: quantile_sorted(&sorted, 0.5),
            p95: quantile_sorted(&sorted, 0.95),
            time_series: decimate(&sd_series, 5000),
        });
    }
    out.sort_by(|a, b| a.product.cmp(&b.product));
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Return autocorrelation + Ljung-Box ──────────────────────────────
//
// ACF(k) = corr(r_t, r_{t+k}) with a single shared mean. Bartlett-bound CI
// ≈ ±1.96/√n. Ljung-Box Q = n(n+2)·Σ ρ_k² / (n−k), tested against χ²(max_lag)
// via the Wilson-Hilferty approximation (df ≥ 2 ⇒ <1% error in the tail).

#[derive(Deserialize)]
struct AutocorrMetaJs {
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
    products: Vec<String>,
    #[serde(rename = "maxLag")] max_lag: usize,
}

#[derive(Serialize)]
struct AutocorrOut {
    product: String,
    n: u32,
    lags: Vec<u32>,
    acf: Vec<f64>,
    #[serde(rename = "ciUpper")] ci_upper: f64,
    #[serde(rename = "ciLower")] ci_lower: f64,
    #[serde(rename = "ljungBoxQ")] ljung_box_q: f64,
    #[serde(rename = "ljungBoxP")] ljung_box_p: f64,
}

fn standard_normal_cdf(z: f64) -> f64 {
    // Abramowitz & Stegun 7.1.26 — max error ≈ 1.5e-7.
    let sign = if z < 0.0 { -1.0 } else { 1.0 };
    let x = z.abs() / std::f64::consts::SQRT_2;
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let erf = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
        - 0.284496736) * t + 0.254829592) * t * (-x * x).exp();
    0.5 * (1.0 + sign * erf)
}

fn chi2_upper_p(q: f64, df: f64) -> f64 {
    if df <= 0.0 || !q.is_finite() || q < 0.0 { return 1.0; }
    // Wilson-Hilferty: (χ²/df)^(1/3) is approx. Normal(1 − 2/9df, 2/9df).
    let h = 2.0 / (9.0 * df);
    let z = ((q / df).powf(1.0 / 3.0) - (1.0 - h)) / h.sqrt();
    (1.0 - standard_normal_cdf(z)).clamp(0.0, 1.0)
}

#[wasm_bindgen(js_name = computeAutocorr)]
pub fn compute_autocorr(
    meta: JsValue,
    _times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: AutocorrMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let mids = mids.to_vec();
    let max_lag = meta.max_lag.max(1);
    let groups = group_indices(&meta.products, &meta.products_allowed);

    let mut out: Vec<AutocorrOut> = Vec::new();
    for (product, indices) in groups {
        let mut returns: Vec<f64> = Vec::with_capacity(indices.len());
        let mut prev_mid: Option<f64> = None;
        for &i in &indices {
            let m = mids[i];
            if !finite(m) { continue; }
            if let Some(p) = prev_mid {
                returns.push(m - p);
            }
            prev_mid = Some(m);
        }
        let n = returns.len();
        if n <= max_lag + 10 { continue; }

        let mu = mean(&returns);
        let mut ss0 = 0.0_f64;
        for &r in &returns { let d = r - mu; ss0 += d * d; }
        if ss0 == 0.0 { continue; }

        let mut lags: Vec<u32> = Vec::with_capacity(max_lag);
        let mut acf: Vec<f64> = Vec::with_capacity(max_lag);
        let mut q_sum = 0.0_f64;
        for k in 1..=max_lag {
            let mut num = 0.0_f64;
            for i in 0..(n - k) {
                num += (returns[i] - mu) * (returns[i + k] - mu);
            }
            let rho = num / ss0;
            lags.push(k as u32);
            acf.push(rho);
            q_sum += rho * rho / ((n - k) as f64);
        }
        let nf = n as f64;
        let ljung_q = nf * (nf + 2.0) * q_sum;
        let ljung_p = chi2_upper_p(ljung_q, max_lag as f64);
        let ci = 1.96 / nf.sqrt();
        out.push(AutocorrOut {
            product,
            n: n as u32,
            lags,
            acf,
            ci_upper: ci,
            ci_lower: -ci,
            ljung_box_q: ljung_q,
            ljung_box_p: ljung_p,
        });
    }
    out.sort_by(|a, b| a.product.cmp(&b.product));
    Ok(serde_wasm_bindgen::to_value(&out)?)
}

// ── Rolling β (pair of products) ────────────────────────────────────
//
// Align midA / midB on matching timestamps (same merge-join pattern as
// pairSpread), diff to get return series, then slide a window computing
// OLS slope of returnsA on returnsB plus rolling R² = corr².

#[derive(Deserialize)]
struct RollingBetaMetaJs {
    products: Vec<String>,
    #[serde(rename = "productA")] product_a: String,
    #[serde(rename = "productB")] product_b: String,
    window: usize,
}

#[derive(Serialize)]
struct RollingBetaOut {
    #[serde(rename = "betaSeries")] beta_series: Vec<[f64; 2]>,
    #[serde(rename = "r2Series")] r2_series: Vec<[f64; 2]>,
    #[serde(rename = "fullBeta")] full_beta: f64,
    #[serde(rename = "fullR2")] full_r2: f64,
    n: u32,
}

#[wasm_bindgen(js_name = computeRollingBeta)]
pub fn compute_rolling_beta(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: RollingBetaMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();

    let mut a_map: HashMap<u64, f64> = HashMap::new();
    let mut b_map: HashMap<u64, f64> = HashMap::new();
    for i in 0..meta.products.len() {
        let t = times[i]; let m = mids[i];
        if !finite(t) || !finite(m) { continue; }
        let k = t.to_bits();
        if meta.products[i] == meta.product_a { a_map.insert(k, m); }
        if meta.products[i] == meta.product_b { b_map.insert(k, m); }
    }
    let mut aligned: Vec<(f64, f64, f64)> = a_map.iter()
        .filter_map(|(k, &va)| b_map.get(k).map(|&vb| (f64::from_bits(*k), va, vb)))
        .collect();
    aligned.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));

    let window = meta.window.max(10);
    if aligned.len() < window + 2 {
        return Ok(serde_wasm_bindgen::to_value(&RollingBetaOut {
            beta_series: Vec::new(),
            r2_series: Vec::new(),
            full_beta: 0.0,
            full_r2: 0.0,
            n: 0,
        })?);
    }

    let n_rets = aligned.len() - 1;
    let mut ts: Vec<f64> = Vec::with_capacity(n_rets);
    let mut ra: Vec<f64> = Vec::with_capacity(n_rets);
    let mut rb: Vec<f64> = Vec::with_capacity(n_rets);
    for i in 1..aligned.len() {
        ts.push(aligned[i].0);
        ra.push(aligned[i].1 - aligned[i - 1].1);
        rb.push(aligned[i].2 - aligned[i - 1].2);
    }

    let (full_beta, _) = ols(&rb, &ra);
    let full_r = pearson(&rb, &ra);

    // Rolling OLS / Pearson via sliding sums. O(N) after the initial window.
    let mut beta_series: Vec<[f64; 2]> = Vec::new();
    let mut r2_series: Vec<[f64; 2]> = Vec::new();
    if n_rets >= window {
        let w = window as f64;
        let (mut sa, mut sb) = (0.0_f64, 0.0_f64);
        let (mut saa, mut sbb, mut sab) = (0.0_f64, 0.0_f64, 0.0_f64);
        for i in 0..window {
            sa += ra[i]; sb += rb[i];
            saa += ra[i] * ra[i]; sbb += rb[i] * rb[i]; sab += ra[i] * rb[i];
        }
        let push = |ts: &[f64], idx: usize,
                    sa: f64, sb: f64, saa: f64, sbb: f64, sab: f64,
                    beta: &mut Vec<[f64; 2]>, r2: &mut Vec<[f64; 2]>| {
            let ma = sa / w;
            let mb = sb / w;
            let cov = sab - w * ma * mb;
            let var_b = sbb - w * mb * mb;
            let var_a = saa - w * ma * ma;
            let slope = if var_b > 0.0 { cov / var_b } else { 0.0 };
            let r = if var_a > 0.0 && var_b > 0.0 { cov / (var_a * var_b).sqrt() } else { 0.0 };
            beta.push([ts[idx], slope]);
            r2.push([ts[idx], r * r]);
        };
        push(&ts, window - 1, sa, sb, saa, sbb, sab, &mut beta_series, &mut r2_series);
        for i in window..n_rets {
            let add_a = ra[i]; let add_b = rb[i];
            let drop_a = ra[i - window]; let drop_b = rb[i - window];
            sa += add_a - drop_a;
            sb += add_b - drop_b;
            saa += add_a * add_a - drop_a * drop_a;
            sbb += add_b * add_b - drop_b * drop_b;
            sab += add_a * add_b - drop_a * drop_b;
            push(&ts, i, sa, sb, saa, sbb, sab, &mut beta_series, &mut r2_series);
        }
    }

    Ok(serde_wasm_bindgen::to_value(&RollingBetaOut {
        beta_series: decimate(&beta_series, 5000),
        r2_series: decimate(&r2_series, 5000),
        full_beta,
        full_r2: full_r * full_r,
        n: n_rets as u32,
    })?)
}

// ── Seasonality: per-product stats by intraday bucket ──────────────

#[derive(Deserialize)]
struct SeasonalityMetaJs {
    products: Vec<String>,
    #[serde(rename = "dayPeriod")] day_period: f64,
    buckets: usize,
    #[serde(rename = "productsAllowed")] products_allowed: Option<Vec<String>>,
}

#[derive(Serialize)]
struct SeasonalityOut {
    product: String,
    #[serde(rename = "bucketCenters")] bucket_centers: Vec<f64>,
    #[serde(rename = "meanSpread")] mean_spread: Vec<f64>,
    #[serde(rename = "returnVol")] return_vol: Vec<f64>,
    n: Vec<u32>,
}

#[wasm_bindgen(js_name = computeSeasonality)]
pub fn compute_seasonality(
    meta: JsValue,
    times: Float64Array,
    mids: Float64Array,
    bid1: Float64Array,
    ask1: Float64Array,
) -> Result<JsValue, JsValue> {
    let meta: SeasonalityMetaJs = serde_wasm_bindgen::from_value(meta)?;
    let times = times.to_vec();
    let mids = mids.to_vec();
    let bid1 = bid1.to_vec();
    let ask1 = ask1.to_vec();
    let allow: Option<HashSet<&str>> = meta.products_allowed.as_ref().map(|v| v.iter().map(String::as_str).collect());
    let buckets = meta.buckets.max(1);
    let period = meta.day_period.max(1.0);

    // Per product: per-bucket (sum_spread, sum_return_sq, n)
    let mut acc: HashMap<String, (Vec<f64>, Vec<f64>, Vec<u32>, Vec<f64>)> = HashMap::new();
    // (spread_sum, ret2_sum, n, last_mid_in_bucket)
    // Approach for return-vol: compute per-row Δmid vs previous row of the SAME product,
    // bucket by that row's time-of-day, and accumulate ret^2.
    let mut prev_mid: HashMap<String, f64> = HashMap::new();
    for i in 0..meta.products.len() {
        let p = &meta.products[i];
        if let Some(a) = &allow { if !a.contains(p.as_str()) { continue; } }
        let t = times[i]; let m = mids[i]; let bp = bid1[i]; let ap = ask1[i];
        if !finite(t) { continue; }
        let bucket = ((t.rem_euclid(period)) / period * buckets as f64).floor() as isize;
        let bucket = bucket.clamp(0, buckets as isize - 1) as usize;
        let slot = acc.entry(p.clone()).or_insert_with(|| (
            vec![0.0; buckets], vec![0.0; buckets], vec![0; buckets], vec![0.0; buckets],
        ));
        if finite(bp) && finite(ap) {
            slot.0[bucket] += ap - bp;
        }
        if finite(m) {
            if let Some(prev) = prev_mid.get(p) {
                let r = m - prev;
                slot.1[bucket] += r * r;
            }
            prev_mid.insert(p.clone(), m);
        }
        slot.2[bucket] += 1;
    }

    let mut out: Vec<SeasonalityOut> = Vec::new();
    let bucket_centers: Vec<f64> = (0..buckets).map(|b| (b as f64 + 0.5) / buckets as f64 * period).collect();
    for (product, (spread_sum, ret2_sum, n, _last)) in acc.into_iter() {
        let mean_spread: Vec<f64> = spread_sum.iter().zip(n.iter())
            .map(|(s, c)| if *c == 0 { 0.0 } else { s / *c as f64 }).collect();
        let return_vol: Vec<f64> = ret2_sum.iter().zip(n.iter())
            .map(|(s, c)| if *c == 0 { 0.0 } else { (s / *c as f64).sqrt() }).collect();
        out.push(SeasonalityOut {
            product,
            bucket_centers: bucket_centers.clone(),
            mean_spread,
            return_vol,
            n,
        });
    }
    out.sort_by(|a, b| a.product.cmp(&b.product));
    Ok(serde_wasm_bindgen::to_value(&out)?)
}
