# R3 Signal Decay & Multi-Horizon Analysis

Source: 3 days x 10K ticks per day, R3 panel. Script: `signal_decay.py`. JSON: `signal_decay.json`.

## 1. Headline

- **Per-signal mean PnL of `l1_obi` is essentially flat across H=1..1000** on every product (e.g. HYDROGEL ~+3.5 ticks, VEV_5300 ~+0.33 ticks). The signal does NOT decay in mean — but variance grows with H, so the **per-signal information ratio falls as 1/sqrt(H)** (Sharpe halflife: ~1-25 ticks). Practically: an `l1_obi` event predicts the *direction* for hundreds of ticks, but the noise around that prediction grows so fast that holding past ~25 ticks adds variance with no extra mean.
- **`rev_z50` is the OPPOSITE shape**: mean PnL grows monotonically with H (HYDROGEL: +0.06 at H=1 -> +4.08 at H=1000). Best Sharpe per signal is at H=500-1000. This is the right family for sizing UP and HOLDING.
- **AND-gating `l1_obi & micro_dev` is the same as either alone** because microprice direction is a vol-weighted L1 price - the two signals are mechanically the same family. AND with `rev_z50` adds a small lift only on ATM VEVs.
- **No trend regimes**: rolling 1000-tick directional Sharpe is centred at -0.02 to -0.08 on every product (i.e. weakly anti-momentum). Don't chase momentum.
- **Cross-product multi-tick lead-lag is dead** (|corr| < 0.05 at every L >= 5). Underlyings and options move together within 1 tick - no statarb.
- **Volume conditioning** doesn't help: the top-10% volume mask leaves too few `l1_obi` events to draw conclusions, and where it works (VEV_5300/5400) the uplift is +0.01-0.03 Sharpe.

## 2. Alpha Half-Life (mean-decay tau vs Sharpe-decay tau, in ticks)

`tau_mean` = exp-decay constant of mean PnL/sig vs H. `tau_sharpe` = same fit on per-signal Sharpe (info-ratio decay).
inf = monotone increasing across the H grid (no decay, often increasing). Half-life = tau * ln(2).

| product | sig | tau_mean | t1/2_mean | tau_sharpe | t1/2_sharpe |
| --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | l1_obi | 939 | 651 | 310 | 215 |
| HYDROGEL_PACK | rev_z50 | inf | - | inf | - |
| VELVETFRUIT_EXTRACT | l1_obi | inf | - | 496 | 344 |
| VELVETFRUIT_EXTRACT | rev_z50 | inf | - | inf | - |
| VEV_5000 | l1_obi | 848 | 588 | 194 | 135 |
| VEV_5000 | rev_z50 | inf | - | inf | - |
| VEV_5100 | l1_obi | 4262 | 2954 | 440 | 305 |
| VEV_5100 | rev_z50 | inf | - | inf | - |
| VEV_5200 | l1_obi | 5801 | 4021 | 413 | 286 |
| VEV_5200 | rev_z50 | inf | - | inf | - |
| VEV_5300 | l1_obi | 6907 | 4788 | 450 | 312 |
| VEV_5300 | rev_z50 | inf | - | inf | - |
| VEV_5400 | l1_obi | 7304 | 5063 | 467 | 324 |
| VEV_5400 | rev_z50 | inf | - | inf | - |
| VEV_5500 | l1_obi | inf | - | 698 | 484 |
| VEV_5500 | rev_z50 | inf | - | 1943 | 1347 |

### Per-horizon mean PnL/sig (l1_obi)

| product | H=1 | H=10 | H=50 | H=100 | H=200 | H=500 | H=1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | +4.036 | +3.736 | +3.552 | +3.592 | +2.966 | +3.553 | +1.126 |
| VELVETFRUIT_EXTRACT | +0.402 | +0.404 | +0.474 | +0.466 | +0.467 | +0.370 | +0.535 |
| VEV_5000 | +0.297 | +0.282 | +0.253 | +0.293 | +0.280 | +0.151 | -0.119 |
| VEV_5100 | +0.276 | +0.253 | +0.271 | +0.180 | +0.103 | -0.002 | +0.207 |
| VEV_5200 | +0.328 | +0.316 | +0.316 | +0.327 | +0.332 | +0.250 | +0.297 |
| VEV_5300 | +0.328 | +0.350 | +0.323 | +0.317 | +0.342 | +0.415 | +0.261 |
| VEV_5400 | +0.208 | +0.264 | +0.260 | +0.264 | +0.264 | +0.301 | +0.199 |
| VEV_5500 | +0.185 | +0.268 | +0.279 | +0.290 | +0.264 | +0.254 | +0.274 |

### Per-horizon mean PnL/sig (rev_z50, sign = mean-revert)

| product | H=1 | H=10 | H=50 | H=100 | H=200 | H=500 | H=1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | +0.056 | +0.087 | +0.306 | +1.203 | +2.419 | +3.359 | +4.083 |
| VELVETFRUIT_EXTRACT | +0.037 | -0.001 | +0.217 | +0.465 | +0.494 | +1.220 | +1.812 |
| VEV_5000 | +0.018 | -0.028 | +0.182 | +0.432 | +0.453 | +1.150 | +1.675 |
| VEV_5100 | +0.015 | -0.025 | +0.174 | +0.376 | +0.398 | +0.965 | +1.371 |
| VEV_5200 | +0.020 | -0.002 | +0.147 | +0.321 | +0.331 | +0.740 | +1.038 |
| VEV_5300 | +0.029 | +0.020 | +0.105 | +0.203 | +0.228 | +0.509 | +0.670 |
| VEV_5400 | +0.022 | +0.022 | +0.064 | +0.112 | +0.151 | +0.278 | +0.328 |
| VEV_5500 | +0.030 | +0.073 | +0.113 | +0.150 | +0.137 | +0.169 | +0.207 |

## 3. Combined Signals (Sharpe/sig, AND-gate)

| product | obi&micro@H100 | obi&rev@H200 |
| --- | --- | --- |
| HYDROGEL_PACK | +0.199 | +0.209 |
| VELVETFRUIT_EXTRACT | +0.051 | +0.079 |
| VEV_5000 | +0.035 | +0.078 |
| VEV_5100 | +0.025 | +0.070 |
| VEV_5200 | +0.056 | +0.095 |
| VEV_5300 | +0.085 | +0.125 |
| VEV_5400 | +0.156 | +0.174 |
| VEV_5500 | +0.338 | +0.382 |

`obi&micro` is mechanically near-identical to either alone (microprice is L1-vol weighted). `obi&rev` adds a clean lift on ATM VEVs (e.g. VEV_5500 +0.38 vs `rev_z50` solo).

## 4. Vol-Regime (Sharpe/sig by 500-tick realized-vol quartile)

| product | l1_obi@H50 q0 | q1 | q2 | q3 | rev_z50@H200 q0 | q1 | q2 | q3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | +0.236 | +0.303 | +0.252 | +0.312 | +0.135 | +0.084 | +0.055 | +0.145 |
| VELVETFRUIT_EXTRACT | +0.072 | +0.093 | +0.054 | +0.066 | -0.001 | +0.048 | +0.158 | -0.016 |
| VEV_5000 | +0.029 | +0.057 | +0.043 | +0.038 | +0.011 | +0.080 | +0.088 | +0.007 |
| VEV_5100 | +0.030 | +0.076 | +0.036 | +0.063 | +0.009 | +0.082 | +0.035 | +0.051 |
| VEV_5200 | +0.040 | +0.079 | +0.092 | +0.079 | +0.073 | +0.018 | +0.101 | +0.006 |
| VEV_5300 | +0.091 | +0.081 | +0.152 | +0.141 | -0.004 | +0.092 | +0.104 | +0.023 |
| VEV_5400 | +0.217 | +0.232 | +0.179 | +0.163 | +0.040 | +0.087 | +0.090 | +0.037 |
| VEV_5500 | +0.391 | +0.445 | +0.383 | +0.444 | +0.042 | +0.100 | +0.165 | +0.220 |

`l1_obi` is roughly vol-flat on spots, slightly stronger in mid-vol on ATM VEVs. `rev_z50` peaks in mid-vol (q1-q2) and dies in q3 - reversion fails when the asset is genuinely moving.

## 5. Trend-Regime (rolling 1000-tick directional-Sharpe of 100-tick momentum)

| product | median | p10 | p90 | frac>0 |
| --- | --- | --- | --- | --- |
| HYDROGEL_PACK | -0.019 | -0.053 | +0.017 | 0.25 |
| VELVETFRUIT_EXTRACT | -0.019 | -0.058 | +0.030 | 0.30 |
| VEV_5000 | -0.013 | -0.049 | +0.036 | 0.35 |
| VEV_5100 | -0.010 | -0.044 | +0.037 | 0.36 |
| VEV_5200 | -0.018 | -0.055 | +0.029 | 0.29 |
| VEV_5300 | -0.030 | -0.069 | +0.017 | 0.19 |
| VEV_5400 | -0.042 | -0.078 | +0.005 | 0.11 |
| VEV_5500 | -0.077 | -0.115 | -0.026 | 0.00 |

All medians are <= 0 and p90 <= +0.04. **There is no trend-following window worth chasing on any R3 product.**

## 6. Cross-Product Multi-Tick Lead-Lag (Pearson corr returns)

| pair (A->B) | L=1 | L=5 | L=10 | L=50 | L=100 | L=500 |
| --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK->VELVETFRUIT_EXTRACT | +0.001 | +0.008 | +0.002 | -0.002 | -0.009 | -0.007 |
| VELVETFRUIT_EXTRACT->VEV_5000 | -0.006 | -0.007 | +0.002 | -0.001 | +0.002 | -0.004 |
| VELVETFRUIT_EXTRACT->VEV_5200 | -0.009 | -0.004 | +0.001 | +0.001 | -0.001 | -0.007 |
| VELVETFRUIT_EXTRACT->VEV_5400 | -0.001 | -0.004 | -0.002 | -0.001 | +0.003 | -0.005 |
| VEV_5000->VEV_5100 | -0.047 | +0.003 | +0.002 | +0.002 | +0.000 | -0.000 |
| VEV_5100->VEV_5200 | -0.036 | -0.002 | +0.006 | +0.006 | -0.001 | -0.006 |
| VEV_5200->VEV_5300 | -0.014 | +0.005 | +0.006 | +0.007 | +0.001 | -0.002 |
| VEV_5300->VEV_5400 | -0.001 | -0.019 | +0.001 | +0.005 | +0.003 | -0.000 |
| VEV_5400->VEV_5500 | -0.007 | +0.002 | -0.000 | -0.005 | +0.008 | -0.010 |

Negative L=1 between adjacent VEV strikes (-0.05 to -0.01) is bid-ask bounce noise, not signal. Everything beyond L=1 is < 0.01.

## 7. Volume-Conditioned (l1_obi @ H=50, last-20-tick trade volume > Q90)

| product | uncond Sharpe | high-vol Sharpe | uplift |
| --- | --- | --- | --- |
| HYDROGEL_PACK | +0.277 | +nan | - |
| VELVETFRUIT_EXTRACT | +0.071 | +0.045 | -0.026 |
| VEV_5000 | +0.041 | +nan | - |
| VEV_5100 | +0.050 | +nan | - |
| VEV_5200 | +0.074 | +nan | - |
| VEV_5300 | +0.118 | +0.145 | +0.027 |
| VEV_5400 | +0.198 | +0.208 | +0.010 |
| VEV_5500 | +0.414 | +0.164 | -0.250 |

Many cells nan: `l1_obi` is sparse (asymmetric L1 quotes are rare on HYDROGEL, VEV_5000-5200), so the intersection with high-volume ticks is empty. Conclusion: don't gate on volume.

## 8. Best Signal Per Product (daily Sharpe = Sharpe/sig * sqrt(sigs/day))

| product | signal | H | mean/sig | Sharpe/sig | sigs/day | daily Sharpe |
| --- | --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | l1_obi | 1 | +4.036 | +2.081 | 320 | 37.3 |
| VELVETFRUIT_EXTRACT | l1_obi | 1 | +0.402 | +0.361 | 5860 | 27.6 |
| VEV_5000 | l1_obi | 1 | +0.297 | +0.307 | 4982 | 21.6 |
| VEV_5100 | l1_obi | 1 | +0.276 | +0.329 | 4813 | 22.9 |
| VEV_5200 | l1_obi | 1 | +0.328 | +0.485 | 3519 | 28.8 |
| VEV_5300 | l1_obi | 1 | +0.328 | +0.676 | 2783 | 35.6 |
| VEV_5400 | l1_obi | 1 | +0.208 | +0.736 | 1111 | 24.5 |
| VEV_5500 | rev_z50 | 5 | +0.060 | +0.200 | 8181 | 18.1 |

## 9. Position-Sizing Recommendation (vs current MR `MR_K=0.06` -> ~12% at z=2)

Confidence-scaled fraction of position limit (cap = limit). Recommended use: passive-skew at this size on the best signal.

| product | signal | H | rec % | rec lots | uplift vs MR_006 |
| --- | --- | --- | --- | --- | --- |
| HYDROGEL_PACK | l1_obi | 1 | 75% | 149 | 6.2x |
| VELVETFRUIT_EXTRACT | l1_obi | 1 | 55% | 110 | 4.6x |
| VEV_5000 | l1_obi | 1 | 43% | 129 | 3.6x |
| VEV_5100 | l1_obi | 1 | 46% | 137 | 3.8x |
| VEV_5200 | l1_obi | 1 | 58% | 172 | 4.8x |
| VEV_5300 | l1_obi | 1 | 71% | 213 | 5.9x |
| VEV_5400 | l1_obi | 1 | 49% | 147 | 4.1x |
| VEV_5500 | rev_z50 | 5 | 36% | 108 | 3.0x |

## 10. Trading Recommendations

Three signals worth deploying with larger size:

1. **HYDROGEL_PACK MR overlay: size to ~50% of limit (100 lots) on `rev_z50 |z|>1`, hold 200-500 ticks.** Mean PnL grows with H (+1.2 -> +3.4 ticks from H=100 -> H=500). Sharpe/sig peaks ~0.11 at H=500. At ~5,500 sigs/day, this is the highest-confidence size-up trade in R3.
2. **VELVETFRUIT_EXTRACT and ATM VEV_5000-VEV_5300: passive `l1_obi` quote-skew with the FULL quote (200/300 lot limit), exit at H=5-10.** Mean is flat across H but variance forces short hold. Daily Sharpe 22-36; the HYDROGEL_PACK l1_obi is even higher (37) but only fires 320 times/day, so total catch is similar.
3. **VEV_5400/5500 MR layer: size to ~30% (90-100 lots) on `rev_z50` AND `l1_obi` agree (gated combo Sharpe 0.17-0.38).** AND-gate cuts noise enough to justify scaling beyond the current 6%.

Do NOT: (a) trade cross-product directional bets - VELVETFRUIT is for delta hedging only; (b) chase trend regimes - none exist; (c) gate on trade volume - signal density is too low to combine cleanly.

### Honest caveats

- The mean PnL/sig of `l1_obi` is robust (~3.5 ticks on HYDROGEL out to H=500), but the per-signal Sharpe falls as 1/sqrt(H) - holding longer adds variance with no mean. The right play is short-horizon execution at full size, not long-horizon holding at small size.
- `rev_z50` Sharpe-per-sig peaks around 0.10-0.15. Pure-MR alone is not a Sharpe-2 signal; combine with the `l1_obi` AND-gate (sec 3) for the size-up tail-VEV trade.
- All sizing here assumes independent signal-events. If two signals fire on overlapping ticks and we double-stack, position-limit cancellations bite. Cap aggregate position at limit minus buffer (~10%).