# ACO Hidden Pattern — Research Findings

## The Signal: Bot1 Outer Wall Asymmetry

Bot1 (outer wall, vol 20-30) posts at FV +/- {10, 11}. The offsets are
almost always **asymmetric**: one side at 10, the other at 11.

```
asym = ask_offset - bid_offset
  +1 = bid at FV-11, ask at FV+10  (bid wider)  -> FV GOES UP
  -1 = bid at FV-10, ask at FV+11  (ask wider)  -> FV GOES DOWN
```

### Accuracy

When FV actually changes (non-zero move), Bot1 asymmetry predicted
the direction correctly:

| Day | Correct | Wrong | Accuracy |
|-----|---------|-------|----------|
| -2  | 631     | 38    | **94.3%** |
| -1  | 586     | 33    | **94.7%** |
|  0  | 562     | 46    | **92.4%** |

### Expected returns by signal direction

When asym = +1 (bullish), across all 3 days consistently:
- ret+1:  +0.12 to +0.16
- ret+5:  +0.23 to +0.27
- ret+10: +0.22 to +0.26
- ret+20: +0.19 to +0.27

When asym = -1 (bearish), mirror image (negative returns).

### Signal availability

- Bot1 visible on both sides: ~4,000 of 10,000 ticks per day (40%)
- ~2,000 of those are bullish, ~2,000 bearish
- Mean run length: 1.3 ticks (78% of runs are 1 tick)

---

## Other Confirmed Properties

### True FV structure
- FV is always **integer** (reconstructed from Bot2 walls at FV +/- 8)
- FV changes are mostly {-1, 0, +1}, occasionally +/-2 or +/-3
- ~34% of ticks: FV unchanged
- AC(1) of FV returns = **-0.50** (exact, all days)

### Bot behavior
- **Bot2** (inner wall, vol 10-15): Always symmetric (equal vol both sides), at FV +/- 8
- **Bot1** (outer wall, vol 20-30): Asymmetric offsets encode direction
- **Bot3** (noise, vol 1-9): Places orders near FV, qty 2-5 common
  - Bids at FV-2 and FV-3
  - Asks at FV+1 and FV+2
  - ~500 appearances per day

### Mean-reversion (OU process)
- kappa ~ 0.004-0.008, half-life ~90-190 ticks
- Long-run mean mu ~ 10000
- Variance ratio declines to ~0.33 at 100-tick horizon

### Cross-product
- Zero correlation between IPR and ACO (independent)

---

## The Monetization Problem

The 16-tick spread (Bot2 at FV +/- 8) makes naive directional trading
unprofitable despite 92-95% accuracy:

- 96% of ticks: best ask at FV+8, best bid at FV-8
- Expected per-tick return: +/-0.14 (too small vs 8-tick entry cost)
- Only ~1% of ticks have asks below FV (Bot3 or stale quotes)

### Favorable entry windows

Ticks where asks are below FV: ~110-170 per day
Ticks where bids are above FV: ~130 per day

When these coincide with Bot1 signal: only 18-32 per day per side.

---

## How Top Scorers Likely Exploit This

Given: avg fill = 2.3, max drawdown = 609-1057, ~3500 PnL gap.

### Hypothesis: Asymmetric market making

Rather than crossing the spread for directional trades, use Bot1
signal to make **informed MM decisions**:

1. When Bot1 asym = +1 (bullish):
   - Tighten bid (post closer to FV, e.g., FV-5 or FV-6)
   - Widen ask (post further from FV, e.g., FV+9)
   - Get filled on bids (accumulate longs before up move)
   - Avoid getting filled on asks (don't sell before up move)

2. When Bot1 asym = -1 (bearish): mirror image

3. When no signal: standard symmetric MM

The 2.3 avg fill matches posting small orders (2-3 qty) that Bot3
can hit. The higher drawdown matches holding directional risk.

### Alternative: Selective aggression at stale quotes

When Bot3 places an order inside the walls AND Bot1 confirms
direction, take the Bot3 order. ~100-200 opportunities per day,
each with 2-3 tick edge from entry + small directional edge.

---

## What We Haven't Found

- No deterministic FV sequence or period
- No cross-product signal
- Bot2 volume is iid uniform (no information)
- FV mod N patterns don't persist across days
- No obvious higher-order Markov structure beyond AC(1)
