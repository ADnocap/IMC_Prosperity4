# IMC Prosperity 4 - Algorithmic Trading Competition

## Project Overview

This is our workspace for **IMC Prosperity 4** (2026), a multi-round algorithmic trading competition where we write Python trading bots that execute on a simulated exchange against bot counterparties. Goal: maximize profit (PnL) in XIRECs currency.

- **Competition**: April 14-30, 2026 (5 rounds)
- **Tutorial**: March 16 - April 13, 2026
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki
- **Prize Pool**: $50,000 USD

## Current Round

**Round 3** (active from 2026-04-21). R1 and R2 both passed. R3 introduces a derivatives book — `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` (spots, position limit 200) plus 10 `VEV_<strike>` call options on VELVETFRUIT (each at limit 300). OSMIUM and PEPPER are NOT tradeable in R3. The shipped submissions live at `traders/round1/submission.py` (portal sub 269599 — R1 algo PnL 99,546) and `traders/round2/submission.py` (portal sub 360419). The **active submission file** for R3 is `traders/round3/a.py` (penny-jump MM on the 10 active assets — dead options VEV_6000/6500 skipped). All R3 calibration in `calibration/<asset>/`.

## Directory Structure

```
IMC_trading_hack/
├── traders/                           # Shipped submission per round (single file each)
│   ├── round3/a.py                    #   ACTIVE — submit this
│   ├── round2/submission.py           #   R2 final (portal sub 360419)
│   ├── round1/submission.py           #   R1 final (portal sub 269599)
│   ├── datamodel.py                   #   Official Prosperity 4 data model
│   └── trader_hold1.py                #   Hold-1-unit strategy for FV extraction
├── results/                           # Post-round-close submission snapshots
│   ├── round1/                        #   round1_results.png + 269599.{log,json}
│   ├── round2/                        #   round2_results.png + 360419.{log,json}
│   └── round3/                        #   (ready for R3)
├── analysis/                          # Market-data analysis scripts (by round)
│   ├── round1/                        #   R1 OSMIUM/PEPPER EDA + FINDINGS.md
│   ├── round2/                        #   (ready for R2 follow-up)
│   └── round3/                        #   (ready for R3)
├── data/                              # Market data
│   ├── prosperity4/round{0,1,2}/      #   P4 historical CSVs
│   ├── prosperity4/round3/            #   placeholder — CSVs drop here
│   └── prosperity3/round1-8/          #   P3 historical data (reference)
├── backtester/                        # Backtester package (install with pip install -e .)
│   ├── prosperity4mcbt/               #   Monte Carlo CLI (primary backtester)
│   └── prosperity3bt/                 #   Historical CSV replay CLI
├── rust_simulator/                    # Rust Monte Carlo simulation engine (one file per asset under src/assets/)
├── wasm_compute/                      # Rust/WASM kernels for the Workshop tab (microstructure analytics)
├── visualizer/                        # Local dashboard frontend (Vite/React) — Workshop + Optimize tabs
├── optimizer/                         # Study-based parameter optimization on top of MC
│   ├── space.py                       #   ParamSpace, constraints, YAML schema
│   ├── runner.py                      #   MC subprocess orchestration, per-trial PnL arrays
│   ├── objective.py                   #   Metric registry (mean_pnl, sharpe, cvar_5, ...)
│   ├── samplers.py                    #   Optuna sampler wrappers (random/TPE/CMA-ES/QMC)
│   ├── validators.py                  #   DSR, PBO (CSCV), cluster stability, fANOVA importance
│   ├── study.py                       #   Lifecycle: sample → run → retest → validate → report
│   └── cli.py                         #   `prosperity4opt` entry point
│   (guide lives at repo root as OPTIMIZER.md)
├── studies/                           # Declarative YAML studies (one per tuning campaign)
├── calibration/                       # Bot reverse-engineering, one dir per asset
│   ├── ANALYSIS_PHILOSOPHY.md         #   Methodology (condition on everything, stat tests)
│   ├── README.md                      #   Per-asset summary + new-asset workflow
│   ├── validate.py                    #   Asset-agnostic stat-test harness
│   ├── extract_fv_and_book.py         #   Asset-agnostic hold-1 FV extractor
│   ├── audit_portal_log.py            #   Audit portal log vs Rust bot formulas
│   ├── emeralds/                      #   Round 0 constant-FV
│   ├── tomatoes/                      #   Round 0 random-walk reference
│   ├── ash_coated_osmium/             #   R1/R2 random-walk
│   └── intarian_pepper_root/          #   R1/R2 deterministic-drift
├── manual/                            # Manual trading challenges (round1/, round2/, round3/)
├── tmp/                               # Backtest + optimizer artifacts
│   ├── backtests/                     #   Default output dir for prosperity4mcbt / prosperity3bt runs
│   └── optimizer/                     #   Per-study SQLite + parquet + validators.json (prosperity4opt)
├── scripts/                           # Helper utilities
│   ├── python_strategy_worker.py      #   Rust sim ↔ Python bridge
│   └── bt_stats.py                    #   Fill analytics wrapper
├── CLAUDE.md                          # This file - project context
├── BACKTEST.md                        # Backtesting & calibration guide
├── DATA_WORKSHOP.md                   # Browser-based data analysis workshop guide
├── OPTIMIZER.md                       # Parameter-optimization framework guide (was optimizer/README.md)
└── PROSPERITY_4_WIKI_COMPLETE.md      # Full game reference
```

## Architecture & Constraints

### Submission Format

- **Single Python file** (currently `traders/round3/a.py`) containing a `Trader` class with a `run()` method
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

### Optional `bid()` Method (R2 only)

```python
def bid(self) -> int:
    return <MAF in XIRECs>
```

Only used in Round 2 for the Market Access Fee auction. Ignored in all other rounds and in testing. Top 50% of bids win +25% quote volume and pay their bid once.

### Position Limit CRITICAL Rule

If the sum of ALL your outstanding orders for a product could push your position past the limit (assuming worst-case all fill), **ALL orders for that product are cancelled**. Always calculate worst-case before submitting.

### Order Matching Sequence (per timestep)

1. Deep-liquidity market makers post orders
2. Bot takers act
3. YOUR algorithm runs (receives TradingState, returns orders)
4. Your orders matched against order book
5. Remaining bots may trade on your quotes
6. All unfilled orders expire

## Products by Round

### Round 0 — Tutorial (shipped)

| Product  | Position Limit | Behavior                                      | Strategy                       |
| -------- | -------------- | --------------------------------------------- | ------------------------------ |
| EMERALDS | 80             | Stationary ~10,000                            | Fixed fair-value market making |
| TOMATOES | 80             | Drifting (Gaussian random walk, σ=0.496/tick) | Adaptive market making         |

### Round 1 — shipped (Apr 14–17)

| Product              | Position Limit | Behavior                                                | Strategy (what worked in R1)                                          |
| -------------------- | -------------- | ------------------------------------------------------- | --------------------------------------------------------------------- |
| ASH_COATED_OSMIUM    | 80             | Gaussian random walk, σ=0.312/tick, starts ~10,000      | MM + OBI quote-skew + Bot1-asym adaptive signal                       |
| INTARIAN_PEPPER_ROOT | 80             | Deterministic drift +0.1/tick, starts ~10,000 → ~13,000 | Long-biased: aggressive take, tiered asks to unload at high inventory |

Bot calibration for R1 is fully solved — see `calibration/ash_coated_osmium/calibration.md` and `calibration/intarian_pepper_root/calibration.md`. Key finding: **PEPPER bots use proportional offsets** (`bid = floor(FV*(1 - K))`, `ask = ceil(FV*(1 + K))`) with Bot1 K=3/4000 and Bot2 K=1/2000.

### Round 2 — shipped (Apr 17–20, 2026, "Growing Your Outpost")

**No new products.** Same symbols, same limits (`ASH_COATED_OSMIUM` 80, `INTARIAN_PEPPER_ROOT` 80). Challenge was a **Market Access Fee (MAF)** sealed-bid auction — `bid()` method on the Trader, top 50% won +25% quote volume. We shipped `MAF_BID = 0` (defensible default) and still cleared the round comfortably. Final submission: `traders/round2/submission.py` (portal sub 360419). Result snapshot in `results/round2/`.

Manual challenge was "Invest & Expand" (allocate % across Research/Scale/Speed; `PnL = Research × Scale × Speed − Budget_Used`). See `manual/round2/` for notes.

### Round 3 — ACTIVE (2026-04-21 →)

R3 introduces a derivatives book. **OSMIUM and PEPPER_ROOT are no longer tradeable** — only the products below appear on the portal:

| Product | Position Limit | Behavior | Notes |
| --- | --- | --- | --- |
| HYDROGEL_PACK | **200** | Random walk, σ ≈ 1.92, drift ≈ −0.05/tick | Spot, ~16-tick spread (outer K=0.001) |
| VELVETFRUIT_EXTRACT | **200** | Random walk, σ ≈ 0.96 | Spot underlying for the VEV vouchers, ~3-tick spread |
| VEV_4000 (voucher) | **300** | Deep ITM call, behaves like underlying with offset | Spread ~16-20 |
| VEV_4500 (voucher) | **300** | ITM call | Spread ~16 |
| VEV_5000 / 5100 / 5200 / 5300 / 5400 / 5500 | **300** each | ATM-area calls | Tight spreads (1-2 ticks), narrow MM edge |
| VEV_6000 / VEV_6500 (voucher) | **300** each | Deep OTM (FV ≈ 0) | Effectively dead; no MM room |

`VEV_<strike>` = `VELVETFRUIT_EXTRACT_VOUCHER` at strike `<strike>`. Per-product calibration lives in `calibration/<asset>/calibration.md`; FV-process and bot models in `calibration/<asset>/params.json` and `rust_simulator/src/assets/<asset>.rs`.

The active R3 submission file is `traders/round3/a.py` (penny-jump MM on the 10 active assets; dead options skipped).

### Data Format (CSV, semicolon-delimited)

- **prices**: day;timestamp;product;bid_price_1-3;bid_volume_1-3;ask_price_1-3;ask_volume_1-3;mid_price;profit_and_loss
- **trades**: timestamp;buyer;seller;symbol;currency;price;quantity
- Currency: XIRECs
- Timestamps: increment by 100 (0, 100, 200, ...)
- 2,000 timesteps per day (portal server)

## Expected Round Types (Based on Prosperity 3 Pattern)

Note: Prosperity 4 breaks the P3 pattern. R1 and R2 both trade only OSMIUM + PEPPER_ROOT — R2 adds the MAF auction instead of new products. Unclear yet how many rounds P4 has in total; the wiki top-level timeline lists 5 rounds but the R2 page calls itself the "final trading round on Intara", suggesting later rounds may be off-planet with new products.

**Update for R3 (confirmed 2026-04-24):** the "all prior-round products remain tradeable" expectation broke at R3 — only the new R3 products (HYDROGEL, VELVETFRUIT, VEV_*) appear on the portal. R3 trader `traders/round3/a.py` no longer carries OSMIUM/PEPPER handlers.

**R3 sim calibration (2026-04-24, portal sub 366383):** the auto-generated `_trade_rates` in `tmp/generate_r3_asset_rs.py` had a 10× bug — it divided trade-event ticks by `3 * n_fv_ticks` (3000) instead of `3 * 10000`. Fix: use the actual CSV horizon (3 days × 10K ticks). Plus the raw trade CSVs under-represent ELASTIC (post-strategy taker) demand because the recordings come from a market with no aggressive MM — so once `traders/round3/a.py` shows up with improved quotes, real takers fire much more often. Resolved by adding per-asset `R3_ELASTIC_OVERRIDES` in the generator, back-fitted from portal sub 366383. Post-fix MC matches portal within 0.1σ on every R3 asset (sim total 1146 vs portal 1273 at 1K ticks).

## Strategy Framework

### 1. Alpha Engine (Fair Value Estimation)

- Stationary: fixed value (e.g., EMERALDS = 10,000)
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

### 5. Per-Product Config (expand as rounds unlock)

```python
PRODUCT_CONFIG = {
    "EMERALDS": {"fair_value": 10000, "spread": 2, "limit": 80, "strategy": "fixed_mm"},
    "TOMATOES": {"ema_window": 20, "spread": 3, "limit": 80, "strategy": "adaptive_mm"},
}
```

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

Output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json` — only pass `--out` when you need a specific path. Rust-backed Monte Carlo using calibrated bot models reverse-engineered from tutorial data. Produces distributional PnL stats (mean, std, percentiles) across hundreds/thousands of synthetic sessions.

#### Portal tick counts

- Portal UI backtest: **1,000 ticks** per day (what the "Run" button shows you)
- Portal final-round eval: **10,000 ticks** per day (actual scoring at round close)
- MC default `--ticks-per-day` is **10,000** (matches final eval). Pass `--ticks-per-day 1000` for portal-UI-backtest comparisons.

#### Flag scheme — global vs per-asset

The sim parses CLI flags into two categories:

- **Global** (`--sessions`, `--ticks-per-day`, `--seed`, `--fv-mode`, `--trade-mode`, `--quote-fraction`, `--maf-bid`, `--strategy`, `--output`, …) apply to the whole run.
- **Per-asset** flags are prefixed by the asset's lowercased-kebab symbol: `--<asset-kebab>-<flag>`. Example: PEPPER's starting-FV override is `--intarian-pepper-root-start-fv 13000`. Passing a flag for an asset the trader doesn't declare is a hard error.

The Python CLI accepts `--ipr-start-fv` as a legacy alias and translates it. Every other per-asset flag must use the full form.

```bash
# R2-style dev iteration (PEPPER start FV = 13000)
prosperity4mcbt traders/round3/a.py --quick --intarian-pepper-root-start-fv 13000
prosperity4mcbt traders/round3/a.py --heavy --intarian-pepper-root-start-fv 13000

# Match portal-UI backtest (1,000 ticks) for apples-to-apples with portal submissions
prosperity4mcbt traders/round3/a.py --heavy --intarian-pepper-root-start-fv 13000 --ticks-per-day 1000

# MAF analysis (at portal final scale)
prosperity4mcbt traders/round3/a.py --sessions 200 --intarian-pepper-root-start-fv 13000 --quote-fraction 0.8
prosperity4mcbt traders/round3/a.py --sessions 200 --intarian-pepper-root-start-fv 13000 --quote-fraction 1.25
prosperity4mcbt traders/round3/a.py --sessions 200 --intarian-pepper-root-start-fv 13000 --quote-fraction 1.25 --maf-bid 500
```

See [BACKTEST.md](BACKTEST.md) for the full flag reference, MAF-uplift table, and the workflow for adding a new asset (one Rust file per asset under `rust_simulator/src/assets/`).

### CSV Replay (sanity checks)

```bash
prosperity3bt traders/round3/a.py 1                    # historical replay on R1 data
py -3.13 scripts/bt_stats.py traders/round3/a.py 1     # fill analytics
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making. Use for relative A/B comparison only.

### Portal Submission Results

Both R1 and R2 cleared the advancement threshold. Post-round-close snapshots (portal `.png`, `.log`, `.json`) live in `results/round{1,2}/`.

**Round 1 (final, `traders/round1/submission.py`, portal sub 269599):**

- Algorithmic Challenge: **99,546 XIRECs**
- Manual Challenge ("An Intarian Welcome"): **87,995 XIRECs**
- Total: 187,541 (94% of the 200k advance threshold)

**Round 2 (final, `traders/round2/submission.py`, portal sub 360419):**

- Shipped with `MAF_BID = 0`. Passed to R3. Specifics in `results/round2/round2_results.png`.

**Sim calibration (final, validated on matched FV paths):**

Three portal submissions drove the calibration:

- **226828** (R1 MM backtest, 1K ticks): total trade-rate observations
- **274082** (R2 hold-1, 1K ticks): pure base-rate takers (no elastic) — extracted server FV to `calibration/intarian_pepper_root/data/r2_day1_fv.json` for replay
- **274250 + 274468** (R2 a.py identical-code repeats): confirmed portal backtest runs a single fixed FV path (only 80% quote subset is randomized)

**Bugs found and fixed:**

1. **PEPPER elastic rate was 7× too high**. Hold-1 base-rate separated clean: PEPPER elastic is ~0.9%, not 3.5% as in the original sim. Fixed via `IPR_ELASTIC_TRADE_PROB: 0.035 → 0.009`.
2. **Matching-engine ordering was wrong**. Sim ran base-rate takers AFTER the strategy ran, so they hit our penny-jumped quotes and inflated edge ~2×. Per P4 spec, bot takers act BEFORE the strategy sees the book. Reordered the tick loop — OSMIUM PnL on matched FV paths dropped from 3,443 → 1,957, matching portal 1,752 within 0.6σ.
3. **R2 PEPPER starting FV**. Drift continues from R1 day 0's end at ~13,000 (not reset to 10,000). Exposed as `--ipr-start-fv 13000` flag.

**Post-fix validation (MC replay on portal's exact FV path, 200 sessions, 1,000 ticks):**
| Product | MC mean | Portal avg (274250+274468) | z |
|---|---|---|---|
| OSMIUM | 1,957 | 1,752 | −0.6σ ✓ |
| PEPPER | 7,323 | 7,455 | +2.2σ ✓ |
| **Total** | **9,280** | **9,207** | **−0.2σ** |

Total gap **+73 XIRECs (0.8%)** — sim is now calibrated against portal reality.

**Post-calibration R2 MC (200 sessions × 10,000 ticks, `--ipr-start-fv 13000`):**

| Scenario                                | Mean PnL per final eval   | Std   | vs R1 portal final |
| --------------------------------------- | ------------------------- | ----- | ------------------ |
| R2 loser (`--quote-fraction 0.8`)       | **98,642**                | 1,042 | −1% from 99,546 ✓  |
| R2 MAF winner (`--quote-fraction 1.25`) | **100,116**               | 1,096 | +1% from 99,546    |
| **MAF uplift (winner − loser)**         | **+1,474 per final eval** |       |                    |

**MAF bid guidance**: uplift is ~1,474 XIRECs per final eval. You only need to beat the median of all teams' bids, not buy the full uplift — shade well below. A first defensible opening is **300-500**; if the field under-bids, much less will do. `MAF_BID = 0` is a fine "do nothing" baseline.

MC absolute numbers are now trustworthy (not just relative deltas) — the sim matches portal reality within 1% on matched FV paths.

Post-round-close logs for R1/R2 are in `results/round{1,2}/` (portal sub id as filename). All backtest artifacts — MC dashboards, replay logs, ad-hoc outputs — go under `tmp/` (gitignored). Default MC output is `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`; default CSV replay log is `tmp/backtests/<timestamp>.log`. Never write backtest output outside `tmp/`.

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
prosperity4opt studies/round2_signal_tuning.yaml --fresh

# Outputs under tmp/optimizer/<study_name>/:
#   study.db           — Optuna SQLite (resumable)
#   results.parquet    — per-trial params + metrics
#   validators.json    — DSR / PBO / cluster / importance diagnostics
#   retest.json        — top-K fresh-seed OOS scores
#   top_trials.csv     — ranked summary
```

Trader contract (copy-paste snippet in `OPTIMIZER.md`): every tunable trader reads its params from a `PARAMS` dict merged with `os.environ["PROSPERITY_PARAMS"]`. Portal submission is unaffected — the env var is never set there, so defaults apply.

`studies/round2_tunable.py` is a reference trader (identical trading logic to the shipped R2, with the contract layered on). Study it before writing a new tunable trader for R3+.

## Coding Conventions

- All trading logic in a single file (currently `traders/round3/a.py`) — submission constraint
- Use `json.dumps()`/`json.loads()` for traderData serialization
- Keep strategies modular within the single file using helper methods
- Price is always `int`, quantity is `int` (positive = buy, negative = sell)
- sell_orders in OrderDepth have **negative** quantities
- Always log key state with `print()` for debugging (visible in activity logs)
- Test locally with backtester before every submission

## Common Pitfalls

- Forgetting sell_orders quantities are negative
- **Position limit bug**: When computing passive order sizes after taking, use STARTING position (from state.position), not the locally-tracked post-take position. The exchange checks all orders against the starting position. Using post-take position over-allocates the opposite side → ALL orders cancelled.
- Not accounting for worst-case position limit check (ALL orders, not individual)
- **EMA-based taking loses money on drifting assets**: For trending products like TOMATOES, EMA lag causes wrong-way trades (buys falling markets, sells rising). Use pure passive quoting instead.
- **CSV replay fills are unrealistic**: Don't trust absolute PnL from `prosperity3bt --match-trades all` for market-making. Use `prosperity4mcbt` Monte Carlo or the portal.
- Hardcoding values that change between rounds
- Not persisting state properly in traderData (init called once, run called per tick)
- Placing orders that cross your own orders (unnecessary self-trade)
- Ignoring market_trades data (contains valuable signal about bot behavior)

## Reference Repos (Top Teams from Prior Years)

- 2nd Place P3: https://github.com/TimoDiehm/imc-prosperity-3
- 9th Place P3: https://github.com/CarterT27/imc-prosperity-3
- 7th Place P3: https://github.com/chrispyroberts/imc-prosperity-3
- 2nd Place P2: https://github.com/ericcccsliu/imc-prosperity-2
- Strategy Guide: https://github.com/MarkBrezina/Ctrl-Alt-DefeatTheMarket
