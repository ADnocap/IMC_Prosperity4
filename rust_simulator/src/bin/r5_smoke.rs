//! R5 scenario smoke test. Generates N synthetic days through R5Scenario and
//! reports moments to compare against `analysis/round5/r5_scenario_v2.py`.
//!
//! Usage: `cargo run --release --bin r5_smoke -- [n_seeds]`
//! n_seeds defaults to 50.
//!
//! Note: needs `R5_SCENARIO_PARAMS` env var or the working dir to be such that
//! `<repo>/calibration/r5/scenario_params.json` is reachable. Most reliable is:
//!   `R5_SCENARIO_PARAMS=$(pwd)/calibration/r5/scenario_params.json \
//!     cargo run --release --bin r5_smoke -- 50`

use anyhow::Result;
use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;
use std::env;

#[path = "../asset.rs"]
mod asset;
#[path = "../scenario.rs"]
mod scenario;
#[path = "../scenarios/mod.rs"]
mod scenarios;

use scenario::{PulseDir, Scenario};

const TICKS: usize = 10_000;
const DAYS: [i32; 3] = [2, 3, 4];

fn mean_std(xs: &[f64]) -> (f64, f64) {
    if xs.is_empty() {
        return (0.0, 0.0);
    }
    let n = xs.len() as f64;
    let mean = xs.iter().sum::<f64>() / n;
    let var = xs.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n;
    (mean, var.sqrt())
}

fn main() -> Result<()> {
    let n_seeds: usize = env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50);

    println!("R5 smoke test: {} seeds × {} days × {} ticks", n_seeds, DAYS.len(), TICKS);
    let scenario = scenarios::r5::R5Scenario::load()?;
    let params = scenario.snapshot_params();

    // Aggregate stats across all (seed, day).
    let mut basket_sum_means: Vec<f64> = Vec::new();
    let mut basket_sum_stds: Vec<f64> = Vec::new();
    let mut k_day_means_per_day: HashMap<i32, Vec<f64>> = HashMap::new();
    let mut k_day_stds_per_day: HashMap<i32, Vec<f64>> = HashMap::new();
    let mut pulse_counts_per_group: HashMap<String, Vec<f64>> = HashMap::new();
    let mut pulse_pbuy_per_group: HashMap<String, Vec<f64>> = HashMap::new();
    let mut pulse_qty_means_per_group: HashMap<String, Vec<f64>> = HashMap::new();
    // Per-asset within-day std (seed-pooled).
    let mut per_asset_stds: HashMap<String, Vec<f64>> = HashMap::new();

    for seed in 0..n_seeds {
        for &day in &DAYS {
            let mut rng = ChaCha8Rng::seed_from_u64(seed as u64 ^ ((day as u64) << 32));
            let day_data = scenario.generate_day_data(day, TICKS, &mut rng)?;

            // Pebble basket sum: should be exactly 50,000.0 per tick.
            let pebble_syms = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"];
            let mut basket_per_tick: Vec<f64> = vec![0.0; TICKS];
            for sym in pebble_syms {
                if let Some(path) = day_data.fv_paths.get(sym) {
                    for (i, v) in path.iter().enumerate() {
                        basket_per_tick[i] += *v;
                    }
                }
            }
            let (b_mean, b_std) = mean_std(&basket_per_tick);
            basket_sum_means.push(b_mean);
            basket_sum_stds.push(b_std);

            // K_day = SNACKPACK_CHOC + SNACKPACK_VANILLA.
            let choc = day_data
                .fv_paths
                .get("SNACKPACK_CHOCOLATE")
                .cloned()
                .unwrap_or_default();
            let van = day_data
                .fv_paths
                .get("SNACKPACK_VANILLA")
                .cloned()
                .unwrap_or_default();
            if choc.len() == TICKS && van.len() == TICKS {
                let k: Vec<f64> = choc.iter().zip(van.iter()).map(|(a, b)| a + b).collect();
                let (m, s) = mean_std(&k);
                k_day_means_per_day.entry(day).or_default().push(m);
                k_day_stds_per_day.entry(day).or_default().push(s);
            }

            // Per-asset within-day std.
            for (sym, path) in &day_data.fv_paths {
                let (_, s) = mean_std(path);
                per_asset_stds.entry(sym.clone()).or_default().push(s);
            }

            // Pulse stats.
            let mut grp_count: HashMap<String, usize> = HashMap::new();
            let mut grp_buys: HashMap<String, usize> = HashMap::new();
            let mut grp_qty_sum: HashMap<String, i64> = HashMap::new();
            for p in &day_data.pulses {
                *grp_count.entry(p.group.clone()).or_insert(0) += 1;
                if matches!(p.direction, PulseDir::Buy) {
                    *grp_buys.entry(p.group.clone()).or_insert(0) += 1;
                }
                *grp_qty_sum.entry(p.group.clone()).or_insert(0) += p.quantity as i64;
            }
            for grp in ["V", "P", "M"] {
                let c = *grp_count.get(grp).unwrap_or(&0);
                pulse_counts_per_group
                    .entry(grp.to_string())
                    .or_default()
                    .push(c as f64);
                if c > 0 {
                    let pb = *grp_buys.get(grp).unwrap_or(&0) as f64 / c as f64;
                    let qm = *grp_qty_sum.get(grp).unwrap_or(&0) as f64 / c as f64;
                    pulse_pbuy_per_group
                        .entry(grp.to_string())
                        .or_default()
                        .push(pb);
                    pulse_qty_means_per_group
                        .entry(grp.to_string())
                        .or_default()
                        .push(qm);
                }
            }
        }
    }

    // ===== Report =====
    println!();
    println!("=== Pebble basket constraint ===");
    let (bsm_mean, bsm_std) = mean_std(&basket_sum_means);
    let (bss_mean, _) = mean_std(&basket_sum_stds);
    println!(
        "  basket sum mean = {:.4}  std-of-mean = {:.4}  (expected 50000.0 / 0.0)",
        bsm_mean, bsm_std
    );
    println!(
        "  basket within-tick std = {:.6}  (expected 0.0)",
        bss_mean
    );

    println!();
    println!("=== K_day (SNACKPACK pair sum) ===");
    let mu_by_day = &params.k_day.daily_mu;
    for &day in &DAYS {
        let means = k_day_means_per_day.get(&day).cloned().unwrap_or_default();
        let stds = k_day_stds_per_day.get(&day).cloned().unwrap_or_default();
        let (m, _) = mean_std(&means);
        let (s, _) = mean_std(&stds);
        let target = mu_by_day.get(&day.to_string()).copied().unwrap_or(0.0);
        println!(
            "  day {}: mean = {:.2} (target_mu = {:.2}, diff = {:+.2}); within-day std = {:.2}",
            day,
            m,
            target,
            m - target,
            s
        );
    }

    println!();
    println!("=== Pulse processes (per day average) ===");
    for grp in ["V", "P", "M"] {
        let counts = pulse_counts_per_group
            .get(grp)
            .cloned()
            .unwrap_or_default();
        let pb = pulse_pbuy_per_group.get(grp).cloned().unwrap_or_default();
        let qm = pulse_qty_means_per_group.get(grp).cloned().unwrap_or_default();
        let (cm, cs) = mean_std(&counts);
        let (pm, ps) = mean_std(&pb);
        let (qmm, qms) = mean_std(&qm);
        // Expected n_pulses = rate_per_tick * ticks
        let proc = params
            .pulses
            .iter()
            .find(|p| p.name == grp)
            .expect("pulse process");
        let exp_n = proc.rate_per_tick * TICKS as f64;
        println!(
            "  {}: n_pulses {:.1} ± {:.1} (expected ~{:.0}); p_buy {:.3} ± {:.3} (target {:.3}); qty {:.3} ± {:.3}",
            grp, cm, cs, exp_n, pm, ps, proc.p_buy, qmm, qms
        );
    }

    println!();
    println!("=== Per-asset within-day std (top/bottom 5 by mean) ===");
    let mut asset_summary: Vec<(String, f64)> = per_asset_stds
        .iter()
        .map(|(k, v)| (k.clone(), mean_std(v).0))
        .collect();
    asset_summary.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
    println!("  -- lowest 5 --");
    for (sym, s) in asset_summary.iter().take(5) {
        println!("    {:<35} std_mean = {:.2}", sym, s);
    }
    println!("  -- highest 5 --");
    for (sym, s) in asset_summary.iter().rev().take(5) {
        println!("    {:<35} std_mean = {:.2}", sym, s);
    }

    Ok(())
}
