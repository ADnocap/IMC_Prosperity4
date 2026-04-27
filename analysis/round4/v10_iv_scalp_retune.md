# V10 IV-scalp re-tune — confirms V10 IV-scalp is locked

**Date:** 2026-04-28. **Verdict:** No further IV-scalp tweak helps at the
new V10 (MR_K=0.080) baseline. V10 stays as-is.

## Hypothesis tested

The 141-trial `iv_scalp_tune` from V2 was run at `MR_K=0.045`. With V10
bumping `MR_K` to 0.080 (wider stratton MR target on VELVETFRUIT), the
IV-scalp activity gate / open thresholds *might* have a slightly shifted
optimum due to interactions through smile_a or per-tick edge.

## Result — 15-trial random search at V10 baseline

`tmp/optimizer/v10_iv_scalp_main/results.csv`. Same 9 IV-scalp params,
same ranges as the original V2 search:

| Metric | Value |
|---|---|
| Trials | 15 |
| Beat V10 total | **0 / 15** |
| Beat V10 BOTH train AND holdout | **0 / 15** |
| Train↔holdout correlation | +0.374 (positive — well-behaved) |

Top 5 (none beat V10):

| Trial | THR_OPEN | THR_CLOSE | IV_THR | SCALP_MAX | Train | Holdout | Total |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **0 (V10)** | 0.54 | −0.40 | 1.09 | 35 | 17,558 | 12,735 | **30,293** |
| 8 | 0.53 | +0.10 | 1.01 | 53 | 16,760 | 12,527 | 29,286 |
| 1 | 0.93 | +0.31 | 1.46 | 94 | 17,704 | 11,557 | 29,261 |
| 5 | 0.40 | +0.44 | 0.92 | 56 | 16,256 | 12,598 | 28,853 |
| 7 | 0.79 | −0.38 | 0.64 | 83 | 15,870 | 12,773 | 28,644 |

## Interpretation

V10's IV-scalp surface is well-behaved (+0.37 corr) and the V2-inherited
optimum (THR_OPEN=0.536, THR_CLOSE=−0.4, IV_THR=1.09, SCALP=35) holds at
the new MR_K=0.080 baseline. This makes mechanistic sense:

- IV-scalp operates on **vouchers** (VEV_5000–5500); MR_K is a knob on
  **VELVETFRUIT** stratton MR. The two systems share only the smile_a
  online refit, but smile_a is computed from observed voucher IVs and
  doesn't depend on VELVET position.
- The 141-trial iv_scalp_tune already converged at the (THR_OPEN=0.536,
  …) locus from random + neighborhood probes. A 15-trial coarse random
  search at the slightly-different V10 baseline will not surface a new
  optimum unless the surface fundamentally shifted, and it didn't.

## Action

Ship V10 as is (MR_K=0.080, IV-scalp params identical to V2).
`traders/round4/submission_v10.py` is the candidate.
`traders/round4/submission_v10_tunable.py` preserved for any future
joint sweeps (it has both MR_K-style and IV-scalp env-var hooks).

## Cumulative R4 status — locked at V10

| Approach | Result |
|---|---|
| V2 baseline | +29,934 |
| **V10 = V2 + MR_K bump 0.045 → 0.080** | **+30,293 (+359, D3 OOS +423)** ← ship |
| V10 IV-scalp retune | 0/15 beat V10 |

V2 → V10 is the only positive-result variant out of 12+ structural
prototypes and 200+ trials this round. Total uplift +1.2% with positive
holdout signal and well-behaved param surface. Ship V10.
