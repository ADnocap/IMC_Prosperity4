# Stratton scaling audit — where did the PnL go?

**TL;DR.** Nothing "went". Stratton ran cleanly the entire 10K ticks, kept quoting at a steady rate, and never got inventory-stuck. The portal-UI 17,449 number is **not** the first 1K ticks of the final-eval path — it must be a different FV scenario (probably a much luckier mid-price drift). The 10K-tick eval is far noisier than 10x the 1K-tick eval because PnL is dominated by mark-to-market on inventory, not realized spread.

## 1. PnL trajectory (from `485183.json`'s `graphLog` + `activitiesLog`)

Cumulative total PnL at every 1,000 logical ticks (100K timestamps):

| ts (k) | 0 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 1000 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Total PnL | 0 | 817 | 1,855 | 2,981 | 4,953 | 9,159 | 8,916 | 7,803 | 8,601 | 9,590 | **11,141** |
| Δ vs prev | — | +817 | +1,038 | +1,126 | +1,973 | +4,206 | -243 | -1,113 | +798 | +989 | +1,855 |

**Peak** was 12,973 at ts=950K; final 11,141. Drawdown from peak ≈ 1,832.

Per-asset peak vs final (give-back):

| Asset | Peak | Peak ts | Final | Give-back | Trough |
|---|---|---|---|---|---|
| HYDROGEL_PACK | 7,544 | 459,700 | 4,735 | **2,809** | -654 |
| VELVETFRUIT_EXTRACT | 3,019 | 963,500 | 1,326 | 1,693 | -1,674 |
| VEV_4000 | 2,759 | 963,500 | 2,589 | 170 | 0 |
| VEV_4500 | 2,125 | 963,500 | 1,888 | 237 | 0 |
| VEV_5000 | 858 | 534,800 | 465 | 393 | -9 |
| VEV_5100 | 650 | 534,800 | 230 | 420 | -10 |
| VEV_5200 | 478 | 949,400 | -26 | 504 | -32 |
| VEV_5300 | 3 | 9,100 | -66 | 68 | -82 |
| VEV_5400/5500/6000/6500 | 0 | — | 0 | 0 | 0 |

VEV_5400/5500/6000/6500 = 0 is correct: stratton has takes disabled and these vouchers' BBO is 0/1 (deep OTM) — no penny-jump room. Trader simply never quotes there profitably (0 of my trades on these symbols, vs 100-336 fills on the others).

## 2. Inventory dynamics — NOT the cause

| Asset | Max pos | Min pos | Limit | %limit hit |
|---|---|---|---|---|
| HYDROGEL_PACK | 81 | -6 | ±200 | 41% |
| VELVETFRUIT | 66 | -33 | ±200 | 33% |
| VEV_4000-5300 | ≤18 | ≥-17 | ±300 | <6% |

Position never exceeded 41% of limit. Inventory is well-controlled. The "MR_K=0.06 → only 12% target at z=2" knob did its job. Final ending position is small (HYDROGEL +39, VELVET +44, vouchers single-digits).

## 3. Trade rate — also NOT the cause

My total trades per 1,000-tick bucket: **120, 178, 132, 177, 162, 131, 102, 148, 136, 161**.
Steady ~140/bucket throughout. The trader never goes idle, never hits position-limit cancellation. Volume scales linearly; PnL just doesn't.

## 4. The portal-UI 17,449 mystery

The first 1,000 ticks of the 10K-tick final eval produced **+817**, not +17,449. The portal-UI backtest must have run a **different FV path** (or a different randomized quote-fraction subset) where mid-price drift happened to favor the trader's inventory. There is no "first 1K of the 10K = portal-UI" relationship in the data.

This matches the calibration table in `CLAUDE.md`: stratton's MC mean over 100 sessions × 10K ticks is 10,768 with std 6,815. The 11,141 final eval sits at z=+0.055σ — totally consistent with the MC distribution. Stratton's PnL is roughly proportional to ticks **on average** but with σ ≈ ±6,800; the portal-UI's 17,449 was a single 1K-tick draw with low priors and high variance.

## 5. Verdict on backtest signals for R4

**The portal-UI backtest (1K ticks) is NOT a reliable signal — its PnL is dominated by mid-price-path luck and has variance comparable to the mean.** Trust only the 10K-tick MC distribution (`prosperity4mcbt --heavy --ticks-per-day 10000`) and the realized portal final-eval number when comparing R4 candidate traders.
