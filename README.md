# IMC Prosperity 4

Algorithmic trading competition workspace with a Rust-backed Monte Carlo backtester.

## Quick Start

```bash
# Install backtester
cd backtester && pip install -e . && cd ..

# Run Monte Carlo backtest
prosperity4mcbt traders/trader.py --quick --out tmp/results/dashboard.json

# Run with dashboard
prosperity4mcbt traders/trader.py --quick --vis --out tmp/results/dashboard.json
```

See [BACKTEST.md](BACKTEST.md) for full backtesting guide and calibration methodology.

## Repo Layout

```
IMC_trading_hack/
├── traders/                   # All trader algorithms
│   ├── trader.py              #   Main trading algorithm (SUBMIT THIS)
│   ├── trader_hold1.py        #   Hold-1-unit strategy for FV extraction
│   ├── example_trader.py      #   IMC official starter template
│   ├── test_algo.py           #   Simple test market maker
│   └── starter.py             #   Alternate starter
├── datamodel.py               # Official Prosperity 4 data model
├── BACKTEST.md                # Backtesting & calibration guide
├── CLAUDE.md                  # Project context for Claude
├── PROSPERITY_4_WIKI_COMPLETE.md
│
├── backtester/                # Backtester package (prosperity3bt + prosperity4mcbt CLIs)
├── rust_simulator/            # Rust Monte Carlo simulation engine
├── visualizer/                # Local dashboard frontend (Vite/React)
│
├── data/round0/               # Tutorial round market data (CSVs)
├── calibration/               # Bot reverse-engineering scripts & docs
├── scripts/                   # Helper scripts (MC runner, analysis, calibration)
├── analysis/                  # EDA notebooks and scripts
│
└── bt_stats.py                # Fill analytics wrapper
```

## Backtesting Tools

| Tool | Purpose | Speed |
|------|---------|-------|
| `prosperity4mcbt` | Monte Carlo simulation (primary) | ~6s quick, ~55s heavy |
| `prosperity3bt` | Historical CSV replay | ~1s |
| `bt_stats.py` | Fill analytics (maker vs taker) | ~1s |

## How the Monte Carlo Works

The simulator generates synthetic market sessions using calibrated bot models reverse-engineered from tutorial data:

1. **Fair value**: EMERALDS fixed at 10,000; TOMATOES follows a Gaussian random walk N(0, 0.496^2)
2. **Bot quotes**: 3 bots place orders around fair value with calibrated spreads, rounding rules, and volume distributions
3. **Your algo runs**: sees the bot-only book, places orders
4. **Bot takers**: simulated market trades hit your resting orders

Parameters were extracted by submitting a hold-1-unit strategy to recover true server fair value, then fitting bot quote rules to >96% accuracy. See [BACKTEST.md](BACKTEST.md) for details.

## Competition

- **IMC Prosperity 4** (2026): April 14-30 (5 rounds)
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki
- **Submission**: Single `traders/trader.py` file with `Trader.run(state)` method
- **Constraints**: stdlib + numpy + jsonpickle only, ~100MB memory, no file/network access

## Attribution

Backtester and visualizer adapted from [chrispyroberts/imc-prosperity-4](https://github.com/chrispyroberts/imc-prosperity-4), which builds on [jmerle's Prosperity 3 tooling](https://github.com/jmerle/imc-prosperity-3-backtester).
