# IMC Prosperity 4

Algorithmic trading competition workspace with a Rust-backed Monte Carlo backtester.

## Quick Start

```bash
# Install backtester
cd backtester && pip install -e . && cd ..

# Run Monte Carlo backtest (active round's trader)
prosperity4mcbt traders/round3/a.py --quick --out tmp/results/dashboard.json

# Run with dashboard
prosperity4mcbt traders/round3/a.py --quick --vis --out tmp/results/dashboard.json
```

See [BACKTEST.md](BACKTEST.md) for full backtesting guide and calibration methodology.

## Repo Layout

```
IMC_trading_hack/
├── traders/                       # Shipped submission per round (single file each)
│   ├── round3/a.py                #   ACTIVE — submit this
│   ├── round2/submission.py       #   R2 final (portal sub 360419)
│   ├── round1/submission.py       #   R1 final (portal sub 269599)
│   ├── datamodel.py               #   Official Prosperity 4 data model
│   └── trader_hold1.py            #   Hold-1-unit FV-extraction strategy
├── results/round{1,2,3}/          # Post-round-close submission snapshots (.png / .log / .json)
├── analysis/round{1,2,3}/         # Market-data analysis scripts + findings per round
├── data/
│   ├── prosperity4/round{0,1,2}/  #   P4 CSVs (R3 placeholder until IMC drops data)
│   └── prosperity3/round1-8/      #   P3 historical data (reference)
├── backtester/                    # Backtester package (prosperity3bt + prosperity4mcbt CLIs)
├── rust_simulator/                # Rust Monte Carlo simulation engine
├── visualizer/                    # Local dashboard frontend (Vite/React)
├── calibration/                   # Bot reverse-engineering, one dir per asset (emeralds, tomatoes, ash_coated_osmium, intarian_pepper_root)
├── manual/                        # Manual trading challenges (round{1,2,3}/)
├── submission_results/            # Raw logs from intermediate portal submissions
├── scripts/                       # Helper utilities (strategy worker, fill analytics)
├── BACKTEST.md                    # Backtesting & calibration guide
└── CLAUDE.md                      # Project context for Claude
```

## Backtesting Tools

| Tool | Purpose | Speed |
|------|---------|-------|
| `prosperity4mcbt` | Monte Carlo simulation (primary) | ~6s quick, ~55s heavy |
| `prosperity3bt` | Historical CSV replay | ~1s |
| `scripts/bt_stats.py` | Fill analytics (maker vs taker) | ~1s |

## How the Monte Carlo Works

The simulator generates synthetic market sessions using calibrated bot models reverse-engineered from tutorial data:

1. **Fair value**: EMERALDS fixed at 10,000; TOMATOES follows a Gaussian random walk N(0, 0.496^2)
2. **Bot quotes**: 3 bots place orders around fair value with calibrated spreads, rounding rules, and volume distributions
3. **Your algo runs**: sees the bot-only book, places orders
4. **Bot takers**: simulated market trades hit your resting orders

Parameters were extracted by submitting a hold-1-unit strategy to recover true server fair value, then fitting bot quote rules to >96% accuracy. See [BACKTEST.md](BACKTEST.md) for details.

## Competition

- **IMC Prosperity 4** (2026): April 14-30 (5 rounds). Round 3 active from 2026-04-21; R1 and R2 cleared.
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki
- **Submission**: Single Python file (currently `traders/round3/a.py`) with `Trader.run(state)` method
- **Constraints**: stdlib + numpy + jsonpickle only, ~100MB memory, no file/network access

## Attribution

Backtester and visualizer adapted from [chrispyroberts/imc-prosperity-4](https://github.com/chrispyroberts/imc-prosperity-4), which builds on [jmerle's Prosperity 3 tooling](https://github.com/jmerle/imc-prosperity-3-backtester).
