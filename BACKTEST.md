# Backtesting Guide

## Data

All tutorial market data lives in `data/round0/` (semicolon-delimited CSVs).

```
data/round0/
├── prices_round_0_day_-1.csv   # Order book snapshots
├── prices_round_0_day_-2.csv
├── trades_round_0_day_-1.csv   # Market trades
└── trades_round_0_day_-2.csv
```

---

## Setup (one-time)

```bash
cd backtester
pip install -e .
```

Rust/Cargo is also required for the Monte Carlo simulator. Install from https://rustup.rs if needed.

### Windows: Application Control policy

Windows may block execution of freshly compiled Rust binaries (error 4551). The build output directory is set to `C:\tmp\rust_target` by default to avoid OneDrive interference. If you still get blocked, you may need to add an exclusion in Windows Security > App & Browser Control > Smart App Control, or temporarily disable it.

---

## 1. CSV Replay (`prosperity3bt`)

Deterministic replay against the historical order book from tutorial data.

```bash
# Basic replay
prosperity3bt traders/trader.py 0 --data data

# With print output
prosperity3bt traders/trader.py 0 --data data --print

# Fill analytics (maker vs taker breakdown)
py -3.13 bt_stats.py traders/trader.py 0 --data data
```

**Note**: `--match-trades all` (default) is too optimistic for market making. Use for relative A/B comparison between strategies only, not absolute PnL prediction.

---

## 2. Monte Carlo (`prosperity4mcbt`)

Rust-backed Monte Carlo simulator. Generates thousands of synthetic market sessions using calibrated bot models, runs your strategy against each, and produces distributional PnL statistics.

This is the primary backtesting tool.

```bash
# Quick (100 sessions, ~6s) -- good for iteration
prosperity4mcbt traders/trader.py --quick --out tmp/results/dashboard.json

# Default (100 sessions, 10 sample paths)
prosperity4mcbt traders/trader.py --out tmp/results/dashboard.json

# Heavy (1000 sessions, ~55s) -- final eval before submission
prosperity4mcbt traders/trader.py --heavy --out tmp/results/dashboard.json

# Open dashboard in browser after run
prosperity4mcbt traders/trader.py --quick --vis --out tmp/results/dashboard.json
```

### Advanced options

```bash
# Reproducible seed
prosperity4mcbt traders/trader.py --quick --seed 42 --out tmp/results/dashboard.json

# Fair value mode: simulate (generative) vs replay (from CSV)
prosperity4mcbt traders/trader.py --quick --fv-mode simulate --out tmp/results/dashboard.json

# Trade arrival mode
prosperity4mcbt traders/trader.py --quick --trade-mode simulate --out tmp/results/dashboard.json

# Custom session/sample counts
prosperity4mcbt traders/trader.py --sessions 3000 --sample-sessions 150 --out tmp/results/dashboard.json
```

### Output bundle

```
tmp/results/
├── dashboard.json       # Load in visualizer
├── session_summary.csv  # Per-session PnL stats
├── run_summary.csv      # Aggregate stats
├── sample_paths/        # Detailed traces for sampled sessions
└── sessions/            # Full session logs
```

### Visualizer

```bash
cd visualizer
npm install
npm run dev
```

Dashboard runs at `http://localhost:5173/`. When using `--vis` with `prosperity4mcbt`, the dashboard auto-opens via a CORS file server on port 8001.

### Rust simulator directly

```bash
py -3.13 scripts/run_monte_carlo_backtest.py --strategy traders/trader.py --sessions 100
```

---

## When to use which

| Scenario | Tool | Command |
|----------|------|---------|
| Quick sanity check | `prosperity3bt` | `prosperity3bt traders/trader.py 0 --data data` |
| Fill breakdown | `bt_stats.py` | `py -3.13 bt_stats.py traders/trader.py 0 --data data` |
| Dev iteration | `prosperity4mcbt --quick` | `prosperity4mcbt traders/trader.py --quick --out tmp/r/d.json` |
| Pre-submission eval | `prosperity4mcbt --heavy` | `prosperity4mcbt traders/trader.py --heavy --out tmp/r/d.json` |
| Ground truth | Portal | Submit on prosperity.imc.com |

---

## Calibration

The Monte Carlo simulator works because the tutorial bots have been reverse-engineered from the data. The calibration scripts and methodology live in `calibration/`.

### Philosophy (`calibration/ANALYSIS_PHILOSOPHY.md`)

- Never examine a variable in isolation -- always condition on every known variable.
- A "uniform [2, 12]" marginal might actually be two processes (aggressive [5,12] + passive [2,6]) only visible when conditioned on price vs fair value.
- Always run stat tests (chi-squared, z-test) before concluding a distribution is non-uniform. Small samples produce lopsided-looking splits by chance.

### How true fair value was extracted

We submitted `trader_hold1.py` (buys 1 TOMATO at t=0, holds forever). Server PnL at each tick = `position * server_FV - buy_cost`, so `server_FV(t) = PnL(t) + buy_price`. This revealed that the server uses a continuous fair value quantized to 1/2048 (~0.0005), following a pure Gaussian random walk: N(0, 0.496^2) per step, zero autocorrelation.

### Bot 1 -- Outer wall (`calibration/tomatoes/bot1_calibration.md`)

The deepest level, always present on both sides. Identified by `|offset from FV| > 7`.

```python
bid = round(FV) - 8
ask = round(FV) + 8
vol = randint(15, 25)  # same both sides per tick
```

- Spread: 16 (96.8%), 15 (3.1%), or 17 (0.1%) -- boundary rounding noise
- Validation: 96.8% exact match on both sides. All misses are +/-1 at FV = X.5 boundaries.

### Bot 2 -- Inner wall (`calibration/tomatoes/bot2_calibration.md`)

The best bid/ask most of the time. Uses asymmetric rounding thresholds for bid vs ask:

```python
bid = floor(FV + 0.75) - 7
ask = ceil(FV + 0.25) + 6
vol = randint(5, 10)  # same both sides per tick
```

- Spread: 13 (53.5%) when FV in [N.25, N.75), 14 (46.5%) otherwise
- Validation: 97.7% exact match. Misses are +/-1 at 0.25/0.75 fractional boundaries.

### Bot 3 -- Near-FV noise (`calibration/tomatoes/bot3_calibration.md`)

A rare single-sided quote inside Bot 2's spread. Negligible impact on strategy.

```python
def bot3_quote(fv):
    if random.random() > 0.063:
        return None  # absent 93.7% of the time
    side = 'bid' if random.random() < 0.46 else 'ask'
    price = round(fv) + random.choice([-2, -1, 0, 1])
    if (side == 'bid' and price > fv) or (side == 'ask' and price < fv):
        vol = random.randint(5, 12)   # crossing/aggressive
    else:
        vol = random.randint(2, 6)    # passive
    return side, price, vol
```

- Present 6.3% of timestamps, duration ~1 tick, always single-sided.

### EMERALDS calibration

Simpler: fixed fair value at 10,000, outer wall at +/-10, inner wall at +/-8. Same volume distributions as TOMATOES bots.

### Recalibrating for new rounds

When new round data arrives:

1. Submit `trader_hold1.py` (buy 1 unit, hold) to extract server fair value from PnL
2. Run `scripts/extract_fv_and_book.py` on the submission log to get `data/fv_and_book.json`
3. Use `calibration/tomatoes/scripts/analyze_bot{1,2}.py` as templates to identify bot quote rules for new products
4. Validate with `calibration/tomatoes/scripts/validate_bot{1,2,3}.py` -- target >95% exact match
5. Update the Rust simulator parameters in `rust_simulator/src/main.rs`
