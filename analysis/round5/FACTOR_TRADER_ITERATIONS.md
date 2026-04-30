# R5 Factor Trader — Iteration log

All variants ship the same 50-asset universe, ±10 position limit per asset.
MC results: 100 sessions × 3 days × 10,000 ticks/day (`prosperity4mcbt --quick`).
CSV replay: `prosperity3bt traders/round5/<file>.py 5 --no-out`.

| # | Variant | Key change | MC mean | MC std | Sharpe | CSV total |
| - | ------- | ---------- | ------- | ------ | ------ | --------- |
| v1 | factor_v1 | 4 PCA factors + dollar-neutral projection, 1-sided | 108,941 | 47,764 | 2.28 | — |
| v1n | factor_v1_noproj | dollar-neutral only, 1-sided directional | 147,436 | 57,246 | 2.58 | 329,949 |
| v1p | factor_v1_pure | no projection at all, 1-sided directional | 152,465 | 62,581 | 2.44 | 292,859 |
| v2 | factor_v2 | 2-sided MM tail (BIG=7 SMALL=3) + bad basket signals | 116,251 | 38,172 | 3.04 | — |
| v3 | factor_v3 | adaptive sizing (full budget directional) + MM tail | 114,086 | 40,384 | 2.83 | — |
| v4 | factor_v4 | basket signals + 1-sided directional (no MM tail) | 77,759 | 63,386 | 1.23 | — |
| v5 | factor_v5 | v1n + correctly-sized snackpack pair signal | 151,549 | 62,424 | 2.43 | — |
| v6 | factor_v6 | per-asset EMA half-life from calibration | 144,554 | 48,328 | 2.99 | — |
| v7 | factor_v7 | + disable MR signal for hl≥2000 OR RW (20 disabled) | 160,212 | 44,157 | 3.63 | 353,633 |
| v8 | factor_v8 | tighter cutoff hl≥1500 (30 disabled) | 132,764 | 37,808 | 3.51 | — |
| v9 | factor_v9 | v7 + pure MM on the 20 disabled assets | 202,469 | 49,329 | 4.10 | 489,225 |
| **v10** | **factor_v10** | **also disable MICROCHIP_SQUARE + UV_VISOR_AMBER (still losing on directional)** | **209,528** | **47,730** | **4.39** | **555,540** |
| v11 | factor_v11 | OBI as position-target (target += OBI_K * obi) | 209,528 | 47,730 | 4.39 | — |
| **v12** | **factor_v12** | **disable list refinement (idx 24, 26, 27, 31)** | **212,276** | **45,187** | **4.70** | **587,106** |
| v13 | factor_v13 | v12 + idx 14, 41, 43 enabled at short HL | 212,420 | 46,944 | 4.52 | — |
| v14 | factor_v14 | v12 + Bollinger range-pos signal | 209,741 | — | — | — |
| v15 | factor_v15 | v12 + heavy-tail enable (idx 24, 41 → HL=1000) | 211,549 | 46,363 | 4.57 | — |
| v15-OBI-tilt | (overwritten) | OBI quote-size tilt on MM layer | 212,276 | 45,187 | 4.70 | 579,503 |

## Findings

### What worked
1. **Disabling EMA-MR for slow-OU and RW assets.** With a fixed HL=1500 EMA, slow-OU (calibrated half-life >2000 ticks) and RW assets generated noisy/biased mean-reversion signals — the EMA can't track the true daily mean fast enough. v5 lost ~24K total on the bottom 10 assets; disabling those (v7) recovered most of that loss.

2. **Hybrid execution layer.** The 30 active OU assets use **directional close-the-gap** orders (drift capture). The 20 signal-disabled assets use **pure 2-sided MM** (penny-jump bid AND ask, sized by remaining position-limit budget, skewed to mean-revert pos to 0). This was the single biggest jump: v7 → v9 added +42K.

3. **Snackpack pair signal.** K = CHOC + VAN follows a slow OU around K_day. The residual K - EMA(K, HL=3000) mean-reverts with std ≈ 35 ticks. Trading both legs together when K deviates from trend adds ~5K per session.

### What didn't work

1. **PCA factor projection** (v1). In our calibrated MC, the PCA-detected factors (snackpack triplet, pebble basket, K_day pair) ARE the alpha sources, not risks to hedge. Projecting them away kills 26% of mean PnL. Dropped.

2. **2-sided MM tail on directional assets** (v2/v3). The opposing-side fills trade against the drift accumulation. ROBOT_DISHES went from +18K (directional only) to +127 (with tail). The MM tail moves PnL from drift capture (high-edge) to spread harvest (small-edge). Net: −30K.

3. **Pebble basket residual signal** (v4). Pebbles drift FAR from 10000 across days (mean residuals ranged from −3,944 to +4,665). The residuals are NOT zero-centred — they have day-specific biases. "Long the cheap pebble" is a slow trade with directional bias, not a clean MR signal. The signal generated −70K of noise.

4. **Triplet residual signal** (v4). The PCA loadings (−0.395, −0.657, +0.643) are unit eigenvectors on **diffs**, not on **levels**. The naive projection `mid_i - L_i × Σ_j L_j × mid_j` produced residuals with means of 7,000-13,000 — algebraically wrong. Dropped.

5. **Slower per-asset EMA half-lives** (v6). Setting per-asset HL to the calibrated value made slow OU assets WORSE — the slower EMA lags even more behind the daily-mu drift. The fix is to disable the signal entirely (v7), not slow it down.

6. **OBI as position-target signal** (v11). OBI = (bid_vol_1 - ask_vol_1) / (bid_vol_1 + ask_vol_1) correlates +0.06 with next-tick mid return on 15+ products. v11 added OBI_K * obi as a position-target perturbation. Result: byte-identical PnL to v10 — alpha decays in 1-2 ticks but position lasts many. Wrong application.

7. **OBI as MM quote-size tilt** (v15-OBI experiment, overwritten). Suppress one quote side when |OBI| > 0.30 to avoid being filled into adverse drift. MC: byte-identical to v12 (sim's symmetric L1 books rarely cross |OBI|=0.30 threshold; only 6.3% of historical ticks do). CSV replay against R5 historical: -7,603 (-1.3%) vs v12. Suppressing one side drops fill volume by more than the 1.3-tick conditional drift makes up. Math: avg fill 13.2 ticks per pulse without tilt vs 8.9 with tilt.

8. **Heavy-tail enable** (v15 final). Hypothesis: ROBOT_DISHES wins +19K because of kurt=25; if enabled, ROBOT_IRONING (kurt=17.8) and OXYGEN_SHAKE_EVENING_BREATH (kurt=17.2) should also win. Result: -728 vs v12 with variance roughly DOUBLED on both products. Lesson: ROBOT_DISHES's edge isn't kurtosis alone — it's the **combination** of heavy tail AND fast OU half-life (319 ticks). The other two have slow half-lives (1768, 1820); the EMA-MR signal can't catch their snap-backs at HL=1000.

### Tick-count sensitivity (important)

PnL does not scale linearly with ticks. Two effects:
- **EMA warmup** (HL ~1500-3000 ticks) — alpha signal is unreliable for the first ~2000 ticks of each session.
- **Drift capture** is bounded by position limit × end-of-day FV move; this dollar amount is roughly fixed regardless of tick count.

| Tick budget | v10 MC mean (3 days) |
|---|---|
| 10,000/day (final eval) | **+209,528** |
| 1,000/day (portal-UI backtest) | −1,163 |

The strategy is calibrated for the final-eval tick count. Portal-UI numbers will look much weaker.

## v10 architecture

```
For each tick:
    1. Update FV EMA per asset (HL = per-asset, 0 = disabled)
    2. Per-asset signal: target_i = clip(KAPPA * (FV_i - mid_i) / sigma_i, ±10)
       (target = 0 if HL_i = 0)
    3. Snackpack pair signal: target += -PAIR_KAPPA * (K - EMA_K) / PAIR_SIGMA_K
       on CHOC and VAN legs
    4. For each asset:
       if signal active:
         directional close-the-gap: bid (target - pos) at penny-jump if positive,
                                     ask (pos - target) at penny-jump if negative
       else:
         2-sided MM: bid_q skewed by current pos to push toward 0, ask similarly,
                    sized by remaining position-limit budget
```

22 assets are signal-disabled (MM-only): RW assets, slow OU (hl ≥ 2000), and 2
high-σ losers (MICROCHIP_SQUARE, UV_VISOR_AMBER). The remaining 28 trade on
EMA-MR signal. Snackpack pair (CHOC+VAN) gets an additional pair-trade overlay.

## Where to push next

- **Per-asset KAPPA tuning** (currently saturated — KAPPA sweep at 3/4/5/6 all gave 148-160K, so there's no easy free PnL there)
- **OBI signal** (top-of-book imbalance) — tested as an addition in v3 but its weight (OBI_K=0.3) was buried under the EMA signal. Could be worth its own pass.
- **Dynamic disable list** — auto-detect underperformers in-session and disable them.
- **Speed up EMA warmup** — initialize FV from a longer-window history embedded in `traderData` from the prior day.
- **MM size tuning** — the current MM_BIG=6 / SMALL=2 / BAL=4 weren't swept.

## Active submission candidate

`traders/round5/factor_v10.py` — MC mean +209K, std 47K, p5 +131K, p95 +281K.
CSV replay 555K (3 days × 10K ticks). Full universe coverage, no degenerate
positions, position-limit-safe.
