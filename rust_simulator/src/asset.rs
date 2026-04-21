//! Asset-sim abstraction. Everything a specific product needs to plug into the
//! Monte Carlo lives behind the `AssetSim` trait. Add a new asset by creating
//! `src/assets/<snake>.rs`, implementing the trait, and registering it in
//! `src/assets/mod.rs::REGISTRY`.

use anyhow::{Context, Result, bail};
use rand_chacha::ChaCha8Rng;
use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

// ---------------- Shared book/fill types ----------------

#[derive(Clone, Debug)]
pub struct Book {
    pub bids: Vec<(i32, i32)>,
    pub asks: Vec<(i32, i32)>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LevelOwner {
    Bot,
    Strategy,
}

#[derive(Clone, Debug)]
pub struct Level {
    pub price: i32,
    pub quantity: i32,
    pub owner: LevelOwner,
}

#[derive(Clone, Debug)]
pub struct SimBook {
    pub bids: Vec<Level>,
    pub asks: Vec<Level>,
}

#[derive(Clone, Debug)]
pub struct Fill {
    pub symbol: String,
    pub price: i32,
    pub quantity: i32,
    pub buyer: Option<String>,
    pub seller: Option<String>,
    pub timestamp: i32,
}

#[derive(Clone, Debug, Default)]
pub struct ProductLedger {
    pub position: i32,
    pub cash: f64,
}

// Input CSV row type that assets use when --fv-mode=replay reads observed market data.
#[allow(dead_code)]
#[derive(Debug, Deserialize)]
pub struct InputPriceRow {
    pub day: i32,
    pub timestamp: i32,
    pub product: String,
    pub bid_price_1: Option<i32>,
    pub bid_volume_1: Option<i32>,
    pub bid_price_2: Option<i32>,
    pub bid_volume_2: Option<i32>,
    pub bid_price_3: Option<i32>,
    pub bid_volume_3: Option<i32>,
    pub ask_price_1: Option<i32>,
    pub ask_volume_1: Option<i32>,
    pub ask_price_2: Option<i32>,
    pub ask_volume_2: Option<i32>,
    pub ask_price_3: Option<i32>,
    pub ask_volume_3: Option<i32>,
    pub mid_price: f64,
    pub profit_and_loss: f64,
}

// ---------------- Numerical helpers shared by all assets ----------------

pub fn quantize_1024(value: f64) -> f64 {
    (value * 1024.0).round() / 1024.0
}

pub fn sample_standard_normal(rng: &mut ChaCha8Rng) -> f64 {
    use rand::Rng;
    let u1 = rng.gen_range(f64::EPSILON..1.0);
    let u2 = rng.gen_range(0.0..1.0);
    (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

// ---------------- Flag spec (per-asset CLI flag declarations) ----------------

#[derive(Clone, Copy, Debug)]
pub enum FlagKind {
    Float,
    Path,
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct FlagSpec {
    /// Short name, e.g. "start-fv". Full CLI flag becomes `--<asset-kebab>-<short>`.
    pub name: &'static str,
    pub kind: FlagKind,
    pub default: Option<String>,
    pub help: &'static str,
}

// ---------------- Replay-FV helper (per-asset) ----------------

/// Load an observed server-FV path from JSON. Accepts two shapes:
///   1. flat array: `[12345.0, 12345.1, ...]`
///   2. object with a key named `short_key`: `{"pepper": [...], "osmium": [...]}`
pub fn load_replay_fv_path(path: &PathBuf, short_key: &str) -> Result<Vec<f64>> {
    let text = fs::read_to_string(path)
        .with_context(|| format!("reading replay FV json {}", path.display()))?;
    // Try the object form first so we can coexist with the combined OSMIUM+PEPPER
    // file at calibration/intarian_pepper_root/data/r2_day1_fv.json.
    if let Ok(map) = serde_json::from_str::<HashMap<String, serde_json::Value>>(&text) {
        if let Some(value) = map.get(short_key) {
            if let Ok(arr) = serde_json::from_value::<Vec<f64>>(value.clone()) {
                return Ok(arr);
            }
        }
    }
    // Fall back to flat-array form.
    serde_json::from_str::<Vec<f64>>(&text).with_context(|| {
        format!(
            "replay FV json {} is neither a flat [f64] array nor an object with key '{}'",
            path.display(),
            short_key
        )
    })
}

// ---------------- AssetSim trait ----------------

pub trait AssetSim: Send + Sync {
    fn symbol(&self) -> &str;
    fn position_limit(&self) -> i32;

    /// Fair-value trajectory for one day. `day_index` is the day's position in the
    /// session (0-based) — drift-style assets use it to compute a continuous FV
    /// across days within a session.
    fn simulate_fv(
        &self,
        day_index: usize,
        ticks: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<Vec<f64>>;

    /// FV inferred from a CSV price row (deepest bid/ask midpoint). Used by --fv-mode=replay.
    fn infer_observed_fair(&self, row: &InputPriceRow) -> f64 {
        let bids = [row.bid_price_1, row.bid_price_2, row.bid_price_3]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>();
        let asks = [row.ask_price_1, row.ask_price_2, row.ask_price_3]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>();
        let worst_bid = bids.into_iter().min().unwrap_or(0);
        let worst_ask = asks.into_iter().max().unwrap_or(0);
        (worst_bid as f64 + worst_ask as f64) / 2.0
    }

    fn make_book(&self, fv: f64, rng: &mut ChaCha8Rng) -> Book;

    fn base_trade_prob(&self) -> f64;
    fn second_trade_prob(&self) -> f64;
    fn elastic_trade_prob(&self) -> f64;
    fn buy_prob(&self) -> f64;

    fn sample_trade_qty(
        &self,
        market_buy: bool,
        volume_limit: i32,
        rng: &mut ChaCha8Rng,
    ) -> i32;
}

// ---------------- Flag parsing helpers ----------------

/// Convert ASSET_SYMBOL → asset-kebab (lowercase, underscores → dashes).
pub fn symbol_to_kebab(symbol: &str) -> String {
    symbol.to_lowercase().replace('_', "-")
}

/// Parse a flag value from CLI args, reporting a helpful error on miss or wrong type.
pub fn parse_f64(flag: &str, raw: &str) -> Result<f64> {
    raw.parse::<f64>()
        .with_context(|| format!("invalid value for --{}: {}", flag, raw))
}

/// For --<asset-kebab>-replay-fv: parse a path. No existence check here; the loader
/// will produce a clear error at use site.
pub fn parse_path(flag: &str, raw: &str) -> Result<PathBuf> {
    if raw.is_empty() {
        bail!("empty path passed to --{}", flag);
    }
    Ok(PathBuf::from(raw))
}
