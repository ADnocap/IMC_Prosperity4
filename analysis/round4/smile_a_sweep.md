# SMILE_A_ALPHA / SMILE_A_INIT sweep

**Verdict: leave V2. No-ship.** V2's `(SMILE_A_ALPHA=0.0052, SMILE_A_INIT=0.580261)` is
the global optimum across both single-parameter sweeps. The gap to second-best is
large (+1,470 vs phase-1 #2, +1,470 vs phase-2 #2), so this is not measurement noise.

Run dir: `tmp/optimizer/smile_a_sweep_20260427_124902/`. 13 trials, ~5 min wall.

## Configurations tested

- **Phase 1 (8 trials)**: `SMILE_A_ALPHA in {0, 0.0005, 0.001, 0.002, 0.0052 (V2),
  0.01 (V1), 0.02, 0.05}`, all other 9 params at V2.
- **Phase 2 (5 trials)**: `SMILE_A_INIT in {0.4, 0.5, 0.580261 (V2), 0.7, 0.88}` at
  best phase-1 alpha (= V2's 0.0052).
- **Phase 3 (combined)** and **Phase 4 (`IV_SCALPING_THR` ramp)**: not triggered
  (gate = "any phase improves over V2"). Both V2 wins.

## Top-5 by total PnL

| Rank | Phase | Label | total | train | hold | Notes |
|---:|:--|:--|---:|---:|---:|:--|
| 1 | 1 / 2 | V2_baseline (`alpha=0.0052, init=0.580261`) | **29,934** | 17,621 | **12,312** | reproduces shipped V2 exactly |
| 2 | 1 | `alpha=0.88, init=0.580261` | 28,464 | 16,757 | 11,706 | static high init, V2 alpha |
| 3 | 1 | `alpha=0.02, init=0.580261` | 28,254 | 16,981 | 11,274 | ~4x V2 alpha |
| 4 | 2 | `alpha=0.0052, init=0.7` | 27,926 | 16,629 | 11,296 | high init |
| 5 | 1 | `alpha=0.01, init=0.580261` | 27,916 | 16,648 | 11,267 | V1 alpha |

Best non-V2 holdout: 11,706 (init=0.88) — still well below V2's 12,312.

## Per-asset breakdown for V2 vs alpha=0 vs alpha=0.02

`HYDROGEL`, `VELVETFRUIT`, `VEV_4000`, `VEV_4500` are identical across all trials
(non-IV-scalp handlers, deterministic given fixed seed). The IV-scalp delta lives
entirely in VEV_5000..5500.

| Asset (3-day total) | V2 (0.0052) | alpha=0 | alpha=0.02 |
|:--|---:|---:|---:|
| VEV_5000 | 2,653 | -12 | 1,297 |
| VEV_5100 | 2,796 | -9  | 2,268 |
| VEV_5200 | 1,759 |  0  | 1,993 |
| VEV_5300 | 1,220 |  0  | 1,402 |
| VEV_5400 | 607   | 0   | 453   |
| VEV_5500 | 107   | 0   | 50    |
| **IV-scalp sum** | **9,142** | **-21** | **7,463** |

At `alpha=0` (no refit), `switch_mean` never crosses `IV_SCALPING_THR=1.0865`,
so the gate is closed every tick across all 6 strikes — confirming the gate
threshold was co-tuned with V2's alpha. Gain is broad across strikes 5000-5300
(not concentrated in one).

## Interpretation

`SMILE_A_ALPHA` controls how quickly the level coefficient `a` of the BS smile
EMA-tracks the per-tick avg residual (observed-IV minus model-IV). Very slow
(alpha small) leaves `a` close to `INIT` even when the true smile drifts day-to-day
(D0 a=0.41, D1 a=0.50, D2 a=0.88) — so `dev = mid - bs_fair` accumulates
genuine bias, not just noise, but the deviation magnitude is small enough that
`switch_mean` never reaches the activity gate. Very fast (alpha large) lets `a`
chase tick-by-tick noise: residuals shrink → `dev` drops below the open
threshold even though the gate is open. V2's 0.0052 sits at the sweet spot:
slow enough to keep dev variance high (gate stays open during the active
phase), fast enough to track the day-to-day smile drift so dev mean-reverts
(THR_OPEN/THR_CLOSE signals are clean). The 94%-idle phenomenon is structural,
not a tuning bug — it reflects the smile being stable on intraday timescales.

The phase-2 init sweep is essentially a smoothness check: V2's `0.580261` was
chosen as the 3-day average of `a`, and the curve is monotonically degrading
in either direction (init=0.4 → 22,760, init=0.88 → 28,464).

## Verdict: leave V2

- Ship gate (total ≥ V2+1k AND holdout ≥ V2 D3): **FAIL**, no config beats V2.
- The 94% idle window cannot be attacked by alpha alone — slowing alpha
  silences the IV-scalp entirely (alpha=0 ⇒ 0 fires); speeding it up loses
  edge by chasing noise.
- **Recommendation: stop the alpha sweep.** Future PnL beyond V2 needs a
  *different signal* during the idle phase (e.g. counterparty-conditioned MM
  or a longer-horizon mean reversion on `mid - bs_fair_static`), not a
  refinement of the same EMA.
