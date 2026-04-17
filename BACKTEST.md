# Backtesting Guide

## Quick Start

```bash
# One-time setup
pip install -e .

# Install Rust (needed for Monte Carlo)
# Download from https://rustup.rs

# Run Monte Carlo backtest with dashboard (points at the active round's trader)
prosperity4mcbt traders/round2/a.py --quick --vis --out tmp/results/dashboard.json
```

Both CLIs auto-resolve bare filenames — e.g. `a.py` → `traders/round2/a.py` (active round). Pass a full path like `traders/round1/final_obi_v4.py` to backtest a historical submission.

---

## Setup

### Python package

```bash
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

### Visualizer

```bash
cd visualizer
npm install
```

#### One-command launch (recommended)

From the repo root, run the PowerShell script, or just run the first one and you can run a backtest in the app:

```powershell
.\run.ps1
```

This starts the Vite frontend + data server and opens the dashboard in your browser. Run backtests from the **Run** tab -- pick a trader, set sessions, and click Simulate. Results are saved to `backtests/` and appear in the Run dropdown.

#### Manual launch (two terminals)

```bash
# Terminal 1: frontend
cd visualizer && npm run dev

# Terminal 2: backtester
prosperity4mcbt a.py --quick --vis --out tmp/results/dashboard.json
```

Dashboard runs at `http://localhost:5555/`. The `--vis` flag starts the data server on port 8001 and opens the browser.

---

## Data

Prosperity 4 market data lives under `data/prosperity4/round<N>/` (semicolon-delimited CSVs). Prosperity 3 historical data is in `data/prosperity3/` for reference.

```
data/
├── prosperity4/round0/            # P4 tutorial round (EMERALDS, TOMATOES)
│   ├── prices_round_0_day_-1.csv  # Order book snapshots
│   ├── prices_round_0_day_-2.csv
│   ├── trades_round_0_day_-1.csv  # Market trades
│   └── trades_round_0_day_-2.csv
├── prosperity4/round1/            # P4 round 1 (ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT)
│   └── prices_round_1_day_{-2,-1,0}.csv + trades_round_1_day_{-2,-1,0}.csv
├── prosperity4/round2/            # placeholder — CSVs drop here when IMC publishes
└── prosperity3/round1-8/          # P3 historical data (reference only)
```

Active-round traders live in `traders/round<N>/`. Both CLIs auto-resolve bare filenames to the active round's trader.

| File                              | Purpose                                                  |
| --------------------------------- | -------------------------------------------------------- |
| `traders/round2/a.py`             | Active R2 submission (seeded from R1 final)              |
| `traders/round1/final_obi_v4.py`  | Best R1 submission (OSMIUM MM + PEPPER long-bias)        |
| `traders/round0/a.py` … `d.py`    | Tutorial-round strategy variants (archived)              |
| `traders/trader_hold1.py`         | Buy 1 unit, hold forever — used to extract server FV     |

---

## 1. Monte Carlo (`prosperity4mcbt`) -- Primary

Rust-backed Monte Carlo simulator. Generates hundreds/thousands of synthetic market sessions using calibrated bot models, runs your strategy against each, and produces distributional PnL statistics.

```bash
# Quick (100 sessions, ~6s) -- good for iteration
prosperity4mcbt traders/round2/a.py --quick --out tmp/results/dashboard.json

# Heavy (1000 sessions, ~55s) -- final eval before submission
prosperity4mcbt traders/round2/a.py --heavy --out tmp/results/dashboard.json

# With dashboard auto-open
prosperity4mcbt traders/round2/a.py --quick --vis --out tmp/results/dashboard.json
```

### Advanced options

```bash
prosperity4mcbt traders/round2/a.py --quick --seed 42 --out tmp/results/dashboard.json
prosperity4mcbt traders/round2/a.py --quick --fv-mode simulate --out tmp/results/dashboard.json
prosperity4mcbt traders/round2/a.py --quick --trade-mode simulate --out tmp/results/dashboard.json
prosperity4mcbt traders/round2/a.py --sessions 3000 --sample-sessions 150 --out tmp/results/dashboard.json
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

### Regenerating the MC baseline for Round 2

The previous strategy-comparison table was R1-specific and has been removed. When R2 data arrives, re-baseline with:

```bash
prosperity4mcbt traders/round2/a.py --heavy --out tmp/results/r2_baseline.json
```

Record the mean / std / P5–P95 in your PR description to track regressions as you iterate.

---

## 2. CSV Replay (`prosperity3bt`)

Deterministic replay against a historical order book from prior rounds. The CLI takes a round number and replays all days for that round from `data/prosperity4/round<N>/`.

```bash
prosperity3bt traders/round2/a.py 1           # replay R1 data
prosperity3bt traders/round2/a.py 1 --print

# Fill analytics (maker vs taker breakdown)
py -3.13 scripts/bt_stats.py traders/round2/a.py 1
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making (26× in our testing on tutorial data). Use for relative A/B comparison only — Monte Carlo + portal submissions are the ground truth.

---

## When to use which

| Scenario            | Tool                      | Command                                                                  |
| ------------------- | ------------------------- | ------------------------------------------------------------------------ |
| Dev iteration       | `prosperity4mcbt --quick` | `prosperity4mcbt traders/round2/a.py --quick --vis --out tmp/r/d.json`   |
| Pre-submission eval | `prosperity4mcbt --heavy` | `prosperity4mcbt traders/round2/a.py --heavy --out tmp/r/d.json`         |
| Quick sanity check  | `prosperity3bt`           | `prosperity3bt traders/round2/a.py 1`                                     |
| Fill breakdown      | `bt_stats.py`             | `py -3.13 scripts/bt_stats.py traders/round2/a.py 1`                      |
| Ground truth        | Portal                    | Submit on prosperity.imc.com                                             |

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

When new round data arrives (e.g. Round 2):

1. Submit `traders/trader_hold1.py` (buy 1 unit, hold forever) on each new product to extract server fair value from PnL
2. Run `calibration/round1/scripts/extract_fv_and_book.py` on the submission log to get the FV + book JSON
3. Copy `calibration/round1/scripts/analyze_*` and `calibrate_*` into `calibration/round2/scripts/` as templates and adapt them
4. Validate the derived bot rules with a `validate_*.py` script — target >95% exact match before trusting the sim
5. Update the Rust simulator parameters in `rust_simulator/src/main.rs` with the new products + bot rules
6. Extend `traders/round2/a.py` with the new product handlers (keep R1 handlers intact — prior products remain tradeable)

Round 1 already went through this pipeline — see `calibration/round1_calibration.md` for the output format to aim for.
