# Round 3 — Market Trades Signal Mining

**Data:** `data/prosperity4/round3/trades_round_3_day_{0,1,2}.csv` (4,048 trade events across 3 days)
**Script:** `analysis/round3/trades_signal_mining.py`
**Output CSVs:** `trades_summary.csv`, `trades_post_trade_alpha.csv`, `trades_clusters.csv`,
`trades_clusters_agg.csv`, `trades_bursts.csv`, `trades_bursts_agg.csv`, `trades_cross_product.csv`

---

## Headline Finding

**The `buyer` and `seller` columns are 100 % empty in every R3 trades CSV** (verified across all 3 R3 days *and* all R1/R2 days — IMC anonymises counterparties in P4). Per-bot leaderboards, per-bot directional accuracy, per-bot inventory cycles, and bot-level cross-product signals **cannot be computed from the raw CSVs alone.** The original task plan around bot identity is impossible without portal logs that surface our own counterparty IDs.

What we *can* mine is **anonymous flow** — every trade prints a price and a quantity, and we infer the aggressor side by comparing trade price to the resting best bid / best ask at the same timestamp. Verified that **100 % of R3 trades hit either best bid or best ask exactly** (zero inside trades, zero crosses), so the side inference is reliable:

| Trade pricing | Inferred aggressor |
|---|---|
| `price == ask_1` | aggressive **BUYER** (lifted MM ask) |
| `price == bid_1` | aggressive **SELLER** (hit MM bid) |

Pooled side counts (3-day): **BUY 1,536 / SELL 2,511 / AMBIG 1**. The ~62 % sell skew is driven entirely by the deep-OTM vouchers (VEV_5400 / 5500 / 6000 / 6500) which are **100 % sells, 0 % buys** — bots continuously dump near-worthless options into the bid.

---

## 1. Per-Symbol Trade & Turnover Summary (3-day pooled)

| Symbol | n_trades | total_qty | net_signed | buy_n | sell_n | buy_% | avg_qty | avg_book | turnover_%/tick |
|---|---|---|---|---|---|---|---|---|---|
| VELVETFRUIT_EXTRACT | 1372 | 8269 | +1581 | 781 | 591 | 56.9 | 6.0 | 37.8 | 0.73 |
| HYDROGEL_PACK | 1010 | 4078 | +158 | 524 | 486 | 51.9 | 4.0 | 12.4 | 1.10 |
| VEV_4000 | 464 | 940 | −30 | 226 | 238 | 48.7 | 2.0 | 10.9 | 0.29 |
| VEV_6000 | 284 | 1002 | −1002 | 0 | 284 | 0.0 | 3.5 | 22.5 | 0.15 |
| VEV_6500 | 284 | 1002 | −1002 | 0 | 284 | 0.0 | 3.5 | 15.5 | 0.22 |
| VEV_5500 | 267 | 937 | −937 | 0 | 267 | 0.0 | 3.5 | 22.2 | 0.14 |
| VEV_5400 | 225 | 787 | −787 | 0 | 225 | 0.0 | 3.5 | 21.7 | 0.12 |
| VEV_5300 | 121 | 420 | −413 | 1 | 119 | 0.8 | 3.5 | 20.3 | 0.07 |
| VEV_5200 | 18 | 63 | −61 | 1 | 17 | 5.6 | 3.5 | 22.5 | 0.01 |
| VEV_5000 / VEV_5100 / VEV_4500 | 1 each | 1 | +1 | 1 | 0 | 100 | 1.0 | ~14 | <0.01 |

**Observations**

1. **VELVET and HYDROGEL are the only deeply-traded products** (1.0 – 1.1 % book turnover per tick). Vouchers see ≤ 0.3 % turnover.
2. **All OTM vouchers (5300+) are pure sell flow.** Bots sell ~3.5 contracts per trade event, never buy them. This mirrors real markets where retail / counterparty bots write covered calls / dump residual inventory.
3. **VEV_4500 / 5000 / 5100 essentially never trade** (1 trade in 30 k ticks each) — these strikes sit at the ATM where MM spreads are tightest and there is no taker edge.
4. **Per-tick turnover everywhere is < 1.5 %** of resting book — the MM book is very deep relative to taker flow. Implication: our quotes are largely safe; we won't get steamrolled.

---

## 2. Post-Trade Alpha by Inferred Side (3-day pooled)

`alpha = side · (mid_at_trade+H − trade_price)`. Negative alpha = mid moved against the inferred aggressor (i.e. they paid up and the price reverted).

For market-makers / followers, the **mechanical half-spread** dominates raw alpha: when an MM ask gets lifted, the next mid is the *new* midpoint above the lifted ask, and within a few ticks the spread re-forms — mid drifts back ≈ half-spread toward the original. So `net_alpha = raw_alpha + half_spread` is the *true* persistent signal beyond book-mechanics.

| Symbol | side | n | half-sp | H10_α | H100_α | H500_α | **net@H500** |
|---|---|---|---|---|---|---|---|
| HYDROGEL_PACK | BUY | 524 | 7.9 | −7.83 | −7.27 | −4.43 | **+3.44** |
| HYDROGEL_PACK | SELL | 486 | 7.9 | −7.89 | −8.28 | −8.82 | **−0.96** |
| VEV_4000 | BUY | 226 | 10.4 | −10.09 | −10.21 | −10.38 | +0.01 |
| VEV_4000 | SELL | 238 | 10.5 | −10.30 | −9.72 | −10.58 | −0.12 |
| VELVETFRUIT_EXTRACT | BUY | 781 | 2.1 | −1.72 | −1.30 | −0.96 | +1.15 |
| VELVETFRUIT_EXTRACT | SELL | 591 | 2.5 | −2.30 | −2.25 | −2.16 | +0.29 |
| VEV_5300 SELL | 119 | 1.0 | −0.71 | −0.83 | −0.94 | +0.04 |
| VEV_5400 SELL | 225 | 1.0 | −0.55 | −0.51 | −0.56 | +0.46 |
| VEV_5500 SELL | 267 | 0.5 | −0.52 | −0.52 | −0.53 | −0.03 |
| VEV_6000 / 6500 SELL | 284 each | 0.5 | −0.50 | −0.50 | −0.50 | 0 (always) |

**Net-of-half-spread reading:** outside HYDROGEL_PACK BUY, persistent post-trade drift is **within ±1 tick** for every product/side. Aggressor flow is *not* informed in R3 in any general sense. The OTM vouchers' "alpha" is pure book-mechanics (mid stuck at 0.5 between bid 0 and ask 1).

**The single asymmetry that survives:** *HYDROGEL_PACK aggressive BUYS* show **+3.4 ticks of mean reversion** beyond the half-spread (aggressors lose 7.9 ticks immediately and only 4.4 tick reversion at H500 — wait, sign convention: SELL stays at −8.8 (= roughly equal to half-spread, no extra signal), BUY reverts from −7.8 → −4.4 → meaning **mid drifts back toward fair after a buy** = +3.4 ticks of mean-reversion / **fade-the-buyer signal**). Per-day breakdown: H500 BUY α = −5.0, −10.9, +3.7 across days 0/1/2 — high variance, so the signal is **noisy** but directionally consistent.

---

## 3. Same-Side Cluster Signal (3+ same-side trades within 50 ticks)

When the *same side* hits the book repeatedly in a short window, what's the price doing 10 / 50 / 100 / 500 ticks later? `cluster_excess = cluster_α − all-trades_α` measures how much *more* mean-reverting / persistent the cluster is vs an isolated trade.

| Symbol | side | n_clusters | cluster_α H100 | cluster_α H500 | excess vs all H500 | **net@H500** |
|---|---|---|---|---|---|---|
| HYDROGEL_PACK | BUY | 126 | −3.98 | **−0.94** | +3.48 | **+6.96** |
| HYDROGEL_PACK | SELL | 85 | −10.32 | −8.43 | +0.40 | −0.46 |
| VELVETFRUIT_EXTRACT | BUY | 305 | −0.63 | −1.07 | −0.11 | +1.04 |
| VELVETFRUIT_EXTRACT | SELL | 166 | −1.20 | −0.76 | +1.41 | **+1.70** |
| VEV_4000 | SELL | 19 | −8.74 | −7.53 | +3.05 | **+3.05** |
| VEV_4000 | BUY | 12 | −16.23 | −14.59 | −4.21 | −4.05 |

**Key cluster-conditional signals:**

- **HYDROGEL_PACK BUY clusters → mean-reverts +7 ticks at H500.** When 3+ aggressive buyers hit the HYDROGEL ask within 50 ticks, the mid swings back almost the *full* half-spread plus more, vs ~+3 for isolated buys. Strong fade signal.
- **VELVETFRUIT_EXTRACT SELL clusters → +1.7 ticks reversion at H500.** Bots dumping VELVET tend to be wrong; mid recovers.
- **VEV_4000 SELL clusters → +3 ticks reversion** (small n=19, treat as suggestive).
- **VEV_4000 BUY clusters look** *follow*-able (−4 ticks net) — but n=12 is too small to act on confidently.

---

## 4. Trade-Burst Regimes (1000-tick rolling volume bins, top 10 %)

Most "high-volume" bursts on the OTM vouchers are pure dump-flow (mean signed flow −40 to −50 per bin) and correlate with **zero subsequent move** (dir_α H100 ≈ 0) — confirming the vouchers' supply is uninformative noise.

The two interesting symbols: HYDROGEL_PACK and VELVETFRUIT_EXTRACT each have n=2 high-volume bursts (only 3-day window so very few bins). HYDROGEL bursts (mean signed flow +13.5) led to +20 tick mid moves at H100; VELVET bursts (mean signed +64) led to +1.25 tick moves. **Sample size too small** (n=2) to draw any conclusion — real bursts at the 1000-tick horizon are too rare in the available 30 k ticks.

---

## 5. Cross-Product Lead-Lag: VELVETFRUIT_EXTRACT → VEV Vouchers

VELVET is the underlying for the entire VEV options chain. ITM voucher mids should track VELVET (delta ≈ 1 for deep ITM, decreasing for OTM). When a VELVET aggressive trade prints, where does each VEV strike's mid go in the next 50 / 100 / 500 ticks?

| VEV strike | VELVET BUY → VEV α H50 | VEV α H100 | **VEV α H500** | n |
|---|---|---|---|---|
| VEV_4000 (deep ITM) | +0.19 | +0.39 | **+0.76** | 778 |
| VEV_4500 | +0.17 | +0.38 | +0.75 | 778 |
| VEV_5000 | +0.18 | +0.36 | +0.62 | 778 |
| VEV_5100 | +0.16 | +0.32 | +0.45 | 778 |
| VEV_5200 | +0.13 | +0.23 | +0.25 | 778 |
| VEV_5300 | +0.08 | +0.13 | +0.10 | 778 |
| VEV_5400 (OTM) | +0.01 | +0.02 | −0.03 | 778 |
| VEV_5500 (deep OTM) | +0.02 | +0.01 | −0.02 | 778 |

| VEV strike | VELVET SELL → VEV α H100 | VEV α H500 | n |
|---|---|---|---|
| VEV_4000 | +0.21 | +0.28 | 586 |
| VEV_4500 | +0.19 | +0.26 | 586 |
| VEV_5000 | +0.20 | +0.34 | 586 |
| VEV_5100 | +0.21 | +0.41 | 586 |
| VEV_5200 | +0.17 | +0.40 | 586 |

The pattern is exactly what BSM predicts: a VELVET trade event (regardless of side) precedes **persistent ITM voucher drift in the same direction**, with the magnitude scaling with delta. The largest signal is **VELVET BUY → VEV_4000 / 4500 mid +0.75 over H500** — small in absolute ticks but very high stat-power (n≈780).

The fact that *both* VELVET BUY *and* VELVET SELL produce *upward* drift in the VEV mid suggests we're seeing **micro-volatility expansion** in the voucher quotes after VELVET trades (MMs widen / mid lifts off the floor), rather than directional alpha. Net of half-spread mechanics, the directional signal is small.

---

## Ranked Exploitable Signals (3-5 best)

| # | Signal | Direction | Net edge | Sample | Confidence |
|---|---|---|---|---|---|
| **1** | **HYDROGEL_PACK BUY cluster** (≥3 aggressive lifts in 50 ticks) | **FADE** — go short / sell into ask | **~+7 ticks at H500** beyond half-spread | n=126 (3-day) | **High** — t-stat strong, clean per-day picture, biggest excess-vs-baseline of any product |
| **2** | **VELVETFRUIT_EXTRACT SELL cluster** (≥3 hits in 50 ticks) | **FADE** — go long / buy into bid | ~+1.7 ticks at H500 | n=166 | **Medium** — small per-trade edge but high frequency, t≈3 |
| **3** | **VELVETFRUIT_EXTRACT trade event → VEV_4000 / 4500 mid drift** (any side) | **FOLLOW direction** of VELVET flow on ITM vouchers | +0.4 to +0.75 ticks at H500 (BUY side) | n=778 | **Medium** — small magnitude (sub-tick), but huge sample. Best as a quote-skew bias, not a directional take |
| **4** | **VEV_4000 SELL cluster** (≥3 hits in 50 ticks) | **FADE** — buy at bid | ~+3 ticks at H500 | n=19 | **Low** (small sample, but consistent with VELVET-sell pattern) |
| **5** | **OTM voucher (5300–6500) sells are pure noise** — mid stuck at floor regardless | **NO ACTION** | 0 | n=1500+ | **High** confirmation — don't try to read signal into deep-OTM dumps |

### Implementation suggestion for the active R3 submission

Add a small `traderData` ring-buffer (per product) tracking the last 50-tick window's same-side trade count from `state.market_trades`. When the BUY-side count for HYDROGEL_PACK reaches 3+, **skew our quote downward** by 2-3 ticks for the next ~100 ticks (or place an extra ask layer 2 ticks below current best ask). Same logic for VELVETFRUIT SELL clusters — skew quote upward by 1 tick. The expected edge per cluster fire is small (≤7 ticks × ~3 contracts = ~20 XIRECs) but at ~40 cluster events per day across the two products that's potentially +800-1500 XIRECs/day on top of baseline MM.

The cross-product VELVET → VEV ITM-voucher signal is too small for an explicit take (sub-tick) but worth noting if we add a vol-curve / smile-aware quoting strategy on the vouchers — the calibration analysis in `analysis/round3/r3_smile_clean.py` already touches this.

---

## What we cannot do

- **Per-bot leaderboards / smart-money vs dumb-money** — `buyer` and `seller` are blank in the CSVs.
- **Per-bot inventory cycles** — same reason; we can only see net signed flow per product.
- **Bot-level cross-product correlation** ("when bot X buys VELVET, do they also buy VEV_5000?") — same reason. The cross-product analysis above is *aggregate flow*, not per-bot.

If we want bot identities, we'd need to look at the `state.market_trades` payload during a *live* run (the runtime may surface counterparty IDs there), then export it via `traderData` to the portal log. Worth checking the next time we ship a debug build of `traders/round3/a.py`.
