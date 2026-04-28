//! Scenario abstraction. Decouples FV/pulse generation from per-asset book +
//! trade-rate logic. Two implementations:
//!   - `IndependentScenario`: thin wrapper over per-asset `AssetSim::simulate_fv`
//!     and Bernoulli trade-count sampling. Used by R3/R4 (and any earlier round).
//!   - `R5Scenario` (in `scenarios::r5`): joint FV generation with constraints
//!     (pebble basket sum, snackpack pair K_day) and shared 3-process pulse
//!     trade events. Used by R5.
//!
//! `IndependentScenario` is structured so that the existing per-tick loop in
//! main.rs is unchanged when it's the active scenario — fields and methods
//! produce the same outputs as the inlined per-asset logic.

use crate::asset::AssetSim;
use anyhow::{Context, Result};
use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PulseDir {
    Buy,
    Sell,
}

#[derive(Clone, Debug)]
pub struct Pulse {
    pub tick: usize,
    pub group: String,
    pub members: Vec<String>,
    pub direction: PulseDir,
    pub quantity: i32,
}

/// Output of a one-day generation step. Both fv_paths and pulses are keyed
/// per-day; per-session orchestration calls `generate_day` once per day.
#[derive(Clone, Debug, Default)]
pub struct DayData {
    /// FV path per active symbol for this day. Length = ticks_per_day.
    pub fv_paths: HashMap<String, Vec<f64>>,
    /// Pulses for this day, sorted by tick. Empty for IndependentScenario.
    pub pulses: Vec<Pulse>,
}

/// One day's bot-trade-count series per asset (Bernoulli sampling from base/second
/// rates). Empty for R5 — pulses replace this.
#[derive(Clone, Debug, Default)]
pub struct DayTradeCounts {
    pub per_asset: HashMap<String, Vec<usize>>,
}

pub trait Scenario: Send + Sync {
    /// True if this scenario uses the pulse trade model (replaces per-asset
    /// Bernoulli base-rate trade sampling). When true, callers should ignore
    /// per-asset trade rates and instead consume `DayData::pulses`.
    fn uses_pulses(&self) -> bool;

    /// Generate FV paths (and pulses, if applicable) for one day.
    fn generate_day_data(
        &self,
        day: i32,
        ticks_per_day: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<DayData>;
}

/// Default scenario: each asset generates its FV independently and trade counts
/// are sampled from per-asset Bernoulli rates. This is the R1/R2/R3/R4 path.
pub struct IndependentScenario {
    /// Active asset symbols, in the same order as `Config::assets`.
    /// Used to drive `simulate_fv` per asset.
    pub day_index_map: Vec<i32>,
}

impl IndependentScenario {
    pub fn new(day_index_map: Vec<i32>) -> Self {
        Self { day_index_map }
    }

    /// Replicates the per-asset FV-simulation step from main.rs::generate_day.
    /// Caller passes the `assets` list (config.assets); FVs are generated in that
    /// order so the shared rng stream is deterministic.
    pub fn simulate_independent_fvs(
        &self,
        assets: &[Box<dyn AssetSim>],
        day: i32,
        ticks_per_day: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<HashMap<String, Vec<f64>>> {
        let day_index = self.day_index_map.iter().position(|d| *d == day).unwrap_or(0);
        let mut fvs: HashMap<String, Vec<f64>> = HashMap::new();
        for asset in assets {
            let symbol = asset.symbol().to_string();
            let fv = asset.simulate_fv(day_index, ticks_per_day, rng)?;
            fvs.insert(symbol, fv);
        }
        Ok(fvs)
    }
}

impl Scenario for IndependentScenario {
    fn uses_pulses(&self) -> bool {
        false
    }

    fn generate_day_data(
        &self,
        _day: i32,
        _ticks_per_day: usize,
        _rng: &mut ChaCha8Rng,
    ) -> Result<DayData> {
        // Independent path computes FVs via per-asset simulate_fv directly in
        // the call site; this trait method isn't used for the R3/R4 flow.
        // Returned DayData is empty; the legacy code reads FVs via the helper above.
        Ok(DayData::default())
    }
}

/// Sample Bernoulli trade counts for one asset over a day. Identical to the
/// existing `simulate_trade_counts` in main.rs — kept here so IndependentScenario
/// can be used for trade-count generation without changing main.rs's semantics.
#[allow(dead_code)]
pub fn simulate_independent_trade_counts(
    base_prob: f64,
    second_prob: f64,
    ticks: usize,
    rng: &mut ChaCha8Rng,
) -> Vec<usize> {
    let mut counts = vec![0usize; ticks];
    for count in &mut counts {
        if rng.gen_bool(base_prob) {
            *count = 1;
            if second_prob > 0.0 && rng.gen_bool(second_prob) {
                *count += 1;
            }
        }
    }
    counts
}

/// Helper: build a fresh ChaCha8Rng from a seed (mirrors main.rs convention).
#[allow(dead_code)]
pub fn rng_from_seed(seed: u64) -> ChaCha8Rng {
    ChaCha8Rng::seed_from_u64(seed)
}

/// Convenience: format a "missing FV" error against a known-good Result chain.
#[allow(dead_code)]
pub fn missing_fv<T>(symbol: &str) -> Result<T> {
    Err(anyhow::anyhow!("missing FV for {symbol}")).context("scenario lookup")
}
