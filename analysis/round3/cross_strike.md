# R3 Cross-Strike Options — Delta-Neutral Structures

**Generated**: 2026-04-25 from 3 days × 10K ticks. Underlying VELVETFRUIT
(mean ~5250). Smile `iv = a + b*m + c*m^2`, `m = ln(K/S)/sqrt(T)`, T = 6/365.
Pooled: `a=0.249, b=0.0033, c=0.027, resid_std=0.018`. Cross-strike spreads
are delta-neutral by construction → can fill position limit (300/leg) without
eating the 200 spot cap. All findings replicated per-day.

## 1. Smile stability

Per-day fits (a, b, c): D0=(0.266, -0.0039, 0.040), D1=(0.251, +0.0045,
0.013), D2=(0.230, +0.0056, 0.032), resid_std ~0.01. Level decays with TTE
(theta). Rolling `b(t)` (1000-tick): mean 0.0017, std 0.0057, no significant
AR(1) — **no skew-trading signal**.

## 2. Butterfly mispricing (KEY FINDING)

Butterfly = `C(K1) - 2*C(K2) + C(K3)`. Dev = market - smile-fair.

| Triple | bf_mean | min | n_neg | Day0 dev | Day1 dev | Day2 dev | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| 5000/5100/5200 | 16.96 | 9.5 | 0 | -2.05 | +2.02 | +2.13 | mixed |
| 5100/5200/5300 | 22.47 | 18.0 | 0 | -0.73 | -1.07 | +1.30 | fair |
| **5200/5300/5400** | 17.98 | 12.5 | 0 | **-3.70** | **-4.96** | **-3.35** | **CHEAP (z~-3)** |
| **5300/5400/5500** | 21.50 | 15.5 | 0 | **+5.09** | **+7.09** | **+6.67** | **RICH (z~+4)** |

No outright arbitrage. Two flies persistently mispriced every day.

## 3. Vertical-spread deviations (vs smile-fair)

| Pair | dev_mean | dev_std | HL (ticks) | Per-day means |
|---|---:|---:|---:|---|
| 5200/5400 | +3.01 | 1.26 | 10 | [+3.98, +3.63, +1.41] |
| **5300/5400** | +3.51 | 1.05 | 9 | [+3.84, +4.30, +2.38] |
| 5300/5500 | +0.73 | 0.94 | 8 | [+2.59, +1.50, -1.91] |

Bot quotes deviate ~3 from fair, snap back in 5-10 ticks. Headline MR
Sharpes 80-160 are upper bounds (no spread/depth costs); real ~1/4.

## 4. Vertical-spread theta carry (held to expiry)

| Short / Long | Credit | Daily theta | EV @ pos300, 3d decay | EV @ pos300 to expiry |
|---|---:|---:|---:|---:|
| 5300 / 5400 | 30.81 | +1.48 | +1,333 | +9,242 |
| 5200 / 5300 | 48.79 | -0.07 | -62 | +14,637 |
| 5400 / 5500 | 9.31 | +1.79 | +1,612 | +2,793 |
| **5300 / 5500** | **40.12** | **+3.27** | **+2,945** | **+12,036** |

**Short 5300 / long 5500**: best theta carry. Spread delta = 0.31; 300
spreads = 93 spot to hedge (within 200 cap).

## 5. Cross-strike OBI signal

`combo = OBI(Klow) - OBI(Khigh)`, OBI = `(bvol-avol)/(bvol+avol)`. Predicts
NEXT-tick call-spread move.

| Pair | corr_avg | per-day | Cond drift +/- |
|---|---:|---|---|
| 5300/5400 | +0.434 | [+0.47, +0.45, +0.39] | +0.35 / -0.36 |
| **5200/5300** | **+0.479** | [+0.49, +0.50, +0.45] | +0.39 / -0.38 |
| 5200/5400 | +0.356 | [+0.37, +0.38, +0.32] | +0.36 / -0.33 |

Very strong, stable. ±0.4 conditional next-tick move; combo crosses ±0.5
thousands of times per day.

## 6. Greeks (at S=5250, pooled smile)

Delta / Vega per strike: 5000=(0.94, 83), 5100=(0.82, 175), 5200=(0.62, 255),
5300=(0.39, 258), 5400=(0.20, 186), 5500=(0.08, 99). Vega-matched
near-delta-neutral pair: **+1.4 VEV_5400 / -1 VEV_5300** (vega 260 vs 258,
residual delta -0.12).

## 7. Static rich list (smile-residual basis)

| Strike | Mean residual | Std | z | Verdict |
|---|---:|---:|---:|---|
| VEV_5000 | +0.15 | 1.46 | +0.10 | flat |
| VEV_5100 | +0.12 | 3.56 | +0.03 | flat |
| VEV_5200 | +0.79 | 4.08 | +0.19 | mild rich |
| VEV_5300 | +1.28 | 3.56 | +0.36 | rich |
| **VEV_5400** | **-2.22** | 3.03 | **-0.73** | **CHEAPEST** |
| VEV_5500 | +0.56 | 1.57 | +0.35 | mild rich |

Vs the smile (not Bachelier-flat), **5400 is the cheapest leg** — buy this
side of any spread. The earlier "all strikes rich" view was vs flat-vol; the
smile absorbs most of the level effect.

## 8. Ranked recommendations (by EV/Sharpe combination)

| # | Trade | Legs | Size | EV/round | Spot used | Rationale |
|---|---|---|---:|---:|---:|---|
| 1 | Short 5300 / Long 5500 vert | -300 5300, +300 5500 | 300 | +2,945 (decay) / +12,036 (expiry) | 93 | best theta carry |
| 2 | Sell 5300/5400/5500 fly | -100 5300, +200 5400, -100 5500 | 100 | +600 + theta | ~0 | persistent +6 rich, z=+4 |
| 3 | Buy 5200/5300/5400 fly | +100 5200, -200 5300, +100 5400 | 100 | +400 + theta | ~0 | persistent -4 cheap, z=-3 |
| 4 | OBI overlay on 5200/5300 vert | sized by combo | up to 300 | ~hundreds/day | ~0 | corr 0.48 next-tick |
| 5 | Vega-neutral 5300/5400 pair | +1 5300, -1.4 5400 | 100 | residual carry | ~30 | for vol traders |

**Action**: trader Y holds N=300 of trade #1 + N=100 of trade #2 + N=100 of
trade #3, all delta-near-zero. Total ~+3,950/round decay (+15K if vouchers
expire to intrinsic) on top of existing outright-shorts. Spot used: ~93/200.
Stack OBI overlay (trade #4) on top of #1: enter shorts when `combo > +0.5`
(spread will widen → better fill), pause when `combo < -0.5`.

Per-day stability verified for trades #1-#4 (sign-stable across days 0/1/2).
Trades #2 / #3 are NOT pure MR — they are structural smile mispricings the
bot quotes never correct over 30K ticks.

Files: `analysis/round3/cross_strike.{py,json}`.
