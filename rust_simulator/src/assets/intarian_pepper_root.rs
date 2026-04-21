//! INTARIAN_PEPPER_ROOT — deterministic +0.1/tick drift, proportional bot offsets.
//!
//! Calibration lives at `calibration/intarian_pepper_root/`.
//!
//! CLI flags (pass as `--intarian-pepper-root-<flag>`):
//!   `start-fv`   f64 — starting FV for day 0 of the session (R2 day 1 = 13000)
//!   `replay-fv`  path — JSON with observed FV (flat [f64] or object with key "pepper")

use crate::asset::{
    AssetSim, Book, FlagKind, FlagSpec, load_replay_fv_path, parse_f64, parse_path,
    quantize_1024,
};
use anyhow::Result;
use rand::distributions::{Distribution, WeightedIndex};
use rand::Rng;
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;

pub const SYMBOL: &str = "INTARIAN_PEPPER_ROOT";

const BASE_TRADE_PROB: f64 = 972.0 / 30_000.0;  // ~3.2% (274082 hold-1 confirmed)
const SECOND_TRADE_PROB: f64 = 4.0 / 972.0;
const ELASTIC_TRADE_PROB: f64 = 0.009;           // ~0.9% (R1 MM + R2 MM minus base rate)
const BUY_PROB: f64 = 0.5;
const DRIFT_PER_TICK: f64 = 0.1;
const POSITION_LIMIT: i32 = 80;

// Proportional offset constants (see calibration/intarian_pepper_root/calibration.md)
const K1: f64 = 3.0 / 4000.0; // Bot 1 outer wall
const K2: f64 = 1.0 / 2000.0; // Bot 2 inner wall

pub struct IntarianPepperRoot {
    start_fv: f64,
    replay_fv: Option<Vec<f64>>,
}

pub fn flag_specs() -> Vec<FlagSpec> {
    vec![
        FlagSpec {
            name: "start-fv",
            kind: FlagKind::Float,
            default: Some("10000.0".to_string()),
            help: "Starting FV for day 0 of the session (R2 day 1 = 13000)",
        },
        FlagSpec {
            name: "replay-fv",
            kind: FlagKind::Path,
            default: None,
            help: "Replay observed FV (JSON: flat [f64] or object with 'pepper' key)",
        },
    ]
}

pub fn build(flags: &HashMap<String, String>) -> Result<Box<dyn AssetSim>> {
    let start_fv = match flags.get("start-fv") {
        Some(raw) => parse_f64("intarian-pepper-root-start-fv", raw)?,
        None => 10_000.0,
    };
    let replay_fv = match flags.get("replay-fv") {
        Some(raw) => {
            let path = parse_path("intarian-pepper-root-replay-fv", raw)?;
            Some(load_replay_fv_path(&path, "pepper")?)
        }
        None => None,
    };
    Ok(Box::new(IntarianPepperRoot {
        start_fv,
        replay_fv,
    }))
}

impl AssetSim for IntarianPepperRoot {
    fn symbol(&self) -> &str {
        SYMBOL
    }

    fn position_limit(&self) -> i32 {
        POSITION_LIMIT
    }

    fn simulate_fv(
        &self,
        day_index: usize,
        ticks: usize,
        _rng: &mut ChaCha8Rng,
    ) -> Result<Vec<f64>> {
        if let Some(observed) = &self.replay_fv {
            let mut out = Vec::with_capacity(ticks);
            for i in 0..ticks {
                out.push(observed[i.min(observed.len() - 1)]);
            }
            return Ok(out);
        }
        let mut values = Vec::with_capacity(ticks);
        for tick in 0..ticks {
            let total_tick = day_index * ticks + tick;
            values.push(quantize_1024(self.start_fv + total_tick as f64 * DRIFT_PER_TICK));
        }
        Ok(values)
    }

    fn make_book(&self, fair: f64, rng: &mut ChaCha8Rng) -> Book {
        // Bot 1: floor(FV*(1-K1)) / ceil(FV*(1+K1)), vol U(15,25), 80% each side
        // Bot 2: floor(FV*(1-K2)) / ceil(FV*(1+K2)), vol U(8,12), 80% each side
        // Bot 3: 5% total, single-sided, REVERSED volume pattern (crossing U(3,8) / passive U(5,12))
        let bot1_bid_present = rng.gen_bool(0.80);
        let bot1_ask_present = rng.gen_bool(0.80);
        let bot2_bid_present = rng.gen_bool(0.80);
        let bot2_ask_present = rng.gen_bool(0.80);

        let bot1_vol = rng.gen_range(15..=25);
        let bot1_bid = (fair * (1.0 - K1)).floor() as i32;
        let bot1_ask = (fair * (1.0 + K1)).ceil() as i32;

        let bot2_vol = rng.gen_range(8..=12);
        let bot2_bid = (fair * (1.0 - K2)).floor() as i32;
        let bot2_ask = (fair * (1.0 + K2)).ceil() as i32;

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

        if bot3_draw < 0.025 {
            let offset = [3, -3][rng.gen_range(0..2)];
            let price = fair.round() as i32 + offset;
            let crossing = price as f64 > fair;
            let vol = if crossing {
                rng.gen_range(3..=8)
            } else {
                rng.gen_range(5..=12)
            };
            bids.push((price, vol));
        } else if bot3_draw < 0.05 {
            let offset = [-4, 2][rng.gen_range(0..2)];
            let price = fair.round() as i32 + offset;
            let crossing = (price as f64) < fair;
            let vol = if crossing {
                rng.gen_range(3..=8)
            } else {
                rng.gen_range(5..=12)
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
            (&[3, 4, 5, 6, 7, 8], &[99, 81, 98, 110, 98, 21])
        } else {
            (&[3, 4, 5, 6, 7, 8], &[99, 80, 97, 109, 97, 21])
        };
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
}
