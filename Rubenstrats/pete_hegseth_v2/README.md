# pete_hegseth_v2

**Harry_potter_v8 + Black-Scholes smile fair value on VEV_5000..5500.**

## Why this exists

- `pete_hegseth_v1` (Mark 67/49 counterparty follower) lost −570 on the portal — spread crossing eats more than the +2 mid-unit signal can deliver.
- Friend's submission (491539, +35,956) made >97% of its PnL from a Black-Scholes smile fitter on the 6 ATM-area vouchers. They price each voucher as a call on VELVETFRUIT, fade dispersions from the smile.
- v8's univariate per-voucher EMA misses this entirely: when VELVETFRUIT moves, voucher fair moves via Δ immediately, but v8's slow EMA (α=0.0005) lags and v8 fades the legitimate underlying move.

v2 keeps Harry_potter_v8 wholesale and only swaps the FV source for VEV_5000..5500.

## Model

```
iv(K) = a + b·m + c·m²,   m = log(K/S) / √T_years
fair  = BS_call(S, K, iv(K), T_years)
dev   = mid − fair
```

- `b = 0.0337`, `c = 0.0898` locked from R3 calibration (curvature stable).
- `a` cold-started at tick 1 from observed IVs (one-shot calibration), then refit online via EMA at α=0.0052.
- Per voucher: `mean_dev` and `sigma_dev` tracked via EMAs (α=0.02). Used as the v8 MR's FV and noise scale: `fv = fair + mean_dev`, `z = (mid − fv) / sigma_dev`.

The cold-start matters: `SMILE_A_INIT=0.580` is calibrated to R3 days, but R4 day 3 sits at IV ≈ 0.30. Without cold-start, the slow EMA refit takes ~200 ticks to converge — during which the FV is wildly wrong and we'd trade nonsense. Cold-start uses one tick's chain-wide observed IVs to solve for `a` directly.

## Execution (smile mode, vs v8)

| | v8 default | smile-mode override |
|---|---|---|
| Take threshold | `\|z\| ≥ MR_TAKE_Z = 1.2` | `\|z\| ≥ SMILE_TAKE_Z = 0.6` AND `\|dev\| ≥ 0.4` |
| Min spread for entry | `≥ 2` | `≥ 1` (takes only; passive layers skipped on 1-tick) |
| FV source | EMA of mid (per-asset, α=0.0005) | `smile_fair + slow EMA of residuals` |
| Sigma source | EMA of mid residuals², floored ≥ 1.0 | EMA of dev residuals² (no floor) |
| Activity gate | none | `sigma_dev ≥ 0.4` else flatten (VEV_5500-pinned regimes) |

Everything else — target sizing (`-MR_K · z`), OBI-tilted passive layers, position-gated stop-loss, HYDROGEL MR, VELVETFRUIT MR, VEV_4000/4500 OBI MM — is bit-for-bit v8.

## Smoke-test results

| Scenario | Behavior |
|---|---|
| Tick 0, R4 d3 day-open book | Cold-start: `smile_a = 0.302`, devs in ±2.7 range. VEV_5200/5300/5400 fire takes; VEV_5000/5100 quote passive. |
| VEV_5300 mid spiked from 58 → 70.5 (chain stays put) | Sells 21 at best_bid=70 in one tick — captures the dispersion via the take. |
| VEV_5400 (1-tick spread) with dev=−1.68 | Buys 21 at best_ask=21 — the relaxed spread guard lets us reach this strike. |
| VEV_5500 pinned for 2000 ticks → `sigma_dev=0.10` | Activity gate fires; existing +50 position flattened at best_bid. |
| Empty/missing order book | Returns `[]` cleanly, no crash. |

## Tunable knobs (top of `Trader` class)

```python
SMILE_A_INIT          = 0.580261          # only used if cold-start has no IVs
SMILE_B               = 0.033704          # locked from R3
SMILE_C               = 0.089775          # locked from R3
SMILE_A_ALPHA         = 0.0052            # online refit rate of `a`

SMILE_DEV_MEAN_ALPHA  = 0.02              # window ~100 for residual mean
SMILE_DEV_VAR_ALPHA   = 0.02              # window ~100 for residual variance
SMILE_DEV_VAR_INIT    = 4.0               # conservative initial sigma~2

SMILE_MIN_SIGMA       = 0.4               # below this, voucher is pinned -> flatten
SMILE_TAKE_Z          = 0.6               # take threshold (smile mode only)
SMILE_TAKE_MIN_ABS_DEV = 0.4              # price-floor on takes
```

## Next experiments

- **Test on portal**: ship and compare v2 PnL on VEV_5000..5500 to friend's +35k baseline. Most likely we leave money on the table (friend's all-in-at-touch with `THR_OPEN=0.536` is more aggressive than v8's `target = −K·z` ramp), but we should be solidly net positive.
- **Tune `SMILE_TAKE_Z` and `MR_K` separately** for smile mode if v2 underperforms friend.
- **Layer the Mark 67/49 signal on top** as quote-skew on VELVETFRUIT (no take) — v1 had the right signal but the wrong execution.
