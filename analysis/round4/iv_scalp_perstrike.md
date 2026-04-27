# Per-strike IV-scalp parameter tuning - R4 historical replay

**TL;DR. NO SHIP.** Per-strike `THR_OPEN` (and per-strike `SCALP_MAX_PER_TICK`)
tuning over 230 trials produced a maximum total uplift of **+148 XIRECs** vs
V2 (29,934 -> 30,082) and a maximum holdout uplift of **+70** (12,312 -> 12,382).
The ship gate required **TOTAL >= V2+1000 = 30,934** AND **HOLDOUT >= V2 = 12,312**.
The total gate is missed by ~850 XIRECs. Recommend leaving `submission.py` as
V2 (already shipped, +29,934 historical replay, +33,784 portal-UI day-3).

## Setup

- **Trader.** `traders/round4/submission_perstrike_tunable.py` - copy of V2
  with per-strike override mechanism. PARAMS dict accepts uniform keys
  (`THR_OPEN`, ...) AND per-strike keys (`THR_OPEN_5000`, `THR_OPEN_5100`, ...).
  Per-strike values fall back to uniform when missing. Class defaults are V2.
  Parity test: `PROSPERITY_PARAMS=` unset reproduces V2 = +29,934 exactly.
- **Search runner.** `analysis/round4/iv_scalp_perstrike.py`. Modes:
  `thr_open` (6 params) and `thr_open_size` (12 params, adds
  `SCALP_MAX_PER_TICK_<K>`).
- **Score.** Total = D1 + D2 + D3 from `prosperity3bt --merge-pnl`. Train =
  D1+D2 (= R3 D1+D2 path). Holdout = D3 (fresh data).
- **Ship gates.** `total >= 30,934` AND `holdout >= 12,312`.

## Search budget + results

| Phase | Mode | N trials | Range | Best total | Best hold | Wallclock |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 1. Random | THR_OPEN per-strike | 130 | [0.20, 1.50] | 30,028 (+94) | 12,365 (+53) | ~50 min |
| 2. Random | + SCALP_MAX per-strike | 100 | size [10, 100] | **30,082 (+148)** | **12,382 (+70)** | ~37 min |
| 3. VEV_5000 grid | thr x size focus | 30 | thr [0.6, 1.1], size [20, 100] | 30,040 (+106) | 12,365 (+53) | ~11 min |
| **Total** | | **260** | | | | **~1.6 h** |

Trial 0 of every phase is uniform-V2 (parity check). All three phases
reproduced 29,934.

## Top-5 configs (mode 2: 12-param)

Ranked by **holdout** (per the brief's pick-by-holdout rule):

| Rk | Train | Hold | Total | dTot | dHold | Note |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 17,663 | **12,382** | 30,044 | +110 | +70 | trial 87 - mixed THR_OPEN, sizes 50/91/48/10/48/73 |
| 2 | 17,625 | 12,379 | 30,004 |  +70 | +67 | trial 42 |
| 3 | 17,660 | 12,378 | 30,038 | +104 | +66 | trial 5 |
| 4 | 17,654 | 12,377 | 30,032 |  +98 | +65 | trial 77 |
| 5 | 17,639 | 12,373 | 30,012 |  +78 | +61 | trial 61 |
| - | 15,543 | 11,901 | 27,444 | (V1 baseline) |
| - | 17,621 | 12,312 | 29,934 | (V2 baseline) |

## Per-strike contribution: where did the edge come from?

This is the critical diagnostic. From `iv_scalp_perstrike_marginal.py`
(per-strike PnL bucketed by per-strike `THR_OPEN`):

| Strike | V2 PnL | Best PnL across all trials | Range | Conclusion |
| --- | ---: | ---: | --- | --- |
| **VEV_5000** | 2,653 | **2,763** (+110) | THR best in [0.80, 1.00) | Only strike that materially responds to THR_OPEN. Sweet spot ~0.8-0.9. |
| VEV_5100 | 2,796 | 2,796 (+0) | flat | Per-strike THR_OPEN has no effect across [0.20, 1.50]. |
| VEV_5200 | 1,759 | 1,759 (+0) | flat | Same. |
| VEV_5300 | 1,220 | 1,245 (+25) | flat for THR>=0.6 | Tiny SIZE-driven uplift, not THR_OPEN. |
| VEV_5400 | 607 | 607 (+0) | flat | No response. |
| VEV_5500 | 107 | 107 (+0) | flat | No response. |

Why most strikes are flat: V2's `IV_SCALPING_THR=1.0865` activity gate plus
`THR_OPEN=0.536` already filter every strike's signal so the few firings that
happen are at extreme deviations - well above any THR_OPEN we sampled in
[0.20, 1.50]. The firing decisions don't change. **The per-strike "knob"
isn't actually a knob for VEV_5100, 5200, 5400, 5500.**

VEV_5000 is the exception because its higher vega (~85) means more candidate
firings, and THR_OPEN does straddle the firing density boundary. But the
maximum uplift on that single strike is ~110 XIRECs.

## Honest validation

- The 12-param search has higher overfit risk (many top trials use random
  per-strike values for the 5 flat strikes - they don't matter, so noise wins
  the tournament). The clean signal is from VEV_5000 only.
- **Cleanest config** (only `THR_OPEN_5000=0.8`, `SCALP_MAX_PER_TICK_5000=20`,
  everything else V2 uniform): total **30,040 (+106)**, holdout **12,365 (+53)**.
- Holdout uplift of +53 is plausibly real (consistent across many sampled
  configs that vary 5000), but is still 19x below the total-uplift gate.
- 39% of trials in both searches passed `holdout >= V2`. So a positive-holdout
  result is not luck-of-the-draw - it's that the per-strike basin barely
  exists.

## Per-asset breakdown (trial 87, best holdout) vs V2

| Asset | V2 | Trial 87 | Delta |
| --- | ---: | ---: | ---: |
| HYDROGEL_PACK | 8,861 | 8,861 | 0 |
| VELVETFRUIT_EXTRACT | 3,577 | 3,577 | 0 |
| VEV_4000 | 8,360 | 8,360 | 0 |
| VEV_4500 | -7 | -7 | 0 |
| VEV_5000 | 2,653 | **2,739** | +86 |
| VEV_5100 | 2,796 | 2,796 | 0 |
| VEV_5200 | 1,759 | 1,759 | 0 |
| VEV_5300 | 1,220 | **1,245** | +25 |
| VEV_5400 | 607 | 607 | 0 |
| VEV_5500 | 107 | 107 | 0 |
| **Total** | **29,934** | **30,044** | **+110** |

## Why per-strike doesn't help (mechanically)

The diagnostic data the brief cites (per-fire EV at H=200) showed VEV_5000 has
the highest *per-fire* edge (+8.50) but the *lowest* fire count (371 sells).
Per-strike `THR_OPEN` lowers/raises the threshold and trades off per-fire EV
for fire frequency. For VEV_5100..5500, V2's THR is already inside a narrow
plateau where firing decisions are dominated by the `IV_SCALPING_THR` activity
gate, not by `THR_OPEN`.

To unlock more per-strike edge we would need to vary `IV_SCALPING_THR_<K>`
itself (the activity gate), or `THEO_NORM_WINDOW_<K>` / `IV_SCALPING_WINDOW_<K>`
(the EMA timescales). But those changes risk redefining the signal rather than
sizing it. Out of scope per the brief.

## Verdict

**No ship.** Per-strike tuning of THR_OPEN +/- SCALP_MAX_PER_TICK gives at most
+148 XIRECs of total uplift, ~850 short of the +1000 gate. The honest holdout
uplift of +70 is positive but in noise territory at this magnitude (D3 PnL
varies by hundreds across uniform parameter perturbations).

**Recommend.** Leave `traders/round4/submission.py` as V2. The shipped
candidate already passes both gates set in the V2 tune (+2,490 total /
+411 holdout) - per-strike tuning can't add more from this knob set.

## Artifacts

- `traders/round4/submission_perstrike_tunable.py` - per-strike-overridable trader
- `analysis/round4/iv_scalp_perstrike.py` - search runner (modes: thr_open / thr_open_size)
- `analysis/round4/iv_scalp_perstrike_analyze.py` - top-K ranker
- `analysis/round4/iv_scalp_perstrike_marginal.py` - per-strike marginal-PnL bucket analysis
- `analysis/round4/iv_scalp_vev5000_focus.py` - VEV_5000-only 30-trial grid
- `tmp/optimizer/iv_scalp_perstrike_main/results.csv` - 131 trials, 6-param THR_OPEN
- `tmp/optimizer/iv_scalp_perstrike_size/results.csv` - 101 trials, 12-param THR_OPEN+SIZE
- `tmp/optimizer/iv_scalp_vev5000_grid/results.csv` - 30-trial VEV_5000 focus

No `submission_v3_perstrike.py` was created - per-strike configs do not pass
the ship gate. `submission.py` (V2) remains the active R4 trader.
