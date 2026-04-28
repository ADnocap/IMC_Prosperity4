---
name: prosperity
description: Helper for the IMC Prosperity 4 algorithmic trading competition. Use this skill whenever the user wants to backtest their trading algorithm, analyze market data, validate their submission, optimize strategy parameters, or check their competition status. Trigger on mentions of prosperity, backtesting trader.py, trading strategy optimization, submission validation, or EDA on round data. Also trigger when the user says things like "run the bot", "test my algo", "check my PnL", "how's my strategy doing", or "prepare for submission".
---

# Prosperity - IMC Trading Competition Helper

You are helping with the IMC Prosperity 4 algorithmic trading competition. The project lives at `C:\Users\alexa\OneDrive\Documents\IMC_trading_hack`.

## Setup

- **Python**: Use `py -3.13` (Python 3.13)
- **Monte Carlo backtester**: `prosperity4mcbt` CLI (install: `pip install -e .` from repo root)
- **CSV replay**: `prosperity3bt` CLI (same package)
- **Active trader file**: lives under `traders/round<N>/submission.py` where N is the current round. Determine N by listing `traders/` — the highest-numbered `roundN/` directory is the active round. **Round 5 is active as of 2026-04-28** (R1, R2, R3, R4 all shipped — results in `results/round{1,2,3,4}/`).
- **Data**: per-round CSVs in `data/prosperity4/round<N>/` (semicolon-delimited). R0–R5 data are present; R5 ships days 2/3/4.
- **Unicode output**: Prefix commands with `PYTHONIOENCODING=utf-8` when needed

## Determining the active round

Before running any subcommand, resolve the active trader path:

1. List `traders/` — pick the highest `roundN/` that contains a `submission.py`
2. Active trader = `traders/round<N>/submission.py`
3. Active data dir = `data/prosperity4/round<N>/` (may be empty if IMC hasn't published yet — fall back to round N-1 for replay)

Note: filenames migrated from `a.py` (R1–R3 era convention) to `submission.py` (R4+). Both are valid; prefer `submission.py` for new work and only fall back to `a.py` if the round directory only has that.

## R5 simulator: 2-layer scenario architecture (calibrated 2026-04-28)

R5 introduced 50 brand-new products with a **uniform position limit of 10 each** and structural cross-product constraints that R3/R4's per-asset independent simulator can't represent. The R5 sim uses a 2-layer architecture:

- **Layer 1 — Joint state generator** (`rust_simulator/src/scenario.rs` trait, `rust_simulator/src/scenarios/r5.rs` impl). Produces FV paths for all 50 assets *jointly* (Pebble basket sum = 50,000 exactly per tick; SNACKPACK_CHOC + SNACKPACK_VANILLA ≈ K_day where K_day is its own slow OU process; 47 free OU walks elsewhere) plus a list of **shared Poisson pulses** for 3 groups (V = 40 vanilla products, P = 5 pebbles, M = 5 microchips). A single pulse fires its whole group on the same side at the same quantity in the same tick.
- **Layer 2 — Per-asset book + execution.** Each asset still owns its L1+L2 symmetric book around its FV and gets pulse takes routed via `apply_pulse_against_book`. R5 uses a single shared Rust impl (`rust_simulator/src/assets/r5_asset.rs`) — the 50 instances are built from `calibration/r5/scenario_params.json` at load time, no boilerplate per-asset files.

Auto-detection: `prosperity4mcbt` checks the trader file for R5 symbol declarations; if found, it routes through `R5Scenario` and uses days `[2,3,4]`. R3/R4 traders are unaffected.

**Key files for R5:**
- `analysis/round5/rigorous_calibration.py` — produces `analysis/round5/calibration_r5.json` from historical CSVs.
- `calibration/r5/scenario_params.json` — Rust-ready bundle loaded by `R5Scenario::load()` (env var `R5_SCENARIO_PARAMS` overrides the search, otherwise the loader walks up to the repo root).
- `analysis/round5/r5_scenario_v2.py` — Python prototype, writes `scenario_v2_validation.csv` for moment checks.
- `analysis/round5/r5_python_sim.py` — full Python end-to-end backtester (hold-1 vs portal sub 545243 = -2160 PnL on day-4 1K ticks).
- `rust_simulator/src/bin/r5_smoke.rs` — Rust binary that validates basket sum / K_day / per-asset moments / pulse moments against calibration targets.

**R5 calibration / backtest commands:**
```bash
# Re-run calibration from historical CSVs
py -3.13 analysis/round5/rigorous_calibration.py

# Validate Python scenario v2 moments vs historical
py -3.13 analysis/round5/r5_scenario_v2.py

# Python end-to-end (hold-1 on day-4 1K ticks vs portal sub 545243)
py -3.13 analysis/round5/r5_python_sim.py

# Rust scenario smoke test
cd rust_simulator && \
  R5_SCENARIO_PARAMS=$(pwd)/../calibration/r5/scenario_params.json \
  cargo run --release --bin r5_smoke -- 50

# Full R5 MC backtest against the active trader (auto-detects R5)
prosperity4mcbt traders/round5/submission.py --quick
prosperity4mcbt traders/round5/submission.py --heavy
```

## Subcommands

Parse the user's input to determine which subcommand to run. If no subcommand is given, default to **status**.

---

### `/prosperity` or `/prosperity status`

Show a status overview:

1. Resolve the active round and read `traders/round<N>/submission.py`. Extract class-level constants / `PARAMS` dict to list all products and their key parameters.
2. List the most recent results in `tmp/backtests/` and `tmp/results/`. Report the best-available PnL stats if present.
3. List all available data directories (`data/prosperity4/round*/`). Flag any round whose directory exists but is empty — that means we're waiting on IMC to publish.
4. Peek at `results/round{1,2,3,4}/` for post-round-close portal logs (portal sub id as filename).
5. For R5: report whether `calibration/r5/scenario_params.json` exists and is current.

Format output as a concise dashboard:

```
## Prosperity Status
**Active round**: 5 (traders/round5/submission.py)
**Products**: 50 across 10 categories (Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV-Visors, Translators, Panels, Oxygen Shakes, Snackpacks) — position limit 10 each
**R5 sim**: 2-layer scenario (calibration/r5/scenario_params.json) — joint FVs + 3 pulse processes
**Last Backtest**: MC quick — Mean: <X> XIRECs (std: <Y>)
**Data available**: round0..round5
**Recent submissions**: 542976 (R4 final, marco_rubio_v2), 485183 (R3 final, 11,141), 360419 (R2 final), 269599 (R1 final)
```

---

### `/prosperity backtest` or `/prosperity backtest [round]`

Run the Monte Carlo backtester and report results:

1. Default to the **active round's trader** (`traders/round<N>/submission.py`). If the user passes a round number, target that round's trader instead.
2. Run: `cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity4mcbt traders/round<N>/submission.py --quick` — use `--quick` for iteration, `--heavy` for final eval. Output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json` — only pass `--out` if you need a specific path.
3. **R5-specific**: the sim auto-detects R5 from the trader's symbol declarations and routes through `R5Scenario` (joint FVs + shared pulses). If `R5Scenario::load()` fails to find `calibration/r5/scenario_params.json`, set `R5_SCENARIO_PARAMS=$(pwd)/calibration/r5/scenario_params.json` and rerun. To validate the scenario itself (not the trader), use `cd rust_simulator && cargo run --release --bin r5_smoke -- 50`.
4. Parse the output for per-product PnL statistics (mean, std, percentiles).
5. Compare against previous backtest results in `tmp/backtests/` if available.
6. Report results with clear comparison showing improvement or regression.

For a quick sanity check, use CSV replay instead (pass a round number whose data exists):
```bash
prosperity3bt traders/round<N>/submission.py <data_round>
```

If the backtest fails, read the error carefully and diagnose it. Common issues:
- Import errors (missing modules)
- Position limit violations (R5 limit = 10 — quote sizes must be small)
- Syntax errors in the trader file
- Rust binary not built (see BACKTEST.md "Windows: Application Control")
- `R5Scenario::load()` cannot find `calibration/r5/scenario_params.json` — set the `R5_SCENARIO_PARAMS` env var

---

### `/prosperity analyze` or `/prosperity analyze [round]`

Run exploratory data analysis on the specified round (defaults to active round):

1. Look under `data/prosperity4/round<N>/` for `prices_round_<N>_day_*.csv` and `trades_*.csv` (R5 day numbering is 2/3/4; R0–R4 used `-2/-1/0`).
2. Use pandas (`py -3.13`) for the analysis. There's no fixed EDA script — write inline or in a scratch file under `tmp/` as needed. R5 has a rich set of EDA scripts under `analysis/round5/` (`eda.py`, `book_structure.py`, `pulse_dive.py`, `pebbles_dive.py`, `snackpack_dive.py`, `fv_dynamics.py`, `basket_search.py`, `trade_event_structure.py`, `variance_ratio.py`).
3. Highlight actionable insights per product:
   - Is the fair value estimate correct? (compare vs calibrated FV if available)
   - Are spreads tight enough to capture edge?
   - Trade frequency and typical volume?
   - Drift patterns / autocorrelation / regime changes?
   - For R5 specifically: are there cross-product constraints (basket sums, pair sums) or shared pulse signatures (groups of products firing together)?
4. **Calibration template by round:**
   - R5 — group/scenario-level: `analysis/round5/rigorous_calibration.py` writes `calibration_r5.json`; the Rust-ready bundle is `calibration/r5/scenario_params.json`. R5 does not use per-asset `calibration/<name>/` directories.
   - R3/R4 — per-asset: `calibration/intarian_pepper_root/scripts/calibrate.py` (drift) or `calibration/ash_coated_osmium/scripts/calibrate.py` (random walk) as templates.

---

### `/prosperity submit`

Validate the active trader for submission readiness:

1. **Read `traders/round<N>/submission.py`** and check:
   - Has a `Trader` class
   - Has a `run(self, state: TradingState)` method
   - Returns a 3-tuple `(result, conversions, traderData)`
   - `result` is `Dict[str, List[Order]]`
   - `conversions` is `int`
   - `traderData` is `str`
   - All imports are from allowed modules (standard library, numpy, jsonpickle, datamodel)
   - No file I/O, no network calls, no subprocess usage
   - No environment variable reads that won't exist in the sandbox
   - Worst-case order sizing respects position limits (the exchange cancels **ALL** orders on a product if any fill combo could breach the limit — see CLAUDE.md pitfalls)
   - For R5: every position limit is **10** — quote sizes must be small enough that worst-case bid + worst-case ask cannot push past 10. Note that R3/R4 products are no longer tradeable, so handlers for OSMIUM/PEPPER/HYDROGEL/VELVETFRUIT/VEV_* must NOT appear in the R5 submission.
   - For R3/R4: handlers exist for every listed product in that round.

2. **Run a quick backtest** to confirm no runtime errors:
   ```
   cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity4mcbt traders/round<N>/submission.py --quick --out tmp/results/dashboard.json
   ```

3. **Report**:
   - Pass/fail for each check
   - Warnings for any issues
   - Final verdict: "Ready to submit" or "Fix issues before submitting"
   - Remind the user to upload the single active-round `submission.py` file on the Prosperity platform

---

### `/prosperity optimize [product]`

Analyze and suggest parameter improvements for a specific product:

1. **Read `traders/round<N>/submission.py`** to get current parameters (class constants or `PARAMS` dict) for the product.
2. **Read the relevant price/trade CSVs** from `data/prosperity4/round<N>/` (or the round where the product was introduced).
3. **Analyze**:
   - Is the fair-value estimator correct? Compare against calibrated FV (R5: `calibration/r5/scenario_params.json` for per-asset OU params; R3/R4: `calibration/<asset>/calibration.md`).
   - Spread optimality: too wide = missing fills, too narrow = adverse selection.
   - For drifting/trending products, check whether the smoothing alpha is tuned.
   - Are take thresholds capturing enough edge?
   - Is inventory management (soft/hard limits, skew) appropriate?
   - For R5: with limit = 10, even tiny quote sizes can breach worst-case math. Check that bid_size + ask_size + |position| ≤ 10 across all market scenarios.
4. **Suggest specific parameter changes** with reasoning.
5. **Optionally run a Monte Carlo backtest** with the suggested changes to show projected improvement.

If no product is specified, analyze all products.

---

## General Guidelines

- Always `cd` to the project directory before running commands
- Use `py -3.13` for all Python execution
- Set `PYTHONIOENCODING=utf-8` when output may contain unicode
- When showing PnL changes, use clear +/- formatting and highlight improvements
- Reference CLAUDE.md and BACKTEST.md for project context when needed
- The competition can swap products each round — always inspect `traders/round<N>/submission.py` for the current set of handled products before making assumptions
- Prior-round products do **not** always carry forward (R3 dropped OSMIUM/PEPPER, R5 dropped the entire R3/R4 book). Only extend handlers when the round wiki confirms continuity; otherwise replace.
