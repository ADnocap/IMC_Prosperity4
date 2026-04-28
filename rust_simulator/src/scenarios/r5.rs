//! R5Scenario — joint FV generator + shared 3-process pulse trade events.
//!
//! Loads `calibration/r5/scenario_params.json`. Per asset: simulates either an
//! Ornstein-Uhlenbeck or random walk path on a half-integer grid, starting at
//! the day's observed mid. PEBBLES_XL is derived (basket-sum constraint to
//! 50,000) and SNACKPACK_VANILLA is derived (pair sum K_day OU process). Three
//! pulse processes (V/P/M) fire all members of their group simultaneously with
//! a single direction + qty drawn from observed empirical histograms.
//!
//! Match-to-Python: distributions only — RNG streams differ (ChaCha8 here vs
//! numpy default_rng in Python), so use n=50+ seeds and compare moments.

use crate::asset::sample_standard_normal;
use crate::scenario::{DayData, Pulse, PulseDir, Scenario};
use anyhow::{Context, Result, anyhow, bail};
use rand::distributions::{Distribution, WeightedIndex};
use rand::Rng;
use rand_chacha::ChaCha8Rng;
use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;

// ---------------- JSON shape ----------------

#[derive(Clone, Debug, Deserialize)]
pub struct ScenarioParams {
    pub days: Vec<i32>,
    pub ticks_per_day: usize,
    pub pebble_constant: f64,
    pub pebble_free: Vec<String>,
    pub pebble_derived: String,
    pub snackpack_choc: String,
    pub snackpack_vanilla: String,
    pub k_day: KDayParams,
    pub pulses: Vec<PulseProcessParams>,
    pub assets: HashMap<String, AssetCfg>,
    /// {day_string: {symbol: starting_mid}}
    pub day_starts: HashMap<String, HashMap<String, f64>>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct KDayParams {
    pub theta: f64,
    pub sigma: f64,
    /// {day_string: mu}
    pub daily_mu: HashMap<String, f64>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PulseProcessParams {
    pub name: String,
    pub members: Vec<String>,
    pub rate_per_tick: f64,
    pub p_buy: f64,
    #[allow(dead_code)]
    pub qty_min: i32,
    #[allow(dead_code)]
    pub qty_max: i32,
    /// {qty_string: count_in_observed_history}
    pub qty_observed_counts: HashMap<String, u32>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct AssetCfg {
    #[allow(dead_code)]
    pub category: String,
    #[allow(dead_code)]
    pub kind: Option<String>,
    /// "OU" | "RW" — absent (None) for derived assets (PEBBLES_XL, SNACKPACK_VANILLA),
    /// which are reconstructed from constraints rather than independently simulated.
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub sigma: f64,
    #[serde(default)]
    pub theta: f64,
    /// {day_string: mu}
    #[serde(default)]
    pub daily_mu: HashMap<String, f64>,
    pub h: f64,
    pub depth_l1: i32,
    pub depth_l2: i32,
    pub l2_lift: i32,
}

// ---------------- Static loading ----------------

static SCENARIO_PARAMS: OnceLock<ScenarioParams> = OnceLock::new();

/// Resolve `calibration/r5/scenario_params.json`. Search order:
///   1. `R5_SCENARIO_PARAMS` env var
///   2. `<repo_root>/calibration/r5/scenario_params.json`, where repo_root is
///      `PROSPERITY4MCBT_ROOT` or the parent of cwd.
fn resolve_params_path() -> Result<PathBuf> {
    if let Ok(raw) = std::env::var("R5_SCENARIO_PARAMS") {
        let p = PathBuf::from(raw);
        if p.is_file() {
            return Ok(p);
        }
    }
    let cwd = std::env::current_dir().context("cwd unavailable")?;
    // Try several plausible repo roots:
    let candidates = [
        std::env::var("PROSPERITY4MCBT_ROOT")
            .ok()
            .map(PathBuf::from),
        cwd.parent().map(|p| p.to_path_buf()),
        Some(cwd.clone()),
    ];
    for opt in candidates.iter().flatten() {
        let p = opt.join("calibration").join("r5").join("scenario_params.json");
        if p.is_file() {
            return Ok(p);
        }
    }
    bail!(
        "could not find calibration/r5/scenario_params.json; set R5_SCENARIO_PARAMS \
         or PROSPERITY4MCBT_ROOT (cwd={})",
        cwd.display()
    )
}

pub fn params() -> Result<&'static ScenarioParams> {
    if let Some(p) = SCENARIO_PARAMS.get() {
        return Ok(p);
    }
    let path = resolve_params_path()?;
    let text = fs::read_to_string(&path)
        .with_context(|| format!("reading {}", path.display()))?;
    let parsed: ScenarioParams = serde_json::from_str(&text)
        .with_context(|| format!("parsing {}", path.display()))?;
    let _ = SCENARIO_PARAMS.set(parsed);
    Ok(SCENARIO_PARAMS.get().unwrap())
}

/// All R5 symbols (50). Derived from the loaded params.
pub fn symbols() -> Result<Vec<String>> {
    let p = params()?;
    let mut s: Vec<String> = p.assets.keys().cloned().collect();
    s.sort();
    Ok(s)
}

// ---------------- R5Scenario ----------------

pub struct R5Scenario {
    params: &'static ScenarioParams,
    /// Per pulse-group: precomputed (qty_value, weight) tables for WeightedIndex.
    qty_tables: HashMap<String, (Vec<i32>, Vec<u32>)>,
}

impl R5Scenario {
    pub fn load() -> Result<Self> {
        let p = params()?;
        let mut qty_tables = HashMap::new();
        for proc in &p.pulses {
            let mut entries: Vec<(i32, u32)> = proc
                .qty_observed_counts
                .iter()
                .map(|(k, v)| {
                    let qty: i32 = k.parse().context("invalid qty key")?;
                    Ok::<_, anyhow::Error>((qty, *v))
                })
                .collect::<Result<Vec<_>>>()?;
            entries.sort_by_key(|e| e.0);
            let vals: Vec<i32> = entries.iter().map(|e| e.0).collect();
            let weights: Vec<u32> = entries.iter().map(|e| e.1).collect();
            qty_tables.insert(proc.name.clone(), (vals, weights));
        }
        Ok(Self { params: p, qty_tables })
    }

    pub fn snapshot_params(&self) -> &ScenarioParams {
        self.params
    }

    /// Snap to half-integer (matches Python: `round(v * 2) / 2`).
    fn snap_half(v: f64) -> f64 {
        (v * 2.0).round() / 2.0
    }

    /// Discrete-time OU: x_{t+1} = x_t + theta*(mu - x_t) + sigma*N(0,1).
    /// theta = 0 → pure RW with drift around x0 (matches Python branch).
    fn simulate_ou_path(
        n: usize,
        x0: f64,
        mu: f64,
        theta: f64,
        sigma: f64,
        rng: &mut ChaCha8Rng,
    ) -> Vec<f64> {
        let mut out = Vec::with_capacity(n);
        if n == 0 {
            return out;
        }
        out.push(x0);
        if theta == 0.0 {
            for _ in 1..n {
                let prev = *out.last().unwrap();
                let step = sigma * sample_standard_normal(rng);
                out.push(prev + step);
            }
        } else {
            for _ in 1..n {
                let prev = *out.last().unwrap();
                let step = theta * (mu - prev) + sigma * sample_standard_normal(rng);
                out.push(prev + step);
            }
        }
        out
    }

    fn simulate_rw_path(
        n: usize,
        x0: f64,
        sigma: f64,
        rng: &mut ChaCha8Rng,
    ) -> Vec<f64> {
        let mut out = Vec::with_capacity(n);
        if n == 0 {
            return out;
        }
        out.push(x0);
        for _ in 1..n {
            let prev = *out.last().unwrap();
            out.push(prev + sigma * sample_standard_normal(rng));
        }
        out
    }

    fn day_start(&self, day: i32, symbol: &str) -> Result<f64> {
        let day_key = day.to_string();
        let starts = self
            .params
            .day_starts
            .get(&day_key)
            .ok_or_else(|| anyhow!("no day_starts entry for day {day}"))?;
        starts
            .get(symbol)
            .copied()
            .ok_or_else(|| anyhow!("no day_starts entry for {} day {}", symbol, day))
    }

    fn daily_mu(&self, cfg: &AssetCfg, day: i32, fallback: f64) -> f64 {
        cfg.daily_mu
            .get(&day.to_string())
            .copied()
            .unwrap_or(fallback)
    }
}

impl Scenario for R5Scenario {
    fn uses_pulses(&self) -> bool {
        true
    }

    fn generate_day_data(
        &self,
        day: i32,
        ticks_per_day: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<DayData> {
        let p = self.params;
        let pebble_derived = &p.pebble_derived;
        let snack_vanilla = &p.snackpack_vanilla;
        let snack_choc = &p.snackpack_choc;

        // Deterministic asset order: sort by symbol so the rng stream is reproducible
        // run-to-run (HashMap iteration is randomized otherwise).
        let mut sorted_symbols: Vec<&String> = p.assets.keys().collect();
        sorted_symbols.sort();

        let mut fvs: HashMap<String, Vec<f64>> = HashMap::with_capacity(sorted_symbols.len());

        // Pass 1: simulate non-derived assets (everything except PEBBLES_XL and
        // SNACKPACK_VANILLA — both are reconstructed from constraints).
        for sym in &sorted_symbols {
            if sym.as_str() == pebble_derived || sym.as_str() == snack_vanilla {
                continue;
            }
            let cfg = p.assets.get(sym.as_str()).unwrap();
            let x0 = self.day_start(day, sym)?;
            let mu = self.daily_mu(cfg, day, x0);
            let model = cfg
                .model
                .as_deref()
                .ok_or_else(|| anyhow!("non-derived asset {} has no `model` field", sym))?;
            let raw = match model {
                "OU" => Self::simulate_ou_path(ticks_per_day, x0, mu, cfg.theta, cfg.sigma, rng),
                "RW" => Self::simulate_rw_path(ticks_per_day, x0, cfg.sigma, rng),
                other => bail!("unsupported asset model '{}' for {}", other, sym),
            };
            let snapped: Vec<f64> = raw.into_iter().map(Self::snap_half).collect();
            fvs.insert((*sym).clone(), snapped);
        }

        // Pass 2: derive PEBBLES_XL = round((50_000 - sum(other 4 pebbles)) * 2) / 2.
        {
            let mut acc = vec![0.0_f64; ticks_per_day];
            for free in &p.pebble_free {
                let path = fvs.get(free).ok_or_else(|| {
                    anyhow!("pebble component {free} missing from fvs (day {day})")
                })?;
                for (i, v) in path.iter().enumerate() {
                    acc[i] += *v;
                }
            }
            let derived: Vec<f64> = acc
                .iter()
                .map(|s| Self::snap_half(p.pebble_constant - s))
                .collect();
            fvs.insert(pebble_derived.clone(), derived);
        }

        // Pass 3: K_day OU process for snackpack pair sum, then derive VANILLA.
        let k_day_start = p
            .k_day
            .daily_mu
            .get(&day.to_string())
            .copied()
            .ok_or_else(|| anyhow!("no k_day daily_mu for day {day}"))?;
        let k_day_path = Self::simulate_ou_path(
            ticks_per_day,
            k_day_start,
            k_day_start,
            p.k_day.theta,
            p.k_day.sigma,
            rng,
        );
        {
            let choc_path = fvs.get(snack_choc).ok_or_else(|| {
                anyhow!("{snack_choc} missing from fvs (day {day})")
            })?;
            let vanilla: Vec<f64> = k_day_path
                .iter()
                .zip(choc_path.iter())
                .map(|(k, c)| Self::snap_half(*k - *c))
                .collect();
            fvs.insert(snack_vanilla.clone(), vanilla);
        }

        // Pass 4: pulses. For each process, draw n_pulses ~ Binomial(ticks, rate)
        // by tick-by-tick Bernoulli (matches the marginal distribution exactly),
        // then assign each fire a direction + qty.
        let mut pulses: Vec<Pulse> = Vec::new();
        for proc in &p.pulses {
            // Tick-by-tick Bernoulli is equivalent to Binomial + uniform-without-
            // replacement positions, both yielding Binom(n_ticks, rate) total fires
            // and uniform-over-ticks positions. Use this so we don't need a separate
            // binomial sampler.
            let (qty_vals, qty_weights) = self
                .qty_tables
                .get(&proc.name)
                .ok_or_else(|| anyhow!("missing qty table for pulse {}", proc.name))?;
            let qty_chooser =
                WeightedIndex::new(qty_weights).context("invalid qty weights")?;
            for tick in 0..ticks_per_day {
                if !rng.gen_bool(proc.rate_per_tick) {
                    continue;
                }
                let direction = if rng.gen_bool(proc.p_buy) {
                    PulseDir::Buy
                } else {
                    PulseDir::Sell
                };
                let qty = qty_vals[qty_chooser.sample(rng)];
                pulses.push(Pulse {
                    tick,
                    group: proc.name.clone(),
                    members: proc.members.clone(),
                    direction,
                    quantity: qty,
                });
            }
        }
        pulses.sort_by_key(|p| p.tick);

        Ok(DayData { fv_paths: fvs, pulses })
    }
}
