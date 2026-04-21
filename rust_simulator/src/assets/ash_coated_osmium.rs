//! ASH_COATED_OSMIUM — Gaussian random-walk product with fixed integer bot offsets.
//!
//! Calibration lives at `calibration/ash_coated_osmium/`.
//!
//! CLI flags (pass as `--ash-coated-osmium-<flag>`):
//!   `replay-fv`  path to JSON with observed FV (flat [f64] or object with key "osmium")

use crate::asset::{
    AssetSim, Book, FlagKind, FlagSpec, InputPriceRow, load_replay_fv_path, parse_path,
    quantize_1024, sample_standard_normal,
};
use anyhow::Result;
use rand::distributions::{Distribution, WeightedIndex};
use rand::Rng;
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;
use std::path::PathBuf;

pub const SYMBOL: &str = "ASH_COATED_OSMIUM";

// Calibrated rates (R2 hold-1 + R2 MM submissions — see calibration/ash_coated_osmium/calibration.md
// and the CLAUDE.md "Portal Submission Results" section for provenance).
const BASE_TRADE_PROB: f64 = 1200.0 / 30_000.0; // ~4.0%
const SECOND_TRADE_PROB: f64 = 13.0 / 1200.0;
const ELASTIC_TRADE_PROB: f64 = 0.040;
const BUY_PROB: f64 = 0.5;
const POSITION_LIMIT: i32 = 80;

pub struct AshCoatedOsmium {
    replay_fv: Option<Vec<f64>>,
}

pub fn flag_specs() -> Vec<FlagSpec> {
    vec![FlagSpec {
        name: "replay-fv",
        kind: FlagKind::Path,
        default: None,
        help: "Replay observed FV (JSON: flat [f64] or object with 'osmium' key)",
    }]
}

pub fn build(flags: &HashMap<String, String>) -> Result<Box<dyn AssetSim>> {
    let replay_fv = match flags.get("replay-fv") {
        Some(raw) => {
            let path = parse_path("ash-coated-osmium-replay-fv", raw)?;
            Some(load_replay_fv_path(&path, "osmium")?)
        }
        None => None,
    };
    Ok(Box::new(AshCoatedOsmium { replay_fv }))
}

impl AssetSim for AshCoatedOsmium {
    fn symbol(&self) -> &str {
        SYMBOL
    }

    fn position_limit(&self) -> i32 {
        POSITION_LIMIT
    }

    fn simulate_fv(
        &self,
        _day_index: usize,
        ticks: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<Vec<f64>> {
        if let Some(observed) = &self.replay_fv {
            // Slice/replicate to the requested tick count.
            let mut out = Vec::with_capacity(ticks);
            for i in 0..ticks {
                out.push(observed[i.min(observed.len() - 1)]);
            }
            return Ok(out);
        }
        // Mean-reverting random walk with AR(1) on steps + OU pullback — calibrated
        // from R1 data (OSMIUM_ANALYSIS.md).
        let start = 10_000.0;
        let mu = 10_000.0;
        let theta = 0.008;
        let ar_coef = -0.32;
        let sigma = 0.38;
        let mut values = vec![0.0; ticks];
        if ticks > 0 {
            values[0] = quantize_1024(start);
        }
        let mut prev_step = 0.0;
        for i in 1..ticks {
            let ou_pull = -theta * (values[i - 1] - mu);
            let noise = sigma * sample_standard_normal(rng);
            let step = ou_pull + ar_coef * prev_step + noise;
            values[i] = quantize_1024(values[i - 1] + step);
            prev_step = values[i] - values[i - 1];
        }
        Ok(values)
    }

    fn infer_observed_fair(&self, row: &InputPriceRow) -> f64 {
        // OSMIUM-specific: deepest bid/ask midpoint (same as the default in the trait)
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

    fn make_book(&self, fair: f64, rng: &mut ChaCha8Rng) -> Book {
        // Bot 1 (outer wall): floor(FV)-10 / ceil(FV)+10, vol U(20,30), 80% each side
        // Bot 2 (inner wall): round(FV)±8 via floor(FV-0.5), vol U(10,15), 80% each side
        // Bot 3 (noise): 8% total, single-sided, offsets {-3,-2,1,2}, vol U(4,10) crossing / U(1,5) passive
        let bot1_bid_present = rng.gen_bool(0.80);
        let bot1_ask_present = rng.gen_bool(0.80);
        let bot2_bid_present = rng.gen_bool(0.80);
        let bot2_ask_present = rng.gen_bool(0.80);

        let bot1_vol = rng.gen_range(20..=30);
        let bot1_bid = fair.floor() as i32 - 10;
        let bot1_ask = fair.ceil() as i32 + 10;

        let bot2_vol = rng.gen_range(10..=15);
        let r = (fair - 0.5).floor() as i32;
        let bot2_bid = r - 7;
        let bot2_ask = r + 9;

        let bot3_draw: f64 = rng.gen_range(0.0..1.0);

        let mut bids: Vec<(i32, i32)> = Vec::new();
        let mut asks: Vec<(i32, i32)> = Vec::new();

        if bot2_bid_present {
            bids.push((bot2_bid, bot2_vol));
        }
        if bot1_bid_present {
            bids.push((bot1_bid, bot1_vol));
        }
        if bot2_ask_present {
            asks.push((bot2_ask, bot2_vol));
        }
        if bot1_ask_present {
            asks.push((bot1_ask, bot1_vol));
        }

        if bot3_draw < 0.04 {
            let offset = [-3, -2, 1, 2][rng.gen_range(0..4)];
            let price = fair.round() as i32 + offset;
            let crossing = price as f64 > fair;
            let vol = if crossing {
                rng.gen_range(4..=10)
            } else {
                rng.gen_range(1..=5)
            };
            bids.push((price, vol));
        } else if bot3_draw < 0.08 {
            let offset = [-3, -2, 1, 2][rng.gen_range(0..4)];
            let price = fair.round() as i32 + offset;
            let crossing = (price as f64) < fair;
            let vol = if crossing {
                rng.gen_range(4..=10)
            } else {
                rng.gen_range(1..=5)
            };
            asks.push((price, vol));
        }

        bids.sort_by(|a, b| b.0.cmp(&a.0));
        asks.sort_by(|a, b| a.0.cmp(&b.0));
        Book { bids, asks }
    }

    fn base_trade_prob(&self) -> f64 {
        BASE_TRADE_PROB
    }

    fn second_trade_prob(&self) -> f64 {
        SECOND_TRADE_PROB
    }

    fn elastic_trade_prob(&self) -> f64 {
        ELASTIC_TRADE_PROB
    }

    fn buy_prob(&self) -> f64 {
        BUY_PROB
    }

    fn sample_trade_qty(
        &self,
        market_buy: bool,
        volume_limit: i32,
        rng: &mut ChaCha8Rng,
    ) -> i32 {
        let (values, weights): (&[i32], &[u32]) = if market_buy {
            (
                &[2, 3, 4, 5, 6, 7, 8, 9, 10],
                &[80, 90, 86, 112, 115, 39, 36, 38, 38],
            )
        } else {
            (
                &[2, 3, 4, 5, 6, 7, 8, 9, 10],
                &[80, 89, 86, 112, 115, 39, 35, 38, 37],
            )
        };
        sample_weighted_within(values, weights, volume_limit, rng)
    }
}

fn sample_weighted_within(
    values: &[i32],
    weights: &[u32],
    volume_limit: i32,
    rng: &mut ChaCha8Rng,
) -> i32 {
    let filtered: Vec<(i32, u32)> = values
        .iter()
        .zip(weights.iter())
        .filter(|(value, _)| **value <= volume_limit)
        .map(|(v, w)| (*v, *w))
        .collect();
    if filtered.is_empty() {
        return volume_limit.max(1);
    }
    let filtered_values: Vec<i32> = filtered.iter().map(|(v, _)| *v).collect();
    let filtered_weights: Vec<u32> = filtered.iter().map(|(_, w)| *w).collect();
    let chooser = WeightedIndex::new(filtered_weights).expect("valid trade weights");
    filtered_values[chooser.sample(rng)]
}

#[allow(dead_code)]
fn _ensure_used(_p: Option<PathBuf>) {}
