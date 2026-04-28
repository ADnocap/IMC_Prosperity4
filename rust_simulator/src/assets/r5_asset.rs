//! R5 generic asset. One impl, parameterized at construction with
//! (symbol, h, depth_l1, depth_l2, l2_lift). All R5 products share the same
//! book-builder (symmetric L1+L2 around FV) and the same "FV is generated
//! externally" contract — `simulate_fv` returns an error if called, since
//! R5Scenario produces the joint FV path before per-asset code runs.
//!
//! Trade rates are not used for R5 (pulses replace per-asset Bernoulli draws);
//! we report 0 for each rate so any code path that still calls them sees
//! "asset emits no taker traffic".

use crate::asset::{AssetSim, Book, FlagSpec};
use anyhow::{Result, bail};
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;

pub const POSITION_LIMIT: i32 = 10;

#[derive(Clone, Debug)]
pub struct R5Asset {
    pub symbol: String,
    pub h: f64,
    pub depth_l1: i32,
    pub depth_l2: i32,
    pub l2_lift: i32,
}

impl R5Asset {
    pub fn new(symbol: &str, h: f64, depth_l1: i32, depth_l2: i32, l2_lift: i32) -> Self {
        Self {
            symbol: symbol.to_string(),
            h,
            depth_l1,
            depth_l2,
            l2_lift,
        }
    }
}

pub fn flag_specs() -> Vec<FlagSpec> {
    Vec::new()
}

impl AssetSim for R5Asset {
    fn symbol(&self) -> &str {
        &self.symbol
    }

    fn position_limit(&self) -> i32 {
        POSITION_LIMIT
    }

    fn simulate_fv(
        &self,
        _day_index: usize,
        _ticks: usize,
        _rng: &mut ChaCha8Rng,
    ) -> Result<Vec<f64>> {
        bail!(
            "R5Asset::simulate_fv called for {} — R5 path must use R5Scenario for joint FV gen",
            self.symbol
        )
    }

    fn make_book(&self, fair: f64, _rng: &mut ChaCha8Rng) -> Book {
        // Per spec & matches r5_python_sim.py::make_bot_book:
        //   bid_1 = floor(fv - h + 0.5), ask_1 = ceil(fv + h - 0.5)
        //   bid_2 = bid_1 - l2_lift,    ask_2 = ask_1 + l2_lift
        let bid1 = (fair - self.h + 0.5).floor() as i32;
        let ask1 = (fair + self.h - 0.5).ceil() as i32;
        let bid2 = bid1 - self.l2_lift;
        let ask2 = ask1 + self.l2_lift;
        let bids = vec![(bid1, self.depth_l1), (bid2, self.depth_l2)];
        let asks = vec![(ask1, self.depth_l1), (ask2, self.depth_l2)];
        Book { bids, asks }
    }

    // Pulses replace per-asset trade rates, so these all return 0. Bot pulses
    // are dispatched at the per-tick level (see main.rs::r5_apply_pulses).
    fn base_trade_prob(&self) -> f64 {
        0.0
    }
    fn second_trade_prob(&self) -> f64 {
        0.0
    }
    fn elastic_trade_prob(&self) -> f64 {
        0.0
    }
    fn buy_prob(&self) -> f64 {
        0.5
    }

    fn sample_trade_qty(
        &self,
        _market_buy: bool,
        volume_limit: i32,
        _rng: &mut ChaCha8Rng,
    ) -> i32 {
        // Defensive: never called in R5 path; fall back to a single unit.
        volume_limit.max(1).min(1)
    }
}

/// Public helper to satisfy the registry build signature.
pub fn build_for_symbol(
    symbol: &str,
    flags: &HashMap<String, String>,
) -> Result<Box<dyn AssetSim>> {
    if !flags.is_empty() {
        bail!(
            "R5 assets accept no per-asset flags; got: {:?}",
            flags.keys().collect::<Vec<_>>()
        );
    }
    let p = crate::scenarios::r5::params()?;
    let cfg = p
        .assets
        .get(symbol)
        .ok_or_else(|| anyhow::anyhow!("no R5 config for {symbol}"))?;
    Ok(Box::new(R5Asset::new(
        symbol,
        cfg.h,
        cfg.depth_l1,
        cfg.depth_l2,
        cfg.l2_lift,
    )))
}

