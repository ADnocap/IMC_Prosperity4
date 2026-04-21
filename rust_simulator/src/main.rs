//! Monte Carlo backtester orchestration. Asset-agnostic — per-asset FV, book,
//! and trade generation is dispatched through the `AssetSim` trait defined in
//! `asset.rs`, with concrete assets under `assets/`.
//!
//! The simulator detects which assets a trader uses by scanning its source file
//! for `NAME = "ASSET_SYMBOL"` lines (see `detect.rs`), then activates only those
//! assets. All CSV output columns for per-asset metrics are prefixed by the
//! asset symbol (`<SYMBOL>_pnl`, `<SYMBOL>_position`, etc.), so the dashboard
//! on the Python side adapts automatically.
//!
//! Flags: global flags (`--sessions`, `--ticks-per-day`, `--seed`, …) are parsed
//! first; per-asset flags use `--<asset-kebab>-<flag>` and are routed to that
//! asset's `build()` function. An unknown flag (or a flag for an asset the
//! trader doesn't declare) is a hard error.

mod asset;
mod assets;
mod detect;

use anyhow::{Context, Result, bail};
use asset::{
    AssetSim, Book, Fill, InputPriceRow, Level, LevelOwner, ProductLedger, SimBook,
    symbol_to_kebab,
};
use csv::{ReaderBuilder, WriterBuilder};
use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

const DAYS: [i32; 2] = [-2, -1];
const DEFAULT_TICKS_PER_DAY: usize = 10_000;
const TIMESTAMP_STEP: i32 = 100;
const STRATEGY_RUN_TIMEOUT_MS: u64 = 900;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FvMode {
    Replay,
    Simulate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TradeMode {
    ReplayTimes,
    Simulate,
}

struct Config {
    output_dir: PathBuf,
    actual_dir: PathBuf,
    fv_mode: FvMode,
    trade_mode: TradeMode,
    seed: u64,
    strategy_path: Option<PathBuf>,
    python_bin: String,
    sessions: usize,
    write_session_limit: usize,
    ticks_per_day: usize,
    quote_fraction: f64,
    maf_bid: i64,
    /// Assets active for this run (detected from the trader, built from CLI flags).
    assets: Vec<Box<dyn AssetSim>>,
}

impl Config {
    /// Active asset symbols in fixed order (sorted alphabetical from detect_assets).
    fn symbols(&self) -> Vec<&str> {
        self.assets.iter().map(|a| a.symbol()).collect()
    }
}

struct ReplayData {
    fair_by_asset_day: HashMap<(String, i32), Vec<f64>>,
    trade_counts_by_key: HashMap<(i32, String), Vec<usize>>,
}

#[derive(Clone, Debug)]
struct DayOutput {
    day: i32,
    price_rows: Vec<PriceRow>,
    trade_rows: Vec<TradeRow>,
    trace_rows: Vec<TraceRow>,
}

#[derive(Clone, Copy, Debug, Default)]
struct RunningLinearFit {
    n: f64,
    sum_x: f64,
    sum_y: f64,
    sum_xx: f64,
    sum_yy: f64,
    sum_xy: f64,
}

impl RunningLinearFit {
    fn update(&mut self, x: f64, y: f64) {
        self.n += 1.0;
        self.sum_x += x;
        self.sum_y += y;
        self.sum_xx += x * x;
        self.sum_yy += y * y;
        self.sum_xy += x * y;
    }
    fn slope_per_step(&self) -> f64 {
        let denom = self.n * self.sum_xx - self.sum_x * self.sum_x;
        if denom.abs() < 1e-12 {
            0.0
        } else {
            (self.n * self.sum_xy - self.sum_x * self.sum_y) / denom
        }
    }
    fn r_squared(&self) -> f64 {
        let x_var = self.n * self.sum_xx - self.sum_x * self.sum_x;
        let y_var = self.n * self.sum_yy - self.sum_y * self.sum_y;
        if x_var.abs() < 1e-12 || y_var.abs() < 1e-12 {
            0.0
        } else {
            let cov = self.n * self.sum_xy - self.sum_x * self.sum_y;
            (cov * cov) / (x_var * y_var)
        }
    }
}

#[derive(Clone, Debug)]
struct SessionOutput {
    session_id: usize,
    summary_values: HashMap<String, f64>,
    run_summaries: Vec<RunSummaryRow>,
    day_outputs: Vec<DayOutput>,
}

#[derive(Clone, Debug)]
struct RunSummaryRow {
    session_id: usize,
    day: i32,
    values: HashMap<String, f64>,
}

// CSV IO types. Price/trade/trace rows are asset-agnostic — assets only generate
// their own rows which we tag with the correct product symbol.
#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct InputTradeRow {
    timestamp: i32,
    buyer: Option<String>,
    seller: Option<String>,
    symbol: String,
    currency: String,
    price: f64,
    quantity: i32,
}

#[derive(Clone, Debug, Serialize)]
struct PriceRow {
    day: i32,
    timestamp: i32,
    product: String,
    bid_price_1: Option<i32>,
    bid_volume_1: Option<i32>,
    bid_price_2: Option<i32>,
    bid_volume_2: Option<i32>,
    bid_price_3: Option<i32>,
    bid_volume_3: Option<i32>,
    ask_price_1: Option<i32>,
    ask_volume_1: Option<i32>,
    ask_price_2: Option<i32>,
    ask_volume_2: Option<i32>,
    ask_price_3: Option<i32>,
    ask_volume_3: Option<i32>,
    mid_price: f64,
    profit_and_loss: f64,
}

#[derive(Clone, Debug, Serialize)]
struct TradeRow {
    timestamp: i32,
    buyer: Option<String>,
    seller: Option<String>,
    symbol: String,
    currency: String,
    price: f64,
    quantity: i32,
}

#[derive(Clone, Debug, Serialize)]
struct TraceRow {
    day: i32,
    timestamp: i32,
    product: String,
    fair_value: f64,
    position: i32,
    cash: f64,
    mtm_pnl: f64,
}

#[derive(Debug, Serialize)]
struct WorkerTrade {
    symbol: String,
    price: i32,
    quantity: i32,
    buyer: Option<String>,
    seller: Option<String>,
    timestamp: i32,
}

#[derive(Debug, Serialize)]
struct WorkerOrderDepth {
    buy_orders: HashMap<String, i32>,
    sell_orders: HashMap<String, i32>,
}

#[derive(Debug, Serialize)]
struct WorkerRequest {
    #[serde(rename = "type")]
    request_type: String,
    timestamp: i32,
    timeout_ms: u64,
    trader_data: String,
    order_depths: HashMap<String, WorkerOrderDepth>,
    own_trades: HashMap<String, Vec<WorkerTrade>>,
    market_trades: HashMap<String, Vec<WorkerTrade>>,
    position: HashMap<String, i32>,
}

#[allow(dead_code)]
#[derive(Clone, Debug, Deserialize)]
struct WorkerOrder {
    symbol: String,
    price: i32,
    quantity: i32,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct WorkerResponse {
    orders: Option<HashMap<String, Vec<WorkerOrder>>>,
    conversions: Option<i32>,
    trader_data: Option<String>,
    stdout: Option<String>,
    error: Option<String>,
}

// ---------------- CLI parsing ----------------

struct RawArgs {
    global: RawGlobal,
    asset_flags: HashMap<String, HashMap<String, String>>,
}

#[derive(Default)]
struct RawGlobal {
    output_dir: Option<PathBuf>,
    actual_dir: Option<PathBuf>,
    fv_mode: Option<FvMode>,
    trade_mode: Option<TradeMode>,
    seed: Option<u64>,
    strategy_path: Option<PathBuf>,
    python_bin: Option<String>,
    sessions: Option<usize>,
    write_session_limit: Option<usize>,
    ticks_per_day: Option<usize>,
    quote_fraction: Option<f64>,
    maf_bid: Option<i64>,
}

/// First pass: split args into (global) vs (asset-prefixed). Asset prefix validation
/// happens later, once we know the active asset set from the trader.
fn parse_raw_args() -> Result<RawArgs> {
    let mut global = RawGlobal::default();
    let mut asset_flags: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let stripped = match arg.strip_prefix("--") {
            Some(s) => s,
            None => bail!("unexpected positional argument: {}", arg),
        };
        let take_value = |args: &mut std::iter::Skip<env::Args>| -> Result<String> {
            args.next()
                .with_context(|| format!("missing value for --{}", stripped))
        };
        match stripped {
            "output" => global.output_dir = Some(PathBuf::from(take_value(&mut args)?)),
            "actual-dir" => global.actual_dir = Some(PathBuf::from(take_value(&mut args)?)),
            "fv-mode" => {
                let v = take_value(&mut args)?;
                global.fv_mode = Some(match v.as_str() {
                    "replay" => FvMode::Replay,
                    "simulate" => FvMode::Simulate,
                    other => bail!("unsupported --fv-mode {}", other),
                });
            }
            "trade-mode" => {
                let v = take_value(&mut args)?;
                global.trade_mode = Some(match v.as_str() {
                    "replay-times" => TradeMode::ReplayTimes,
                    "simulate" => TradeMode::Simulate,
                    other => bail!("unsupported --trade-mode {}", other),
                });
            }
            "seed" => {
                global.seed = Some(
                    take_value(&mut args)?
                        .parse()
                        .context("invalid --seed")?,
                )
            }
            "strategy" => global.strategy_path = Some(PathBuf::from(take_value(&mut args)?)),
            "python-bin" => global.python_bin = Some(take_value(&mut args)?),
            "sessions" => {
                global.sessions = Some(
                    take_value(&mut args)?
                        .parse()
                        .context("invalid --sessions")?,
                )
            }
            "write-session-limit" => {
                global.write_session_limit = Some(
                    take_value(&mut args)?
                        .parse()
                        .context("invalid --write-session-limit")?,
                )
            }
            "ticks-per-day" => {
                global.ticks_per_day = Some(
                    take_value(&mut args)?
                        .parse()
                        .context("invalid --ticks-per-day")?,
                )
            }
            "quote-fraction" => {
                let qf: f64 = take_value(&mut args)?
                    .parse()
                    .context("invalid --quote-fraction")?;
                if !(0.0..=2.0).contains(&qf) {
                    bail!("--quote-fraction must be in [0.0, 2.0]");
                }
                global.quote_fraction = Some(qf);
            }
            "maf-bid" => {
                global.maf_bid = Some(
                    take_value(&mut args)?
                        .parse()
                        .context("invalid --maf-bid")?,
                )
            }
            other => {
                // Asset-prefixed flag: --<asset-kebab>-<flag>.
                let value = take_value(&mut args)?;
                // Will be fully validated once we know the active asset set.
                asset_flags
                    .entry("__raw__".to_string())
                    .or_default()
                    .insert(other.to_string(), value);
            }
        }
    }
    Ok(RawArgs { global, asset_flags })
}

/// Second pass: split raw asset flags by active asset and error on any flag
/// that doesn't resolve to a known asset/flag pair.
fn resolve_asset_flags(
    raw: &HashMap<String, String>,
    active_symbols: &[&str],
) -> Result<HashMap<String, HashMap<String, String>>> {
    let mut out: HashMap<String, HashMap<String, String>> = HashMap::new();
    // Longest-prefix match against active asset kebab names.
    let mut kebabs: Vec<(String, &str)> = active_symbols
        .iter()
        .map(|sym| (symbol_to_kebab(sym), *sym))
        .collect();
    kebabs.sort_by(|a, b| b.0.len().cmp(&a.0.len()));

    for (flag, value) in raw {
        let mut matched = false;
        for (kebab, symbol) in &kebabs {
            if let Some(rest) = flag.strip_prefix(&format!("{}-", kebab)) {
                out.entry(symbol.to_string())
                    .or_default()
                    .insert(rest.to_string(), value.clone());
                matched = true;
                break;
            }
        }
        if !matched {
            // Check if the flag uses an unknown asset prefix vs. a totally unknown flag.
            let all_kebabs: Vec<String> = assets::known_symbols()
                .iter()
                .map(|s| symbol_to_kebab(s))
                .collect();
            for kebab in &all_kebabs {
                if flag.starts_with(&format!("{}-", kebab)) {
                    bail!(
                        "--{} references asset '{}' which is not declared by this trader. \
                         Active assets: {:?}",
                        flag,
                        kebab,
                        active_symbols
                    );
                }
            }
            bail!(
                "unknown flag: --{}. Known asset prefixes for this trader: {:?}",
                flag,
                active_symbols
                    .iter()
                    .map(|s| symbol_to_kebab(s))
                    .collect::<Vec<_>>()
            );
        }
    }
    Ok(out)
}

fn build_config() -> Result<Config> {
    let raw = parse_raw_args()?;
    let strategy_path = raw
        .global
        .strategy_path
        .clone()
        .context("--strategy is required for Monte Carlo backtest mode")?;
    let trader_abs = fs::canonicalize(&strategy_path).with_context(|| {
        format!("failed to canonicalize strategy path {}", strategy_path.display())
    })?;
    let active_symbols = detect::detect_assets(&trader_abs)?;
    let active_refs: Vec<&str> = active_symbols.iter().map(|s| s.as_str()).collect();

    // Resolve asset-prefixed flags against the detected active set.
    let raw_asset = raw
        .asset_flags
        .get("__raw__")
        .cloned()
        .unwrap_or_default();
    let per_asset_flags = resolve_asset_flags(&raw_asset, &active_refs)?;

    // Build each asset with its (possibly empty) flag map.
    let mut assets_built: Vec<Box<dyn AssetSim>> = Vec::with_capacity(active_symbols.len());
    for symbol in &active_symbols {
        let flags = per_asset_flags.get(symbol).cloned().unwrap_or_default();
        assets_built.push(assets::build_asset(symbol, &flags)?);
    }

    Ok(Config {
        output_dir: raw.global.output_dir.unwrap_or_else(|| PathBuf::from("../tmp/rust_simulator_output")),
        actual_dir: raw.global.actual_dir.unwrap_or_else(|| PathBuf::from("../data/round1")),
        fv_mode: raw.global.fv_mode.unwrap_or(FvMode::Simulate),
        trade_mode: raw.global.trade_mode.unwrap_or(TradeMode::Simulate),
        seed: raw.global.seed.unwrap_or(20_260_401),
        strategy_path: Some(trader_abs),
        python_bin: raw.global.python_bin.unwrap_or_else(|| "python3".to_string()),
        sessions: raw.global.sessions.unwrap_or(1),
        write_session_limit: raw.global.write_session_limit.unwrap_or(0),
        ticks_per_day: raw.global.ticks_per_day.unwrap_or(DEFAULT_TICKS_PER_DAY),
        quote_fraction: raw.global.quote_fraction.unwrap_or(1.0),
        maf_bid: raw.global.maf_bid.unwrap_or(0),
        assets: assets_built,
    })
}

fn main() -> Result<()> {
    let config = build_config()?;
    let replay_data = ReplayData::load(&config)?;

    if config.strategy_path.is_some() {
        let outputs = run_backtests(&config, &replay_data)?;
        write_backtest_outputs(&config, &outputs)?;
        write_run_log(&config)?;
        return Ok(());
    }

    // Data-generation mode (no strategy): run one day per DAYS entry.
    let outputs = DAYS
        .par_iter()
        .map(|day| generate_day(*day, &config, &replay_data))
        .collect::<Result<Vec<_>>>()?;
    write_outputs(&config, &outputs)?;
    write_run_log(&config)?;
    Ok(())
}

// ---------------- Replay data load ----------------

impl ReplayData {
    fn load(config: &Config) -> Result<Self> {
        let mut fair_by_asset_day = HashMap::new();
        let mut trade_counts_by_key = HashMap::new();

        if config.fv_mode == FvMode::Replay {
            // For each active asset, read deepest-midpoint FV per timestep per day.
            for day in DAYS {
                let prices = load_price_rows(&config.actual_dir, day)?;
                for asset in &config.assets {
                    let symbol = asset.symbol().to_string();
                    let mut rows: Vec<_> = prices
                        .iter()
                        .filter(|row| row.product == symbol)
                        .collect();
                    rows.sort_by_key(|row| row.timestamp);
                    let fair_values = rows
                        .iter()
                        .map(|row| asset.infer_observed_fair(row))
                        .collect::<Vec<_>>();
                    fair_by_asset_day.insert((symbol, day), fair_values);
                }
            }
        }

        if config.trade_mode == TradeMode::ReplayTimes {
            for day in DAYS {
                let trades = load_trade_rows(&config.actual_dir, day)?;
                for asset in &config.assets {
                    let symbol = asset.symbol().to_string();
                    let mut counts = vec![0usize; DEFAULT_TICKS_PER_DAY];
                    for trade in trades.iter().filter(|row| row.symbol == symbol) {
                        let index = usize::try_from(trade.timestamp / TIMESTAMP_STEP)
                            .context("negative timestamp while loading replay trades")?;
                        if index < counts.len() {
                            counts[index] += 1;
                        }
                    }
                    trade_counts_by_key.insert((day, symbol), counts);
                }
            }
        }

        Ok(Self {
            fair_by_asset_day,
            trade_counts_by_key,
        })
    }
}

// ---------------- Data generation (no strategy) ----------------

fn generate_day(day: i32, config: &Config, replay: &ReplayData) -> Result<DayOutput> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed_for_day(config.seed, day));
    let day_index = DAYS.iter().position(|&d| d == day).unwrap_or(0);

    // FV paths per asset.
    let mut fv_per_asset: HashMap<String, Vec<f64>> = HashMap::new();
    for asset in &config.assets {
        let symbol = asset.symbol().to_string();
        let fv = if config.fv_mode == FvMode::Replay {
            replay
                .fair_by_asset_day
                .get(&(symbol.clone(), day))
                .cloned()
                .with_context(|| format!("missing replay FV values for {}", symbol))?
        } else {
            asset.simulate_fv(day_index, config.ticks_per_day, &mut rng)?
        };
        fv_per_asset.insert(symbol, fv);
    }

    // Trade counts per asset.
    let mut trade_counts_per_asset: HashMap<String, Vec<usize>> = HashMap::new();
    for asset in &config.assets {
        let symbol = asset.symbol().to_string();
        let counts = trade_counts_for(asset.as_ref(), day, config, replay, &mut rng)?;
        trade_counts_per_asset.insert(symbol, counts);
    }

    let mut price_rows = Vec::with_capacity(config.ticks_per_day * config.assets.len());
    let mut trade_rows = Vec::new();

    for tick in 0..config.ticks_per_day {
        let timestamp = (tick as i32) * TIMESTAMP_STEP;
        for asset in &config.assets {
            let symbol = asset.symbol();
            let fv = fv_per_asset[symbol][tick];
            let mut book = asset.make_book(fv, &mut rng);
            apply_quote_fraction(&mut book, config.quote_fraction, &mut rng);
            price_rows.push(book_to_price_row(day, timestamp, symbol, &book));
            let count = trade_counts_per_asset[symbol][tick];
            for _ in 0..count {
                trade_rows.extend(sample_trade_rows(
                    timestamp,
                    asset.as_ref(),
                    &book,
                    &mut rng,
                ));
            }
        }
    }

    price_rows.sort_by(|a, b| {
        a.timestamp
            .cmp(&b.timestamp)
            .then(a.product.cmp(&b.product))
    });
    trade_rows.sort_by(|a, b| a.timestamp.cmp(&b.timestamp).then(a.symbol.cmp(&b.symbol)));

    Ok(DayOutput {
        day,
        price_rows,
        trade_rows,
        trace_rows: Vec::new(),
    })
}

fn write_outputs(config: &Config, outputs: &[DayOutput]) -> Result<()> {
    let round_dir = config.output_dir.join("round1");
    fs::create_dir_all(&round_dir)
        .with_context(|| format!("failed to create {}", round_dir.display()))?;

    for output in outputs {
        let price_path = round_dir.join(format!("prices_round_1_day_{}.csv", output.day));
        let trade_path = round_dir.join(format!("trades_round_1_day_{}.csv", output.day));

        let mut price_writer = WriterBuilder::new()
            .delimiter(b';')
            .from_path(&price_path)
            .with_context(|| format!("failed to open {}", price_path.display()))?;
        for row in &output.price_rows {
            price_writer.serialize(row)?;
        }
        price_writer.flush()?;

        let mut trade_writer = WriterBuilder::new()
            .delimiter(b';')
            .from_path(&trade_path)
            .with_context(|| format!("failed to open {}", trade_path.display()))?;
        for row in &output.trade_rows {
            trade_writer.serialize(row)?;
        }
        trade_writer.flush()?;
    }
    Ok(())
}

// ---------------- Strategy worker (unchanged infrastructure) ----------------

struct StrategyWorker {
    child: Child,
    stdin: BufWriter<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl StrategyWorker {
    fn spawn(config: &Config) -> Result<Self> {
        let strategy_path = config
            .strategy_path
            .as_ref()
            .context("missing strategy path")?;
        let project_root = env::var("PROSPERITY4MCBT_ROOT")
            .map(PathBuf::from)
            .or_else(|_| {
                env::current_dir().map(|cwd| {
                    cwd.parent().map(Path::to_path_buf).unwrap_or(cwd)
                })
            })
            .context("failed to resolve project root for python strategy worker")?;
        let worker_path = project_root.join("scripts/python_strategy_worker.py");
        if !worker_path.is_file() {
            bail!(
                "python strategy worker not found at {}",
                worker_path.display()
            );
        }
        let mut child = Command::new(&config.python_bin)
            .arg(worker_path)
            .arg(strategy_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .context("failed to spawn python strategy worker")?;
        let stdin = BufWriter::new(child.stdin.take().context("missing worker stdin")?);
        let stdout = BufReader::new(child.stdout.take().context("missing worker stdout")?);
        Ok(Self { child, stdin, stdout })
    }

    fn reset(&mut self) -> Result<()> {
        let payload = serde_json::json!({ "type": "reset" });
        self.send(&payload)?;
        let response = self.read_response()?;
        if let Some(error) = response.error {
            bail!("python worker reset failed: {}", error);
        }
        Ok(())
    }

    fn run(&mut self, request: &WorkerRequest) -> Result<WorkerResponse> {
        self.send(request)?;
        let response = self.read_response()?;
        if let Some(error) = &response.error {
            bail!("python worker failed: {}", error);
        }
        Ok(response)
    }

    fn send<T: Serialize>(&mut self, payload: &T) -> Result<()> {
        serde_json::to_writer(&mut self.stdin, payload)?;
        self.stdin.write_all(b"\n")?;
        self.stdin.flush()?;
        Ok(())
    }

    fn read_response(&mut self) -> Result<WorkerResponse> {
        let mut line = String::new();
        let bytes = self.stdout.read_line(&mut line)?;
        if bytes == 0 {
            bail!("python worker exited unexpectedly");
        }
        let response = serde_json::from_str::<WorkerResponse>(line.trim())
            .context("failed to decode python worker response")?;
        Ok(response)
    }
}

impl Drop for StrategyWorker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

// ---------------- Backtest orchestration ----------------

fn run_backtests(config: &Config, replay: &ReplayData) -> Result<Vec<SessionOutput>> {
    let mut outputs = (0..config.sessions)
        .into_par_iter()
        .map(|session_id| {
            run_backtest_session(
                session_id,
                session_id < config.write_session_limit,
                config,
                replay,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    outputs.sort_by_key(|output| output.session_id);
    Ok(outputs)
}

fn monte_carlo_session_day(session_id: usize) -> i32 {
    DAYS[session_id % DAYS.len()]
}

fn run_backtest_session(
    session_id: usize,
    capture_outputs: bool,
    config: &Config,
    replay: &ReplayData,
) -> Result<SessionOutput> {
    let mut worker = StrategyWorker::spawn(config)?;
    let symbols: Vec<String> = config.symbols().into_iter().map(|s| s.to_string()).collect();

    // Aggregates across the session.
    let mut asset_total_pnl: HashMap<String, f64> = HashMap::new();
    let mut asset_total_cash: HashMap<String, f64> = HashMap::new();
    let mut asset_final_pos: HashMap<String, i32> = HashMap::new();
    let mut asset_total_fit: HashMap<String, RunningLinearFit> = HashMap::new();
    let mut total_fit = RunningLinearFit::default();
    for symbol in &symbols {
        asset_total_pnl.insert(symbol.clone(), 0.0);
        asset_total_cash.insert(symbol.clone(), 0.0);
        asset_final_pos.insert(symbol.clone(), 0);
        asset_total_fit.insert(symbol.clone(), RunningLinearFit::default());
    }

    let mut day_outputs = Vec::with_capacity(1);
    let mut run_summaries = Vec::with_capacity(1);
    let mut global_step = 0usize;
    let session_day = monte_carlo_session_day(session_id);

    for day in [session_day] {
        worker.reset()?;
        let mut rng = ChaCha8Rng::seed_from_u64(seed_for_session_day(
            config.seed,
            session_id,
            day,
        ));
        let day_index = DAYS.iter().position(|&d| d == day).unwrap_or(0);

        // Resolve per-asset FV for the day. CRITICAL: this must happen in a fixed
        // asset order (config.assets order) so the RNG stream stays deterministic.
        let mut fv_per_asset: HashMap<String, Vec<f64>> = HashMap::new();
        for asset in &config.assets {
            let symbol = asset.symbol().to_string();
            let fv = if config.fv_mode == FvMode::Replay {
                replay
                    .fair_by_asset_day
                    .get(&(symbol.clone(), day))
                    .cloned()
                    .with_context(|| format!("missing replay FV for {}", symbol))?
            } else {
                asset.simulate_fv(day_index, config.ticks_per_day, &mut rng)?
            };
            fv_per_asset.insert(symbol, fv);
        }

        // Per-asset trade counts.
        let mut trade_counts: HashMap<String, Vec<usize>> = HashMap::new();
        for asset in &config.assets {
            let counts = trade_counts_for(asset.as_ref(), day, config, replay, &mut rng)?;
            trade_counts.insert(asset.symbol().to_string(), counts);
        }

        // Ledgers + prev-trade tracking per asset.
        let mut ledgers: HashMap<String, ProductLedger> = symbols
            .iter()
            .map(|s| (s.clone(), ProductLedger::default()))
            .collect();
        let mut trader_data = String::new();
        let mut prev_own_trades = empty_trade_map(&symbols);
        let mut prev_market_trades = empty_trade_map(&symbols);

        // Per-day tracking.
        let mut day_asset_fit: HashMap<String, RunningLinearFit> = symbols
            .iter()
            .map(|s| (s.clone(), RunningLinearFit::default()))
            .collect();
        let mut day_total_fit = RunningLinearFit::default();
        let mut day_step = 0usize;

        let mut price_rows = if capture_outputs {
            Vec::with_capacity(config.ticks_per_day * symbols.len())
        } else {
            Vec::new()
        };
        let mut trade_rows = Vec::new();
        let mut trace_rows = Vec::new();

        for tick in 0..config.ticks_per_day {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;

            // Build books from bot quotes (per asset).
            let mut books: HashMap<String, Book> = HashMap::new();
            for asset in &config.assets {
                let symbol = asset.symbol();
                let fv = fv_per_asset[symbol][tick];
                let mut book = asset.make_book(fv, &mut rng);
                apply_quote_fraction(&mut book, config.quote_fraction, &mut rng);
                if capture_outputs {
                    price_rows.push(book_to_price_row(day, timestamp, symbol, &book));
                }
                books.insert(symbol.to_string(), book);
            }

            // Post-take live book per asset (bots can be taken pre-strategy).
            let mut live_books: HashMap<String, SimBook> = books
                .iter()
                .map(|(s, b)| (s.clone(), book_to_sim_book(b)))
                .collect();

            let mut own_trades_this_tick = empty_trade_map(&symbols);
            let mut market_trades_this_tick = empty_trade_map(&symbols);

            // Step 2: base-rate takers act on the pre-existing bot book.
            for asset in &config.assets {
                let symbol = asset.symbol().to_string();
                let count = trade_counts[&symbol][tick];
                let book = live_books
                    .get_mut(&symbol)
                    .context("missing live book for base-taker")?;
                let ledger = ledgers
                    .get_mut(&symbol)
                    .context("missing ledger for base-taker")?;
                for _ in 0..count {
                    let market_buy = rng.gen_bool(asset.buy_prob());
                    let fills = execute_taker_trade(
                        asset.as_ref(),
                        timestamp,
                        book,
                        ledger,
                        market_buy,
                        &mut rng,
                    );
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        market_trades_this_tick
                            .entry(symbol.clone())
                            .or_default()
                            .push(fill);
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            // Step 3: strategy sees post-take book.
            let order_depths: HashMap<String, WorkerOrderDepth> = config
                .assets
                .iter()
                .map(|asset| {
                    let symbol = asset.symbol().to_string();
                    let depth = sim_book_to_worker_depth(live_books.get(&symbol).unwrap());
                    (symbol, depth)
                })
                .collect();
            let position = ledgers
                .iter()
                .map(|(s, l)| (s.clone(), l.position))
                .collect::<HashMap<_, _>>();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                timeout_ms: STRATEGY_RUN_TIMEOUT_MS,
                trader_data: trader_data.clone(),
                order_depths,
                own_trades: fills_to_worker_trade_map(&prev_own_trades, &symbols),
                market_trades: fills_to_worker_trade_map(&prev_market_trades, &symbols),
                position,
            };
            let response = worker.run(&request)?;
            trader_data = response.trader_data.unwrap_or_default();

            let strategy_orders =
                normalize_strategy_orders(response.orders.unwrap_or_default(), &symbols);
            let filtered_orders = enforce_strategy_limits(&strategy_orders, &ledgers, &config.assets);

            // Step 4: strategy orders match against post-take book.
            for asset in &config.assets {
                let symbol = asset.symbol().to_string();
                let orders = filtered_orders.get(&symbol).cloned().unwrap_or_default();
                let book = live_books.get_mut(&symbol).context("missing live book")?;
                let ledger = ledgers.get_mut(&symbol).context("missing ledger")?;
                let fills = execute_strategy_orders(&symbol, timestamp, book, ledger, &orders);
                if capture_outputs {
                    trade_rows.extend(fills.iter().map(fill_to_trade_row));
                }
                own_trades_this_tick.insert(symbol, fills);
            }

            // Step 5: elastic takers (conditional on strategy quoting).
            for asset in &config.assets {
                let symbol = asset.symbol().to_string();
                let book = live_books
                    .get_mut(&symbol)
                    .context("missing live book for elastic")?;
                let strategy_quoting = book
                    .bids
                    .iter()
                    .any(|l| l.owner == LevelOwner::Strategy)
                    || book.asks.iter().any(|l| l.owner == LevelOwner::Strategy);
                if strategy_quoting && rng.gen_bool(asset.elastic_trade_prob()) {
                    let ledger = ledgers.get_mut(&symbol).context("missing ledger")?;
                    let market_buy = rng.gen_bool(asset.buy_prob());
                    let fills = execute_taker_trade(
                        asset.as_ref(),
                        timestamp,
                        book,
                        ledger,
                        market_buy,
                        &mut rng,
                    );
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        if fill_involves_strategy(&fill) {
                            own_trades_this_tick
                                .entry(symbol.clone())
                                .or_default()
                                .push(fill);
                        } else {
                            market_trades_this_tick
                                .entry(symbol.clone())
                                .or_default()
                                .push(fill);
                        }
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            // Trace + running fit per asset.
            let mut tick_total_mtm = 0.0;
            for asset in &config.assets {
                let symbol = asset.symbol().to_string();
                let fv = fv_per_asset[&symbol][tick];
                let ledger = ledgers.get(&symbol).context("missing ledger for trace")?;
                let mtm = ledger.cash + ledger.position as f64 * fv;
                if capture_outputs {
                    trace_rows.push(TraceRow {
                        day,
                        timestamp,
                        product: symbol.clone(),
                        fair_value: fv,
                        position: ledger.position,
                        cash: ledger.cash,
                        mtm_pnl: mtm,
                    });
                }
                let session_x = global_step as f64;
                let day_x = day_step as f64;
                asset_total_fit.get_mut(&symbol).unwrap().update(session_x, mtm);
                day_asset_fit.get_mut(&symbol).unwrap().update(day_x, mtm);
                tick_total_mtm += mtm;
            }
            total_fit.update(global_step as f64, tick_total_mtm);
            day_total_fit.update(day_step as f64, tick_total_mtm);
            global_step += 1;
            day_step += 1;

            prev_own_trades = own_trades_this_tick;
            prev_market_trades = market_trades_this_tick;
        }

        // End-of-day PnL per asset.
        let mut day_total = 0.0;
        let mut run_values: HashMap<String, f64> = HashMap::new();
        for asset in &config.assets {
            let symbol = asset.symbol().to_string();
            let final_fv = *fv_per_asset[&symbol]
                .last()
                .unwrap_or(&10_000.0);
            let ledger = ledgers.get(&symbol).context("missing ledger for day-end")?;
            let pnl = ledger.cash + ledger.position as f64 * final_fv;
            *asset_total_pnl.get_mut(&symbol).unwrap() += pnl;
            *asset_total_cash.get_mut(&symbol).unwrap() += ledger.cash;
            *asset_final_pos.get_mut(&symbol).unwrap() = ledger.position;
            day_total += pnl;
            run_values.insert(format!("{}_pnl", symbol), pnl);
            let fit = day_asset_fit.get(&symbol).unwrap();
            run_values.insert(format!("{}_slope_per_step", symbol), fit.slope_per_step());
            run_values.insert(format!("{}_r2", symbol), fit.r_squared());
        }
        run_values.insert("total_pnl".to_string(), day_total);
        run_values.insert(
            "total_slope_per_step".to_string(),
            day_total_fit.slope_per_step(),
        );
        run_values.insert("total_r2".to_string(), day_total_fit.r_squared());
        run_summaries.push(RunSummaryRow {
            session_id,
            day,
            values: run_values,
        });
        day_outputs.push(DayOutput {
            day,
            price_rows,
            trade_rows,
            trace_rows,
        });
    }

    // MAF bid deducted from total.
    let mut session_total = 0.0;
    for v in asset_total_pnl.values() {
        session_total += v;
    }
    session_total -= config.maf_bid as f64;

    let mut summary_values: HashMap<String, f64> = HashMap::new();
    summary_values.insert("total_pnl".to_string(), session_total);
    summary_values.insert(
        "total_slope_per_step".to_string(),
        total_fit.slope_per_step(),
    );
    summary_values.insert("total_r2".to_string(), total_fit.r_squared());
    for symbol in &symbols {
        summary_values.insert(
            format!("{}_pnl", symbol),
            asset_total_pnl[symbol],
        );
        summary_values.insert(
            format!("{}_cash", symbol),
            asset_total_cash[symbol],
        );
        summary_values.insert(
            format!("{}_position", symbol),
            asset_final_pos[symbol] as f64,
        );
        let fit = asset_total_fit.get(symbol).unwrap();
        summary_values.insert(
            format!("{}_slope_per_step", symbol),
            fit.slope_per_step(),
        );
        summary_values.insert(format!("{}_r2", symbol), fit.r_squared());
    }

    Ok(SessionOutput {
        session_id,
        summary_values,
        run_summaries,
        day_outputs,
    })
}

// ---------------- CSV writing (dynamic per-asset columns) ----------------

fn write_backtest_outputs(config: &Config, outputs: &[SessionOutput]) -> Result<()> {
    fs::create_dir_all(&config.output_dir)?;
    let symbols: Vec<String> = config.symbols().into_iter().map(|s| s.to_string()).collect();

    // session_summary.csv
    let summary_headers = build_summary_headers(&symbols);
    let summary_path = config.output_dir.join("session_summary.csv");
    let mut w = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&summary_path)
        .with_context(|| format!("failed to open {}", summary_path.display()))?;
    w.write_record(&summary_headers)?;
    for output in outputs {
        let mut record: Vec<String> = Vec::with_capacity(summary_headers.len());
        record.push(output.session_id.to_string());
        for header in &summary_headers[1..] {
            let value = output.summary_values.get(header).copied().unwrap_or(0.0);
            record.push(format_value(header, value));
        }
        w.write_record(&record)?;
    }
    w.flush()?;

    // run_summary.csv
    let run_headers = build_run_headers(&symbols);
    let run_path = config.output_dir.join("run_summary.csv");
    let mut w = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&run_path)
        .with_context(|| format!("failed to open {}", run_path.display()))?;
    w.write_record(&run_headers)?;
    for output in outputs {
        for run in &output.run_summaries {
            let mut record: Vec<String> = Vec::with_capacity(run_headers.len());
            record.push(run.session_id.to_string());
            record.push(run.day.to_string());
            for header in &run_headers[2..] {
                let value = run.values.get(header).copied().unwrap_or(0.0);
                record.push(format_value(header, value));
            }
            w.write_record(&record)?;
        }
    }
    w.flush()?;

    // Per-session sample dirs (prices + trades + trace).
    for output in outputs.iter().take(config.write_session_limit) {
        let round_dir = config
            .output_dir
            .join("sessions")
            .join(format!("session_{:05}", output.session_id))
            .join("round1");
        fs::create_dir_all(&round_dir)?;
        for day_output in &output.day_outputs {
            let price_path = round_dir.join(format!("prices_round_1_day_{}.csv", day_output.day));
            let trade_path = round_dir.join(format!("trades_round_1_day_{}.csv", day_output.day));
            let trace_path = round_dir.join(format!("trace_round_1_day_{}.csv", day_output.day));
            let mut pw = WriterBuilder::new().delimiter(b';').from_path(&price_path)?;
            for row in &day_output.price_rows {
                pw.serialize(row)?;
            }
            pw.flush()?;
            let mut tw = WriterBuilder::new().delimiter(b';').from_path(&trade_path)?;
            for row in &day_output.trade_rows {
                tw.serialize(row)?;
            }
            tw.flush()?;
            let mut trw = WriterBuilder::new().delimiter(b';').from_path(&trace_path)?;
            for row in &day_output.trace_rows {
                trw.serialize(row)?;
            }
            trw.flush()?;
        }
    }
    Ok(())
}

fn build_summary_headers(symbols: &[String]) -> Vec<String> {
    let mut headers = vec![
        "session_id".to_string(),
        "total_pnl".to_string(),
    ];
    for s in symbols {
        headers.push(format!("{}_pnl", s));
    }
    for s in symbols {
        headers.push(format!("{}_position", s));
    }
    for s in symbols {
        headers.push(format!("{}_cash", s));
    }
    headers.push("total_slope_per_step".to_string());
    headers.push("total_r2".to_string());
    for s in symbols {
        headers.push(format!("{}_slope_per_step", s));
        headers.push(format!("{}_r2", s));
    }
    headers
}

fn build_run_headers(symbols: &[String]) -> Vec<String> {
    let mut headers = vec![
        "session_id".to_string(),
        "day".to_string(),
        "total_pnl".to_string(),
    ];
    for s in symbols {
        headers.push(format!("{}_pnl", s));
    }
    headers.push("total_slope_per_step".to_string());
    headers.push("total_r2".to_string());
    for s in symbols {
        headers.push(format!("{}_slope_per_step", s));
        headers.push(format!("{}_r2", s));
    }
    headers
}

fn format_value(header: &str, value: f64) -> String {
    if header.ends_with("_position") {
        // Integer-valued field.
        format!("{}", value.round() as i64)
    } else {
        format!("{}", value)
    }
}

fn write_run_log(config: &Config) -> Result<()> {
    let log_path = config.output_dir.join("run.log");
    let symbol_list = config
        .symbols()
        .into_iter()
        .collect::<Vec<_>>()
        .join(",");
    let contents = format!(
        "seed={}\nfv_mode={:?}\ntrade_mode={:?}\nactive_assets={}\nactual_dir={}\nstrategy={}\nsessions={}\nwrite_session_limit={}\n",
        config.seed,
        config.fv_mode,
        config.trade_mode,
        symbol_list,
        config.actual_dir.display(),
        config
            .strategy_path
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_default(),
        config.sessions,
        config.write_session_limit,
    );
    fs::create_dir_all(&config.output_dir)?;
    fs::write(&log_path, contents)
        .with_context(|| format!("failed to write {}", log_path.display()))?;
    Ok(())
}

// ---------------- Seeds ----------------

fn seed_for_day(seed: u64, day: i32) -> u64 {
    let mut value = seed ^ (day as i64 as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    value ^= value >> 33;
    value = value.wrapping_mul(0xFF51_AFD7_ED55_8CCD);
    value ^= value >> 33;
    value
}

fn seed_for_session_day(seed: u64, session_id: usize, day: i32) -> u64 {
    seed_for_day(
        seed ^ ((session_id as u64).wrapping_mul(0xA24B_AED4_963E_E407)),
        day,
    )
}

// ---------------- Trade-map helpers ----------------

fn empty_trade_map(symbols: &[String]) -> HashMap<String, Vec<Fill>> {
    symbols.iter().map(|s| (s.clone(), Vec::new())).collect()
}

fn fills_to_worker_trade_map(
    source: &HashMap<String, Vec<Fill>>,
    symbols: &[String],
) -> HashMap<String, Vec<WorkerTrade>> {
    symbols
        .iter()
        .map(|symbol| {
            let trades = source
                .get(symbol)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .map(|fill| WorkerTrade {
                    symbol: fill.symbol,
                    price: fill.price,
                    quantity: fill.quantity,
                    buyer: fill.buyer,
                    seller: fill.seller,
                    timestamp: fill.timestamp,
                })
                .collect::<Vec<_>>();
            (symbol.clone(), trades)
        })
        .collect()
}

fn sim_book_to_worker_depth(book: &SimBook) -> WorkerOrderDepth {
    let buy_orders = book
        .bids
        .iter()
        .map(|l| (l.price.to_string(), l.quantity))
        .collect::<HashMap<_, _>>();
    let sell_orders = book
        .asks
        .iter()
        .map(|l| (l.price.to_string(), -l.quantity))
        .collect::<HashMap<_, _>>();
    WorkerOrderDepth {
        buy_orders,
        sell_orders,
    }
}

fn book_to_sim_book(book: &Book) -> SimBook {
    SimBook {
        bids: book
            .bids
            .iter()
            .map(|(p, q)| Level {
                price: *p,
                quantity: *q,
                owner: LevelOwner::Bot,
            })
            .collect(),
        asks: book
            .asks
            .iter()
            .map(|(p, q)| Level {
                price: *p,
                quantity: *q,
                owner: LevelOwner::Bot,
            })
            .collect(),
    }
}

fn normalize_strategy_orders(
    raw: HashMap<String, Vec<WorkerOrder>>,
    symbols: &[String],
) -> HashMap<String, Vec<WorkerOrder>> {
    symbols
        .iter()
        .map(|symbol| {
            (
                symbol.clone(),
                raw.get(symbol).cloned().unwrap_or_default(),
            )
        })
        .collect()
}

fn enforce_strategy_limits(
    orders: &HashMap<String, Vec<WorkerOrder>>,
    ledgers: &HashMap<String, ProductLedger>,
    assets: &[Box<dyn AssetSim>],
) -> HashMap<String, Vec<WorkerOrder>> {
    let limit_by_symbol: HashMap<&str, i32> = assets
        .iter()
        .map(|a| (a.symbol(), a.position_limit()))
        .collect();
    orders
        .iter()
        .map(|(product, orders)| {
            let current = ledgers.get(product).map(|l| l.position).unwrap_or(0);
            let limit = *limit_by_symbol.get(product.as_str()).unwrap_or(&i32::MAX);
            let total_buy: i32 = orders.iter().filter(|o| o.quantity > 0).map(|o| o.quantity).sum();
            let total_sell: i32 = orders
                .iter()
                .filter(|o| o.quantity < 0)
                .map(|o| -o.quantity)
                .sum();
            let accepted = if current + total_buy > limit || current - total_sell < -limit {
                Vec::new()
            } else {
                orders.clone()
            };
            (product.clone(), accepted)
        })
        .collect()
}

fn execute_strategy_orders(
    product: &str,
    timestamp: i32,
    book: &mut SimBook,
    ledger: &mut ProductLedger,
    orders: &[WorkerOrder],
) -> Vec<Fill> {
    let mut fills = Vec::new();
    let mut passive_bids: HashMap<i32, i32> = HashMap::new();
    let mut passive_asks: HashMap<i32, i32> = HashMap::new();

    for order in orders {
        if order.quantity > 0 {
            let mut remaining = order.quantity;
            while remaining > 0 {
                let Some(best_ask) = book.asks.first_mut() else {
                    break;
                };
                if best_ask.owner != LevelOwner::Bot || best_ask.price > order.price {
                    break;
                }
                let fill_qty = remaining.min(best_ask.quantity);
                fills.push(Fill {
                    symbol: product.to_string(),
                    price: best_ask.price,
                    quantity: fill_qty,
                    buyer: Some("SUBMISSION".to_string()),
                    seller: Some("BOT".to_string()),
                    timestamp,
                });
                ledger.position += fill_qty;
                ledger.cash -= best_ask.price as f64 * fill_qty as f64;
                remaining -= fill_qty;
                best_ask.quantity -= fill_qty;
                if best_ask.quantity == 0 {
                    book.asks.remove(0);
                }
            }
            if remaining > 0 {
                *passive_bids.entry(order.price).or_insert(0) += remaining;
            }
        } else if order.quantity < 0 {
            let mut remaining = -order.quantity;
            while remaining > 0 {
                let Some(best_bid) = book.bids.first_mut() else {
                    break;
                };
                if best_bid.owner != LevelOwner::Bot || best_bid.price < order.price {
                    break;
                }
                let fill_qty = remaining.min(best_bid.quantity);
                fills.push(Fill {
                    symbol: product.to_string(),
                    price: best_bid.price,
                    quantity: fill_qty,
                    buyer: Some("BOT".to_string()),
                    seller: Some("SUBMISSION".to_string()),
                    timestamp,
                });
                ledger.position -= fill_qty;
                ledger.cash += best_bid.price as f64 * fill_qty as f64;
                remaining -= fill_qty;
                best_bid.quantity -= fill_qty;
                if best_bid.quantity == 0 {
                    book.bids.remove(0);
                }
            }
            if remaining > 0 {
                *passive_asks.entry(order.price).or_insert(0) += remaining;
            }
        }
    }

    for (price, quantity) in passive_bids {
        insert_level(
            &mut book.bids,
            Level {
                price,
                quantity,
                owner: LevelOwner::Strategy,
            },
            true,
        );
    }
    for (price, quantity) in passive_asks {
        insert_level(
            &mut book.asks,
            Level {
                price,
                quantity,
                owner: LevelOwner::Strategy,
            },
            false,
        );
    }
    fills
}

fn execute_taker_trade(
    asset: &dyn AssetSim,
    timestamp: i32,
    book: &mut SimBook,
    ledger: &mut ProductLedger,
    market_buy: bool,
    rng: &mut ChaCha8Rng,
) -> Vec<Fill> {
    let mut fills = Vec::new();
    let available_volume = if market_buy {
        book.asks.iter().map(|l| l.quantity).sum()
    } else {
        book.bids.iter().map(|l| l.quantity).sum()
    };
    if available_volume <= 0 {
        return fills;
    }
    let mut remaining = asset.sample_trade_qty(market_buy, available_volume, rng);

    while remaining > 0 {
        let (price, owner, fill_qty) = if market_buy {
            let Some(best_ask) = book.asks.first_mut() else {
                break;
            };
            let fill_qty = remaining.min(best_ask.quantity);
            let price = best_ask.price;
            let owner = best_ask.owner;
            best_ask.quantity -= fill_qty;
            if best_ask.quantity == 0 {
                book.asks.remove(0);
            }
            (price, owner, fill_qty)
        } else {
            let Some(best_bid) = book.bids.first_mut() else {
                break;
            };
            let fill_qty = remaining.min(best_bid.quantity);
            let price = best_bid.price;
            let owner = best_bid.owner;
            best_bid.quantity -= fill_qty;
            if best_bid.quantity == 0 {
                book.bids.remove(0);
            }
            (price, owner, fill_qty)
        };
        if fill_qty <= 0 {
            break;
        }
        let symbol = asset.symbol().to_string();
        let fill = match (market_buy, owner) {
            (true, LevelOwner::Bot) => Fill {
                symbol,
                price,
                quantity: fill_qty,
                buyer: Some("BOT_TAKER".to_string()),
                seller: Some("BOT_MAKER".to_string()),
                timestamp,
            },
            (true, LevelOwner::Strategy) => {
                ledger.position -= fill_qty;
                ledger.cash += price as f64 * fill_qty as f64;
                Fill {
                    symbol,
                    price,
                    quantity: fill_qty,
                    buyer: Some("BOT_TAKER".to_string()),
                    seller: Some("SUBMISSION".to_string()),
                    timestamp,
                }
            }
            (false, LevelOwner::Bot) => Fill {
                symbol,
                price,
                quantity: fill_qty,
                buyer: Some("BOT_MAKER".to_string()),
                seller: Some("BOT_TAKER".to_string()),
                timestamp,
            },
            (false, LevelOwner::Strategy) => {
                ledger.position += fill_qty;
                ledger.cash -= price as f64 * fill_qty as f64;
                Fill {
                    symbol,
                    price,
                    quantity: fill_qty,
                    buyer: Some("SUBMISSION".to_string()),
                    seller: Some("BOT_TAKER".to_string()),
                    timestamp,
                }
            }
        };
        fills.push(fill);
        remaining -= fill_qty;
    }
    fills
}

fn insert_level(levels: &mut Vec<Level>, level: Level, descending: bool) {
    if let Some(existing) = levels
        .iter_mut()
        .find(|e| e.price == level.price && e.owner == level.owner)
    {
        existing.quantity += level.quantity;
    } else {
        levels.push(level);
    }
    if descending {
        levels.sort_by(|a, b| {
            b.price
                .cmp(&a.price)
                .then(owner_priority(a.owner).cmp(&owner_priority(b.owner)))
        });
    } else {
        levels.sort_by(|a, b| {
            a.price
                .cmp(&b.price)
                .then(owner_priority(a.owner).cmp(&owner_priority(b.owner)))
        });
    }
}

fn owner_priority(owner: LevelOwner) -> i32 {
    match owner {
        LevelOwner::Bot => 0,
        LevelOwner::Strategy => 1,
    }
}

fn fill_involves_strategy(fill: &Fill) -> bool {
    fill.buyer.as_deref() == Some("SUBMISSION") || fill.seller.as_deref() == Some("SUBMISSION")
}

fn fill_to_trade_row(fill: &Fill) -> TradeRow {
    TradeRow {
        timestamp: fill.timestamp,
        buyer: fill.buyer.clone(),
        seller: fill.seller.clone(),
        symbol: fill.symbol.clone(),
        currency: "XIRECS".to_string(),
        price: fill.price as f64,
        quantity: fill.quantity,
    }
}

fn load_price_rows(actual_dir: &Path, day: i32) -> Result<Vec<InputPriceRow>> {
    let path = actual_dir.join(format!("prices_round_1_day_{}.csv", day));
    let mut reader = ReaderBuilder::new()
        .delimiter(b';')
        .from_path(&path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let mut rows = Vec::new();
    for record in reader.deserialize() {
        let row: InputPriceRow = record?;
        rows.push(row);
    }
    Ok(rows)
}

fn load_trade_rows(actual_dir: &Path, day: i32) -> Result<Vec<InputTradeRow>> {
    let path = actual_dir.join(format!("trades_round_1_day_{}.csv", day));
    let mut reader = ReaderBuilder::new()
        .delimiter(b';')
        .from_path(&path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let mut rows = Vec::new();
    for record in reader.deserialize() {
        let row: InputTradeRow = record?;
        rows.push(row);
    }
    Ok(rows)
}

fn trade_counts_for(
    asset: &dyn AssetSim,
    day: i32,
    config: &Config,
    replay: &ReplayData,
    rng: &mut ChaCha8Rng,
) -> Result<Vec<usize>> {
    match config.trade_mode {
        TradeMode::ReplayTimes => replay
            .trade_counts_by_key
            .get(&(day, asset.symbol().to_string()))
            .cloned()
            .with_context(|| format!("missing replay trade count series for {}", asset.symbol())),
        TradeMode::Simulate => Ok(simulate_trade_counts(asset, config.ticks_per_day, rng)),
    }
}

fn simulate_trade_counts(asset: &dyn AssetSim, ticks: usize, rng: &mut ChaCha8Rng) -> Vec<usize> {
    let base_prob = asset.base_trade_prob();
    let second_prob = asset.second_trade_prob();
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

fn apply_quote_fraction(book: &mut Book, f: f64, rng: &mut ChaCha8Rng) {
    if (f - 1.0).abs() < 1e-9 {
        return;
    }
    if f < 1.0 {
        book.bids.retain(|_| rng.gen_bool(f));
        book.asks.retain(|_| rng.gen_bool(f));
    } else {
        for level in &mut book.bids {
            level.1 = ((level.1 as f64) * f).round() as i32;
        }
        for level in &mut book.asks {
            level.1 = ((level.1 as f64) * f).round() as i32;
        }
    }
}

fn book_to_price_row(day: i32, timestamp: i32, product: &str, book: &Book) -> PriceRow {
    let bid1 = book.bids.first().copied();
    let bid2 = book.bids.get(1).copied();
    let bid3 = book.bids.get(2).copied();
    let ask1 = book.asks.first().copied();
    let ask2 = book.asks.get(1).copied();
    let ask3 = book.asks.get(2).copied();
    let best_bid = book.bids.first().map(|x| x.0 as f64).unwrap_or(0.0);
    let best_ask = book.asks.first().map(|x| x.0 as f64).unwrap_or(0.0);
    let mid_price = if !book.bids.is_empty() && !book.asks.is_empty() {
        (best_bid + best_ask) / 2.0
    } else if !book.bids.is_empty() {
        best_bid
    } else {
        best_ask
    };
    PriceRow {
        day,
        timestamp,
        product: product.to_string(),
        bid_price_1: bid1.map(|x| x.0),
        bid_volume_1: bid1.map(|x| x.1),
        bid_price_2: bid2.map(|x| x.0),
        bid_volume_2: bid2.map(|x| x.1),
        bid_price_3: bid3.map(|x| x.0),
        bid_volume_3: bid3.map(|x| x.1),
        ask_price_1: ask1.map(|x| x.0),
        ask_volume_1: ask1.map(|x| x.1),
        ask_price_2: ask2.map(|x| x.0),
        ask_volume_2: ask2.map(|x| x.1),
        ask_price_3: ask3.map(|x| x.0),
        ask_volume_3: ask3.map(|x| x.1),
        mid_price,
        profit_and_loss: 0.0,
    }
}

fn sample_trade_rows(
    timestamp: i32,
    asset: &dyn AssetSim,
    book: &Book,
    rng: &mut ChaCha8Rng,
) -> Vec<TradeRow> {
    let market_buy = rng.gen_bool(asset.buy_prob());
    let available_volume: i32 = if market_buy {
        book.asks.iter().map(|(_, v)| *v).sum()
    } else {
        book.bids.iter().map(|(_, v)| *v).sum()
    };
    if available_volume <= 0 {
        return Vec::new();
    }
    let quantity = asset.sample_trade_qty(market_buy, available_volume, rng);
    let mut rows = Vec::new();
    let mut remaining = quantity;
    let side_iter = if market_buy {
        book.asks.iter()
    } else {
        book.bids.iter()
    };
    for (price, volume_limit) in side_iter {
        if remaining <= 0 {
            break;
        }
        let fill_qty = remaining.min(*volume_limit);
        rows.push(TradeRow {
            timestamp,
            buyer: None,
            seller: None,
            symbol: asset.symbol().to_string(),
            currency: "XIRECS".to_string(),
            price: *price as f64,
            quantity: fill_qty,
        });
        remaining -= fill_qty;
    }
    rows
}
