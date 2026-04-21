---
name: prosperity
description: Helper for the IMC Prosperity 4 algorithmic trading competition. Use this skill whenever the user wants to backtest their trading algorithm, analyze market data, validate their submission, optimize strategy parameters, or check their competition status. Trigger on mentions of prosperity, backtesting trader.py, trading strategy optimization, submission validation, or EDA on round data. Also trigger when the user says things like "run the bot", "test my algo", "check my PnL", "how's my strategy doing", or "prepare for submission".
---

# Prosperity - IMC Trading Competition Helper

You are helping with the IMC Prosperity 4 algorithmic trading competition. The project lives at `C:\Users\alexa\OneDrive\Documents\IMC_trading_hack`.

## Setup

- **Python**: Use `py -3.13` (Python 3.13)
- **Monte Carlo backtester**: `prosperity4mcbt` CLI (install: `cd backtester && pip install -e .`)
- **CSV replay**: `prosperity3bt` CLI (same package)
- **Active trader file**: lives under `traders/round<N>/a.py` where N is the current round. Determine N by listing `traders/` — the highest-numbered `roundN/` directory is the active round. Round 3 is active as of 2026-04-21 (R1 and R2 shipped — results in `results/round{1,2}/`).
- **Data**: per-round CSVs in `data/prosperity4/round<N>/` (semicolon-delimited). R0–R2 data are present; R3 lands when IMC publishes.
- **Unicode output**: Prefix commands with `PYTHONIOENCODING=utf-8` when needed

## Determining the active round

Before running any subcommand, resolve the active trader path:

1. List `traders/` — pick the highest `roundN/` that contains an `a.py`
2. Active trader = `traders/round<N>/a.py`
3. Active data dir = `data/prosperity4/round<N>/` (may be empty if IMC hasn't published yet — fall back to round N-1 for replay)

Use this path everywhere instead of the old `traders/a.py`.

## Subcommands

Parse the user's input to determine which subcommand to run. If no subcommand is given, default to **status**.

---

### `/prosperity` or `/prosperity status`

Show a status overview:

1. Resolve the active round and read `traders/round<N>/a.py`. Extract class-level constants / `PARAMS` dict to list all products and their key parameters.
2. List the most recent results in `tmp/backtests/` and `tmp/results/`. Report the best-available PnL stats if present.
3. List all available data directories (`data/prosperity4/round*/`). Flag any round whose directory exists but is empty — that means we're waiting on IMC to publish.
4. Peek at `results/round{1,2}/` for post-round-close portal logs (portal sub id as filename).

Format output as a concise dashboard:

```
## Prosperity Status
**Active round**: 3 (traders/round3/a.py)
**Products**: ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT  (R3 products pending data)
**Last Backtest**: MC heavy -- Mean: 10,600 XIRECs (std: 820, P05: 9,200, P95: 12,000)
**Data available**: round0, round1, round2   |   round3 EMPTY (waiting on IMC)
**Recent submissions**: 360419 (R2 final), 269599 (R1 final) — see results/round{1,2}/
```

---

### `/prosperity backtest` or `/prosperity backtest [round]`

Run the Monte Carlo backtester and report results:

1. Default to the **active round's trader**. If the user passes a round number, target that round's trader instead.
2. Run: `cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity4mcbt traders/round<N>/a.py --quick` — use `--quick` for iteration, `--heavy` for final eval. Output defaults to `tmp/backtests/<timestamp>_monte_carlo/dashboard.json` — only pass `--out` if you need a specific path.
3. Parse the output for per-product PnL statistics (mean, std, percentiles).
4. Compare against previous backtest results in `tmp/backtests/` if available.
5. Report results with clear comparison showing improvement or regression.

For a quick sanity check, use CSV replay instead (pass a round number whose data exists):
```bash
prosperity3bt traders/round<N>/a.py <data_round>
```

If the backtest fails, read the error carefully and diagnose it. Common issues:
- Import errors (missing modules)
- Position limit violations
- Syntax errors in the trader file
- Rust binary not built (see BACKTEST.md "Windows: Application Control")

---

### `/prosperity analyze` or `/prosperity analyze [round]`

Run exploratory data analysis on the specified round (defaults to active round):

1. Look under `data/prosperity4/round<N>/` for `prices_round_<N>_day_{-2,-1,0}.csv` and `trades_*.csv`.
2. Use pandas (`py -3.13`) for the analysis. There's no fixed EDA script — write inline or in a scratch file under `tmp/` as needed.
3. Highlight actionable insights per product:
   - Is the fair value estimate correct? (compare vs calibrated FV if available)
   - Are spreads tight enough to capture edge?
   - Trade frequency and typical volume?
   - Drift patterns / autocorrelation / regime changes?
4. If analyzing a brand-new round right after IMC publishes, FIRST check whether calibration exists under `calibration/<asset_name>/`. If not, point the user at `calibration/intarian_pepper_root/scripts/calibrate.py` (drift process) or `calibration/ash_coated_osmium/scripts/calibrate.py` (random walk) as templates.

---

### `/prosperity submit`

Validate the active trader for submission readiness:

1. **Read `traders/round<N>/a.py`** and check:
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
   - Handlers still exist for all prior-round products (they remain tradeable)

2. **Run a quick backtest** to confirm no runtime errors:
   ```
   cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity4mcbt traders/round<N>/a.py --quick --out tmp/results/dashboard.json
   ```

3. **Report**:
   - Pass/fail for each check
   - Warnings for any issues
   - Final verdict: "Ready to submit" or "Fix issues before submitting"
   - Remind the user to upload the single active-round `a.py` file on the Prosperity platform

---

### `/prosperity optimize [product]`

Analyze and suggest parameter improvements for a specific product:

1. **Read `traders/round<N>/a.py`** to get current parameters (class constants or `PARAMS` dict) for the product.
2. **Read the relevant price/trade CSVs** from `data/prosperity4/round<N>/` (or the round where the product was introduced).
3. **Analyze**:
   - Is the fair-value estimator correct? Compare against calibrated FV (see `calibration/round<N>_calibration.md`).
   - Spread optimality: too wide = missing fills, too narrow = adverse selection.
   - For drifting/trending products, check whether the smoothing alpha is tuned.
   - Are take thresholds capturing enough edge?
   - Is inventory management (soft/hard limits, skew) appropriate?
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
- The competition adds new products each round — always inspect `traders/round<N>/a.py` for the current set of handled products before making assumptions
- Prior-round products remain tradeable — never delete handlers when starting a new round, extend them
