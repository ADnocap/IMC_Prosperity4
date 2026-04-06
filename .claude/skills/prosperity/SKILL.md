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
- **Main algo file**: `traders/a.py` (single-file submission with `Trader` class)
- **Data**: `data/round0/` and subsequent `round_N/` folders
- **Analysis**: `analysis/tutorial_eda.py`
- **Unicode output**: Prefix commands with `PYTHONIOENCODING=utf-8` when needed

## Subcommands

Parse the user's input to determine which subcommand to run. If no subcommand is given, default to **status**.

---

### `/prosperity` or `/prosperity status`

Show a status overview:

1. Read `traders/a.py` and extract the `PARAMS` dict to list all products, their strategies, and key parameters
2. Find the most recent results in `tmp/` directory
3. If recent backtest results exist, report the PnL breakdown. If not, suggest running a backtest.
4. List all available data directories (data/round0, round_N, etc.)

Format output as a concise dashboard:

```
## Prosperity Status
**Products**: EMERALDS (fixed_mm, fair=10000), TOMATOES (adaptive_mm, ema=0.15)
**Last Backtest**: Monte Carlo heavy -- Mean: 1,200 XIRECs (std: 450, P05: 300, P95: 2,100)
**Available Data**: data/round0
```

---

### `/prosperity backtest` or `/prosperity backtest [round]`

Run the Monte Carlo backtester and report results:

1. Default round is `0` (tutorial). Use `--quick` for fast iteration, `--heavy` for final eval.
2. Run: `cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity4mcbt traders/a.py --quick --out tmp/results/dashboard.json`
3. Parse the output for per-product PnL statistics (mean, std, percentiles)
4. Compare against previous backtest results if available
5. Report results with clear comparison showing improvement or regression

For a quick sanity check, use CSV replay instead:
```bash
prosperity3bt traders/a.py 0 --data data
```

If the backtest fails, read the error carefully and diagnose it. Common issues:
- Import errors (missing modules)
- Position limit violations
- Syntax errors in traders/a.py

---

### `/prosperity analyze` or `/prosperity analyze [round]`

Run exploratory data analysis:

1. Run: `cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && PYTHONIOENCODING=utf-8 py -3.13 analysis/tutorial_eda.py`
2. Parse the output and present key findings in a structured summary
3. Highlight actionable insights:
   - Is the fair value estimate correct for each product?
   - Are spreads tight enough to capture edge?
   - What's the trade frequency and typical volume?
   - Any drift patterns that need attention?

If analyzing a new round's data, check if the EDA script needs updating first (it may only handle tutorial data).

---

### `/prosperity submit`

Validate `traders/a.py` for submission readiness:

1. **Read `traders/a.py`** and check:
   - Has a `Trader` class
   - Has a `run(self, state: TradingState)` method
   - Returns a 3-tuple `(result, conversions, traderData)`
   - `result` is `Dict[str, List[Order]]`
   - `conversions` is `int`
   - `traderData` is `str`
   - All imports are from allowed modules (standard library, numpy, jsonpickle, datamodel)
   - No file I/O, no network calls, no subprocess usage
   - No environment variable reads that won't exist in the sandbox
   - Position limits are respected (check that worst-case fills don't exceed limits)

2. **Run a quick backtest** to confirm no runtime errors:
   `cd "C:/Users/alexa/OneDrive/Documents/IMC_trading_hack" && prosperity3bt traders/a.py 0 --data data`

3. **Report**:
   - Green/pass for each check
   - Warnings for any issues
   - Final verdict: "Ready to submit" or "Fix issues before submitting"
   - Remind the user to upload the single `traders/a.py` file on the Prosperity platform

---

### `/prosperity optimize [product]`

Analyze and suggest parameter improvements for a specific product:

1. **Read `traders/a.py`** to get current parameters for the product
2. **Read the relevant price/trade CSVs** for that product
3. **Analyze**:
   - Is the fair value correct? Compare against actual mid-price distribution
   - Is the spread optimal? Too wide = missing fills, too narrow = adverse selection
   - Is the EMA alpha tuned well? Compare different alpha values against the price series
   - Are take_width thresholds capturing enough edge?
   - Is the soft_limit/hard_limit balance right for inventory management?
4. **Suggest specific parameter changes** with reasoning
5. **Optionally run a Monte Carlo backtest** with the suggested changes to show projected improvement

If no product is specified, analyze all products.

---

## General Guidelines

- Always `cd` to the project directory before running commands
- Use `py -3.13` for all Python execution
- Set `PYTHONIOENCODING=utf-8` when output may contain unicode
- When showing PnL changes, use clear +/- formatting and highlight improvements
- Reference the CLAUDE.md and BACKTEST.md for project context when needed
- The competition adds new products each round - check what products exist in traders/a.py's PARAMS before making assumptions
