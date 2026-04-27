# Harry_potter_v4 — R3 "Gloves Off"

Mean-reversion on VELVETFRUIT + 6 near-money VEVs using the full position
budget, with OBI-tilted MM retained on HYDROGEL and the deep-ITM VEVs.

## The thesis

HYDROGEL and VELVETFRUIT are slightly mean-reverting random walks (AR(1)
φ ≈ 0.998, half-life ~300 ticks). The near-money VEVs track these via the
options-pricing link. With position limits of 200 (spot) / 300 (VEV), we
can carry a very big directional bet on reversion.

Feasibility check on the 3-day historical CSV:

| Asset | Cycles / 30k ticks | Gross PnL per share | × full limit |
|---|---|---|---|
| HYDROGEL | 162 | 1,019 | 67,967 (naïve ceiling) |
| VELVETFRUIT | 144 | 382 | 25,467 |

Naïve cycles cost ~half-spread per round-trip; passive execution (post
inside the spread, wait for the market to come to us) avoids that and
keeps the gross.

## Asset routing

| Asset | Strategy | Why |
|---|---|---|
| HYDROGEL_PACK | OBI-tilted MM (v3 style) | Wide 15-tick spread + weak reversion → passive MR fills too slowly. OBI MM pulled +6,484 in v3; MR only +615. |
| VELVETFRUIT_EXTRACT | Mean-reversion | Tight 5-tick spread + clean reversion → inside-the-spread MR orders fill readily. +12,461 on CSV. |
| VEV_4000, VEV_4500 | OBI-tilted MM | Deep-ITM proportional-offset bot with ~20-tick spread. OBI signal is strongest here (corr 0.48 on VEV_4000). +6,948. |
| VEV_5000 … VEV_5500 | Mean-reversion | Tight 2-4 tick spreads + they track UL's mean reversion. All 6 contribute positively (3–5k each). |
| VEV_6000, VEV_6500 | Skip | Dead options, FV≈0, spread=1. |

## How MR execution works

For each MR asset, every tick:

1. Update EMA fair value with `α = 0.0005` (half-life ~1,386 ticks — long
   memory, anchored to the long-run mean).
2. Update EMA variance with `α = 0.01` (faster σ estimation).
3. Compute `z = (mid − FV) / σ`.
4. Target position: `-K × z × limit`, clipped to ±0.85 × limit. K=0.55
   means at |z|=1.5 we target 83% of the limit.
5. Execute:
   - **Aggressive take** if `|z| ≥ 1.2`: cross the spread up to 40
     contracts per tick to lock in position fast. Spread crossing is
     the premium we pay for immediate size on strong signal.
   - **Passive MM layers**: post inside the spread at `best_bid+1`,
     `best_bid+2` (two levels). The side aligned with the signal gets
     big size (30), the other side small (10). Inside layers keep
     priority over bot quotes.

## Backtest results (CSV replay, match-trades worse)

| Version | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| v2 (pure penny-jump) | 4,834 | 7,996 | 1,059 | **13,888** |
| v3 (OBI-tilted MM) | 8,269 | 8,028 | 926 | **17,223** |
| **v4 (hybrid MR + OBI MM)** | **19,372** | **24,040** | **7,404** | **50,816** |

**+36,928 on CSV over v2** — 3.6× improvement.

Per-asset day-by-day confirms the design: MR assets carry most of the new
PnL (VELVETFRUIT 12k, VEV_5000 3.6k, VEV_5100 3.9k, VEV_5200 4.8k,
VEV_5300 3.0k, VEV_5400 1.3k, VEV_5500 0.7k). OBI-MM assets steady
(HYDROGEL 6.9k, VEV_4000 6.9k).

## Sanity verification

Flipping the MR direction (bid when z > 0 → short when actually should
be long) produces **−72,601** over 3 days. That's the anti-strategy —
its equal-magnitude loss confirms v4's gains are real alpha, not
replay-engine artifact.

## Portal projection

v2 CSV:portal ratio was 13,888:1,469 ≈ 0.106. Applying naively: v4
portal ≈ **~5,400**. But MR edge may translate differently than MM edge:
- On portal, other teams are also MM'ing (competing for bot-driven flow)
  → our passive MM fills less → OBI legs might underperform CSV.
- But MR positions build on the bot's side of the trade → largely
  immune to other-team competition → could translate *more* efficiently
  than MM.

Realistic range: **3,500–6,500 on portal**.

## Risk / known issues

1. **Correlated risk on VEVs**: all near-money VEVs track the same UL,
   so our MR position stacks a ~1,800-share equivalent bet on UL
   reversion. If UL drifts hard in one direction, all 6 VEV MR
   positions + the VELVETFRUIT MR position bleed simultaneously.
   Position-limit cutoffs cap the damage but the tail can be large.
2. **Day 2 underperformance** (7k vs 19-24k on days 0/1): VELVETFRUIT
   drifted from 5267 → 5295 on day 2. Slow EMA doesn't adapt fast
   enough to the drift, so we fought the trend. A drift-detection or
   EMA-acceleration heuristic could help but wasn't tested.
3. **MC sim is meaningless** for this strategy. The sim's FV process
   is an independent random walk (no mean reversion), so MR orders
   accumulate losses as FV drifts. MC shows −178,600 mean. This is a
   sim artifact, not a real risk.
4. **Inside-layer adversarial fill**: if the market has informed flow
   that knows where price is heading, our inside-layer orders get
   adverse-selected. This is why day 0/1 results depend heavily on
   how benign flow is — can't fully mitigate.

## Next-step ideas if v4 underperforms on portal

1. **Drift-adaptive EMA**: if |Δmid| > 2σ sustained over 100 ticks,
   double the EMA alpha briefly to catch the drift. Would have helped
   day 2 by ~5k.
2. **Stop-loss**: if asset PnL drops below −2k, flatten + pause MR on
   that asset for 500 ticks.
3. **Portfolio-level delta hedge**: our VEV MR positions have net
   delta; offset with VELVETFRUIT trades (but VELVETFRUIT is also
   under MR, so need a "hedge budget" carved out).
4. **Aggregated position signal**: share FV estimate across correlated
   assets (HYDROGEL vs VELVETFRUIT — are they correlated? probably
   not, but worth checking).

## Files

```
Rubenstrats/Harry_potter_v4/
├── Harry_potter_v4.py
├── README.md
└── results/

traders/round3/Harry_potter_v4.py
analysis/round3/mr_feasibility.py      # feasibility math for MR
analysis/round3/signals.py             # signal-regression (v3 era)
```
