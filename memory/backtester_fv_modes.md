---
name: prosperity4mcbt FV modes and signal testing
description: MC backtester simulate vs replay modes and when each can measure directional signals
type: reference
---

`prosperity4mcbt --fv-mode` controls OSMIUM fair value generation in the Rust Monte Carlo sim:

- **`simulate` (default)**: F_t = 10000 constant. No FV dynamics. Directional signals (OBI→return, mean reversion, step-reversal) have nothing to predict — these signals show ≈0 effect here regardless of real-world edge. Use for pure market-making fill-rate tests only.
- **`replay`**: replays real historical FV from `data/prosperity4/round1/`. Preserves AC(-0.50) step reversals, OU reversion to μ≈10000, and volatility clustering. Huge per-session PnL variance (std ~113K) because extreme real-FV paths dominate. Median is the robust stat, not mean.

For modest ACO signal changes (~+500 PnL), `--quick` (100 sessions) is too noisy. Use `--heavy` (1000 sessions) to detect via shifted median.

MC bots' book quotes are calibrated but **decoupled from FV direction** — OBI in the sim is noise even in replay mode. So OBI-specific signals can't be measured locally; trust real-data analysis (friend found +0.59 OBI→return corr on d-2/d-1/d0) and ship as a free option.

`prosperity3bt --match-trades all` over-reports MM PnL by ~50K/day and is insensitive to 1-tick quote skews — treat ±200 PnL deltas there as noise.
