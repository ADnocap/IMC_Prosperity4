# Pebble_fucker_v1 — basket-residual MM on the 5 PEBBLES products

## Idea

Empirical constraint (calibration/r5/scenario_params.json + analysis/round5/FINDINGS.md):

```
PEBBLES_XS + PEBBLES_S + PEBBLES_M + PEBBLES_L + PEBBLES_XL  =  50,000
(std 2.8 over 30K ticks; ~2% of ticks deviate by ±14–18 transiently)
```

Per tick we compute a single scalar:

```
r = sum(pebble_mids) - 50,000
```

`r` is **the same number for every leg**: there's no per-pebble decomposition
of the residual. A naive `edge_i = mid_i - implied_fv_i` works out to `r` for
every i, so the strategy can't pick which pebble is the offender. We trade
symmetric instead:

- `r > +threshold` → basket overpriced → only post asks on all 5
- `r < -threshold` → basket underpriced → only post bids on all 5
- `|r| ≤ threshold` → noise floor (half-tick parity) → penny-jump both sides

Whichever leg actually reverts pays out via that leg; the others wash.
Inventory-aware sizing keeps us within the per-product limit of 10.

## Backtest results (2026-04-29)

`prosperity4mcbt --quick` (100 sessions, calibrated R5 simulator, 3-day eval per session):

| | mean | std | p05 | p95 | pos_rate |
|---|---|---|---|---|---|
| **TOTAL** | **+16,315** | 1,420 | 14,147 | 18,888 | 100% |
| PEBBLES_XL | 4,431 | 18,163 | -27,023 | 32,533 | 60% |
| PEBBLES_S | 4,110 | 9,391 | -9,108 | 22,203 | 62% |
| PEBBLES_L | 4,089 | 10,518 | -15,499 | 20,488 | 66% |
| PEBBLES_XS | 1,921 | 9,455 | -12,815 | 17,612 | 57% |
| PEBBLES_M | 1,764 | 8,216 | -11,103 | 15,761 | 55% |

**Two structural observations:**

1. **All 100 sessions positive**, std 1,420 vs mean 16,315 (≈12× signal-to-noise). The strategy doesn't have a downside session in the sample.
2. **Per-leg variance is huge but the basket-sum variance is tiny.** Sum of leg stds ≈ 56k; total std is 1.4k. That's massive cross-leg anti-correlation, which is exactly the basket-arb signature: the offender on any given session captures the gain through *its* leg, the others wash. Across sessions the offender varies, so leg-level PnL is volatile but portfolio-level PnL is stable.

For comparison: R3 portal final +11,141, R4 portal final +27,444. Pebbles alone projects ~16k, and there are nine more categories to do.

### Other validation runs

`prosperity3bt Pebble_fucker_v1.py 5` (CSV replay, 3 days × 10K ticks): +54,266 total — over-fills MM per CLAUDE.md, ~3.3× overstated vs the trustworthy MC number above. Useful as a sanity check that the strategy executes cleanly.

`analysis/round5/r5_python_sim.py` (50 seeds × 3 days): 0 — that sim doesn't model step 5 of the per-tick matching ("remaining bots may trade on your quotes"), so passive MM never fills. Confirmed sim limitation, not a strategy bug.

## Open items

- **Threshold tuning** — `RESIDUAL_THRESHOLD = 1.0` is a guess. Run an
  Optuna study to sweep it (along with quote sizes and any inventory
  parameters we add later).
- **Take layer for giant residuals.** The ~2% of ticks where the basket
  deviates by ±14–18 might pay aggressive cross-spread takes when the
  residual exceeds round-trip 5-leg spread cost (~30 ticks). Test it.
- **Inventory skew.** Currently we just hard-cap at limit=10. A continuous
  z-score-style skew on quote prices (not just sides) could improve
  inventory turnover.
- **M/L are the lowest contributors** (1,764 / 4,089 mean). Both have
  middle-of-pack mids and h=6.5. Check whether their per-leg variance is
  bid/ask asymmetric — might be adverse selection from the basket gate.

## Files

- `Pebble_fucker_v1.py` — the strategy (single Trader class, no external deps)
- `run_python_mc.py` — driver that loads the Python R5 sim and runs N seeds
  through this trader. Reports 0 today; useful once the post-strategy bot
  activity is added to the sim or the Rust MC is rebuilt.
- `results/` — empty until we get a real number out
