# Backtesting Guide

## Quick Start

```bash
# One-time setup
cd backtester && pip install -e . && cd ..

# Install Rust (needed for Monte Carlo)
# Download from https://rustup.rs

# Run Monte Carlo backtest with dashboard
prosperity4mcbt a.py --quick --vis --out tmp/results/dashboard.json
```

Both CLIs auto-resolve `a.py` to `traders/a.py`, so you don't need to type the full path.

---

## Setup

### Python package

```bash
cd backtester
pip install -e .
```

This installs two CLIs: `prosperity3bt` (CSV replay) and `prosperity4mcbt` (Monte Carlo).

### Rust toolchain (for Monte Carlo only)

Install from https://rustup.rs. On Windows, use the GNU toolchain:

```bash
rustup default stable-x86_64-pc-windows-gnu
```

### Windows: Application Control

Windows Smart App Control blocks freshly compiled Rust binaries (error 4551). To fix:

1. Open **Windows Security > App & Browser Control > Smart App Control**
2. Set to **Off**

The Rust build output is stored in `C:\tmp\rust_target` to avoid OneDrive sync interference.

### Visualizer (optional)

```bash
cd visualizer
npm install
npm run dev
```

Dashboard runs at `http://localhost:5555/`. Use `--vis` flag with `prosperity4mcbt` to auto-open it.

---

## Data

All tutorial market data lives in `data/round0/` (semicolon-delimited CSVs).

```
data/round0/
├── prices_round_0_day_-1.csv   # Order book snapshots
├── prices_round_0_day_-2.csv
├── trades_round_0_day_-1.csv   # Market trades
└── trades_round_0_day_-2.csv
```

Trader files live in `traders/`. Both CLIs auto-resolve bare filenames (e.g. `a.py` -> `traders/a.py`).

| File | Strategy | Description |
|------|----------|-------------|
| `a.py` | Market making + penny jump + inventory skew | Main strategy (SUBMIT THIS) |
| `b.py` | Simple opportunistic taking (fixed FV) | Basic taker |
| `c.py` | Simple MM around mid with position skew | Basic market maker |
| `trader_hold1.py` | Buy 1 unit, hold forever | Calibration utility (extracts server FV) |

---

## 1. Monte Carlo (`prosperity4mcbt`) -- Primary

Rust-backed Monte Carlo simulator. Generates hundreds/thousands of synthetic market sessions using calibrated bot models, runs your strategy against each, and produces distributional PnL statistics.

```bash
# Quick (100 sessions, ~6s) -- good for iteration
prosperity4mcbt a.py --quick --out tmp/results/dashboard.json

# Heavy (1000 sessions, ~55s) -- final eval before submission
prosperity4mcbt a.py --heavy --out tmp/results/dashboard.json

# With dashboard auto-open
prosperity4mcbt a.py --quick --vis --out tmp/results/dashboard.json
```

### Advanced options

```bash
prosperity4mcbt a.py --quick --seed 42 --out tmp/results/dashboard.json
prosperity4mcbt a.py --quick --fv-mode simulate --out tmp/results/dashboard.json
prosperity4mcbt a.py --quick --trade-mode simulate --out tmp/results/dashboard.json
prosperity4mcbt a.py --sessions 3000 --sample-sessions 150 --out tmp/results/dashboard.json
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

### Strategy comparison (Monte Carlo, 100 sessions each)

| Trader | Mean PnL | Std | Median | P5-P95 |
|--------|----------|-----|--------|--------|
| **a.py** | **14,408** | 2,012 | 14,150 | 11,341 - 17,964 |
| c.py | 7,884 | 934 | 7,973 | 6,402 - 9,223 |
| b.py | -2,224 | 3,043 | -1,571 | -7,738 - 1,840 |

---

## 2. CSV Replay (`prosperity3bt`)

Deterministic replay against the historical order book from tutorial data.

```bash
prosperity3bt a.py 0 --data data
prosperity3bt a.py 0 --data data --print

# Fill analytics (maker vs taker breakdown)
py -3.13 bt_stats.py traders/a.py 0 --data data
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making (26x in our testing). Use for relative A/B comparison only.

### Current replay results

| Day | EMERALDS | TOMATOES | Total |
|-----|----------|----------|-------|
| -2 | 6,746 | 8,242 | 14,988 |
| -1 | 7,523 | 6,642 | 14,165 |
| **Total** | **14,269** | **14,884** | **29,154** |

Note: replay PnL is inflated vs portal because `--match-trades all` lets you trade against bot-to-bot trades.

---

## When to use which

| Scenario | Tool | Command |
|----------|------|---------|
| Dev iteration | `prosperity4mcbt --quick` | `prosperity4mcbt a.py --quick --vis --out tmp/r/d.json` |
| Pre-submission eval | `prosperity4mcbt --heavy` | `prosperity4mcbt a.py --heavy --out tmp/r/d.json` |
| Quick sanity check | `prosperity3bt` | `prosperity3bt a.py 0 --data data` |
| Fill breakdown | `bt_stats.py` | `py -3.13 bt_stats.py traders/a.py 0 --data data` |
| Ground truth | Portal | Submit on prosperity.imc.com |

---

## Calibration

The Monte Carlo simulator works because the tutorial bots have been reverse-engineered from the data. Scripts and docs live in `calibration/`.

### Philosophy (`calibration/ANALYSIS_PHILOSOPHY.md`)

- Never examine a variable in isolation -- always condition on every known variable.
- A "uniform [2, 12]" marginal might actually be two processes (aggressive [5,12] + passive [2,6]) only visible when conditioned on price vs fair value.
- Always run stat tests (chi-squared, z-test) before concluding a distribution is non-uniform.

### How true fair value was extracted

We submitted `traders/trader_hold1.py` (buys 1 TOMATO at t=0, holds forever). Server PnL at each tick = `position * server_FV - buy_cost`, so `server_FV(t) = PnL(t) + buy_price`. This revealed that the server uses a continuous fair value quantized to 1/2048 (~0.0005), following a pure Gaussian random walk: N(0, 0.496^2) per step, zero autocorrelation.

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

1. Submit `traders/trader_hold1.py` (buy 1 unit, hold) to extract server fair value from PnL
2. Run `scripts/extract_fv_and_book.py` on the submission log to get `data/fv_and_book.json`
3. Use `calibration/tomatoes/scripts/analyze_bot{1,2}.py` as templates to identify bot quote rules for new products
4. Validate with `calibration/tomatoes/scripts/validate_bot{1,2,3}.py` -- target >95% exact match
5. Update the Rust simulator parameters in `rust_simulator/src/main.rs`
