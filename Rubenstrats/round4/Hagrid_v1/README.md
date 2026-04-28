# Hagrid_v1 — voucher stacking on VELVETFRUIT z, with our v6 wins kept

## Origin

Friend's portal sub 386072 hit **+25,281**, beating our v6 (+17,450) by
+7,831. Per-asset diff:

| Asset | v6 (~est) | Friend | Δ |
|---|---|---|---|
| HYDROGEL | 610 | 610 | 0 |
| VELVETFRUIT | ~3,500 | 3,050 | −450 |
| **VEV_4000** | **~2,300** | 104 | **−2,200 (we win)** |
| VEV_4500 | ~−10 | 69 | +80 |
| **VEV_5000** | ~1,200 | **7,042** | **+5,800** |
| **VEV_5100** | ~1,500 | **6,682** | **+5,200** |
| VEV_5200 | ~3,300 | 4,561 | +1,300 |
| VEV_5300 | ~2,100 | 2,291 | +200 |
| VEV_5400 | ~700 | 655 | −50 |
| VEV_5500 | ~700 | 216 | −500 |

The +9k advantage is concentrated on VEV_5000/5100. Our +2k advantage
is on VEV_4000 (OBI MM beats their voucher stacking on wide-spread
deep-ITM vouchers).

## What changed

Friend's key insight: **drive ALL voucher MR trades from VELVETFRUIT's
z-score**, not each voucher's own. Vouchers are calls on VELVET — when
the spot reverts, the chain reverts together. Using VELVET (cleanest
mid, tightest spread) as the master signal × 8 vouchers × 300 limit
each = a much bigger position bank than our voucher-by-voucher
z-scoring.

```python
# When velvet_z >= +1.2 (velvet rich, expect to fall):
sign = -1                                          # short the vouchers
target = sign * 0.90 * limit * (|delta| + 0.3)     # delta-sized
# VEV_5000 (delta 0.654) → target ±257 contracts
```

## Hagrid_v1 = friend's stacking engine + our wins

| Asset | Strategy | Source |
|---|---|---|
| HYDROGEL | OBI MM (size 15, 3-tier OBI sizing) | v6 (matched friend's +610) |
| **VEV_4000** | **OBI MM** | **v6 (we beat friend by +2,200 here)** |
| **VEV_4500** | **OBI MM** | v6 |
| VELVETFRUIT | MR + regime gating + flow signal | friend |
| VEV_5000..5500 | MR driven by velvet_z, sized by delta | friend |
| VEV_6000/6500 | skip (deep OTM, dead) | both |

**Three regimes** for VELVETFRUIT and stacked vouchers:

- `|z| ≥ 1.2` — pure MR stack, aggressive cross-spread take (cap 80), no flow noise
- `|z| < 0.3` — flatten to 0, defensive flow skew on quote prices only
- middle — flow-bias target + defensive skew

**Trade-flow signal**: signed taker volume (price > mid → +, < mid → −)
over a 5000-tick rolling window. Used for:
1. Defensive quote-price skew when flow is hot
2. Offensive position bias in middle zone (`|z|` between 0.3 and 1.2)

**Position-gated stop-loss** kept from v6: fires only when |pos|≥80%
of limit AND MTM<−2500 sustained for 300 ticks. Pure insurance, never
fires on profitable runs.

## CSV results (round-3 historical, 3 days × 10K ticks)

| Strategy | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| Friend (sub 386072) | 19,072 | 19,376 | 152 | 38,600 |
| **Hagrid_v1** | **20,666** | **22,297** | **2,460** | **45,424** |
| v6 baseline (different harness) | 19,372 | 24,040 | 7,404 | 50,816 |

Hagrid_v1 beats friend's CSV by **+6,824**, almost entirely from
VEV_4000 OBI MM (+2,308 on day 2 alone). v6's higher CSV total reflects
that voucher-by-voucher MR over-fills on CSV replay's loose match rules
— but its **portal** PnL was only 17,450 because real fills are
size-saturated. Friend's voucher-stacking captures the actual portal
edge.

## Portal projection

- Friend portal: 25,281 (day 2 only)
- Hagrid_v1 inherits friend's voucher-stacking → expect ~25k base
- Plus our VEV_4000 OBI MM advantage: +2,200 over friend's day-2 result
- Plus VEV_4500 (small) ≈ +0
- HYDROGEL identical to both → 610

**Estimate: +27,000–28,000 on portal day 2**, vs v6's +17,450.

## Risks

1. **Friend's day-2 result might not generalize** — their +25k came on
   one specific portal session. If next session's regime differs, the
   stacking mechanics could underperform. SL gate is the backstop.
2. **VOUCHER_STACK_FRAC = 0.90** — packs the position book to 90% of
   limit on strong z. If the signal is wrong, drawdowns are bigger.
   The position-gated SL is exactly the insurance for this.
3. **Flow signal in middle zone** could conflict with MR. Friend keeps
   `FLOW_BIAS_MAX_FRAC = 0.15` (small) which dampens the conflict.

## Files

```
Rubenstrats/Hagrid_v1/
├── Hagrid_v1.py
├── README.md
└── results/

traders/round3/Hagrid_v1.py
```
