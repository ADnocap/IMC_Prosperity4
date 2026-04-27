# V3 — L2 Mark-flow VELVET directional layer (KILL)

**Date:** 2026-04-27. **Verdict: kill.** Keep V2 (`submission_v2.py`,
+29,934 R4 historical replay) as the shipped candidate.

## What was tested

Hypothesis (from user prompt + smile_a sweep "different signal in idle
phase" verdict + marks_d_fallback "longer-window net-imbalance gate"
suggestion): a 200-tick net Mark 01 (informed) − Mark 55 (adverse fade)
flow signal on VELVETFRUIT, used to build a directional position on
VELVET (and later, leveraged via VEV_5000-5300 deltas), would beat V2.

Signal direction validated against `calibration/marks/mark_profiles.md`:
- Mark 01 buyer drift +2.05, seller +2.73 (informed → follow direction)
- Mark 55 buyer drift -1.62, seller -1.36 (adverse → fade)

Code: `traders/round4/submission_v3.py` (kept as DO-NOT-SHIP). Toggled by
`L2_ENABLED` flag at module top; default `False` (= V2 byte-for-byte).

## Results vs V2 +29,934 (R4 prosperity3bt --merge-pnl, D1+D2+D3, 10K ticks/day)

| Variant | Description | Total | D1 | D2 | D3 | Δ vs V2 |
|---|---|---:|---:|---:|---:|---:|
| V2 baseline | shipped | **29,934** | 14,675 | 2,946 | 12,312 | 0 |
| V3a small | replace `_trade_mr` on VELVET, target ±30, vouchers 0 | 21,446 | 10,247 | 2,364 | 8,835 | **−8,488** |
| V3a big | replace + vouchers ±100/80/60/40 (delta-weighted) | -2,283,961 | -787K | -759K | -738K | catastrophic |
| V3b | additive bias on `_trade_mr` target (+30 / -30) | 26,102 | 14,646 | 2,713 | 8,743 | **−3,832** |

Day-3 is the killer in both surviving variants. V3a VELVET D3 = -718
vs V2 +2,759 (Δ -3,477). V3b VELVET D3 = -810 vs V2 +2,759 (Δ -3,569).

## Why it doesn't work

1. **Replacement (V3a) loses stratton MR alpha**. V2's `_trade_mr` makes
   +3,577 on VELVET across 3 days (D3 +2,759 alone). The L2 directional
   builder, even when correct in direction, doesn't generate enough
   per-fire edge to recover that.

2. **Take economics**. VELVET spread = 5 ticks → half-spread 2.5.
   Mark 01/55 drift @H=200 ≈ 2.0–2.7 ticks. Edge ≤ entry cost. Same
   reason `marks_b_takes` and `marks_d_fallback` failed on tight-spread
   products.

3. **Passive-only adverse selection**. Position-builder via penny-jump
   only fills when MM bots are ready to dump on you — and they're ready
   to dump precisely when the price is about to move *against* your
   position. Net: directional bets via passive MM are wrong-way during
   regime shifts (D3 in this dataset).

4. **Additive bias (V3b) inherits the same regime issue**. D1+D2 are
   noise-level (-28, -233) but D3 is structurally adverse (-3,569).
   Mirror of the marks_a kill verdict's "D3 disaster as net long-tilt
   fights choppy tape".

## Consistent with prior kill verdicts

This adds to the pile:
- `analysis/round4/marks_only.md` — 3 standalone Mark-only traders, all lose.
- `analysis/round4/marks_d_fallback.md` — 4 Mark-overlay variants on V2, all lose.
- This file — net-flow gate variant, also loses.

The unifying insight from all of them: **V2's penny-jump MM + stratton
MR already captures the Mark counterparty edge implicitly.** Adding an
explicit Mark layer re-routes the same alpha through a worse executor.

## Where edge actually remains (not yet shipped)

Both V3 variants leave the *real* un-shipped opportunities from R3
final_audit untouched:

- `_trade_velvet_obi` dedicated handler with OBI-tier confidence sizing
  (R3 audit estimated +2-4k/day uplift on VELVET).
- `_trade_deep_itm_obi` for VEV_4000/VEV_4500 with size 100-150 instead
  of stratton's tiny `VEV_BASE_SIZE=3` (estimated +1-2.5k/day on VEV_4000).

These are *orthogonal* to Mark IDs — they exploit OBI directly, not
counterparty identity — and they specifically address V2's known
under-sizing on those assets. They're the next thing to try.
