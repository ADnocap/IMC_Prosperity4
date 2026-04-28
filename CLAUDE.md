# IMC Prosperity 4 - Algorithmic Trading Competition

## Project Overview

This is our workspace for **IMC Prosperity 4** (2026), a multi-round algorithmic trading competition where we write Python trading bots that execute on a simulated exchange against bot counterparties. Goal: maximize profit (PnL) in XIRECs currency.

- **Competition**: April 14-30, 2026 (5 rounds)
- **Tutorial**: March 16 - April 13, 2026
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki
- **Prize Pool**: $50,000 USD

## Current Round

**Round 5** (active from 2026-04-28, "The Final Stretch"). R1, R2, R3, R4 all passed. R5 is the final round and **wipes the slate clean** — all R3/R4 products (HYDROGEL/VELVETFRUIT/VEV_*) are no longer tradeable. **50 brand-new products** are introduced, evenly distributed across 10 categories of 5 (Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV-Visors, Translators, Panels, Oxygen Shakes, Snackpacks). **Position limit is 10 for every product.** Some categories embed strong patterns waiting to be discovered; others will need vanilla MM. The shipped submissions live at `traders/round{1,2,3,4}/submission.py` (portal subs 269599 / 360419 / 485183 / **542976**). The **active submission file** for R5 is `traders/round5/submission.py` (currently a no-op scaffold — calibration is the next step). Manual challenge ("Extra! Extra!") happens on the Ignith exchange via Ashflow Alpha news — out of scope for the algo file.

## Directory Structure

```
IMC_trading_hack/
├── traders/                           # Per-round trader code (submission.py + experiments)
│   ├── round5/submission.py           #   ACTIVE — submit this for R5 (currently no-op scaffold)
│   ├── round4/                        #   R4 final = submission.py (portal sub 542976, "marco_rubio_v2")
│   │                                  #   Plus ~30 named experiments (stratton, timo, marks_*, master_v1,
│   │                                  #   submission_v1..v30) — frozen reference; R5 products are all-new
│   ├── round3/                        #   R3 final = submission.py (portal sub 485183, "stratton.py")
│   │                                  #   Plus ~25 named experiments (max, porush, jordan, wolf,
│   │                                  #   harry_potter_v4, etc.) — frozen reference
│   ├── round2/                        #   submission.py (portal sub 360419) + spongebob_v1-v4 experiments
│   ├── round1/submission.py           #   R1 final (portal sub 269599)
│   ├── datamodel.py                   #   Official Prosperity 4 data model
│   └── trader_hold1.py                #   Hold-1-unit strategy for FV extraction
├── Rubenstrats/                       # Ruben's R4 trader experiments (Hagrid_*, Harry_potter_*,
│                                      #   pete_hegseth_*) — kept as reference, not active for R5
├── results/                           # Post-round-close submission snapshots
│   ├── round1/                        #   round1_results.png + 269599.{log,json}
│   ├── round2/                        #   round2_results.png + 360419.{log,json}
│   ├── round3/                        #   round3_results.png + 485183.{log,json,py}
│   ├── round4/                        #   round4_results.png + 542976.{log,json,py}
│   └── round5/                        #   (ready for R5)
├── analysis/                          # Market-data analysis scripts (by round)
│   ├── round1/                        #   R1 OSMIUM/PEPPER EDA + FINDINGS.md
│   ├── round3/                        #   R3 derivatives EDA: FINDINGS, FINDINGS_v2,
│   │                                  #   SUBMISSION_PLAN, PARAM_SEARCHES + per-topic .md/.py/.json
│   ├── round4/                        #   R4 IV-scalp / cross-strike / Mark-layer EDA
│   └── round5/                        #   (ready for R5 — 50 new products to characterize)
├── data/                              # Market data
│   ├── prosperity4/round{0,1,2,3,4,5}/ #  P4 historical CSVs (R4+ have buyer/seller populated;
│   │                                  #   R5 ships days 2/3/4)
│   └── prosperity3/round1-8/          #   P3 historical data (reference)
├── backtester/                        # Backtester package (install with pip install -e .)
│   ├── prosperity4mcbt/               #   Monte Carlo CLI (primary backtester)
│   └── prosperity3bt/                 #   Historical CSV replay CLI
├── rust_simulator/                    # Rust Monte Carlo simulation engine
│   ├── src/asset.rs                   #   Per-asset trait (book + bot params)
│   ├── src/assets/<one_per_asset>.rs  #   R3/R4 per-asset modules (RW/drift FV)
│   ├── src/assets/r5_asset.rs         #   R5: single generic impl, 50 instances built from scenario_params.json
│   ├── src/scenario.rs                #   Scenario trait + DayData/Pulse types (R5 2-layer architecture)
│   ├── src/scenarios/r5.rs            #   R5Scenario: joint OU FVs + 3 shared pulse processes
│   └── src/bin/r5_smoke.rs            #   Validation binary (basket sum / K_day / per-asset moments)
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
│   ├── intarian_pepper_root/          #   R1/R2 deterministic-drift
│   ├── hydrogel_pack/                 #   R3/R4 spot, drifting random-walk
│   ├── velvetfruit_extract/           #   R3/R4 spot underlying (random-walk)
│   ├── vev_4000..vev_6500/            #   R3/R4 voucher options on VELVETFRUIT
│   ├── marks/                         #   R4 per-counterparty profiling (Mark 01..67)
│   └── r5/scenario_params.json        #   R5 Rust-ready calibration bundle (50 assets + K_day + pulses)
├── manual/                            # Manual trading challenges (round1/, round2/, round3/, round4/)
├── tmp/                               # Backtest + optimizer artifacts
│   ├── backtests/                     #   Default output dir for prosperity4mcbt / prosperity3bt runs (gitignored)
│   ├── optimizer/                     #   Per-study SQLite + parquet + validators.json (prosperity4opt)
│   └── portal_<id>/                   #   Extracted portal-submission .log/.json/.py snapshots
├── scripts/                           # Helper utilities
│   ├── python_strategy_worker.py      #   Rust sim ↔ Python bridge
│   ├── bt_stats.py                    #   Fill analytics wrapper
│   ├── csv_to_parquet.py              #   Convert raw CSVs to parquet for the Workshop
│   ├── generate_r3_asset_rs.py        #   Auto-generate Rust AssetSim modules from calibration/<asset>/params.json
│   └── write_r3_calibration_md.py     #   Generate calibration.md per asset from params.json
├── CLAUDE.md                          # This file - project context
├── BACKTEST.md                        # Backtesting & calibration guide
├── DATA_WORKSHOP.md                   # Browser-based data analysis workshop guide
├── OPTIMIZER.md                       # Parameter-optimization framework guide (was optimizer/README.md)
└── PROSPERITY_4_WIKI_COMPLETE.md      # Full game reference
```

## Architecture & Constraints

### Submission Format

- **Single Python file** (currently `traders/round5/submission.py`) containing a `Trader` class with a `run()` method
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

### Round 3 — shipped (Apr 21–25, 2026, "Frontier Trade Watch I")

R3 introduced a derivatives book. **OSMIUM and PEPPER_ROOT became un-tradeable**; only HYDROGEL/VELVETFRUIT + 10 VEV vouchers were live (same products carry over to R4):

| Product | Position Limit | Behavior | Notes |
| --- | --- | --- | --- |
| HYDROGEL_PACK | **200** | Random walk, σ ≈ 1.92, drift ≈ −0.05/tick | Spot, ~16-tick spread (outer K=0.001) |
| VELVETFRUIT_EXTRACT | **200** | Random walk, σ ≈ 0.96 | Spot underlying for the VEV vouchers, ~3-tick spread |
| VEV_4000 (voucher) | **300** | Deep ITM call, behaves like underlying with offset | Spread ~16-20 |
| VEV_4500 (voucher) | **300** | ITM call | Spread ~16 |
| VEV_5000 / 5100 / 5200 / 5300 / 5400 / 5500 | **300** each | ATM-area calls | Tight spreads (1-2 ticks), narrow MM edge |
| VEV_6000 / VEV_6500 (voucher) | **300** each | Deep OTM (FV ≈ 0) | Effectively dead; no MM room |

`VEV_<strike>` = `VELVETFRUIT_EXTRACT_VOUCHER` at strike `<strike>`. Per-product calibration in `calibration/<asset>/calibration.md`, `params.json`, and `rust_simulator/src/assets/<asset>.rs`.

R3 final shipped trader = `traders/round3/submission.py` ("stratton" — search-2 OOS winner, trial #233; mean-reversion + tight passive MM, takes disabled). Portal final eval **11,140.94 XIRECs**. Result snapshot in `results/round3/`. The other ~25 named files in `traders/round3/` are intermediate experiments preserved because R4 reuses the same products.

### Round 4 — shipped (2026-04-26 → 2026-04-28, "The More The Merrier")

**Same products and limits as R3.** Two new wrinkles:

1. **Counterparty disclosure.** Every `Trade` now has `buyer` and `seller` populated with one of seven `Mark <NN>` IDs: **Mark 01, 14, 22, 38, 49, 55, 67**. In R1–R3 these fields were always `None`. R4 day 1 and day 2 are the *exact same FV path and trades* as R3 days 1 and 2 — re-released with the buyer/seller fields filled — so we can map our calibrated bots to specific Marks by behavior. Day 3 is genuinely new data.
   - Quick R4 day-1 pair frequency: `Mark 01 → Mark 22` (393 trades) is the dominant flow, `Mark 14 ↔ Mark 38` (~270 each direction), `Mark 14 ↔ Mark 55` (~110), `Mark 67 → Mark 22` (~32). Mark 22 and Mark 38 look passive (typically on the opposite side of more directional Marks); Mark 67 is asymmetric (only ever buyer).
2. **Manual challenge: Aether Crystal exotics.** Independent from the algo book — out of scope for `traders/round4/submission.py`. See `manual/round4/` for notes.

R4 final shipped trader = portal sub **542976** ("marco_rubio_v2" — Hagrid_v1 voucher stack + Pete Hegseth v3 VELVETFRUIT execution merged in late). Final submission preserved at `results/round4/542976.py` and `traders/round4/submission.py`. The other ~30 named files in `traders/round4/` (stratton, timo, marks_*, master_v1, submission_v1..v30) are intermediate experiments preserved for reference, but R5 swaps the entire product set so they're frozen. The Mark counterparty layer was profiled (`calibration/marks/`) but all integration variants net-lost in replay — see "Mark layer kill verdict" below.

**Cross-strike kill verdict (2026-04-26, `analysis/round4/cs_reconciliation.md`):** the audit's claim that 5200/5400 vert spread MR makes +11,265 over 3 days is a **mid-to-mid accounting artifact**. Adding realistic spread cost (half-spread per leg per side) flips it to **−15,128**. Cross-spread mode (worst case) is −41,520. 94-config sweep over k_sigma × hold × pair × execution_mode found exactly 1 positive result (+20 over 3d, n=3 trades, noise). The structural reason CS doesn't survive transaction costs while IV-scalp does: **IV-scalp earns deviations by selling AT best_bid above fair (someone posted *to* us); CS pays half-spread per leg to access positions the model says are mispriced**. CS trades when the model wants the book to be wrong, IV-scalp trades when the book pays us. Only the latter survives. Don't revisit unless we find a structurally different harvest mechanism. Note: `traders/round3/rothschild.py` has a `KeyError` bug (CS_PAIRS references VEV_5200 but STRIKES_CS omits it) — patched copy at `tmp/cs_test/rothschild_fixed.py` if anyone needs to reference the logic.

**Mark layer kill verdict (2026-04-26, three variants in `traders/round4/marks_{a_skew,b_takes,c_widen}.py`):** All three integration approaches *lost* money in replay vs the +27,444 baseline: (a) skew/size bias −4,448 (D3 disaster as net long-tilt fights choppy tape), (b) gated cross-spread takes −10,058 (1-tick lag + half-spread > residual edge), (c) defensive widen −4,832 (bidirectional Mark 14↔Mark 38 flow widens both sides → wash). Per-Mark profiling lives in `calibration/marks/` (mark_profiles.md, signals.json) and the *signals are real* — Mark 14 is informed (+6.2 drift @H=200), Mark 38 is dumb (−8.6), Mark 22/55/49 are adversely selected, Mark 67 is inconsistent. But our **existing OBI-skewed quotes already capture most of it** (Mark 14 buying = aggressive sell pressure → OBI tilts → stratton already reacts). The Mark layer adds redundant info that interferes. If revisited: try a fundamentally different harvest — e.g. only one Mark per product to avoid the bidirectional cancel, or a longer-window net-imbalance gate.

### Round 5 — ACTIVE (2026-04-28 →, "The Final Stretch")

**Total product reset.** R3/R4 products are gone from the portal. R5 ships **50 brand-new products** across 10 categories of 5, with a **uniform position limit of 10** for every product. Some categories embed strong patterns ("Cherry Picking Winners" — find the inefficient ones); others will need vanilla MM. Calibration has not started yet — `traders/round5/submission.py` is currently a no-op scaffold that just declares the symbol universe.

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

**Position-limit implication.** Limit = 10 is *much* tighter than R1–R4 (80–300). Worst-case open-order math (the hard rule that ALL orders cancel if the worst-case fill could breach the limit) is now extremely unforgiving — a single 5-lot bid plus a 6-lot ask can already exceed limits and cancel everything. Quote sizes will be small; turnover and tick-by-tick rebalancing matter more than per-trade size. Strategies that relied on stacking 30+ unit passive layers (Hagrid voucher stack, stratton OBI MM) **do not transfer** — every per-asset config has to be re-thought.

**Manual challenge: "Extra! Extra! Read all about it!"** — out of scope for `traders/round5/submission.py`. One-day Ignith exchange portfolio sized via Ashflow Alpha news, with a quadratic per-product fee `fee = (volume/100)² × budget` against a 1,000,000-XIRECs budget. See `manual/round5/` (when set up) for notes.

**Data shipped:** `data/prosperity4/round5/{prices,trades}_round_5_day_{2,3,4}.csv` — three days of pre-round-close historical CSVs. Trades will have buyer/seller fields populated (R4 onward).

**Calibration approach (decided 2026-04-28).** R5 does **not** use the per-asset `calibration/<asset>/` pattern from R1–R4. Instead, all 50 products share a single bundle at `calibration/r5/scenario_params.json`, generated from historical CSVs by `analysis/round5/rigorous_calibration.py`, and consumed by the new `Scenario` layer in the Rust simulator (see "R5 simulator: 2-layer architecture" below). Per-product fits live as entries inside that one JSON; per-category constraints (Pebble basket, Snackpack pair/triplet) are first-class invariants in the scenario, not asset-level concerns.

### Data Format (CSV, semicolon-delimited)

- **prices**: day;timestamp;product;bid_price_1-3;bid_volume_1-3;ask_price_1-3;ask_volume_1-3;mid_price;profit_and_loss
- **trades**: timestamp;buyer;seller;symbol;currency;price;quantity
  - Through R3, `buyer` and `seller` were always empty. From R4 onward they're populated with `Mark <NN>` counterparty IDs (7 Marks total in the R4 dataset).
- Currency: XIRECs
- Timestamps: increment by 100 (0, 100, 200, ...)
- 10,000 timesteps per day in the final eval (1,000 in portal-UI backtests)

## Round-to-round product carry-over

P4 breaks the P3 "all-prior-products-stay-tradeable" pattern: at each new round, only the products listed for that round appear on the portal. R1 and R2 traded only OSMIUM + PEPPER_ROOT. R3 dropped both and added the HYDROGEL / VELVETFRUIT / VEV book. R4 kept the R3 book and added counterparty IDs. R5 wipes the slate again — none of the R3/R4 products survive, and 50 new ones replace them with a uniform position limit of 10.

**R3 sim calibration (2026-04-24, portal sub 366383):** the auto-generated `_trade_rates` in `scripts/generate_r3_asset_rs.py` had a 10× bug — it divided trade-event ticks by `3 * n_fv_ticks` (3000) instead of `3 * 10000`. Fix: use the actual CSV horizon (3 days × 10K ticks). Plus the raw trade CSVs under-represent ELASTIC (post-strategy taker) demand because the recordings come from a market with no aggressive MM — so once a real penny-jumping trader shows up with improved quotes, real takers fire much more often. Resolved by adding per-asset `R3_ELASTIC_OVERRIDES` in the generator, back-fitted from portal sub 366383. Post-fix MC matches portal within 0.1σ on every R3 asset (sim total 1146 vs portal 1273 at 1K ticks).

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
# R5 dev iteration (calibrated 2026-04-28). The MC sim auto-detects R5 from
# symbol declarations in the trader file and routes through R5Scenario
# (joint FVs respecting Pebble basket + Snackpack constraints + 3 shared
# pulse processes). Days = [2,3,4] from data/prosperity4/round5/.
prosperity4mcbt traders/round5/submission.py --quick
prosperity4mcbt traders/round5/submission.py --heavy

# Match portal-UI backtest (1,000 ticks) for apples-to-apples with portal submissions
prosperity4mcbt traders/round5/submission.py --heavy --ticks-per-day 1000

# Validate the scenario directly (constraint + pulse moments) without a trader
cd rust_simulator && \
  R5_SCENARIO_PARAMS=$(pwd)/../calibration/r5/scenario_params.json \
  cargo run --release --bin r5_smoke -- 50

# Re-run calibration if the historical CSVs change or you tweak the model
py -3.13 analysis/round5/rigorous_calibration.py
py -3.13 analysis/round5/r5_python_sim.py    # Python end-to-end sanity vs portal sub 545243
```

See [BACKTEST.md](BACKTEST.md) for the full flag reference and the workflow for adding a new asset (one Rust file per asset under `rust_simulator/src/assets/`).

### CSV Replay (sanity checks)

```bash
prosperity3bt traders/round5/submission.py 5                    # historical replay on R5 data
py -3.13 scripts/bt_stats.py traders/round5/submission.py 5     # fill analytics
```

**Warning**: `--match-trades all` (default) over-reports PnL for market making. Use for relative A/B comparison only.

### Portal Submission Results

R1, R2, R3, and R4 all cleared the advancement threshold. Post-round-close snapshots (portal `.png`, `.log`, `.json`, `.py`) live in `results/round{1,2,3,4}/`.

**Round 1 (final, `traders/round1/submission.py`, portal sub 269599):**

- Algorithmic Challenge: **99,546 XIRECs**
- Manual Challenge ("An Intarian Welcome"): **87,995 XIRECs**
- Total: 187,541 (94% of the 200k advance threshold)

**Round 2 (final, `traders/round2/submission.py`, portal sub 360419):**

- Shipped with `MAF_BID = 0`. Passed to R3. Specifics in `results/round2/round2_results.png`.

**Round 3 (final, `traders/round3/submission.py` = "stratton", portal sub 485183):**

- Algorithmic Challenge: **11,140.94 XIRECs** (final eval). Source `results/round3/485183.py` (identical to `traders/round3/submission.py`).
- Strategy: search-2 OOS winner — slow EMA fair value, mean-reversion sizing on VELVETFRUIT + 5000–5400 vouchers, OBI-skew passive MM on HYDROGEL + far-strike vouchers, takes disabled. Selected from 400+ Optuna trials (`tmp/optimizer/round3_param_search_v2_*`).
- Trade-off vs more aggressive candidates (max.py, porush.py, wolf.py): ~19% lower mean PnL but ~33% lower std and a positive 5th percentile. Chose risk-adjusted return given the round's volatility.

**Round 4 (final, `traders/round4/submission.py` = "marco_rubio_v2", portal sub 542976):**

- Source preserved at `results/round4/542976.py`. Full R4 result snapshot in `results/round4/`.
- Strategy: Hagrid_v1 voucher stack (3-regime gating + flow signal + 3-level passive layers on VEV_5000–5500) merged with Pete Hegseth v3 VELVETFRUIT execution (continuous z-target + OBI-tilted 2-level). HYDROGEL + VEV_4000/4500 traded via OBI MM. CS spread MR and Mark-counterparty layers both confirmed unrecoverable in replay (see verdicts above).
- Replay context (prosperity3bt `--merge-pnl` on the 3-day R4 dataset, prior to ship): the IV-scalp baseline at `traders/round4/submission_v30.py` produced **+27,444** (D1 14,961 / D2 582 / D3 11,901) vs stratton baseline +20,954. The shipped marco_rubio_v2 was selected over that line for VELVETFRUIT execution improvements.

**R3 → R4 sim recalibration sanity check (2026-04-26):** R4 days 1–2 reproduce R3 days 1–2 exactly, so the Rust AssetSim modules generated under `rust_simulator/src/assets/` from `calibration/<asset>/params.json` remain valid against day-1/2 of R4. Day 3 is fresh — refit the FV start price and bot trade rates if you see divergence.

**R4 → R5 sim status (2026-04-28, calibrated):** R5 introduces 50 new products with no carry-over from R3/R4. **Calibration is in** — the simulator now uses a 2-layer architecture (see "R5 simulator: 2-layer architecture" below). `prosperity4mcbt traders/round5/submission.py --quick` works end-to-end against the R5 universe; CSV replay (`prosperity3bt traders/round5/submission.py 5` against `data/prosperity4/round5/`) still works for sanity checks.

### R5 simulator: 2-layer architecture (calibrated 2026-04-28)

R3/R4 generated **1 FV path + 1 Poisson trade process per asset, independent**. R5's market structure breaks that:

- 50 FVs are **not** independent — `PEBBLES_XS+S+M+L+XL = 50,000` exactly every tick; `SNACKPACK_CHOCOLATE + SNACKPACK_VANILLA ≈ K_day` (a slow OU-process pair sum that drifts ~50–100/day); a looser snackpack triplet (PIS/STRAW/RASP) with day-varying loadings.
- Trades fire in **3 shared Poisson pulse processes**, not 50 independent Poissons:
  - **V (Vanilla)**: 40 products, λ ≈ 0.0244/tick (~244 pulses/10K-tick day), qty ∈ {1,2,3,4}
  - **P (Pebbles)**: 5 pebbles, λ ≈ 0.0215/tick, qty ∈ {2,3,4,5}
  - **M (Microchips)**: 5 microchips, λ ≈ 0.0190/tick, qty ∈ {1,2,3}
- Each pulse fires its full member group on the **same** side (buy/sell, p_buy ≈ 0.49) at the **same** quantity in the same tick — basket-arb signal lives in the pulse co-firing.
- All FVs are bounded (OU-like, daily-resampled mean), not free random walks.

**Layer 1 — Joint state generator (`Scenario` trait).** New `rust_simulator/src/scenario.rs` defines the trait; `rust_simulator/src/scenarios/r5.rs` implements `R5Scenario`. Per session/day it produces:
- `fv_paths: HashMap<(symbol, day) → Vec<f64>>` — joint OU walks with derived constraints applied per tick (Pebble basket sum is exact, K_day pair is exact, triplet residual handled).
- `pulses_per_day: HashMap<day → Vec<Pulse>>` — pre-sampled list of `(tick, members, direction, quantity)` records from the 3 Poisson processes.

**Layer 2 — Per-asset book + execution (existing `AssetSim`).** Each tick still calls `asset.make_book(fv[asset][tick], rng)` for symmetric L1+L2 books, but FV is read from the scenario instead of being simulated per-asset. Pulses are routed through `apply_pulse_against_book` — direction = sell takes qty units at `bid_price_1` (sweeping into L2 if shallow), direction = buy takes at `ask_price_1`. Strategy quotes still get priority via `LevelOwner::Strategy` vs `LevelOwner::Bot`.

**Auto-detection.** `main.rs::r5_active(config)` checks if any active asset belongs to the R5 universe (via `assets::is_r5_symbol`); if so, the run uses days `[2,3,4]` (matching R5 historical CSVs) and routes through `R5Scenario`. R3/R4 traders continue using the per-asset path with no changes.

**Generic R5 asset.** `rust_simulator/src/assets/r5_asset.rs` is a single shared impl, parametrised by `(symbol, h, depth_l1, depth_l2, l2_lift)`. The 50 instances are built from `calibration/r5/scenario_params.json` at startup — no boilerplate per-asset Rust files. `simulate_fv` / `base_trade_prob` are stubs (the scenario owns those decisions).

**Calibration files.**
- `analysis/round5/calibration_r5.json` — raw per-asset OU/RW fits + book params + pulse rates + variance-ratio diagnostics, produced by `analysis/round5/rigorous_calibration.py`.
- `calibration/r5/scenario_params.json` — Rust-ready bundle loaded at runtime by `R5Scenario::load()`. Resolves via `R5_SCENARIO_PARAMS` env var, then via repo-root walk. Structure: `days`, `ticks_per_day`, `pebble_constant`, `pebble_free`/`pebble_derived`, `snackpack_choc`/`snackpack_vanilla`, `k_day` (OU θ/σ + per-day μ), `pulses` (V/P/M specs), `assets` (50 entries with model="OU"|"RW", θ, σ, daily_μ, h, depth_l1, depth_l2, l2_lift), `day_starts`.

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

End-to-end calibration check on the shipped R3 trader vs portal final:

| | Portal sub 485183 (final eval) | MC `--quick` (100 sessions × 10K ticks) | z |
|---|---|---|---|
| Total PnL | **11,140.94** | mean **10,768.32**, std **6,815** | **+0.055σ** ✓ |

Per-asset portal final breakdown (for future reference): HYDROGEL +4,734.84, VELVETFRUIT +1,326.39, VEV_4000 +2,589.00, VEV_4500 +1,888.01, VEV_5000 +464.93, VEV_5100 +229.69, VEV_5200 −26.28, VEV_5300 −65.64, VEV_5400/5500/6000/6500 = 0.

Sim absolute numbers remain trustworthy on R3/R4 products — no recalibration needed for R4 unless day-3 behavior diverges. The 17,449 number that appears in `analysis/round3/SUBMISSION_PLAN.md` was a portal-UI backtest result (1K ticks/day), not the final eval.

**Sim calibration (R1/R2 audit trail, validated on matched FV paths):**

Three portal submissions drove the calibration:

- **226828** (R1 MM backtest, 1K ticks): total trade-rate observations
- **274082** (R2 hold-1, 1K ticks): pure base-rate takers (no elastic) — extracted server FV to `calibration/intarian_pepper_root/data/r2_day1_fv.json` for replay
- **274250 + 274468** (R2 submission identical-code repeats): confirmed portal backtest runs a single fixed FV path (only 80% quote subset is randomized)

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

Post-round-close logs for R1/R2/R3 are in `results/round{1,2,3}/` (portal sub id as filename). All backtest artifacts — MC dashboards, replay logs, ad-hoc outputs — go under `tmp/`. `tmp/backtests/` is gitignored; `tmp/optimizer/` and `tmp/portal_<id>/` are tracked so the team can browse each other's runs. Default MC output is `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`; default CSV replay log is `tmp/backtests/<timestamp>.log`. Never write backtest output outside `tmp/`.

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

- All trading logic in a single file (currently `traders/round4/submission.py`) — submission constraint
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
