# R3 VELVETFRUIT_EXTRACT Options — Trading Edges Found

**Generated**: 2026-04-24 from 3 days of R3 historical CSVs (30,000 ticks total).
**Underlying**: VELVETFRUIT_EXTRACT, mean 5250.10, observed range [5198, 5300], per-tick σ ≈ 1.13 (vs calibrated 0.96), drift +0.0015/tick. Total 3-day move: **+8.9** (5246.5 → 5255.4).

**Bottom line**: The market makers who quote VEV_5100..VEV_5500 are pricing options at **3–7× their theoretical Bachelier value at the calibrated σ=0.96/tick**. The bid side is permanently rich vs intrinsic and **bots actively dump these options into the bid** (98% of trade flow is seller-initiated for K∈[5300, 6500]). The biggest single edge is **VEV_5300 at +46 XIRECs of premium per unit sold to bid**, with 300-unit position cap → up to **~13,800 XIRECs of pure premium per round** from that strike alone.

---

## 1. Underlying behavior (3-day data)

| Metric | Value |
|---|---|
| Min mid | 5198 |
| Max mid | 5300 |
| Mean mid | 5250.10 |
| Per-tick σ (observed) | 1.131 |
| Per-tick σ (calibration) | 0.96 |
| Total 3-day std | 15.6 |
| Trend over 3 days | +8.9 (negligible) |

The underlying is essentially **mean-reverting around 5250 with very low total variance over 3 days**. It NEVER crosses any strike from 5300 upward. So calls with K ≥ 5300 finish OTM 100% of the time on the historical path.

`HYDROGEL_PACK`: range [9891, 10079], mean 9990, per-tick σ 2.17, drift ~0 (matches calibration).

---

## 2. Strike-arbitrage check (no free money in bull spreads / butterflies)

- Tested all (K_low, K_high) pairs: zero ticks where ASK(K_low) < BID(K_high). **No bull-spread arbitrage** in the existing book.
- All 6 equally-spaced butterflies (e.g., 4000/4500/5000) have positive mid-cost at every tick. **No butterfly arbitrage** either.
- This means the cross-strike structure is monotone — but the *level* is far above fair value.

---

## 3. Implied volatility surface (Bachelier model, T=ticks-remaining-in-round)

Bachelier (arithmetic Brownian) is the right model since the underlying is a random walk on an absolute price scale, not log-normal.

**Calibrated σ = 0.96/tick. Implied σ from quoted mids (assuming 30K-tick TTE):**

| Strike | Obs mid | Bachelier@σ=0.96 | Implied σ | Richness vs model |
|---|---:|---:|---:|---:|
| 4000 | 1250.11 | 1250.10 | (deep ITM, IV unstable) | +0.01 |
| 4500 | 750.11 | 750.10 | (deep ITM) | +0.01 |
| 5000 | 255.02 | 250.80 | 1.84 | **+4.2** |
| 5100 | 166.81 | 155.72 | 1.80 | **+11.1** |
| 5200 | 95.55 | 76.15 | 1.84 | **+19.4** |
| 5300 | 46.76 | 26.12 | 1.88 | **+20.6** |
| 5400 | 15.95 | 5.64 | 1.78 | **+10.3** |
| 5500 | 6.64 | 0.71 | 1.95 | **+5.9** |
| 6000 | 0.50 | ~0 | 3.27 | +0.5 (1-tick spread floor) |
| 6500 | 0.50 | 0 | 5.08 | +0.5 (1-tick spread floor) |

**Vol smile is roughly flat at IV ≈ 1.8 in [5000–5500]** (a clean ~2× over realized 0.96), then turns up in the deep OTM wings — but those wings (6000, 6500) are pinned at the minimum-tick of 0/1 so the wings can't be traded for that "richness".

---

## 4. Bid quotes vs intrinsic value (the headline finding)

For each strike, the table below shows the average distance of the best bid and best ask above the intrinsic value max(0, S−K).

| Strike | bid − intrinsic | ask − intrinsic | bid vol | ask vol | mid − intrinsic |
|---:|---:|---:|---:|---:|---:|
| 4000 | **−10.40** | +10.42 | 10.9 | 10.9 | +0.01 |
| 4500 | **−7.91** | +7.94 | 9.0 | 8.9 | +0.01 |
| 5000 | +1.90 | +7.95 | 15.3 | 15.5 | +4.92 |
| 5100 | **+14.56** | +18.86 | 19.2 | 19.3 | +16.71 |
| 5200 | **+44.01** | +46.89 | 22.6 | 22.5 | +45.45 |
| **5300** | **+45.71** | +47.81 | 20.3 | 20.2 | +46.76 |
| 5400 | **+15.26** | +16.64 | 21.8 | 21.7 | +15.95 |
| 5500 | **+6.07** | +7.22 | 22.2 | 22.2 | +6.64 |
| 6000 | 0.00 | +1.00 | 22.5 | 22.5 | +0.50 |
| 6500 | 0.00 | +1.00 | 15.5 | 15.5 | +0.50 |

Two important sub-findings:

- **VEV_4000 / VEV_4500 (deep ITM): bid sits ~10/8 BELOW intrinsic.** The MMs are quoting these as if they had high vol on the downside. That is: **buying at the ask costs only intrinsic + 10**, while the option is essentially worth intrinsic + ~0 since the underlying is rangebound. The **ask side is cheap** — slight edge.
- **VEV_5200..VEV_5500 (slightly-OTM band): bid is permanently very rich.** Selling units at the bid captures the displayed premium, which is 6–46 XIRECs per unit depending on strike. That premium decays toward 0 as time passes (see §5).

---

## 5. Theta is real — observed per-day decay

Even with the underlying drifting UP +8.9 over 3 days (which should *raise* call values), OTM option mids **fell** every day:

| Strike | Day-0 mean mid | Day-1 | Day-2 | 3-day Δ |
|---|---:|---:|---:|---:|
| VEV_5100 | 168.11 | 164.98 | 167.33 | −0.78 |
| VEV_5200 | 97.47 | 95.13 | 94.05 | **−3.42** |
| VEV_5300 | 48.89 | 46.91 | 44.48 | **−4.41** |
| VEV_5400 | 18.47 | 15.65 | 13.73 | **−4.74** |
| VEV_5500 | 8.06 | 6.57 | 5.29 | **−2.76** |
| VEV_6000 | 0.50 | 0.50 | 0.50 | 0.00 |
| VEV_6500 | 0.50 | 0.50 | 0.50 | 0.00 |

This implies an effective theta of roughly **−1.5 XIRECs/day for VEV_5400 and VEV_5300** — which is *exactly* the kind of decay you get if these are real European calls expiring within ~10–20 days total horizon. Either way, **shorts collect this decay just by holding**.

---

## 6. Bot trade flow is overwhelmingly seller-initiated for K ≥ 5300

Classifying each historical trade by whether it printed at the bid or the ask:

| Symbol | n_trades | volume | avg price | direction (vs mid) |
|---|---:|---:|---:|---|
| VEV_5200 | 18 | 63 | 85.28 | **94% seller-init** |
| VEV_5300 | 121 | 420 | 44.16 | **98% seller-init** (419/420 at bid) |
| VEV_5400 | 225 | 787 | 14.88 | **100% seller-init** |
| VEV_5500 | 267 | 937 | 5.95 | **100% seller-init** |
| VEV_6000 | 284 | 1002 | 0.00 | 100% seller-init (sells at price 0) |
| VEV_6500 | 284 | 1002 | 0.00 | 100% seller-init |

Translation: **a population of bots is constantly DUMPING the OTM strikes into the bid stack.** The recorded CSV market is a "no aggressive MM" baseline; once we post a passive ASK at or just inside the prevailing bid, those sellers will sweep through us first (price/time priority). Because their sells are aggressive, *we can sit at the bid (or one tick above) and still get filled by them*.

For VEV_6000/6500, the price 0 trades likely represent bots BUYING at price 0 from a 0-bid (i.e., free puts/calls) — these trades are "noise" since no XIRECs change hands; ignore.

---

## 7. Numerical delta (regression dC vs dS, untangled vs Bachelier delta)

| Strike | Empirical β (Δ) | Bachelier Δ at S=5250, T=15K | R² |
|---:|---:|---:|---:|
| 4000 | 0.745 | 1.00 | 0.41 |
| 4500 | 0.662 | 1.00 | 0.42 |
| 5000 | 0.654 | 0.98 | 0.62 |
| 5100 | 0.577 | 0.90 | 0.63 |
| 5200 | 0.437 | 0.66 | 0.56 |
| 5300 | 0.273 | 0.34 | 0.42 |
| 5400 | 0.129 | 0.10 | 0.32 |
| 5500 | 0.055 | 0.02 | 0.14 |
| 6000 / 6500 | 0 | 0 | — |

Empirical deltas are SMALLER than Bachelier deltas (because option moves contain a quote-noise component that diversifies away in regression). For practical hedging, use **Δ ≈ 0.7 (5000), 0.6 (5100), 0.45 (5200), 0.27 (5300), 0.13 (5400), 0.05 (5500)**. With underlying limit 200 spot and per-option limit 300, you can fully delta-hedge:

- 5300 short: 300 × 0.27 = 81 spot needed (well within 200) → easy to neutralize
- 5200 short: 300 × 0.45 = 135 spot needed → still fine
- 5100 short: 300 × 0.58 = 174 spot needed → near the spot cap

Stacking shorts across multiple strikes will quickly exceed the 200 spot limit. Plan: prioritize strikes with the highest premium-per-delta ratio (= "vega per delta-dollar").

**Premium captured per spot-unit consumed for delta hedge**:
- 5500: 6.07 / 0.055 = **110** XIRECs/spot
- 5400: 15.26 / 0.13 = **117**
- 5300: 45.71 / 0.27 = **169** (BEST)
- 5200: 44.01 / 0.44 = **100**
- 5100: 14.56 / 0.58 = **25**

**VEV_5300 is the clear winner: highest premium AND highest premium-per-delta-cost.**

---

## 8. Spread vs option-mid std (MM opportunity index)

| Strike | mean spread | per-tick mid σ | spread / σ ratio |
|---:|---:|---:|---:|
| 4000 | 20.81 | 1.42 | 14.7 |
| 4500 | 15.85 | 1.25 | 12.7 |
| 5000 | 6.04 | 0.98 | 6.2 |
| 5100 | 4.30 | 0.85 | 5.0 |
| 5200 | 2.89 | 0.69 | 4.2 |
| 5300 | 2.11 | 0.50 | 4.2 |
| 5400 | 1.38 | 0.27 | 5.1 |
| 5500 | 1.15 | 0.18 | 6.4 |
| 6000 | 1.00 | 0.00 | ∞ (frozen) |
| 6500 | 1.00 | 0.00 | ∞ (frozen) |

The deep ITM strikes (4000, 4500) have the WIDEST spreads relative to mid noise — penny-jump MM is highly profitable here, and additionally the **bid is below intrinsic** so they're under-priced. ATM strikes (5200–5400) have ~3-tick spreads which still leaves room.

---

## 9. Dead strikes (6000, 6500) — confirmed truly dead

VEV_6000 bid is 0 at 100% of ticks (only value seen), ask is 1 at 100% of ticks. Same for VEV_6500. No non-zero outliers across 30,000 ticks. **No edge here — skip in trading code.** (This matches the existing `traders/round3/a.py` which already excludes them.)

---

## 10. Sanity check — could we capture this edge with the same exchange model the calibration used?

Three concerns and the data response:

1. **"Bots will pull their bids if I take them aggressively."** The bid book stays populated with 20-unit average size at the rich premium price across **30,000 consecutive ticks** in the data. There is no observed shrinkage even though existing trades constantly hit it. The bid is mechanically posted by the layer-1/layer-2 MMs (see calibration `bot.layer1` formula `floor(fv − 0.5) − 3`), and they will RE-POST every tick irrespective of takes (the FV update is independent of order flow per the calibration model). This is robust.

2. **"Maybe the FV the bots use is not S − K + premium; maybe it really is the option mid we observe."** Look at per-day decay (§5): mids fell 4–5 XIRECs over 3 days even with S drifting up. The decay reveals the bot FV is grinding toward zero (as a true call would). So holding the short captures decay deterministically.

3. **"The position-limit-canceller might bite."** Per `traders/round3/a.py` we only ever check worst-case net exposure once per tick. As long as the strategy code ladders into the 300 limit *cumulatively* (e.g., 30 contracts/tick for 10 ticks) it stays well below the limit at every step.

---

# 11. Concrete trading ideas (ranked by EV)

## Idea 1 — SHORT VEV_5300 to position limit, delta-hedge with VELVETFRUIT_EXTRACT
- **Mechanism**: Post asks at `best_bid + 1` (or take the bot bid directly with an aggressive sell at `bid_price_1`). Sellers from the bot population will continue absorbing ours (price-time priority). Build to position −300.
- **Edge per unit (held to round end)**: ≈ 46 XIRECs (= bid premium over intrinsic = mid-of-day-0 minus mid-of-day-2 captures most of this)
- **Delta hedge**: long 300 × 0.27 ≈ 81 units of VELVETFRUIT_EXTRACT
- **EV per round (no expiry / pure mid-decay over 3 days)**: 300 × 4.4 = **+1,320 XIRECs**
- **EV per round (true expiry to intrinsic 0 at end of round)**: 300 × 46 = **+13,800 XIRECs**
- **Risk**: If S spikes to 5350+ during the round (rare per σ=0.96/tick over 30K ticks; 99th percentile observed S = 5283.5, max 5300), short loses ~50 XIRECs/unit. Delta hedge makes this self-funding.

## Idea 2 — SHORT VEV_5200 to position limit, delta-hedge
- **Edge per unit (round end)**: ≈ 44 XIRECs
- **Delta**: 300 × 0.45 ≈ 135 spot (combined with idea 1: 81 + 135 = 216 — exceeds 200 spot limit!)
  - Mitigation: split spot capacity. E.g., 150 short on 5300 + 100 short on 5200 ⇒ 40 + 45 = 85 spot. Or skip 5200, do 5300 + 5400.
- **EV per round (mid decay)**: 300 × 3.4 = **+1,020 XIRECs**
- **EV per round (expiry to intrinsic 0)**: 300 × 44 = **+13,200 XIRECs**

## Idea 3 — SHORT VEV_5400 to position limit (low delta, easy hedge)
- **Edge per unit (round end)**: ≈ 16 XIRECs
- **Delta**: 300 × 0.13 ≈ 39 spot (cheap)
- **EV (decay)**: 300 × 4.7 = **+1,410 XIRECs**
- **EV (expiry)**: 300 × 16 = **+4,800 XIRECs**
- **Why it's attractive**: tiny delta, so we can stack it ON TOP of 5300 short without exceeding spot limit. Combined 5300 + 5400 short = (300+300) × decay-component ≈ 1,320 + 1,410 = **+2,730 XIRECs** decay-only.

## Idea 4 — SHORT VEV_5500 (smallest premium but free of delta concerns)
- **Edge per unit (round end)**: ≈ 6 XIRECs
- **Delta**: 0.05 → 300 × 0.05 = 15 spot needed
- **EV (decay)**: 300 × 2.8 = **+840 XIRECs**
- **EV (expiry)**: 300 × 6 = **+1,800 XIRECs**

## Idea 5 — BUY VEV_4000 / VEV_4500 deep ITMs (bid-below-intrinsic edge)
- **Mechanism**: The ask sits at intrinsic + 10 (4000) or +8 (4500). This is fair-ish, but the BID is below intrinsic. So we buy at the ask, then post a SELL at the ask price (joining or improving). When other ask-takers come, we sell at intrinsic + 10 and pocket the spread. Delta is 1.0 → just a synthetic spot position.
- This is **basically equivalent to spot MM with extra steps** — given spot already has its own MM, this is mostly redundant. **Skip unless spreads tighten on these.**

## Idea 6 — Penny-jump MM the deep ITM 4000/4500 (current `a.py` already does this)
- Spread of 21 / 16 with per-tick mid σ of 1.4 / 1.25 → ratio 14.7 / 12.7. Very fat. **Tighten quotes by 1 tick on both sides** (the existing `a.py` `_trade_r3_generic` already does this). Edge per round-trip: ~6–8 ticks per fill. Already shipped.

---

## Combined campaign — recommended R3 strategy

**Total expected uplift over current `traders/round3/a.py`**: in the **conservative case** (treating the round as pure 3-day mid-decay capture, no terminal expiry assumption): **+2,730 to +5,000 XIRECs** from short-decay alone (idea 1 + 3, optionally + 4). In the **aggressive case** (vouchers expire to intrinsic at end of round 3 — confirmed P3 behavior, suspected P4 R3 behavior): **+18,000 to +25,000 XIRECs** if we maintain max-short positions to expiry.

Either way, this dwarfs the current ~2K total PnL gap that we noticed vs leaderboard-leading teams.

**Action items for `traders/round3/a.py`:**

1. Add a "rich-options short" module that, for each of {VEV_5300, VEV_5400, VEV_5500}, posts asks at `best_bid` (= cross the spread to hit the bid, taking advantage of the constantly-replenished bot bids). Build incrementally to position limit (e.g., 30 units/tick).
2. Add a delta-hedge module that holds VELVETFRUIT_EXTRACT spot ≈ −Σ(short_position × Δ_BS) computed each tick from the calibrated Bachelier with σ = 0.96 and T = ticks_remaining_in_round.
3. Skip VEV_6000 / VEV_6500 (already done).
4. Keep penny-jump MM on the spot products and the deep ITMs (current code).

**Risk caveats**:
- If MMs change behavior under aggressive flow (bid pulling, widening), edge reduces. Calibration of `joint_empirical` presence model says they re-post 80%+ of ticks regardless. Test on Monte Carlo backtest first.
- If P4 R3 vouchers DON'T expire at end of round but persist as positions valued at last mid, the "expiry" component disappears and we only capture the per-round-decay (~2,700 XIRECs) instead of the full premium. Still a 2× improvement over current PnL.

---

## Files

- Analysis script: `analysis/round3/options_analysis.py`
- Raw findings JSON: `tmp/r3_options/options_findings.json`
- This report: `analysis/round3/options_analysis.md`
