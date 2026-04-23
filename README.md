# IMC Prosperity 4

Algorithmic trading competition workspace with a Rust-backed Monte Carlo backtester, an Optuna-based parameter optimizer, and a browser-based market-microstructure analysis workshop.

## Quick Start

```bash
# Install backtester + optimizer
cd backtester && pip install -e . && cd ..

# Run Monte Carlo backtest (active round's trader)
prosperity4mcbt traders/round3/a.py --quick

# Tune trader params via Bayesian optimization
prosperity4opt studies/round2_signal_tuning.yaml --fresh

# Run with dashboard (Workshop + Optimize + Calibration + Submissions tabs)
prosperity4mcbt traders/round3/a.py --quick --vis

# Or launch the full dashboard (frontend + data server + WASM compute) directly:
./run.sh        # macOS / Linux
.\run.ps1       # Windows
```

Artifacts:
- Backtest runs → `tmp/backtests/<timestamp>_monte_carlo/dashboard.json`
- Optimizer studies → `tmp/optimizer/<study_name>/` (SQLite + parquet + validators.json)

See:

- [BACKTEST.md](BACKTEST.md) — full backtesting guide, calibration methodology, flag reference.
- [optimizer/README.md](optimizer/README.md) — parameter-optimization framework (Optuna + TPE/CMA-ES + anti-overfitting validators).
- [DATA_WORKSHOP.md](DATA_WORKSHOP.md) — the Workshop tab: 13 market-microstructure panels powered by Rust/WASM kernels. **Load P3 R5 to see every feature light up.**

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
├── wasm_compute/                  # Rust/WASM kernels for the Workshop (13 microstructure kernels)
├── visualizer/                    # Local dashboard frontend (Vite/React) — Workshop + Optimize tabs
├── optimizer/                     # Parameter-optimization framework (Optuna + validators)
├── studies/                       # Declarative YAML studies (one per tuning campaign)
├── calibration/                   # Bot reverse-engineering, one dir per asset (emeralds, tomatoes, ash_coated_osmium, intarian_pepper_root)
├── manual/                        # Manual trading challenges (round{1,2,3}/)
├── tmp/                           # Backtest + optimizer artifacts (MC dashboards, study DBs)
├── scripts/                       # Helper utilities (strategy worker, fill analytics)
├── BACKTEST.md                    # Backtesting & calibration guide
├── DATA_WORKSHOP.md               # Data Analysis Workshop guide
├── optimizer/README.md            # Parameter-optimization framework guide
└── CLAUDE.md                      # Project context for Claude
```

## Data Analysis Workshop

Browser-based market-microstructure lab for any historical round (P3 and P4). Launch via `./run.sh` / `.\run.ps1` and click the **Workshop** tab. Features:

- **Overview**: mid/microprice overlay, bid-ask spread with distribution
- **LOB**: book-depth stacked area, queue imbalance → next-k-tick return (signal curve), Cont-Kukanov OFI
- **MM Alpha**: mark-out by counterparty (THE Prosperity alpha), effective vs realized spread, trade offset from mid
- **Cross-Asset**: return correlation matrix, lead-lag CCF, pair-spread with OU half-life
- **Exogenous**: auto-line chart per observation column, lagged-β table
- **Seasonality**: intraday spread + return-vol patterns

All compute in Rust/WASM, dispatched to a Web Worker. Tabs schema-gate themselves — load a round and only the panels whose data is present light up. **Load P3 R5 for the full tour** — see [DATA_WORKSHOP.md](DATA_WORKSHOP.md) for the detailed guide.

## Backtesting Tools

| Tool                  | Purpose                                                 | Speed                                       |
| --------------------- | ------------------------------------------------------- | ------------------------------------------- |
| `prosperity4mcbt`     | Monte Carlo simulation (primary)                        | ~6s quick, ~55s heavy                       |
| `prosperity4opt`      | Parameter optimization via Optuna (TPE/CMA-ES/QMC)      | per-study, ~5-60 min depending on scale     |
| `prosperity3bt`       | Historical CSV replay                                   | ~1s                                         |
| `scripts/bt_stats.py` | Fill analytics (maker vs taker)                         | ~1s                                         |

## Parameter Optimization

Study-based hyperparameter tuning on top of the Monte Carlo sim. Declare a search space + objective in `studies/<name>.yaml`, point at a trader that reads `os.environ["PROSPERITY_PARAMS"]`, and run:

```bash
prosperity4opt studies/<name>.yaml --fresh
```

Features:
- Samplers: random / TPE (Bayesian) / CMA-ES / QMC (Sobol)
- Seed splits: per-trial train/val slice + end-of-study retest on fresh test seeds
- Objectives: `mean_pnl`, `sharpe`, `cvar_5/10`, per-symbol PnL, composable with weights
- Anti-overfitting validators: Deflated Sharpe Ratio, Probability of Backtest Overfitting (CSCV), cluster stability, fANOVA importance
- Outputs: resumable SQLite + parquet export + validators.json + top-K CSV
- Optimize tab in the visualizer: study picker, convergence, importance bar chart, 1D param effects, 2D slice scatter, top-K table

Full schema + interpretation guide in [optimizer/README.md](optimizer/README.md).

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
