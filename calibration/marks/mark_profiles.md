# Round 4 — Per-Mark Counterparty Profiles

Source: `data/prosperity4/round4/{trades,prices}_round_4_day_{1,2,3}.csv`. R4 days 1–2 reproduce R3 days 1–2 (same FV path); day 3 is fresh data. Per-day stratification of every effect is in `mark_profiles.json`.

## 7-Mark summary (all products, all days)

| Mark | Trades | Volume | Aggressive % | Passive % | Mean informed drift @H=200 |
|---|---:|---:|---:|---:|---:|
| Mark 01 | 1843 | 7428 | 0.0 | 100.0 | 1.128 |
| Mark 14 | 2172 | 8718 | 0.0 | 99.9 | 6.206 |
| Mark 22 | 1584 | 5889 | 90.7 | 9.2 | -0.601 |
| Mark 38 | 1478 | 5000 | 100.0 | 0.0 | -8.635 |
| Mark 49 | 122 | 1186 | 1.7 | 98.3 | -1.848 |
| Mark 55 | 1198 | 6551 | 100.0 | 0.0 | -1.492 |
| Mark 67 | 165 | 1510 | 99.4 | 0.6 | 1.033 |

*Informed drift sign convention*: positive = the Mark's trades print on the side that wins over the next 200 ticks (buyer drift = future mid − price; seller drift sign-flipped). Positive ⇒ informed; negative ⇒ adversely-selected / dumb.

### Same metric, per day (H=200)

| Mark | Day 1 | Day 2 | Day 3 |
|---|---:|---:|---:|
| Mark 01 | 0.975 | 1.447 | 0.99 |
| Mark 14 | 7.141 | 4.314 | 6.948 |
| Mark 22 | -0.803 | -0.589 | -0.461 |
| Mark 38 | -10.019 | -5.952 | -9.492 |
| Mark 49 | -3.15 | -1.663 | -0.718 |
| Mark 55 | -0.66 | -1.77 | -2.002 |
| Mark 67 | 3.759 | -0.352 | -0.565 |

## Per-product classification grid

Each cell shows the Mark's role on that product, computed from BOTH sides (buyer, seller). Format: `buyer-side / seller-side`. Codes: `inf` informed (drift>+0.5), `dumb` adverse (drift<−0.5), `neu` neutral (|drift|≤0.5), `passΛ` passive lucky, `passN` passive neutral, `passD` passive dumb (passive but adverse), `n/a` <8 trades.

| Mark | HYDRO | VELVET | VEV_4000 | VEV_4500 | VEV_5000 | VEV_5100 | VEV_5200 | VEV_5300 | VEV_5400 | VEV_5500 | VEV_6000 | VEV_6500 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Mark 01 | —/— | passΛ/passΛ | —/— | —/— | —/— | —/— | passΛ/— | passΛ/— | passΛ/— | passΛ/— | passN/— | passN/— |
| Mark 14 | passΛ/passΛ | passΛ/passΛ | passΛ/passΛ | —/— | —/— | —/— | passΛ/— | passΛ/— | passD/— | n/a/— | —/— | —/— |
| Mark 22 | passD/passΛ | inf/passN | n/a/n/a | n/a/n/a | n/a/n/a | n/a/n/a | n/a/dumb | n/a/dumb | —/dumb | —/dumb | —/neu | —/neu |
| Mark 38 | dumb/dumb | —/— | dumb/dumb | n/a/n/a | n/a/n/a | n/a/n/a | n/a/n/a | n/a/n/a | —/— | —/— | —/— | —/— |
| Mark 49 | —/— | passD/passD | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— |
| Mark 55 | —/— | dumb/dumb | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— |
| Mark 67 | —/— | inf/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— | —/— |

## Counterparty pair frequencies (all 3 days, all products)

| Buyer → Seller | Trades | Volume |
|---|---:|---:|
| Mark 01 → Mark 22 | 1339 | 4636 |
| Mark 14 → Mark 38 | 728 | 2447 |
| Mark 38 → Mark 14 | 714 | 2445 |
| Mark 55 → Mark 14 | 331 | 1763 |
| Mark 14 → Mark 55 | 316 | 1761 |
| Mark 01 → Mark 55 | 260 | 1417 |
| Mark 55 → Mark 01 | 244 | 1375 |
| Mark 67 → Mark 49 | 89 | 963 |
| Mark 14 → Mark 22 | 83 | 302 |
| Mark 67 → Mark 22 | 75 | 546 |
| Mark 38 → Mark 22 | 19 | 48 |
| Mark 22 → Mark 55 | 18 | 92 |
| Mark 22 → Mark 38 | 17 | 60 |
| Mark 55 → Mark 22 | 14 | 62 |
| Mark 49 → Mark 22 | 12 | 89 |
| Mark 55 → Mark 49 | 9 | 54 |
| Mark 22 → Mark 49 | 7 | 54 |
| Mark 49 → Mark 55 | 5 | 26 |
| Mark 67 → Mark 55 | 1 | 1 |

### Top pairs — day1

| Buyer → Seller | Trades |
|---|---:|
| Mark 01 → Mark 22 | 393 |
| Mark 14 → Mark 38 | 274 |
| Mark 38 → Mark 14 | 259 |
| Mark 14 → Mark 55 | 114 |
| Mark 55 → Mark 14 | 97 |
| Mark 55 → Mark 01 | 81 |
| Mark 01 → Mark 55 | 76 |
| Mark 67 → Mark 22 | 32 |
| Mark 67 → Mark 49 | 26 |
| Mark 14 → Mark 22 | 20 |

### Top pairs — day2

| Buyer → Seller | Trades |
|---|---:|
| Mark 01 → Mark 22 | 390 |
| Mark 38 → Mark 14 | 225 |
| Mark 14 → Mark 38 | 206 |
| Mark 55 → Mark 14 | 118 |
| Mark 14 → Mark 55 | 92 |
| Mark 55 → Mark 01 | 92 |
| Mark 01 → Mark 55 | 91 |
| Mark 67 → Mark 49 | 35 |
| Mark 14 → Mark 22 | 27 |
| Mark 67 → Mark 22 | 26 |

### Top pairs — day3

| Buyer → Seller | Trades |
|---|---:|
| Mark 01 → Mark 22 | 556 |
| Mark 14 → Mark 38 | 248 |
| Mark 38 → Mark 14 | 230 |
| Mark 55 → Mark 14 | 116 |
| Mark 14 → Mark 55 | 110 |
| Mark 01 → Mark 55 | 93 |
| Mark 55 → Mark 01 | 71 |
| Mark 14 → Mark 22 | 36 |
| Mark 67 → Mark 49 | 28 |
| Mark 67 → Mark 22 | 17 |

## Top actionable signals (drift @ H=200 ticks, sample-weighted)

Only signals with |drift|≥0.5 XIRECs and n≥25 trades are listed. Confidence: `high` = signs agree on day1+2 *and* day3, n≥60. `med` = signs agree across our two FV samples but lighter sample. `low` = single-sample (likely day3 alone or sign disagrees).

| # | Mark | Side | Product | n | Aggr% | Drift@200 | Per-day [d1,d2,d3] | Conf | Action |
|---|---|---|---|---:|---:|---:|---|---|---|
| 1 | Mark 14 | buyer | HYDROGEL_PACK | 496 | 0.0 | 8.938 | [10.210382513661202, 7.436619718309859, 8.821637426900585] | high | BUY on HYDROGEL_PACK when we see Mark 14 BUY in last 50t |
| 2 | Mark 38 | seller | HYDROGEL_PACK | 507 | 100.0 | -8.554 | [-9.959677419354838, -7.0479452054794525, -8.317142857142857] | high | BUY on HYDROGEL_PACK when we see Mark 38 SELL in last 50t |
| 3 | Mark 14 | seller | HYDROGEL_PACK | 507 | 0.0 | 7.415 | [11.040106951871659, 2.040372670807453, 8.59433962264151] | high | SELL on HYDROGEL_PACK when we see Mark 14 SELL in last 50t |
| 4 | Mark 38 | buyer | HYDROGEL_PACK | 515 | 100.0 | -7.321 | [-10.928571428571429, -1.9181818181818182, -8.624223602484472] | high | SELL on HYDROGEL_PACK when we see Mark 38 BUY in last 50t |
| 5 | Mark 14 | seller | VEV_4000 | 207 | 0.0 | 11.263 | [10.215277777777779, 8.8828125, 14.471830985915492] | high | SELL on VEV_4000 when we see Mark 14 SELL in last 50t |
| 6 | Mark 38 | buyer | VEV_4000 | 209 | 100.0 | -11.081 | [-9.965753424657533, -8.8828125, -14.166666666666666] | high | SELL on VEV_4000 when we see Mark 38 BUY in last 50t |
| 7 | Mark 38 | seller | VEV_4000 | 233 | 100.0 | -9.938 | [-9.175824175824175, -10.921875, -10.01923076923077] | high | BUY on VEV_4000 when we see Mark 38 SELL in last 50t |
| 8 | Mark 14 | buyer | VEV_4000 | 232 | 0.0 | 9.892 | [9.175824175824175, 10.921875, 9.883116883116884] | high | BUY on VEV_4000 when we see Mark 14 BUY in last 50t |
| 9 | Mark 01 | seller | VELVETFRUIT_EXTRACT | 244 | 0.0 | 2.73 | [1.8950617283950617, 3.744565217391304, 2.3661971830985915] | high | SELL on VELVETFRUIT_EXTRACT when we see Mark 01 SELL in last 50t |
| 10 | Mark 55 | buyer | VELVETFRUIT_EXTRACT | 598 | 100.0 | -1.622 | [0.34408602150537637, -2.165137614678899, -2.8969072164948453] | high | SELL on VELVETFRUIT_EXTRACT when we see Mark 55 BUY in last 50t |
| 11 | Mark 55 | seller | VELVETFRUIT_EXTRACT | 600 | 100.0 | -1.363 | [-1.6035353535353536, -1.3238341968911918, -1.1722488038277512] | high | BUY on VELVETFRUIT_EXTRACT when we see Mark 55 SELL in last 50t |
| 12 | Mark 01 | buyer | VELVETFRUIT_EXTRACT | 260 | 0.0 | 2.054 | [2.013157894736842, 2.659340659340659, 1.4946236559139785] | high | BUY on VELVETFRUIT_EXTRACT when we see Mark 01 BUY in last 50t |
| 13 | Mark 22 | seller | VEV_5200 | 46 | 95.7 | -2.978 | [1.0, -5.8125, -3.1451612903225805] | med | BUY on VEV_5200 when we see Mark 22 SELL in last 50t |
| 14 | Mark 22 | seller | VEV_5300 | 163 | 98.8 | -1.27 | [-0.717948717948718, -1.8111111111111111, -1.2341772151898733] | high | BUY on VEV_5300 when we see Mark 22 SELL in last 50t |
| 15 | Mark 14 | buyer | VELVETFRUIT_EXTRACT | 316 | 0.0 | 0.91 | [1.8245614035087718, 0.15760869565217392, 0.5909090909090909] | high | BUY on VELVETFRUIT_EXTRACT when we see Mark 14 BUY in last 50t |
| 16 | Mark 14 | seller | VELVETFRUIT_EXTRACT | 331 | 0.0 | 0.838 | [-2.381443298969072, 1.1610169491525424, 3.2025862068965516] | low | SELL on VELVETFRUIT_EXTRACT when we see Mark 14 SELL in last 50t |
| 17 | Mark 01 | buyer | VEV_5300 | 132 | 0.0 | 1.205 | [0.828125, 1.5483870967741935, 1.2246376811594204] | high | BUY on VEV_5300 when we see Mark 01 BUY in last 50t |
| 18 | Mark 67 | buyer | VELVETFRUIT_EXTRACT | 165 | 99.4 | 1.033 | [3.7586206896551726, -0.3524590163934426, -0.5652173913043478] | low | BUY on VELVETFRUIT_EXTRACT when we see Mark 67 BUY in last 50t |
| 19 | Mark 49 | seller | VELVETFRUIT_EXTRACT | 105 | 1.0 | -1.162 | [-1.9411764705882353, -1.635135135135135, 0.1323529411764706] | low | BUY on VELVETFRUIT_EXTRACT when we see Mark 49 SELL in last 50t |
| 20 | Mark 01 | buyer | VEV_5400 | 263 | 0.0 | 0.66 | [0.756578947368421, 0.6025641025641025, 0.6330275229357798] | high | BUY on VEV_5400 when we see Mark 01 BUY in last 50t |
| 21 | Mark 14 | buyer | VEV_5200 | 33 | 0.0 | 1.833 | [-1.9166666666666667, 5.8125, 1.3421052631578947] | med | BUY on VEV_5200 when we see Mark 14 BUY in last 50t |
| 22 | Mark 22 | seller | VEV_5400 | 276 | 99.6 | -0.601 | [-0.6111111111111112, -0.5625, -0.6217391304347826] | high | BUY on VEV_5400 when we see Mark 22 SELL in last 50t |
| 23 | Mark 01 | buyer | VEV_5500 | 299 | 0.0 | 0.538 | [0.5393258426966292, 0.5769230769230769, 0.5084033613445378] | high | BUY on VEV_5500 when we see Mark 01 BUY in last 50t |
| 24 | Mark 22 | seller | VEV_5500 | 306 | 100.0 | -0.518 | [-0.483695652173913, -0.5638297872340425, -0.5083333333333333] | high | BUY on VEV_5500 when we see Mark 22 SELL in last 50t |
| 25 | Mark 01 | buyer | VEV_6000 | 317 | 0.0 | 0.5 | [0.5, 0.5, 0.5] | high | BUY on VEV_6000 when we see Mark 01 BUY in last 50t |
| 26 | Mark 01 | buyer | VEV_6500 | 317 | 0.0 | 0.5 | [0.5, 0.5, 0.5] | high | BUY on VEV_6500 when we see Mark 01 BUY in last 50t |
| 27 | Mark 22 | seller | VEV_6000 | 317 | 100.0 | -0.5 | [-0.5, -0.5, -0.5] | high | BUY on VEV_6000 when we see Mark 22 SELL in last 50t |
| 28 | Mark 22 | seller | VEV_6500 | 317 | 100.0 | -0.5 | [-0.5, -0.5, -0.5] | high | BUY on VEV_6500 when we see Mark 22 SELL in last 50t |
| 29 | Mark 22 | buyer | VELVETFRUIT_EXTRACT | 25 | 24.0 | 1.74 | [0.1, 3.1666666666666665, 2.3333333333333335] | med | BUY on VELVETFRUIT_EXTRACT when we see Mark 22 BUY in last 50t |
| 30 | Mark 14 | buyer | VEV_5300 | 30 | 0.0 | 1.5 | [-0.25, 2.392857142857143, 1.3] | med | BUY on VEV_5300 when we see Mark 14 BUY in last 50t |

## Top 5 recommended signals (to layer on stratton baseline)

**S1. Mark 14 on HYDROGEL_PACK (informed (follow))** — n=496, drift@200=+8.94, conf=high. When `state.market_trades['HYDROGEL_PACK']` shows a Mark 14 BUY within last 50 ticks → place an aggressive BUY of up to 15 lots at the ask (or join the queue 1 tick inside).

**S2. Mark 14 on VEV_4000 (informed (follow))** — n=207, drift@200=+11.26, conf=high. When `state.market_trades['VEV_4000']` shows a Mark 14 SELL within last 50 ticks → place an aggressive SELL of up to 15 lots at the bid (or join the queue 1 tick inside).

**S3. Mark 01 on VELVETFRUIT_EXTRACT (informed (follow))** — n=244, drift@200=+2.73, conf=high. When `state.market_trades['VELVETFRUIT_EXTRACT']` shows a Mark 01 SELL within last 50 ticks → place an aggressive SELL of up to 11 lots at the bid (or join the queue 1 tick inside).

**S4. Mark 22 on VEV_5300 (adverse (fade))** — n=163, drift@200=-1.27, conf=high. When `state.market_trades['VEV_5300']` shows a Mark 22 SELL within last 50 ticks → place a BUY of up to 5 lots; expect mid to move -1.27 over the next 200 ticks.

**S5. Mark 01 on VEV_5400 (informed (follow))** — n=263, drift@200=+0.66, conf=high. When `state.market_trades['VEV_5400']` shows a Mark 01 BUY within last 50 ticks → place an aggressive BUY of up to 3 lots at the ask (or join the queue 1 tick inside).

## Layering on top of `traders/round4/submission.py` (stratton)

- **Compatible additions** (no structural change): a thin `counterparty_signal()` method that scans `state.market_trades[product]` for the last 50 ticks of trades and, when it finds a high-conf signal above, *biases* one of stratton's existing knobs — e.g. shifts the inventory-target or quote-skew on that product by a small amount. This avoids fighting the IV-scalp logic on vouchers and the OBI-skew MM on HYDROGEL/far-strike vouchers.

- **Structural changes (riskier)**: re-enabling takes guarded by a Mark filter. Stratton has takes disabled because of toxic flow; if a clear `informed = follow` signal exists for one product, we could re-enable taking *only when* the signal fires, sized small. Test offline first because re-enabling takes interacts with position limits and can cancel passive quotes.

- **Adverse-selection avoidance**: any Mark classified `inf` on a product means we should *avoid being on the other side of their trades*. For passive MM that means widening the quote on the side that mark is hitting (e.g. if Mark X aggressively buys, widen our ask). This is a 1-line skew tweak inside stratton's quote builder.

- **Caveats**: N=2 independent FV samples is *very* small. Only the `high`-confidence signals above are safe to ship; `med` should go behind a feature flag, `low` is research-only. Do not stack more than 2-3 signals on one product without re-testing in MC, or you risk eating into the IV-scalp edge.
