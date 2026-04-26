# Backtesting Guide

## Quick Start

```bash
# One-time setup
pip install -e .

# Install Rust (needed for Monte Carlo)
# Download from https://rustup.rs

# Run Monte Carlo backtest with dashboard (points at the active round's trader)
prosperity4mcbt traders/round4/submission.py --quick --vis
```

Both CLIs auto-resolve bare filenames — e.g. `submission.py` → `traders/round4/submission.py` (active round). Pass a full path like `traders/round1/submission.py` to backtest a historical submission.

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

This starts the Vite frontend + data server and opens the dashboard in your browser. Run backtests from the **Run** tab -- pick a trader, set sessions, and click Simulate. Results are saved to `tmp/backtests/` and appear in the Run dropdown.

**All backtest artifacts live under `tmp/` (gitignored).** CLI runs default to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json` (MC) or `tmp/backtests/<timestamp>.log` (CSV replay). Always write custom `--out` paths inside `tmp/` so the repo stays clean.

#### Manual launch (two terminals)

```bash
# Terminal 1: frontend
cd visualizer && npm run dev

# Terminal 2: backtester
prosperity4mcbt a.py --quick --vis
```

Dashboard runs at `http://localhost:5555/`. The `--vis` flag starts the data server on port 8001 and opens the browser. Backtest output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`.

---

## Data

Prosperity 4 market data lives under `data/prosperity4/round<N>/` (semicolon-delimited CSVs). Prosperity 3 historical data is in `data/prosperity3/` for reference.

```
data/
├── prosperity4/round0/            # P4 tutorial round (EMERALDS, TOMATOES)
├── prosperity4/round1/            # P4 round 1 (ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT)
├── prosperity4/round2/            # P4 round 2 (same products + MAF auction)
├── prosperity4/round3/            # P4 round 3 (HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_*)
├── prosperity4/round4/            # P4 round 4 (same as R3 + buyer/seller fields populated)
└── prosperity3/round1-8/          # P3 historical data (reference only)
```

Active-round traders live in `traders/round<N>/`. Both CLIs auto-resolve bare filenames to the active round's trader.

| File                           | Purpose                                                                  |
| ------------------------------ | ------------------------------------------------------------------------ |
| `traders/round4/submission.py` | ACTIVE submission (seeded from R3 stratton)                              |
| `traders/round3/submission.py` | R3 shipped (portal sub 485183, "stratton" — search-2 OOS winner #233)    |
| `traders/round2/submission.py` | R2 shipped (portal sub 360419)                                           |
| `traders/round1/submission.py` | R1 shipped (portal sub 269599, OSMIUM MM + PEPPER long)                  |
| `traders/trader_hold1.py`      | Buy 1 unit, hold forever — used to extract server FV                     |

---

## 1. Monte Carlo (`prosperity4mcbt`) -- Primary

Rust-backed Monte Carlo simulator. Generates hundreds/thousands of synthetic market sessions using calibrated bot models, runs your strategy against each, and produces distributional PnL statistics.

```bash
# Quick (100 sessions, ~6s) -- good for iteration
prosperity4mcbt traders/round4/submission.py --quick

# Heavy (1000 sessions, ~55s) -- final eval before submission
prosperity4mcbt traders/round4/submission.py --heavy

# With dashboard auto-open
prosperity4mcbt traders/round4/submission.py --quick --vis
```

Output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`. Pass `--out path.json` only when you need a specific path — and keep it under `tmp/`.

### Advanced options

```bash
prosperity4mcbt traders/round4/submission.py --quick --seed 42
prosperity4mcbt traders/round4/submission.py --quick --fv-mode simulate
prosperity4mcbt traders/round4/submission.py --quick --trade-mode simulate
prosperity4mcbt traders/round4/submission.py --sessions 3000 --sample-sessions 150
```

---

## Running a backtest for the active round (R4)

R4 kicked off 2026-04-26 ("The More The Merrier"). Same products as R3 — OSMIUM and PEPPER stopped being tradeable at R3, so no PEPPER `--start-fv` flags are needed. The new R4 wrinkle is that `Trade.buyer` and `Trade.seller` are now populated with `Mark <NN>` IDs instead of `None` (7 distinct Marks: 01, 14, 22, 38, 49, 55, 67).

Note: P4 does **not** carry prior-round products forward. At each new round only that round's listed products appear on the portal. R4 trades exactly the R3 book — `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and the 10 `VEV_<strike>` vouchers. See per-asset Rust modules under `rust_simulator/src/assets/` and per-asset calibration in `calibration/<asset>/`.

R4 days 1 and 2 reproduce R3 days 1 and 2 exactly (same FV path, same trades) — only the buyer/seller fields differ. Day 3 is fresh data. So existing R3 calibration of FV processes and bot models still applies; the new analysis surface is bot/Mark identification.

### Portal tick counts (important!)

- **Portal UI backtest** (the "Run" button in the portal): **1,000 ticks** = 0.1 real day
- **Portal final-round eval** (actual scoring at round close): **10,000 ticks** = 1 real day
- **MC default `--ticks-per-day` is now 10,000** (matches final eval, not the portal UI backtest)

Use `--ticks-per-day 1000` when you want MC numbers comparable to the portal UI backtest output.

### Standard dev iteration

```bash
# Quick iteration (100 sessions, 10,000 ticks each)
prosperity4mcbt traders/round4/submission.py --quick

# Pre-submission eval (1000 sessions, 10,000 ticks each — matches final-eval scale)
prosperity4mcbt traders/round4/submission.py --heavy

# Match portal UI backtest (1,000 ticks) for apples-to-apples with portal submissions
prosperity4mcbt traders/round4/submission.py --heavy --ticks-per-day 1000
```

### MAF analysis (R2-only — kept here for reference)

The MAF auction was R2-specific and is not active in R3 or R4. The `--quote-fraction` and `--maf-bid` flags still work (they let you stress-test quote-volume sensitivity in any round), but they don't affect R3/R4 scoring.

### CSV replay against R4 historical data

```bash
prosperity3bt traders/round4/submission.py 4                    # replay against R4 days 1–3
py -3.13 scripts/bt_stats.py traders/round4/submission.py 4     # fill breakdown
```

### Flag reference

The simulator splits flags into **global** and **per-asset**. Per-asset flags are prefixed by the asset's lowercased-kebab symbol (e.g. `--intarian-pepper-root-start-fv`). Passing a flag for an asset the trader doesn't declare is a hard error.

**Global flags**

| Flag                                  | Purpose                                                                                                                             |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `--sessions N`                        | Number of Monte Carlo sessions (`--quick` = 100, `--heavy` = 1000).                                                                 |
| `--ticks-per-day N`                   | Default **10,000** (portal final-round eval scale). Pass `1000` for portal-UI-backtest scale.                                       |
| `--seed N`                            | Base RNG seed.                                                                                                                      |
| `--quote-fraction f`                  | R2 quote overlay. `0.8` = loser (each level dropped w.p. 0.2). `1.25` = MAF winner (level volumes × 1.25). Default `1.0` untouched. |
| `--maf-bid N`                         | Deducts N XIRECs from each session's total PnL. Use when modelling MAF-winner net PnL.                                              |
| `--fv-mode simulate\|replay`          | Replay uses observed FV from historical CSVs.                                                                                       |
| `--trade-mode simulate\|replay-times` | Replay-times uses observed taker-arrival times from historical CSVs.                                                                |

**Per-asset flags** — each asset exposes its own flags under `--<asset-kebab>-<flag>`:

| Asset                  | Flag                                    | Purpose                                                                                                |
| ---------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `INTARIAN_PEPPER_ROOT` | `--intarian-pepper-root-start-fv N`     | Starting FV for day 0 of the sim. R2 day 1 = **13000**.                                                |
| `INTARIAN_PEPPER_ROOT` | `--intarian-pepper-root-replay-fv PATH` | Replay observed PEPPER FV path. Accepts a flat `[f64]` JSON array or an object with a `"pepper"` key.  |
| `ASH_COATED_OSMIUM`    | `--ash-coated-osmium-replay-fv PATH`    | Replay observed OSMIUM FV path. Accepts a flat `[f64]` JSON array or an object with an `"osmium"` key. |

The legacy alias `--ipr-start-fv` is translated to `--intarian-pepper-root-start-fv` by the Python wrapper for back-compat.

### Sim calibration status

The sim is calibrated against portal reality on matched FV paths (within 0.8% total, 0.6σ on OSMIUM, 2.2σ on PEPPER). See `CLAUDE.md` "Sim calibration" section for the fix history — the last critical bug was matching-engine ordering (base takers now run BEFORE the strategy, per P4 spec). Absolute MC numbers are trustworthy, not just relative deltas.

To validate on a fresh portal backtest, drop the `activitiesLog` into the extractor and regenerate `calibration/intarian_pepper_root/data/r2_day1_fv.json`, then:

```bash
prosperity4mcbt traders/round4/submission.py --sessions 200 --ticks-per-day 1000 \
  --intarian-pepper-root-replay-fv calibration/intarian_pepper_root/data/r2_day1_fv.json \
  --ash-coated-osmium-replay-fv   calibration/intarian_pepper_root/data/r2_day1_fv.json
```

### R2 MAF uplift sensitivity (historical, recorded against the R2 trader on R2 calibration)

Run against the R2 submission with `--intarian-pepper-root-start-fv 13000`:

| `--quote-fraction`          | Mean PnL per final eval | Std   |
| --------------------------- | ----------------------- | ----- |
| 0.8 (R2 loser)              | **98,642**              | 1,042 |
| 1.25 (MAF winner)           | **100,116**             | 1,096 |
| **Uplift (winner − loser)** | **+1,474**              |       |

**MAF bid guidance**: uplift is ~1,474 XIRECs per final eval — that's the absolute upper-bound bid. You only need to beat the median of all teams' bids, not buy the full uplift. Shade well below: **300-500** is a defensible opening, `MAF_BID = 0` is a fine do-nothing default.

Sanity vs R1 portal final (99,546): MC loser mean 98,642 — within 1% ✓.

---

### Output bundle

```
tmp/backtests/<timestamp>_monte_carlo/
├── dashboard.json       # Load in visualizer
├── session_summary.csv  # Per-session PnL stats
├── run_summary.csv      # Aggregate stats
├── sample_paths/        # Detailed traces for sampled sessions
└── sessions/            # Full session logs
```

### Tracking a baseline across iterations

Before changing the trader, grab a reference MC run so you can detect regressions:

```bash
prosperity4mcbt traders/round4/submission.py --heavy
```

Post-calibration, MC absolute numbers are trustworthy within ~1% on matched FV paths — not just relative deltas. Record mean / std / P5–P95 from the `run_summary.csv` in the output dir and diff after each change. The R2 MAF-uplift table above is the current reference for what "good" looks like on OSMIUM + PEPPER.

---

## 2. CSV Replay (`prosperity3bt`)

Deterministic replay against a historical order book from prior rounds. The CLI takes a round number and replays all days for that round from `data/prosperity4/round<N>/`.

```bash
prosperity3bt traders/round4/submission.py 4           # replay R4 data
prosperity3bt traders/round4/submission.py 4 --print

# Fill analytics (maker vs taker breakdown)
py -3.13 scripts/bt_stats.py traders/round4/submission.py 4
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making (26× in our testing on tutorial data). Use for relative A/B comparison only — Monte Carlo + portal submissions are the ground truth.

---

## When to use which

| Scenario            | Tool                      | Command                                              |
| ------------------- | ------------------------- | ---------------------------------------------------- |
| Dev iteration       | `prosperity4mcbt --quick` | `prosperity4mcbt traders/round4/submission.py --quick --vis`  |
| Pre-submission eval | `prosperity4mcbt --heavy` | `prosperity4mcbt traders/round4/submission.py --heavy`        |
| Tune params         | `prosperity4opt`          | `prosperity4opt studies/<name>.yaml --fresh`         |
| Quick sanity check  | `prosperity3bt`           | `prosperity3bt traders/round4/submission.py 4`                |
| Fill breakdown      | `bt_stats.py`             | `py -3.13 scripts/bt_stats.py traders/round4/submission.py 4` |
| Ground truth        | Portal                    | Submit on prosperity.imc.com                         |

For parameter tuning, see [OPTIMIZER.md](OPTIMIZER.md) — Bayesian optimization on top of the MC sim with train/val/test seed splits, Deflated Sharpe Ratio, PBO, and fANOVA importance.

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

### Recalibrating + adding a new asset to the sim

When a new product drops, the work splits cleanly between calibration (statistical) and simulator integration (Rust).

**Calibration pipeline:**

1. Submit `traders/trader_hold1.py` — it's asset-agnostic and will hold 1 unit of every product in the book, letting you recover server FV from PnL.
2. `py -3.13 calibration/extract_fv_and_book.py <submission_id> <PRODUCT>` → writes `calibration/<asset_lower>/data/fv_and_book.json`.
3. Clone `calibration/ash_coated_osmium/scripts/calibrate.py` (random-walk asset) or `calibration/intarian_pepper_root/scripts/calibrate.py` (deterministic-drift asset) into the new asset dir, adapt the formula search.
4. Add a `(NAME, path)` entry to `calibration/validate.py`'s `PRODUCTS` list and run it — target >95% exact match before trusting the sim.

**Simulator integration (one file per asset):**

5. Create `rust_simulator/src/assets/<asset_lower>.rs`. Copy the closer of the two existing files as a template:
   - `ash_coated_osmium.rs` → random-walk FV, fixed integer bot offsets
   - `intarian_pepper_root.rs` → deterministic drift, proportional bot offsets
     Each file declares:
   - `const SYMBOL: &str = "<YOUR_SYMBOL>";`
   - Trade probabilities (`BASE_TRADE_PROB`, `SECOND_TRADE_PROB`, `ELASTIC_TRADE_PROB`, `BUY_PROB`)
   - Position limit
   - Bot formulas via `make_book()`
   - FV process via `simulate_fv()`
   - CLI flags via `flag_specs()` + consumed in `build()`
6. Register the asset in `rust_simulator/src/assets/mod.rs` by adding an entry to the `REGISTRY` constant.
7. `cargo build --release` (from `rust_simulator/`).
8. Extend `traders/round<N>/submission.py` with handlers for the new product, and declare the symbol near the top: `NEW = "YOUR_SYMBOL"`. The simulator scans the first 40 lines of the trader for `NAME = "SYMBOL"` patterns and activates the matching assets from the registry automatically — no other wiring needed.

Note: P4 does **not** carry prior-round products forward (R3 dropped OSMIUM/PEPPER, R4 keeps the R3 book). Trim handlers for products no longer listed when porting between rounds, otherwise the simulator will reject unknown per-asset flags.

See `calibration/ash_coated_osmium/calibration.md` and `calibration/intarian_pepper_root/calibration.md` for the output format to aim for, and `rust_simulator/src/asset.rs` for the `AssetSim` trait contract.
