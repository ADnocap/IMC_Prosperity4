# V7 — Overfit audit (KILL verdict)

**Date:** 2026-04-27. **Verdict:** v7 is overfit. Don't ship. V2 stays the
ship candidate. v7's `OPTIMP_VELVET_ENABLED` defaults to `False`.

## What the initial 6-trial sweep claimed

V7 (option-implied VELVET fair as IOC take signal) looked like a +4,716
uplift over V2 R4 historical replay, with the default `thr=3.0 sz=15`
hitting **+34,650 total** (D1 13,890 / D2 9,376 / D3 11,384) vs V2's
+29,934. All 6 (thr × sz) combos in the initial narrow sweep beat V2 by
+2,630 to +4,716. Locally, a robust-looking optimum.

## What the 26-trial random search showed

`tmp/optimizer/v7_optimp_main/results.csv` (26 trials, ranges thr ∈
[1, 10], sz ∈ [5, 50], cooldown ∈ [30, 500]):

| Metric | Value | Reading |
|---|---:|---|
| Train↔holdout correlation | **−0.700** | textbook overfit signature |
| Configs beating V2 on BOTH train + holdout | **0 / 26** | not a single one |
| Best balanced config (max min(train_uplift, hold_uplift)) | thr=4.1 sz=33 cd=177 | train +513, holdout **−227** |
| Best train | thr=3.0 sz=15 (default) | train +5,645, holdout **−928** |
| Best holdout | thr=4.8 sz=41 cd=93 | train **−2,630**, holdout +4,100 |

**The −0.700 correlation is the smoking gun.** Configs that win on D1+D2
systematically lose on D3 by a mirror-image amount, and vice versa. The
optimizer cannot find a single config that beats V2 on both samples.

## Per-fire diagnostic confirms

`analysis/round4/submission_v7_diag.py` instrumented v7 with `print` at
each fire. R4 replay (3 days, 10K ticks/day, default thr=3.0 sz=15):

| Day | Fires | Drift med | Drift max | VELVET delta vs V2 | $/fire |
|---:|---:|---:|---:|---:|---:|
| D1 | 47 | 3.34 | 72.23 | −786 | **−16.7** |
| D2 | 27 | 3.27 | 76.75 | **+6,430** | **+238** |
| D3 | 65 | 3.35 | 79.75 | −928 | −14.3 |

Same fire-frequency, same per-fire drift magnitude, drastically different
per-fire P&L. **D2's +238/fire vs D1/D3's −15/fire is a path artifact**,
not a regime-conditioned edge — there's no obvious environmental difference
(stratton's MR struggles on D2 in V2 too, +2,946 vs +14,675/+12,312, but
that doesn't mechanically generate +6,430 of OPTIMP-take edge specifically).

## Why we got fooled initially

1. **Sample size.** 3-day historical replay = ~1 OOS day. The naive 6-trial
   sweep landed on the train-best config which happened to also avoid
   catastrophic D3 loss. With wider param ranges, it's clear the train-
   best is not the holdout-best.
2. **The signal is mechanically sensible.** Vega-weighted average of
   per-voucher implied-S deviations *could* be informative. But on this
   sample, what looks like a 3-tick consensus drift signal is dominated
   by VELVET path noise relative to the half-spread cost (2.5 ticks).
3. **D2 is the same FV path as R3 D2** (per CLAUDE.md). So it's a single
   realization for both train days, not 2 independent samples.

## What this teaches us about R4 ship process

- A single-day holdout (D3) is too thin to validate any signal that
  doesn't have *strong* OOS uplift (>1k absolute, ideally >10% of total).
- Going forward, **gate on holdout-positive AND train-positive
  simultaneously** — refuse to ship configs that excel on one but not the
  other. The optimizer found 0 such configs in this search.
- Correlation between train and holdout PnL across the search trials is a
  cheap, decisive overfit detector. Run it routinely.

## Ship action

- `traders/round4/submission_v7.py` — `OPTIMP_VELVET_ENABLED = False` by
  default. File preserved with this audit as `# === Original (now
  invalidated) V7 docstring ===` for reproducibility.
- **Active R4 candidate stays `traders/round4/submission_v2.py` (+29,934
  R4 historical replay).** No real R4-improvement found in v3, v4, v5, v6,
  v7.

## Cumulative R4 search summary (post-audit)

| Mechanism | Variants tried | Outcome |
|---|:---:|---|
| Mark counterparty layer (v3 + marks_a-d + marks_only) | 9 | All lose |
| Cross-strike spread MR | 1 + sweeps | Lose post-spread |
| Static theta carry (v4) | 5 | All lose |
| R3 OBI handlers (v5) | 1 | Lose |
| Delta hedge (v6) | 2 | Lose |
| **Option-implied drift (v7)** | **6 narrow + 26 random = 32** | **0/32 beat V2 on both train + holdout** |
| IV-scalp param tune | 141 | V2 = optimum |
| smile_a sweep | 13 | V2 = optimum |

V2 has now survived **190+ trials and 12 structural variants**. The R4
algo book is genuinely saturated at V2's local optimum. Real remaining
upside: manual challenge (Aether Crystal exotics) or a multi-week
joint-param re-search at the V2 level (high effort, uncertain).
