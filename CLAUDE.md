# IMC Prosperity 4 - Algorithmic Trading Competition

## Project Overview

This is our workspace for **IMC Prosperity 4** (2026), a multi-round algorithmic trading competition where we write Python trading bots that execute on a simulated exchange against bot counterparties. Goal: maximize profit (PnL) in XIRECs currency.

- **Competition**: April 14-30, 2026 (5 rounds)
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki
- **Prize Pool**: $50,000 USD

## Current Round

**Round 5** (active from 2026-04-28, "The Final Stretch"). R1, R2, R3, R4 all passed. R5 is the final round and **wipes the slate clean** — all R3/R4 products (HYDROGEL/VELVETFRUIT/VEV_*) are no longer tradeable. **50 brand-new products** are introduced, evenly distributed across 10 categories of 5 (Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV-Visors, Translators, Panels, Oxygen Shakes, Snackpacks). **Position limit is 10 for every product.** Some categories embed strong patterns waiting to be discovered; others will need vanilla MM. The **active submission file** for R5 is `traders/round5/submission.py` (still a no-op scaffold — sim calibration is done; strategy work is the next step). Manual challenge ("Extra! Extra!") happens on the Ignith exchange via Ashflow Alpha news — out of scope for the algo file.

## Directory Structure

```
IMC_trading_hack/
├── traders/                           # Per-round trader code (submission.py + experiments)
│   ├── round5/submission.py           #   ACTIVE — submit this for R5 (currently no-op scaffold)
│   ├── round{1,2,3,4}/                #   Frozen prior-round work; products don't carry into R5
│   ├── datamodel.py                   #   Official Prosperity 4 data model
│   └── trader_hold1.py                #   Hold-1-unit strategy for FV extraction
├── Rubenstrats/                       # Ruben's per-round experiments (frozen reference)
├── results/round{1,2,3,4,5}/          # Post-round-close submission snapshots
├── analysis/                          # Market-data analysis scripts (by round)
│   └── round5/                        #   R5 calibration + per-category EDA (50 new products)
├── data/                              # Market data
│   ├── prosperity4/round{0..5}/       #   P4 historical CSVs (R5 ships days 2/3/4)
│   └── prosperity3/round1-8/          #   P3 historical data (reference)
├── backtester/                        # Backtester package (install with pip install -e .)
│   ├── prosperity4mcbt/               #   Monte Carlo CLI (primary backtester)
│   └── prosperity3bt/                 #   Historical CSV replay CLI
├── rust_simulator/                    # Rust Monte Carlo simulation engine
│   ├── src/asset.rs                   #   Per-asset trait (book + bot params)
│   ├── src/assets/r5_asset.rs         #   R5: single generic impl, 50 instances built from scenario_params.json
│   ├── src/scenario.rs                #   Scenario trait + DayData/Pulse types (R5 2-layer architecture)
│   ├── src/scenarios/r5.rs            #   R5Scenario: joint OU FVs + 3 shared pulse processes
│   └── src/bin/r5_smoke.rs            #   Validation binary (basket sum / K_day / per-asset moments)
├── wasm_compute/                      # Rust/WASM kernels for the Workshop tab (microstructure analytics)
├── visualizer/                        # Local dashboard frontend (Vite/React) — Workshop + Optimize tabs
├── optimizer/                         # Study-based parameter optimization on top of MC
│   ├── space.py / runner.py / objective.py / samplers.py / validators.py / study.py / cli.py
│   └── (guide lives at repo root as OPTIMIZER.md)
├── studies/                           # Declarative YAML studies (one per tuning campaign)
├── calibration/                       # Bot reverse-engineering
│   ├── ANALYSIS_PHILOSOPHY.md         #   Methodology (condition on everything, stat tests)
│   ├── README.md / validate.py / extract_fv_and_book.py / audit_portal_log.py
│   ├── <r1-r4 per-asset dirs>/        #   Frozen reference; not exercised in R5 runs
│   └── r5/scenario_params.json        #   R5 Rust-ready calibration bundle (50 assets + K_day + pulses)
├── manual/                            # Manual trading challenges (round1..round5)
├── tmp/                               # Backtest + optimizer artifacts
│   ├── backtests/                     #   Default output dir for prosperity4mcbt / prosperity3bt runs (gitignored)
│   ├── optimizer/                     #   Per-study SQLite + parquet + validators.json (prosperity4opt)
│   └── portal_<id>/                   #   Extracted portal-submission .log/.json/.py snapshots
├── scripts/                           # Helper utilities
│   ├── python_strategy_worker.py      #   Rust sim ↔ Python bridge
│   ├── bt_stats.py                    #   Fill analytics wrapper
│   └── csv_to_parquet.py              #   Convert raw CSVs to parquet for the Workshop
├── CLAUDE.md                          # This file - project context
├── BACKTEST.md                        # Backtesting & calibration guide
├── DATA_WORKSHOP.md                   # Browser-based data analysis workshop guide
├── OPTIMIZER.md                       # Parameter-optimization framework guide
└── PROSPERITY_4_WIKI_COMPLETE.md      # Full game reference
```

## Architecture & Constraints

### Submission Format

- **Single Python file** (`traders/round5/submission.py`) containing a `Trader` class with a `run()` method
- No external file access, no network, no pip installs at runtime
- Available: standard library + numpy + jsonpickle
- Memory limit: ~100 MB (AWS Lambda)
- State persists ONLY via `traderData` string (JSON serialized)
- All orders expire each timestep (no GTC orders)

### Run Method Signature

```python
def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
    return result, conversions, traderData
```

- `result`: Dict[Symbol, List[Order]] - orders per product
- `conversions`: int - cross-market conversions (0 unless applicable)
- `traderData`: str - serialized state for next iteration

### Position Limit CRITICAL Rule

If the sum of ALL your outstanding orders for a product could push your position past the limit (assuming worst-case all fill), **ALL orders for that product are cancelled**. Always calculate worst-case before submitting.

### Order Matching Sequence (per timestep)

1. Deep-liquidity market makers post orders
2. Bot takers act
3. YOUR algorithm runs (receives TradingState, returns orders)
4. Your orders matched against order book
5. Remaining bots may trade on your quotes
6. All unfilled orders expire

## Round 5 — ACTIVE (2026-04-28 →, "The Final Stretch")

**Total product reset.** R3/R4 products are gone from the portal. R5 ships **50 brand-new products** across 10 categories of 5, with a **uniform position limit of 10** for every product. Some categories embed strong patterns ("Cherry Picking Winners" — find the inefficient ones); others will need vanilla MM. Sim calibration is done (see "R5 simulator: 2-layer architecture" below); `traders/round5/submission.py` is still a no-op scaffold that just declares the symbol universe — strategy work is the next step.

| Category | 5 Products | Position Limit (each) |
| --- | --- | --- |
| **Galaxy Sounds Recorders** | `GALAXY_SOUNDS_DARK_MATTER`, `GALAXY_SOUNDS_BLACK_HOLES`, `GALAXY_SOUNDS_PLANETARY_RINGS`, `GALAXY_SOUNDS_SOLAR_WINDS`, `GALAXY_SOUNDS_SOLAR_FLAMES` | **10** |
| **Vertical Sleeping Pods** | `SLEEP_POD_SUEDE`, `SLEEP_POD_LAMB_WOOL`, `SLEEP_POD_POLYESTER`, `SLEEP_POD_NYLON`, `SLEEP_POD_COTTON` | **10** |
| **Organic Microchips** | `MICROCHIP_CIRCLE`, `MICROCHIP_OVAL`, `MICROCHIP_SQUARE`, `MICROCHIP_RECTANGLE`, `MICROCHIP_TRIANGLE` | **10** |
| **Purification Pebbles** | `PEBBLES_XS`, `PEBBLES_S`, `PEBBLES_M`, `PEBBLES_L`, `PEBBLES_XL` | **10** |
| **Domestic Robots** | `ROBOT_VACUUMING`, `ROBOT_MOPPING`, `ROBOT_DISHES`, `ROBOT_LAUNDRY`, `ROBOT_IRONING` | **10** |
| **UV-Visors** | `UV_VISOR_YELLOW`, `UV_VISOR_AMBER`, `UV_VISOR_ORANGE`, `UV_VISOR_RED`, `UV_VISOR_MAGENTA` | **10** |
| **Instant Translators** | `TRANSLATOR_SPACE_GRAY`, `TRANSLATOR_ASTRO_BLACK`, `TRANSLATOR_ECLIPSE_CHARCOAL`, `TRANSLATOR_GRAPHITE_MIST`, `TRANSLATOR_VOID_BLUE` | **10** |
| **Construction Panels** | `PANEL_1X2`, `PANEL_2X2`, `PANEL_1X4`, `PANEL_2X4`, `PANEL_4X4` | **10** |
| **Liquid Breath Oxygen Shakes** | `OXYGEN_SHAKE_MORNING_BREATH`, `OXYGEN_SHAKE_EVENING_BREATH`, `OXYGEN_SHAKE_MINT`, `OXYGEN_SHAKE_CHOCOLATE`, `OXYGEN_SHAKE_GARLIC` | **10** |
| **Protein Snack Packs** | `SNACKPACK_CHOCOLATE`, `SNACKPACK_VANILLA`, `SNACKPACK_PISTACHIO`, `SNACKPACK_STRAWBERRY`, `SNACKPACK_RASPBERRY` | **10** |

**Position-limit implication.** Limit = 10 is *much* tighter than R1–R4 (80–300). Worst-case open-order math (the hard rule that ALL orders cancel if the worst-case fill could breach the limit) is now extremely unforgiving — a single 5-lot bid plus a 6-lot ask can already exceed limits and cancel everything. Quote sizes will be small; turnover and tick-by-tick rebalancing matter more than per-trade size. Strategies that relied on stacking 30+ unit passive layers from prior rounds **do not transfer** — every per-asset config has to be re-thought.

**Manual challenge: "Extra! Extra! Read all about it!"** — out of scope for `traders/round5/submission.py`. One-day Ignith exchange portfolio sized via Ashflow Alpha news, with a quadratic per-product fee `fee = (volume/100)² × budget` against a 1,000,000-XIRECs budget. See `manual/round5/` (when set up) for notes.

**Data shipped:** `data/prosperity4/round5/{prices,trades}_round_5_day_{2,3,4}.csv` — three days of pre-round-close historical CSVs. Trades have buyer/seller fields populated.

**Calibration approach (decided 2026-04-28).** R5 does **not** use the per-asset `calibration/<asset>/` pattern from R1–R4. Instead, all 50 products share a single bundle at `calibration/r5/scenario_params.json`, generated from historical CSVs by `analysis/round5/rigorous_calibration.py`, and consumed by the `Scenario` layer in the Rust simulator (see "R5 simulator: 2-layer architecture" below). Per-product fits live as entries inside that one JSON; per-category constraints (Pebble basket, Snackpack pair/triplet) are first-class invariants in the scenario, not asset-level concerns.

### Data Format (CSV, semicolon-delimited)

- **prices**: day;timestamp;product;bid_price_1-3;bid_volume_1-3;ask_price_1-3;ask_volume_1-3;mid_price;profit_and_loss
- **trades**: timestamp;buyer;seller;symbol;currency;price;quantity (buyer/seller populated from R4 onward)
- Currency: XIRECs
- Timestamps: increment by 100 (0, 100, 200, ...)
- 10,000 timesteps per day in the final eval (1,000 in portal-UI backtests)

## Strategy Framework

### 1. Alpha Engine (Fair Value Estimation)

- Stationary: fixed value
- Drifting: EMA of mid-price, VWAP, or weighted regression
- Volatile: Bollinger bands, z-score mean-reversion

### 2. Risk Engine

- Soft position limits (e.g., start tightening at 60% of hard limit)
- Skew quotes based on inventory (bid tighter when long, ask tighter when short)
- Max drawdown checks via traderData

### 3. Inventory Management

- Track position in traderData
- Reduce spread asymmetrically to shed inventory
- Never let worst-case fills breach position limits

### 4. Execution

- Aggressive: take mispriced orders from the book immediately
- Passive: place limit orders at fair_value +/- spread
- Hybrid: take extreme mispricings, quote passively otherwise

## Python Version

Use **Python 3.13** via `py -3.13`. For console output with unicode, set `PYTHONIOENCODING=utf-8`.

## Backtesting

See [BACKTEST.md](BACKTEST.md) for the full guide including calibration methodology.

### Monte Carlo Backtester (PRIMARY -- use this)

```bash
# Install (one-time): pip install -e .
prosperity4mcbt a.py --quick              # dev iteration (~6s)
prosperity4mcbt a.py --heavy              # pre-submission (~55s)
prosperity4mcbt a.py --quick --vis        # with dashboard
```

Output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json` — only pass `--out` when you need a specific path. Rust-backed Monte Carlo using calibrated bot models. Produces distributional PnL stats (mean, std, percentiles) across hundreds/thousands of synthetic sessions.

#### Portal tick counts

- Portal UI backtest: **1,000 ticks** per day (what the "Run" button shows you)
- Portal final-round eval: **10,000 ticks** per day (actual scoring at round close)
- MC default `--ticks-per-day` is **10,000** (matches final eval). Pass `--ticks-per-day 1000` for portal-UI-backtest comparisons.

#### Flag scheme — global vs per-asset

- **Global** (`--sessions`, `--ticks-per-day`, `--seed`, `--fv-mode`, `--trade-mode`, `--quote-fraction`, `--strategy`, `--output`, …) apply to the whole run.
- **Per-asset** flags are prefixed by the asset's lowercased-kebab symbol: `--<asset-kebab>-<flag>`. Passing a flag for an asset the trader doesn't declare is a hard error.

```bash
# R5 dev iteration. The MC sim auto-detects R5 from symbol declarations
# in the trader file and routes through R5Scenario (joint FVs respecting
# Pebble basket + Snackpack constraints + 3 shared pulse processes).
# Days = [2,3,4] from data/prosperity4/round5/.
prosperity4mcbt traders/round5/submission.py --quick
prosperity4mcbt traders/round5/submission.py --heavy

# Match portal-UI backtest (1,000 ticks) for apples-to-apples
prosperity4mcbt traders/round5/submission.py --heavy --ticks-per-day 1000

# Validate the scenario directly (constraint + pulse moments) without a trader
cd rust_simulator && \
  R5_SCENARIO_PARAMS=$(pwd)/../calibration/r5/scenario_params.json \
  cargo run --release --bin r5_smoke -- 50

# Re-run calibration if the historical CSVs change or you tweak the model
py -3.13 analysis/round5/rigorous_calibration.py
py -3.13 analysis/round5/r5_python_sim.py    # Python end-to-end sanity vs portal sub 545243
```

See [BACKTEST.md](BACKTEST.md) for the full flag reference.

### CSV Replay (sanity checks)

```bash
prosperity3bt traders/round5/submission.py 5                    # historical replay on R5 data
py -3.13 scripts/bt_stats.py traders/round5/submission.py 5     # fill analytics
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making. Use for relative A/B comparison only.

### R5 simulator: 2-layer architecture (calibrated 2026-04-28)

R3/R4 generated **1 FV path + 1 Poisson trade process per asset, independent**. R5's market structure breaks that:

- 50 FVs are **not** independent — `PEBBLES_XS+S+M+L+XL = 50,000` exactly every tick; `SNACKPACK_CHOCOLATE + SNACKPACK_VANILLA ≈ K_day` (a slow OU-process pair sum that drifts ~50–100/day); **SNACKPACK_PISTACHIO/STRAWBERRY/RASPBERRY** share a 1-factor model `F_i = OU_i(σ_idio) + ℓ_i · K_triplet` with stable loadings ~[−0.40, −0.66, +0.64] (~94% of triplet variance) producing the historical pairwise corr +0.91 / −0.92 / −0.83 — calibrated 2026-04-28 by `analysis/round5/snackpack_triplet_factor.py` and auto-invoked from `rigorous_calibration.py`.
- Trades fire in **3 shared Poisson pulse processes**, not 50 independent Poissons:
  - **V (Vanilla)**: 40 products, λ ≈ 0.0244/tick (~244 pulses/10K-tick day), qty ∈ {1,2,3,4}
  - **P (Pebbles)**: 5 pebbles, λ ≈ 0.0215/tick, qty ∈ {2,3,4,5}
  - **M (Microchips)**: 5 microchips, λ ≈ 0.0190/tick, qty ∈ {1,2,3}
- Each pulse fires its full member group on the **same** side (buy/sell, p_buy ≈ 0.49) at the **same** quantity in the same tick — basket-arb signal lives in the pulse co-firing.
- All FVs are bounded (OU-like, daily-resampled mean), not free random walks.

**Layer 1 — Joint state generator (`Scenario` trait).** `rust_simulator/src/scenario.rs` defines the trait; `rust_simulator/src/scenarios/r5.rs` implements `R5Scenario`. Per session/day it produces:
- `fv_paths: HashMap<(symbol, day) → Vec<f64>>` — joint OU walks with derived constraints applied per tick (Pebble basket sum is exact, K_day pair is exact, triplet residual handled).
- `pulses_per_day: HashMap<day → Vec<Pulse>>` — pre-sampled list of `(tick, members, direction, quantity)` records from the 3 Poisson processes.

**Layer 2 — Per-asset book + execution (existing `AssetSim`).** Each tick still calls `asset.make_book(fv[asset][tick], rng)` for symmetric L1+L2 books, but FV is read from the scenario instead of being simulated per-asset. Pulses are routed through `apply_pulse_against_book` — direction = sell takes qty units at `bid_price_1` (sweeping into L2 if shallow), direction = buy takes at `ask_price_1`. Strategy quotes still get priority via `LevelOwner::Strategy` vs `LevelOwner::Bot`.

**Auto-detection.** `main.rs::r5_active(config)` checks if any active asset belongs to the R5 universe (via `assets::is_r5_symbol`); if so, the run uses days `[2,3,4]` (matching R5 historical CSVs) and routes through `R5Scenario`.

**Generic R5 asset.** `rust_simulator/src/assets/r5_asset.rs` is a single shared impl, parametrised by `(symbol, h, depth_l1, depth_l2, l2_lift)`. The 50 instances are built from `calibration/r5/scenario_params.json` at startup — no boilerplate per-asset Rust files. `simulate_fv` / `base_trade_prob` are stubs (the scenario owns those decisions).

**Calibration files.**
- `analysis/round5/calibration_r5.json` — raw per-asset OU/RW fits + book params + pulse rates + variance-ratio diagnostics + `snackpack_triplet` factor block, produced by `analysis/round5/rigorous_calibration.py`. The triplet calibration runs automatically at the end of `rigorous_calibration.py`.
- `analysis/round5/snackpack_triplet_factor.py` — fits the 1-factor model for {PIS, STRAW, RASP} (loadings via PCA on tick-diffs, K_triplet OU fit, σ_idio per asset) and patches `calibration/r5/scenario_params.json` in place. Idempotent. Pre-fix file is backed up to `scenario_params.json.bak` on first run only.
- `calibration/r5/scenario_params.json` — Rust-ready bundle loaded at runtime by `R5Scenario::load()`. Resolves via `R5_SCENARIO_PARAMS` env var, then via repo-root walk. Structure: `days`, `ticks_per_day`, `pebble_constant`, `pebble_free`/`pebble_derived`, `snackpack_choc`/`snackpack_vanilla`, `k_day` (OU θ/σ + per-day μ), **`snackpack_triplet`** (members + loadings + k_factor OU), `pulses` (V/P/M specs), `assets` (50 entries with model="OU"|"RW", θ, σ, daily_μ, h, depth_l1, depth_l2, l2_lift; the 3 triplet members carry `kind: "triplet_factor"` and have their σ replaced by `σ_idio`, with the original σ preserved as `sigma_total_pre_factor`), `day_starts`.

**How to run R5 calibration / backtest / validation.**

```bash
# 1) Re-run calibration from historical CSVs (writes analysis/round5/calibration_r5.json)
py -3.13 analysis/round5/rigorous_calibration.py

# 2) Validate the scenario in Python end-to-end (hold-1 against synthetic day 4, 1K ticks)
#    Targets portal sub 545243 = -2160 PnL on day-4 1K-tick backtest.
py -3.13 analysis/round5/r5_python_sim.py

# 3) Rust scenario smoke test (constraint + pulse moments vs historical)
cd rust_simulator
R5_SCENARIO_PARAMS=$(pwd)/../calibration/r5/scenario_params.json \
  cargo run --release --bin r5_smoke -- 50

# 4) Full R5 MC backtest against the active trader (auto-detects R5 from symbol declarations)
prosperity4mcbt traders/round5/submission.py --quick
prosperity4mcbt traders/round5/submission.py --heavy

# 5) CSV replay sanity (3 days of R5 historical data)
prosperity3bt traders/round5/submission.py 5
```

The Python prototype lives at `analysis/round5/r5_scenario_v2.py` and produced `analysis/round5/scenario_v2_validation.csv` (per-asset within-day std synthetic-vs-historical) before the Rust port. Keep it as a regression check whenever the calibration is regenerated.

### Output paths

All backtest artifacts — MC dashboards, replay logs, ad-hoc outputs — go under `tmp/`. `tmp/backtests/` is gitignored; `tmp/optimizer/` and `tmp/portal_<id>/` are tracked so the team can browse each other's runs. Default MC output is `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`; default CSV replay log is `tmp/backtests/<timestamp>.log`. Never write backtest output outside `tmp/`.

### Visualization

- Local dashboard: `./run.sh` (macOS/Linux) or `.\run.ps1` (Windows) — starts the Python data server, Vite frontend, and rebuilds WASM if stale. Dashboard at `http://localhost:5555/`.
- Tabs: **Results** (MC dashboard from `tmp/backtests/`), **Run** (kick off backtests from the browser), **Workshop** (market-microstructure analysis on raw CSV data — see [DATA_WORKSHOP.md](DATA_WORKSHOP.md)), **Calibration** (9-stage bot-calibration discovery pipeline), **Optimize** (parameter-optimization study browser), **Submissions** (portal submission log viewer).
- The Workshop needs `wasm-pack` (`cargo install wasm-pack`) — its Rust kernels live in `wasm_compute/` and rebuild automatically when the source changes.
- IMC Prosperity Visualizer: https://jmerle.github.io/imc-prosperity-visualizer/

## Parameter Optimization

See [OPTIMIZER.md](OPTIMIZER.md) for the full guide.

TL;DR: declare a study in `studies/<name>.yaml`, point it at a trader that follows the env-var override contract, run `prosperity4opt studies/<name>.yaml --fresh`, and browse results in the Optimize tab. Built on Optuna with honest out-of-sample retest, Deflated Sharpe Ratio multiple-testing correction, Probability of Backtest Overfitting (CSCV), cluster stability, and fANOVA param importance.

```bash
# Tune a trader.
prosperity4opt studies/<study_name>.yaml --fresh

# Outputs under tmp/optimizer/<study_name>/:
#   study.db           — Optuna SQLite (resumable)
#   results.parquet    — per-trial params + metrics
#   validators.json    — DSR / PBO / cluster / importance diagnostics
#   retest.json        — top-K fresh-seed OOS scores
#   top_trials.csv     — ranked summary
```

Trader contract (copy-paste snippet in `OPTIMIZER.md`): every tunable trader reads its params from a `PARAMS` dict merged with `os.environ["PROSPERITY_PARAMS"]`. Portal submission is unaffected — the env var is never set there, so defaults apply.

## Coding Conventions

- All trading logic in a single file (`traders/round5/submission.py`) — submission constraint
- Use `json.dumps()`/`json.loads()` for traderData serialization
- Keep strategies modular within the single file using helper methods
- Price is always `int`, quantity is `int` (positive = buy, negative = sell)
- sell_orders in OrderDepth have **negative** quantities
- Always log key state with `print()` for debugging (visible in activity logs)
- Test locally with backtester before every submission

## Common Pitfalls

- Forgetting sell_orders quantities are negative
- **Position limit bug**: When computing passive order sizes after taking, use STARTING position (from state.position), not the locally-tracked post-take position. The exchange checks all orders against the starting position. Using post-take position over-allocates the opposite side → ALL orders cancelled.
- Not accounting for worst-case position limit check (ALL orders, not individual) — extra dangerous in R5 where the limit is 10
- **EMA-based taking loses money on drifting assets**: EMA lag causes wrong-way trades (buys falling markets, sells rising). Use pure passive quoting instead.
- **CSV replay fills are unrealistic**: Don't trust absolute PnL from `prosperity3bt --match-trades all` for market-making. Use `prosperity4mcbt` Monte Carlo or the portal.
- Not persisting state properly in traderData (init called once, run called per tick)
- Placing orders that cross your own orders (unnecessary self-trade)
- Ignoring market_trades data (contains valuable signal about bot behavior)

## Reference Repos (Top Teams from Prior Years)

- 2nd Place P3: https://github.com/TimoDiehm/imc-prosperity-3
- 9th Place P3: https://github.com/CarterT27/imc-prosperity-3
- 7th Place P3: https://github.com/chrispyroberts/imc-prosperity-3
- 2nd Place P2: https://github.com/ericcccsliu/imc-prosperity-2
- Strategy Guide: https://github.com/MarkBrezina/Ctrl-Alt-DefeatTheMarket
