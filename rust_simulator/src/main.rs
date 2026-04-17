use anyhow::{Context, Result, bail};
use csv::{ReaderBuilder, WriterBuilder};
use rand::distributions::{Distribution, WeightedIndex};
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
const PRODUCTS: [&str; 2] = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"];
// Portal reality: final round eval runs 10,000 ticks per day. Portal backtest
// (the UI's "Run" button) runs only 1,000 ticks. Default here matches the final
// eval — use `--ticks-per-day 1000` to simulate the portal backtest environment.
const DEFAULT_TICKS_PER_DAY: usize = 10_000;
const TIMESTAMP_STEP: i32 = 100;
const POSITION_LIMIT: i32 = 80;
// Base taker rates calibrated from R2 hold-1 submission 274082 (pure base-rate,
// no elastic firing because hold-1 places no resting orders after t=0):
//   OSMIUM: 46 market-only trades / 1000 ticks = 4.6% (sim retained at 4.0%, close)
//   PEPPER: 31 market-only trades / 1000 ticks = 3.1% (matches original 3.2%)
const ASH_TRADE_ACTIVE_PROB: f64 = 1200.0 / 30_000.0;     // ~4.0% base takers
const IPR_TRADE_ACTIVE_PROB: f64 = 972.0 / 30_000.0;       // ~3.2% base takers (confirmed by 274082)
const ASH_SECOND_TRADE_PROB: f64 = 13.0 / 1200.0;          // rare 2nd trade
const IPR_SECOND_TRADE_PROB: f64 = 4.0 / 972.0;            // very rare 2nd trade
const ASH_TRADE_BUY_PROB: f64 = 0.5;                        // approximate
const IPR_TRADE_BUY_PROB: f64 = 0.5;                        // approximate
// Elastic taker demand: additional takers when player has resting orders. Derived
// from three portal submissions minus the hold-1 base rate (274082, base 3.1% PEPPER / 4.6% OSMIUM):
//   226828 (R1 MM):  OSMIUM 9.0% → 4.4% elastic   | PEPPER 3.6% →  0.5% elastic
//   274250 (R2 MM):  OSMIUM 7.6% → 3.0% elastic   | PEPPER 4.3% →  1.2% elastic
//   Average:         OSMIUM ~3.7-4.4% elastic     | PEPPER ~0.8-1.0% elastic
// Sample is still only two MM strategies × 1000 ticks each, so these rates have
// substantial uncertainty — expect to retune as more portal data lands.
const ASH_ELASTIC_TRADE_PROB: f64 = 0.040;
const IPR_ELASTIC_TRADE_PROB: f64 = 0.009;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum IprSupport {
    Continuous,
    Half,
    Quarter,
}

#[derive(Clone, Debug)]
struct Config {
    output_dir: PathBuf,
    actual_dir: PathBuf,
    fv_mode: FvMode,
    trade_mode: TradeMode,
    ipr_support: IprSupport,
    seed: u64,
    strategy_path: Option<PathBuf>,
    python_bin: String,
    sessions: usize,
    write_session_limit: usize,
    ticks_per_day: usize,
    // R2: probability each generated bot quote appears in the book.
    // Default 1.0 (full book). Portal R2 testing rule is 0.8. MAF winner is 1.05
    // (interpreted as +25pp of the generated set per the R2 spec's example).
    quote_fraction: f64,
    // R2: flat XIRECs deduction from reported total PnL (MAF bookkeeping).
    maf_bid: i64,
    // PEPPER starting FV. Default 10,000 (R1 day -2 start). For R2 day 1, the
    // drift continues from R1 day 0's end — hold-1 submission 274082 confirms
    // FV starts at ~13,000 on R2 day 1. Set via --ipr-start-fv.
    ipr_start_fv: f64,
    // Optional: path to a JSON file { "osmium": [...], "pepper": [...], "ticks": N }
    // that overrides both OSMIUM and PEPPER FV generation with observed server-FV
    // paths (typically extracted from a hold-1 submission). Used to compare MC on
    // the exact FV path that the portal ran against, removing FV-realization noise.
    replay_fv_json: Option<PathBuf>,
}

#[derive(Clone, Debug)]
struct ReplayData {
    ash_fair_by_day: HashMap<i32, Vec<f64>>,
    trade_counts_by_key: HashMap<(i32, String), Vec<usize>>,
}


#[derive(Clone, Debug)]
struct DayOutput {
    day: i32,
    price_rows: Vec<PriceRow>,
    trade_rows: Vec<TradeRow>,
    trace_rows: Vec<TraceRow>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LevelOwner {
    Bot,
    Strategy,
}

#[derive(Clone, Debug)]
struct Level {
    price: i32,
    quantity: i32,
    owner: LevelOwner,
}

#[derive(Clone, Debug)]
struct SimBook {
    bids: Vec<Level>,
    asks: Vec<Level>,
}

#[derive(Clone, Debug)]
struct Fill {
    symbol: String,
    price: i32,
    quantity: i32,
    buyer: Option<String>,
    seller: Option<String>,
    timestamp: i32,
}

#[derive(Clone, Debug, Default)]
struct ProductLedger {
    position: i32,
    cash: f64,
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

#[derive(Clone, Debug, Serialize)]
struct SessionSummary {
    session_id: usize,
    total_pnl: f64,
    ash_pnl: f64,
    ipr_pnl: f64,
    ash_position: i32,
    ipr_position: i32,
    ash_cash: f64,
    ipr_cash: f64,
    total_slope_per_step: f64,
    total_r2: f64,
    ash_slope_per_step: f64,
    ash_r2: f64,
    ipr_slope_per_step: f64,
    ipr_r2: f64,
}

#[derive(Clone, Debug, Serialize)]
struct RunSummary {
    session_id: usize,
    day: i32,
    total_pnl: f64,
    ash_pnl: f64,
    ipr_pnl: f64,
    total_slope_per_step: f64,
    total_r2: f64,
    ash_slope_per_step: f64,
    ash_r2: f64,
    ipr_slope_per_step: f64,
    ipr_r2: f64,
}

#[derive(Clone, Debug)]
struct SessionOutput {
    session_id: usize,
    summary: SessionSummary,
    run_summaries: Vec<RunSummary>,
    day_outputs: Vec<DayOutput>,
}

#[derive(Clone, Debug)]
struct Book {
    bids: Vec<(i32, i32)>,
    asks: Vec<(i32, i32)>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct InputPriceRow {
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

impl Config {
    fn from_args() -> Result<Self> {
        let mut config = Config {
            output_dir: PathBuf::from("../tmp/rust_simulator_output"),
            actual_dir: PathBuf::from("../data/round1"),
            fv_mode: FvMode::Simulate,
            trade_mode: TradeMode::Simulate,
            ipr_support: IprSupport::Continuous,
            seed: 20_260_401,
            strategy_path: None,
            python_bin: "python3".to_string(),
            sessions: 1,
            write_session_limit: 0,
            ticks_per_day: DEFAULT_TICKS_PER_DAY,
            quote_fraction: 1.0,
            maf_bid: 0,
            ipr_start_fv: 10_000.0,
            replay_fv_json: None,
        };

        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--output" => {
                    config.output_dir =
                        PathBuf::from(args.next().context("missing value for --output")?);
                }
                "--actual-dir" => {
                    config.actual_dir =
                        PathBuf::from(args.next().context("missing value for --actual-dir")?);
                }
                "--fv-mode" => {
                    let value = args.next().context("missing value for --fv-mode")?;
                    config.fv_mode = match value.as_str() {
                        "replay" => FvMode::Replay,
                        "simulate" => FvMode::Simulate,
                        other => bail!("unsupported --fv-mode {}", other),
                    };
                }
                "--trade-mode" => {
                    let value = args.next().context("missing value for --trade-mode")?;
                    config.trade_mode = match value.as_str() {
                        "replay-times" => TradeMode::ReplayTimes,
                        "simulate" => TradeMode::Simulate,
                        other => bail!("unsupported --trade-mode {}", other),
                    };
                }
                "--ipr-support" => {
                    let value = args.next().context("missing value for --ipr-support")?;
                    config.ipr_support = match value.as_str() {
                        "continuous" => IprSupport::Continuous,
                        "0.5" | "half" => IprSupport::Half,
                        "0.25" | "quarter" => IprSupport::Quarter,
                        other => bail!("unsupported --ipr-support {}", other),
                    };
                }
                "--seed" => {
                    config.seed = args
                        .next()
                        .context("missing value for --seed")?
                        .parse()
                        .context("invalid --seed")?;
                }
                "--strategy" => {
                    config.strategy_path = Some(PathBuf::from(
                        args.next().context("missing value for --strategy")?,
                    ));
                }
                "--python-bin" => {
                    config.python_bin = args.next().context("missing value for --python-bin")?;
                }
                "--sessions" => {
                    config.sessions = args
                        .next()
                        .context("missing value for --sessions")?
                        .parse()
                        .context("invalid --sessions")?;
                }
                "--write-session-limit" => {
                    config.write_session_limit = args
                        .next()
                        .context("missing value for --write-session-limit")?
                        .parse()
                        .context("invalid --write-session-limit")?;
                }
                "--ticks-per-day" => {
                    config.ticks_per_day = args
                        .next()
                        .context("missing value for --ticks-per-day")?
                        .parse()
                        .context("invalid --ticks-per-day")?;
                }
                "--quote-fraction" => {
                    config.quote_fraction = args
                        .next()
                        .context("missing value for --quote-fraction")?
                        .parse()
                        .context("invalid --quote-fraction")?;
                    if config.quote_fraction < 0.0 || config.quote_fraction > 2.0 {
                        bail!("--quote-fraction must be in [0.0, 2.0]");
                    }
                }
                "--maf-bid" => {
                    config.maf_bid = args
                        .next()
                        .context("missing value for --maf-bid")?
                        .parse()
                        .context("invalid --maf-bid")?;
                }
                "--ipr-start-fv" => {
                    config.ipr_start_fv = args
                        .next()
                        .context("missing value for --ipr-start-fv")?
                        .parse()
                        .context("invalid --ipr-start-fv")?;
                }
                "--replay-fv-json" => {
                    config.replay_fv_json = Some(PathBuf::from(
                        args.next().context("missing value for --replay-fv-json")?,
                    ));
                }
                other => bail!("unknown argument {}", other),
            }
        }

        Ok(config)
    }
}

fn main() -> Result<()> {
    let config = Config::from_args()?;
    let replay_data = ReplayData::load(&config)?;

    if config.strategy_path.is_some() {
        let outputs = run_backtests(&config, &replay_data)?;
        write_backtest_outputs(&config, &outputs)?;
        write_run_log(&config)?;
        return Ok(());
    }

    let outputs = DAYS
        .par_iter()
        .map(|day| generate_day(*day, &config, &replay_data))
        .collect::<Result<Vec<_>>>()?;

    write_outputs(&config, &outputs)?;
    write_run_log(&config)?;
    Ok(())
}

impl ReplayData {
    fn load(config: &Config) -> Result<Self> {
        let mut ash_fair_by_day = HashMap::new();
        let mut trade_counts_by_key = HashMap::new();

        if config.fv_mode == FvMode::Replay {
            for day in DAYS {
                let prices = load_price_rows(&config.actual_dir, day)?;
                let mut rows: Vec<_> = prices
                    .into_iter()
                    .filter(|row| row.product == "ASH_COATED_OSMIUM")
                    .collect();
                rows.sort_by_key(|row| row.timestamp);
                let fair_values = rows
                    .iter()
                    .map(|row| infer_observed_fair(row))
                    .collect::<Vec<_>>();
                ash_fair_by_day.insert(day, fair_values);
            }
        }

        if config.trade_mode == TradeMode::ReplayTimes {
            for day in DAYS {
                let trades = load_trade_rows(&config.actual_dir, day)?;
                for product in PRODUCTS {
                    let mut counts = vec![0usize; DEFAULT_TICKS_PER_DAY];
                    for trade in trades.iter().filter(|row| row.symbol == product) {
                        let index = usize::try_from(trade.timestamp / TIMESTAMP_STEP)
                            .context("negative timestamp while loading replay trades")?;
                        if index < counts.len() {
                            counts[index] += 1;
                        }
                    }
                    trade_counts_by_key.insert((day, product.to_string()), counts);
                }
            }
        }

        Ok(Self {
            ash_fair_by_day,
            trade_counts_by_key,
        })
    }
}

fn generate_day(day: i32, config: &Config, replay: &ReplayData) -> Result<DayOutput> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed_for_day(config.seed, day));
    let ash_fair_values = match config.fv_mode {
        FvMode::Replay => replay
            .ash_fair_by_day
            .get(&day)
            .cloned()
            .context("missing replay ASH fair values")?,
        FvMode::Simulate => simulate_ash_fair(config.ticks_per_day, &mut rng),
    };
    let day_index = DAYS.iter().position(|&d| d == day).unwrap_or(0);

    let ash_trade_counts = trade_counts_for("ASH_COATED_OSMIUM", day, config, replay, &mut rng)?;
    let ipr_trade_counts = trade_counts_for("INTARIAN_PEPPER_ROOT", day, config, replay, &mut rng)?;

    let mut price_rows = Vec::with_capacity(config.ticks_per_day * PRODUCTS.len());
    let mut trade_rows = Vec::new();

    for tick in 0..config.ticks_per_day {
        let timestamp = (tick as i32) * TIMESTAMP_STEP;
        let mut ash_book = make_ash_book(ash_fair_values[tick], &mut rng);
        let ipr_fair = compute_ipr_fair(day_index, tick, config.ticks_per_day, config.ipr_start_fv);
        let mut ipr_book = make_ipr_book(ipr_fair, &mut rng);
        apply_quote_fraction(&mut ash_book, config.quote_fraction, &mut rng);
        apply_quote_fraction(&mut ipr_book, config.quote_fraction, &mut rng);

        price_rows.push(book_to_price_row(day, timestamp, "ASH_COATED_OSMIUM", &ash_book));
        price_rows.push(book_to_price_row(day, timestamp, "INTARIAN_PEPPER_ROOT", &ipr_book));

        for _ in 0..ash_trade_counts[tick] {
            trade_rows.extend(sample_trade_rows(timestamp, "ASH_COATED_OSMIUM", &ash_book, &mut rng));
        }
        for _ in 0..ipr_trade_counts[tick] {
            trade_rows.extend(sample_trade_rows(timestamp, "INTARIAN_PEPPER_ROOT", &ipr_book, &mut rng));
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
            .context("missing strategy path")?
            .canonicalize()
            .with_context(|| "failed to canonicalize strategy path")?;
        let project_root = env::var("PROSPERITY4MCBT_ROOT")
            .map(PathBuf::from)
            .or_else(|_| {
                env::current_dir().map(|cwd| {
                    cwd.parent()
                        .map(Path::to_path_buf)
                        .unwrap_or(cwd)
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

        Ok(Self {
            child,
            stdin,
            stdout,
        })
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

fn run_backtests(config: &Config, replay: &ReplayData) -> Result<Vec<SessionOutput>> {
    let mut outputs = (0..config.sessions)
        .into_par_iter()
        .map(|session_id| {
            run_backtest_session(session_id, session_id < config.write_session_limit, config, replay)
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
    let mut day_outputs = Vec::with_capacity(1);
    let mut ash_total = 0.0;
    let mut ipr_total = 0.0;
    let mut ash_cash_total = 0.0;
    let mut ipr_cash_total = 0.0;
    let mut ash_final_position = 0;
    let mut ipr_final_position = 0;
    let mut total_fit = RunningLinearFit::default();
    let mut ash_fit = RunningLinearFit::default();
    let mut ipr_fit = RunningLinearFit::default();
    let mut global_step = 0usize;
    let mut run_summaries = Vec::with_capacity(1);
    let session_day = monte_carlo_session_day(session_id);

    // Optional: pre-loaded replay FV arrays (both OSMIUM + PEPPER) from a hold-1
    // extraction. When present, overrides all FV generation so every session
    // replays the exact same portal path — the right apples-to-apples comparison
    // for sim validation against portal backtests.
    let replay_fv: Option<ReplayFvPaths> = match &config.replay_fv_json {
        Some(path) => Some(ReplayFvPaths::load(path)?),
        None => None,
    };

    for day in [session_day] {
        worker.reset()?;
        let mut rng = ChaCha8Rng::seed_from_u64(seed_for_session_day(config.seed, session_id, day));
        let ash_fair_values = if let Some(rp) = &replay_fv {
            rp.osmium.clone()
        } else {
            match config.fv_mode {
                FvMode::Replay => replay
                    .ash_fair_by_day
                    .get(&day)
                    .cloned()
                    .context("missing replay ASH fair values")?,
                FvMode::Simulate => simulate_ash_fair(config.ticks_per_day, &mut rng),
            }
        };
        let day_index = DAYS.iter().position(|&d| d == day).unwrap_or(0);

        let ash_trade_counts = trade_counts_for("ASH_COATED_OSMIUM", day, config, replay, &mut rng)?;
        let ipr_trade_counts = trade_counts_for("INTARIAN_PEPPER_ROOT", day, config, replay, &mut rng)?;

        let mut ledgers = HashMap::from([
            ("ASH_COATED_OSMIUM".to_string(), ProductLedger::default()),
            ("INTARIAN_PEPPER_ROOT".to_string(), ProductLedger::default()),
        ]);
        let mut trader_data = String::new();
        let mut prev_own_trades = empty_trade_map();
        let mut prev_market_trades = empty_trade_map();
        let mut day_total_fit = RunningLinearFit::default();
        let mut day_ash_fit = RunningLinearFit::default();
        let mut day_ipr_fit = RunningLinearFit::default();
        let mut day_step = 0usize;
        let mut price_rows = if capture_outputs {
            Vec::with_capacity(config.ticks_per_day * PRODUCTS.len())
        } else {
            Vec::new()
        };
        let mut trade_rows = Vec::new();
        let mut trace_rows = Vec::new();

        for tick in 0..config.ticks_per_day {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;
            let mut ash_book = make_ash_book(ash_fair_values[tick], &mut rng);
            let ipr_fair = if let Some(rp) = &replay_fv {
                rp.pepper[tick]
            } else {
                compute_ipr_fair(day_index, tick, config.ticks_per_day, config.ipr_start_fv)
            };
            let mut ipr_book = make_ipr_book(ipr_fair, &mut rng);
            apply_quote_fraction(&mut ash_book, config.quote_fraction, &mut rng);
            apply_quote_fraction(&mut ipr_book, config.quote_fraction, &mut rng);

            if capture_outputs {
                price_rows.push(book_to_price_row(day, timestamp, "ASH_COATED_OSMIUM", &ash_book));
                price_rows.push(book_to_price_row(day, timestamp, "INTARIAN_PEPPER_ROOT", &ipr_book));
            }

            // Build the live (mutable) books from bot-posted quotes. Base-rate takers
            // run against THIS book before the strategy sees anything, matching the
            // P4 matching sequence: (1) MMs post, (2) bot takers act, (3) strategy
            // runs on post-take book, (4) strategy orders match, (5) remaining bots
            // may trade on strategy quotes. Running base takers first is critical
            // for OSMIUM — otherwise they hit the strategy's penny-jumped quotes
            // and systematically over-report fill edge (~2× in R2 replay vs portal).
            let mut live_books = HashMap::from([
                ("ASH_COATED_OSMIUM".to_string(), book_to_sim_book(&ash_book)),
                ("INTARIAN_PEPPER_ROOT".to_string(), book_to_sim_book(&ipr_book)),
            ]);

            let mut own_trades_this_tick = empty_trade_map();
            let mut market_trades_this_tick = empty_trade_map();

            // Step 2: base-rate bot takers act on the pre-existing bot book.
            // Since no strategy orders are in the book yet, all fills are bot-to-bot.
            for (product, count) in [("ASH_COATED_OSMIUM", ash_trade_counts[tick]), ("INTARIAN_PEPPER_ROOT", ipr_trade_counts[tick])] {
                let product_key = product.to_string();
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book for base-taker execution")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger for base-taker execution")?;
                for _ in 0..count {
                    let market_buy = sample_trade_side(product, &mut rng);
                    let fills = execute_taker_trade(product, timestamp, book, ledger, market_buy, &mut rng);
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        // Pre-strategy takers never touch our orders (nothing posted yet),
                        // so these are always market-only trades.
                        market_trades_this_tick.entry(product_key.clone()).or_default().push(fill);
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            // Step 3: strategy sees post-take book.
            let order_depths = HashMap::from([
                ("ASH_COATED_OSMIUM".to_string(), sim_book_to_worker_depth(live_books.get("ASH_COATED_OSMIUM").unwrap())),
                ("INTARIAN_PEPPER_ROOT".to_string(), sim_book_to_worker_depth(live_books.get("INTARIAN_PEPPER_ROOT").unwrap())),
            ]);
            let position = ledgers
                .iter()
                .map(|(product, ledger)| (product.clone(), ledger.position))
                .collect::<HashMap<_, _>>();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                timeout_ms: STRATEGY_RUN_TIMEOUT_MS,
                trader_data: trader_data.clone(),
                order_depths,
                own_trades: fills_to_worker_trade_map(&prev_own_trades),
                market_trades: fills_to_worker_trade_map(&prev_market_trades),
                position,
            };
            let response = worker.run(&request)?;
            trader_data = response.trader_data.unwrap_or_default();

            let strategy_orders = normalize_strategy_orders(response.orders.unwrap_or_default());
            let filtered_orders = enforce_strategy_limits(&strategy_orders, &ledgers);

            // Step 4: strategy orders match against the post-take book.
            for product in PRODUCTS {
                let product_key = product.to_string();
                let orders = filtered_orders
                    .get(product)
                    .cloned()
                    .unwrap_or_default();
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger")?;
                let fills = execute_strategy_orders(product, timestamp, book, ledger, &orders);
                if capture_outputs {
                    trade_rows.extend(fills.iter().map(fill_to_trade_row));
                }
                own_trades_this_tick.insert(product_key.clone(), fills);
            }

            // Step 5: elastic takers attracted by tighter spreads from strategy quotes.
            // Only fires when the strategy has resting orders in the book.
            for (product, elastic_prob) in [("ASH_COATED_OSMIUM", ASH_ELASTIC_TRADE_PROB), ("INTARIAN_PEPPER_ROOT", IPR_ELASTIC_TRADE_PROB)] {
                let product_key = product.to_string();
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book for elastic taker")?;
                // Check if strategy has any resting orders in the book
                let strategy_quoting = book.bids.iter().any(|l| l.owner == LevelOwner::Strategy)
                    || book.asks.iter().any(|l| l.owner == LevelOwner::Strategy);
                if strategy_quoting && rng.gen_bool(elastic_prob) {
                    let ledger = ledgers.get_mut(&product_key).context("missing ledger for elastic taker")?;
                    let market_buy = sample_trade_side(product, &mut rng);
                    let fills = execute_taker_trade(product, timestamp, book, ledger, market_buy, &mut rng);
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        if fill_involves_strategy(&fill) {
                            own_trades_this_tick.entry(product_key.clone()).or_default().push(fill);
                        } else {
                            market_trades_this_tick.entry(product_key.clone()).or_default().push(fill);
                        }
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            if capture_outputs {
                let ash_fair_tick = ash_fair_values[tick];
                let ipr_fair_tick = ipr_fair;
                for (product, fair) in [("ASH_COATED_OSMIUM", ash_fair_tick), ("INTARIAN_PEPPER_ROOT", ipr_fair_tick)] {
                    let product_key = product.to_string();
                    let ledger = ledgers.get(&product_key).context("missing ledger for trace")?;
                    trace_rows.push(TraceRow {
                        day,
                        timestamp,
                        product: product_key,
                        fair_value: fair,
                        position: ledger.position,
                        cash: ledger.cash,
                        mtm_pnl: ledger.cash + ledger.position as f64 * fair,
                    });
                }
            }

            let ash_ledger = ledgers.get("ASH_COATED_OSMIUM").context("missing ash ledger for fit")?;
            let ipr_ledger = ledgers.get("INTARIAN_PEPPER_ROOT").context("missing ipr ledger for fit")?;
            let ash_mtm = ash_ledger.cash + ash_ledger.position as f64 * ash_fair_values[tick];
            let ipr_mtm = ipr_ledger.cash + ipr_ledger.position as f64 * ipr_fair;
            let session_x = global_step as f64;
            let day_x = day_step as f64;
            ash_fit.update(session_x, ash_mtm);
            ipr_fit.update(session_x, ipr_mtm);
            total_fit.update(session_x, ash_mtm + ipr_mtm);
            day_ash_fit.update(day_x, ash_mtm);
            day_ipr_fit.update(day_x, ipr_mtm);
            day_total_fit.update(day_x, ash_mtm + ipr_mtm);
            global_step += 1;
            day_step += 1;

            prev_own_trades = own_trades_this_tick;
            prev_market_trades = market_trades_this_tick;
        }

        let ash_final_fair = *ash_fair_values.last().unwrap_or(&10_000.0);
        let ipr_final_fair = if let Some(rp) = &replay_fv {
            rp.pepper[config.ticks_per_day.saturating_sub(1)]
        } else {
            compute_ipr_fair(day_index, config.ticks_per_day.saturating_sub(1), config.ticks_per_day, config.ipr_start_fv)
        };
        let ash_ledger = ledgers.get("ASH_COATED_OSMIUM").context("missing ash ledger")?;
        let ipr_ledger = ledgers.get("INTARIAN_PEPPER_ROOT").context("missing ipr ledger")?;
        let ash_pnl = ash_ledger.cash + ash_ledger.position as f64 * ash_final_fair;
        let ipr_pnl = ipr_ledger.cash + ipr_ledger.position as f64 * ipr_final_fair;

        ash_total += ash_pnl;
        ipr_total += ipr_pnl;
        ash_cash_total += ash_ledger.cash;
        ipr_cash_total += ipr_ledger.cash;
        ash_final_position = ash_ledger.position;
        ipr_final_position = ipr_ledger.position;

        run_summaries.push(RunSummary {
            session_id,
            day,
            total_pnl: ash_pnl + ipr_pnl,
            ash_pnl,
            ipr_pnl,
            total_slope_per_step: day_total_fit.slope_per_step(),
            total_r2: day_total_fit.r_squared(),
            ash_slope_per_step: day_ash_fit.slope_per_step(),
            ash_r2: day_ash_fit.r_squared(),
            ipr_slope_per_step: day_ipr_fit.slope_per_step(),
            ipr_r2: day_ipr_fit.r_squared(),
        });

        day_outputs.push(DayOutput {
            day,
            price_rows,
            trade_rows,
            trace_rows,
        });
    }

    // R2: deduct MAF bid from session total PnL (losers pay nothing; this is a pure
    // bookkeeping subtraction modelling the MAF-winner case).
    let session_total = ash_total + ipr_total - config.maf_bid as f64;
    let summary = SessionSummary {
        session_id,
        total_pnl: session_total,
        ash_pnl: ash_total,
        ipr_pnl: ipr_total,
        ash_position: ash_final_position,
        ipr_position: ipr_final_position,
        ash_cash: ash_cash_total,
        ipr_cash: ipr_cash_total,
        total_slope_per_step: total_fit.slope_per_step(),
        total_r2: total_fit.r_squared(),
        ash_slope_per_step: ash_fit.slope_per_step(),
        ash_r2: ash_fit.r_squared(),
        ipr_slope_per_step: ipr_fit.slope_per_step(),
        ipr_r2: ipr_fit.r_squared(),
    };

    Ok(SessionOutput {
        session_id,
        summary,
        run_summaries,
        day_outputs,
    })
}

fn write_backtest_outputs(config: &Config, outputs: &[SessionOutput]) -> Result<()> {
    fs::create_dir_all(&config.output_dir)?;
    let summary_path = config.output_dir.join("session_summary.csv");
    let mut writer = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&summary_path)
        .with_context(|| format!("failed to open {}", summary_path.display()))?;
    for output in outputs {
        writer.serialize(&output.summary)?;
    }
    writer.flush()?;

    let run_summary_path = config.output_dir.join("run_summary.csv");
    let mut run_writer = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&run_summary_path)
        .with_context(|| format!("failed to open {}", run_summary_path.display()))?;
    for output in outputs {
        for run_summary in &output.run_summaries {
            run_writer.serialize(run_summary)?;
        }
    }
    run_writer.flush()?;

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
            let mut price_writer = WriterBuilder::new().delimiter(b';').from_path(&price_path)?;
            for row in &day_output.price_rows {
                price_writer.serialize(row)?;
            }
            price_writer.flush()?;

            let mut trade_writer = WriterBuilder::new().delimiter(b';').from_path(&trade_path)?;
            for row in &day_output.trade_rows {
                trade_writer.serialize(row)?;
            }
            trade_writer.flush()?;

            let mut trace_writer = WriterBuilder::new().delimiter(b';').from_path(&trace_path)?;
            for row in &day_output.trace_rows {
                trace_writer.serialize(row)?;
            }
            trace_writer.flush()?;
        }
    }

    Ok(())
}

fn write_run_log(config: &Config) -> Result<()> {
    let log_path = config.output_dir.join("run.log");
    let contents = format!(
        "seed={}\nfv_mode={:?}\ntrade_mode={:?}\nipr_support={:?}\nactual_dir={}\nstrategy={}\nsessions={}\nwrite_session_limit={}\n",
        config.seed,
        config.fv_mode,
        config.trade_mode,
        config.ipr_support,
        config.actual_dir.display()
        ,
        config
            .strategy_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "".to_string()),
        config.sessions,
        config.write_session_limit,
    );
    fs::create_dir_all(&config.output_dir)?;
    fs::write(&log_path, contents)
        .with_context(|| format!("failed to write {}", log_path.display()))?;
    Ok(())
}

fn seed_for_day(seed: u64, day: i32) -> u64 {
    let mut value = seed ^ (day as i64 as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    value ^= value >> 33;
    value = value.wrapping_mul(0xFF51_AFD7_ED55_8CCD);
    value ^= value >> 33;
    value
}

fn seed_for_session_day(seed: u64, session_id: usize, day: i32) -> u64 {
    seed_for_day(seed ^ ((session_id as u64).wrapping_mul(0xA24B_AED4_963E_E407)), day)
}

fn empty_trade_map() -> HashMap<String, Vec<Fill>> {
    HashMap::from([
        ("ASH_COATED_OSMIUM".to_string(), Vec::new()),
        ("INTARIAN_PEPPER_ROOT".to_string(), Vec::new()),
    ])
}

fn fills_to_worker_trade_map(source: &HashMap<String, Vec<Fill>>) -> HashMap<String, Vec<WorkerTrade>> {
    PRODUCTS
        .iter()
        .map(|product| {
            let trades = source
                .get(*product)
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
            ((*product).to_string(), trades)
        })
        .collect()
}

fn book_to_worker_depth(book: &Book) -> WorkerOrderDepth {
    let buy_orders = book
        .bids
        .iter()
        .map(|(price, qty)| (price.to_string(), *qty))
        .collect::<HashMap<_, _>>();
    let sell_orders = book
        .asks
        .iter()
        .map(|(price, qty)| (price.to_string(), -*qty))
        .collect::<HashMap<_, _>>();
    WorkerOrderDepth {
        buy_orders,
        sell_orders,
    }
}

/// Convert a (post-take) SimBook back into the WorkerOrderDepth format the
/// Python strategy worker consumes. Used when base-rate takers run before the
/// strategy sees the book — the strategy must see the thinned book, not the
/// raw generated one.
fn sim_book_to_worker_depth(book: &SimBook) -> WorkerOrderDepth {
    let buy_orders = book
        .bids
        .iter()
        .map(|level| (level.price.to_string(), level.quantity))
        .collect::<HashMap<_, _>>();
    let sell_orders = book
        .asks
        .iter()
        .map(|level| (level.price.to_string(), -level.quantity))
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
            .map(|(price, quantity)| Level {
                price: *price,
                quantity: *quantity,
                owner: LevelOwner::Bot,
            })
            .collect(),
        asks: book
            .asks
            .iter()
            .map(|(price, quantity)| Level {
                price: *price,
                quantity: *quantity,
                owner: LevelOwner::Bot,
            })
            .collect(),
    }
}

fn normalize_strategy_orders(
    raw: HashMap<String, Vec<WorkerOrder>>,
) -> HashMap<String, Vec<WorkerOrder>> {
    PRODUCTS
        .iter()
        .map(|product| {
            (
                (*product).to_string(),
                raw.get(*product).cloned().unwrap_or_default(),
            )
        })
        .collect()
}

fn enforce_strategy_limits(
    orders: &HashMap<String, Vec<WorkerOrder>>,
    ledgers: &HashMap<String, ProductLedger>,
) -> HashMap<String, Vec<WorkerOrder>> {
    orders
        .iter()
        .map(|(product, product_orders)| {
            let current_position = ledgers.get(product).map(|ledger| ledger.position).unwrap_or(0);
            let total_buy: i32 = product_orders
                .iter()
                .filter(|order| order.quantity > 0)
                .map(|order| order.quantity)
                .sum();
            let total_sell: i32 = product_orders
                .iter()
                .filter(|order| order.quantity < 0)
                .map(|order| -order.quantity)
                .sum();

            let accepted = if current_position + total_buy > POSITION_LIMIT
                || current_position - total_sell < -POSITION_LIMIT
            {
                Vec::new()
            } else {
                product_orders.clone()
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
    product: &str,
    timestamp: i32,
    book: &mut SimBook,
    ledger: &mut ProductLedger,
    market_buy: bool,
    rng: &mut ChaCha8Rng,
) -> Vec<Fill> {
    let mut fills = Vec::new();
    let available_volume = if market_buy {
        book.asks.iter().map(|level| level.quantity).sum()
    } else {
        book.bids.iter().map(|level| level.quantity).sum()
    };
    if available_volume <= 0 {
        return fills;
    }

    let mut remaining = sample_trade_quantity_by_side(product, market_buy, available_volume, rng);

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

        let fill = match (market_buy, owner) {
            (true, LevelOwner::Bot) => Fill {
                symbol: product.to_string(),
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
                    symbol: product.to_string(),
                    price,
                    quantity: fill_qty,
                    buyer: Some("BOT_TAKER".to_string()),
                    seller: Some("SUBMISSION".to_string()),
                    timestamp,
                }
            }
            (false, LevelOwner::Bot) => Fill {
                symbol: product.to_string(),
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
                    symbol: product.to_string(),
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
        .find(|existing| existing.price == level.price && existing.owner == level.owner)
    {
        existing.quantity += level.quantity;
    } else {
        levels.push(level);
    }
    if descending {
        levels.sort_by(|a, b| b.price.cmp(&a.price).then(owner_priority(a.owner).cmp(&owner_priority(b.owner))));
    } else {
        levels.sort_by(|a, b| a.price.cmp(&b.price).then(owner_priority(a.owner).cmp(&owner_priority(b.owner))));
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

fn sample_trade_side(product: &str, rng: &mut ChaCha8Rng) -> bool {
    let buy_prob = if product == "ASH_COATED_OSMIUM" {
        ASH_TRADE_BUY_PROB
    } else {
        IPR_TRADE_BUY_PROB
    };
    rng.gen_bool(buy_prob)
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

fn infer_observed_fair(row: &InputPriceRow) -> f64 {
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


fn trade_counts_for(
    product: &str,
    day: i32,
    config: &Config,
    replay: &ReplayData,
    rng: &mut ChaCha8Rng,
) -> Result<Vec<usize>> {
    match config.trade_mode {
        TradeMode::ReplayTimes => replay
            .trade_counts_by_key
            .get(&(day, product.to_string()))
            .cloned()
            .context("missing replay trade count series"),
        TradeMode::Simulate => Ok(simulate_trade_counts(product, config.ticks_per_day, rng)),
    }
}

fn simulate_trade_counts(product: &str, ticks: usize, rng: &mut ChaCha8Rng) -> Vec<usize> {
    let (base_prob, second_trade_prob) = if product == "ASH_COATED_OSMIUM" {
        (ASH_TRADE_ACTIVE_PROB, ASH_SECOND_TRADE_PROB)
    } else {
        (IPR_TRADE_ACTIVE_PROB, IPR_SECOND_TRADE_PROB)
    };
    let mut counts = vec![0usize; ticks];
    for count in &mut counts {
        if rng.gen_bool(base_prob) {
            *count = 1;
            if second_trade_prob > 0.0 && rng.gen_bool(second_trade_prob) {
                *count += 1;
            }
        }
    }
    counts
}

fn simulate_ash_fair(ticks: usize, rng: &mut ChaCha8Rng) -> Vec<f64> {
    // Calibrated from data/prosperity4/round1 (3 days, see OSMIUM_ANALYSIS.md):
    //   - AR(1) on steps: coef = -0.32 (65% reversal after each move)
    //   - OU pullback toward 10000 with theta ≈ 0.008 (half-life ~90 ticks)
    //   - Innovation sigma preserved from prior calibration
    let start = 10_000.0;
    let mu = 10_000.0;
    let theta = 0.008;
    let ar_coef = -0.32;
    let sigma = 0.38;
    let mut values = vec![0.0; ticks];
    values[0] = quantize_1024(start);
    let mut prev_step = 0.0;
    for index in 1..ticks {
        let ou_pull = -theta * (values[index - 1] - mu);
        let noise = sigma * sample_standard_normal(rng);
        let step = ou_pull + ar_coef * prev_step + noise;
        values[index] = quantize_1024(values[index - 1] + step);
        prev_step = values[index] - values[index - 1];
    }
    values
}

fn compute_ipr_fair(day_index: usize, tick: usize, ticks_per_day: usize, start_fv: f64) -> f64 {
    let total_tick = day_index * ticks_per_day + tick;
    quantize_1024(start_fv + total_tick as f64 * 0.1)
}

fn quantize_1024(value: f64) -> f64 {
    (value * 1024.0).round() / 1024.0
}

/// Observed server-FV arrays for OSMIUM + PEPPER, typically extracted from a
/// hold-1 portal submission. When present, MC replays these exact paths instead
/// of simulating — lets us compare MC PnL against portal PnL on matched FV paths,
/// removing FV-realization variance as a confounder during sim validation.
struct ReplayFvPaths {
    osmium: Vec<f64>,
    pepper: Vec<f64>,
}

impl ReplayFvPaths {
    fn load(path: &Path) -> Result<Self> {
        #[derive(Deserialize)]
        struct Raw {
            osmium: Vec<f64>,
            pepper: Vec<f64>,
        }
        let text = fs::read_to_string(path)
            .with_context(|| format!("reading replay FV json {}", path.display()))?;
        let raw: Raw = serde_json::from_str(&text)
            .with_context(|| format!("parsing replay FV json {}", path.display()))?;
        if raw.osmium.len() != raw.pepper.len() {
            bail!(
                "replay FV json arrays must have equal length (osmium={}, pepper={})",
                raw.osmium.len(),
                raw.pepper.len()
            );
        }
        Ok(Self { osmium: raw.osmium, pepper: raw.pepper })
    }
}

/// Apply the --quote-fraction overlay to a generated book.
///
/// For f < 1.0: each level survives independently with probability f, modeling
/// the R2 testing rule ("randomized 80% subset of generated quotes"). At f = 0.8
/// combined with the calibrated 80% bot presence this yields 64% effective
/// presence per side.
///
/// For f > 1.0: each level's volume is scaled by f. This approximates the MAF
/// "+25% more quotes" uplift by increasing fill capacity proportionally rather
/// than synthesizing new price levels (simpler, same expected PnL effect).
///
/// f = 1.0 (default) leaves the book untouched.
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

fn sample_standard_normal(rng: &mut ChaCha8Rng) -> f64 {
    let u1 = rng.gen_range(f64::EPSILON..1.0);
    let u2 = rng.gen_range(0.0..1.0);
    (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

fn make_ash_book(fair: f64, rng: &mut ChaCha8Rng) -> Book {
    // Bot presence: each bot appears on each side independently ~80%
    let bot1_bid_present = rng.gen_bool(0.80);
    let bot1_ask_present = rng.gen_bool(0.80);
    let bot2_bid_present = rng.gen_bool(0.80);
    let bot2_ask_present = rng.gen_bool(0.80);

    // Bot 1 (outer wall): bid = floor(FV) - 10, ask = ceil(FV) + 10, vol = U(20,30)
    let bot1_vol = rng.gen_range(20..=30);
    let bot1_bid = fair.floor() as i32 - 10;
    let bot1_ask = fair.ceil() as i32 + 10;

    // Bot 2 (inner wall): bid = floor(FV-0.5) - 7, ask = floor(FV-0.5) + 9, vol = U(10,15)
    let bot2_vol = rng.gen_range(10..=15);
    let r = (fair - 0.5).floor() as i32;
    let bot2_bid = r - 7;
    let bot2_ask = r + 9;

    // Bot 3 (noise): ~8% presence, single-sided
    let bot3_draw: f64 = rng.gen_range(0.0..1.0);

    let mut bids = Vec::new();
    let mut asks = Vec::new();

    if bot2_bid_present { bids.push((bot2_bid, bot2_vol)); }
    if bot1_bid_present { bids.push((bot1_bid, bot1_vol)); }
    if bot2_ask_present { asks.push((bot2_ask, bot2_vol)); }
    if bot1_ask_present { asks.push((bot1_ask, bot1_vol)); }

    // Bot 3: ~8% presence, 50/50 side
    // Crossing (price on wrong side of FV): vol U(4,10)
    // Passive (price on correct side): vol U(1,5)
    if bot3_draw < 0.04 {
        // bid-side noise
        let offset = [-3, -2, 1, 2][rng.gen_range(0..4)];
        let price = fair.round() as i32 + offset;
        let crossing = price as f64 > fair;
        let vol = if crossing { rng.gen_range(4..=10) } else { rng.gen_range(1..=5) };
        bids.push((price, vol));
    } else if bot3_draw < 0.08 {
        // ask-side noise
        let offset = [-3, -2, 1, 2][rng.gen_range(0..4)];
        let price = fair.round() as i32 + offset;
        let crossing = (price as f64) < fair;
        let vol = if crossing { rng.gen_range(4..=10) } else { rng.gen_range(1..=5) };
        asks.push((price, vol));
    }

    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));

    Book { bids, asks }
}

fn make_ipr_book(fair: f64, rng: &mut ChaCha8Rng) -> Book {
    // Bot presence: each bot appears on each side independently ~80%
    let bot1_bid_present = rng.gen_bool(0.80);
    let bot1_ask_present = rng.gen_bool(0.80);
    let bot2_bid_present = rng.gen_bool(0.80);
    let bot2_ask_present = rng.gen_bool(0.80);

    // Bot 1 (outer wall): proportional offset K = 3/4000 = 0.000750
    // bid = floor(FV * (1 - K)), ask = ceil(FV * (1 + K)), vol = U(15,25)
    // Validated at 99.9% across 30,000 ticks (3 days, FV 10000-13000)
    const K1: f64 = 3.0 / 4000.0;
    let bot1_vol = rng.gen_range(15..=25);
    let bot1_bid = (fair * (1.0 - K1)).floor() as i32;
    let bot1_ask = (fair * (1.0 + K1)).ceil() as i32;

    // Bot 2 (inner wall): proportional offset K = 1/2000 = 0.000500
    // bid = floor(FV * (1 - K)), ask = ceil(FV * (1 + K)), vol = U(8,12)
    // Validated at 99.0% across 30,000 ticks (3 days, FV 10000-13000)
    const K2: f64 = 1.0 / 2000.0;
    let bot2_vol = rng.gen_range(8..=12);
    let bot2_bid = (fair * (1.0 - K2)).floor() as i32;
    let bot2_ask = (fair * (1.0 + K2)).ceil() as i32;

    // Bot 3 (noise): ~5% presence, single-sided
    let bot3_draw: f64 = rng.gen_range(0.0..1.0);

    let mut bids = Vec::new();
    let mut asks = Vec::new();

    if bot2_bid_present { bids.push((bot2_bid, bot2_vol)); }
    if bot1_bid_present { bids.push((bot1_bid, bot1_vol)); }
    if bot2_ask_present { asks.push((bot2_ask, bot2_vol)); }
    if bot1_ask_present { asks.push((bot1_ask, bot1_vol)); }

    // Bot 3: ~5% presence, 50/50 side
    // IPR Bot 3 is REVERSED from ASH: crossing vol U(3,8), passive vol U(5,12)
    if bot3_draw < 0.025 {
        let offset = [3, -3][rng.gen_range(0..2)];
        let price = fair.round() as i32 + offset;
        let crossing = price as f64 > fair;
        let vol = if crossing { rng.gen_range(3..=8) } else { rng.gen_range(5..=12) };
        bids.push((price, vol));
    } else if bot3_draw < 0.05 {
        let offset = [-4, 2][rng.gen_range(0..2)];
        let price = fair.round() as i32 + offset;
        let crossing = (price as f64) < fair;
        let vol = if crossing { rng.gen_range(3..=8) } else { rng.gen_range(5..=12) };
        asks.push((price, vol));
    }

    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));

    Book { bids, asks }
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

fn sample_trade_rows(timestamp: i32, product: &str, book: &Book, rng: &mut ChaCha8Rng) -> Vec<TradeRow> {
    let market_buy = sample_trade_side(product, rng);
    let available_volume: i32 = if market_buy {
        book.asks.iter().map(|(_, volume)| *volume).sum()
    } else {
        book.bids.iter().map(|(_, volume)| *volume).sum()
    };
    if available_volume <= 0 {
        return Vec::new();
    }

    let quantity = sample_trade_quantity_by_side(product, market_buy, available_volume, rng);

    let mut rows = Vec::new();
    let mut remaining = quantity;
    if market_buy {
        for (price, volume_limit) in &book.asks {
            if remaining <= 0 {
                break;
            }
            let fill_qty = remaining.min(*volume_limit);
            rows.push(TradeRow {
                timestamp,
                buyer: None,
                seller: None,
                symbol: product.to_string(),
                currency: "XIRECS".to_string(),
                price: *price as f64,
                quantity: fill_qty,
            });
            remaining -= fill_qty;
        }
    } else {
        for (price, volume_limit) in &book.bids {
            if remaining <= 0 {
                break;
            }
            let fill_qty = remaining.min(*volume_limit);
            rows.push(TradeRow {
                timestamp,
                buyer: None,
                seller: None,
                symbol: product.to_string(),
                currency: "XIRECS".to_string(),
                price: *price as f64,
                quantity: fill_qty,
            });
            remaining -= fill_qty;
        }
    }

    rows
}

fn sample_trade_quantity_by_side(
    product: &str,
    market_buy: bool,
    volume_limit: i32,
    rng: &mut ChaCha8Rng,
) -> i32 {
    let (values, weights): (&[i32], &[u32]) = match (product, market_buy) {
        ("ASH_COATED_OSMIUM", true) => (&[2, 3, 4, 5, 6, 7, 8, 9, 10], &[80, 90, 86, 112, 115, 39, 36, 38, 38]),
        ("ASH_COATED_OSMIUM", false) => (&[2, 3, 4, 5, 6, 7, 8, 9, 10], &[80, 89, 86, 112, 115, 39, 35, 38, 37]),
        ("INTARIAN_PEPPER_ROOT", true) => (&[3, 4, 5, 6, 7, 8], &[99, 81, 98, 110, 98, 21]),
        ("INTARIAN_PEPPER_ROOT", false) => (&[3, 4, 5, 6, 7, 8], &[99, 80, 97, 109, 97, 21]),
        _ => (&[1], &[1]),
    };

    let filtered = values
        .iter()
        .zip(weights.iter())
        .filter(|(value, _)| **value <= volume_limit)
        .map(|(value, weight)| (*value, *weight))
        .collect::<Vec<_>>();

    if filtered.is_empty() {
        return volume_limit.max(1);
    }

    let filtered_values = filtered.iter().map(|(value, _)| *value).collect::<Vec<_>>();
    let filtered_weights = filtered
        .iter()
        .map(|(_, weight)| *weight)
        .collect::<Vec<_>>();
    let chooser = WeightedIndex::new(filtered_weights).expect("valid filtered trade weights");
    filtered_values[chooser.sample(rng)]
}
