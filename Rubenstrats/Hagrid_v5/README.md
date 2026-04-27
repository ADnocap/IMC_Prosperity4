# Hagrid_v5 — Hagrid_v3 + loose voucher SL as path-divergence insurance

## Why this version exists

MC backtest revealed the gap between portal SR and across-session SR:

| Strategy | Portal SR | MC SR (across 100 sessions) |
|---|---|---|
| Hagrid_v2 | +1.13 | **−1.01** |
| Hagrid_v3 | +1.15 | **−1.01** |

Portal is one realized FV path. The MC distribution shows the typical
session loses heavily because vouchers stack into runaway-drift
sessions with no cap — same failure mode as v8's HYDROGEL collapse,
applied to all 6 stacked vouchers simultaneously.

The portal we've been hitting is a favorable ~10% draw. The actual
round-end eval session may differ. **v5 is insurance, not a tweak.**

## What changed

Single addition: **loose position-gated voucher SL**.

```python
VOUCHER_STOP_THRESHOLD = -5000   # 2× deeper than velvet's -2,500
VOUCHER_STOP_DURATION  = 500     # 1.67× longer than velvet's 300
VOUCHER_STOP_POS_GATE  = 0.80    # arms once stack load reached
VOUCHER_STOP_PAUSE     = 500
```

Design rationale:

| Parameter | Choice | Why |
|---|---|---|
| Gate 0.80 | matches velvet | Arms when |pos| ≥ 240 (full stack load) |
| Threshold −5,000 | 2× velvet's | Per-voucher max drawdown on portal stays ~−2k during normal MR build-up; this sits well above the noise floor |
| Duration 500 | 1.67× velvet's | Filters v1-style transient dips that fired Hagrid_v1's SL prematurely; only sustained drift triggers |

The Hagrid_v1 lesson: SL with gate 0.80, threshold −2,500, duration
300 fired during normal MR build-up on VEV_5000 (cost −5,561). v5's
SL is 2× deeper and 1.67× longer — empirically tuned to NOT fire on
the v3 portal trajectory.

## Validation

### CSV replay (round 3, 3 days)

| Strategy | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| Hagrid_v3 | 19,300 | 23,263 | 2,000 | **44,562** |
| **Hagrid_v5** | 19,300 | 23,263 | 2,000 | **44,562** |

**Bit-identical.** The SL never fires on the proven portal path.

### MC across 100 synthetic sessions

| Metric | Hagrid_v3 | Hagrid_v5 | Δ |
|---|---|---|---|
| Mean | −39,139 | **−29,923** | **+9,216** |
| Std | 38,798 | 36,610 | −2,188 |
| Median | −33,838 | −28,970 | +4,868 |
| 5% worst | −106,008 | **−93,343** | **+12,665** |
| 95% best | +18,059 | +31,889 | +13,830 |
| **MC SR** | **−1.01** | **−0.82** | **+0.19** |

The 95% best case actually *improves* (+13,830) because the SL
prevents drift sessions from compounding losses, freeing up
position-budget for productive reversions later in the session.

## Portal projection

Same as v3: **+25,801** (no SL fires on the deterministic portal
session). Insurance comes for free if portal session is benign.

## Tradeoff summary

| Scenario | Hagrid_v3 | Hagrid_v5 |
|---|---|---|
| Portal session (proven good draw) | +25,801 | **+25,801** (identical) |
| Final eval similar to portal | +25,800 ± noise | +25,800 ± noise |
| Final eval moderately adverse | bleeds | **caps at SL fires** |
| Final eval severely adverse (v8-style) | catastrophic | **caps at SL fires** |

## Position-limit safety check

Voucher gate fires when |pos| ≥ 0.80 × 300 = 240. Stack target at
0.90 frac = 271 (VEV_5000). So the gate ARMS during normal stacking.

Then the threshold check (−5,000 sustained for 500 ticks) determines
if SL fires. On portal v3, per-voucher MTM during build-up bottoms at
roughly −2k → never below −5k for 500 ticks → SL doesn't fire.

On adverse-drift session: position locks at +271, mid keeps falling,
MTM passes −5k, stays there 500+ ticks → SL fires, unwinds passively.
Loss capped around per-voucher −5k to −7k instead of compounding.

## Architecture

```
HYDROGEL_PACK    →  OBI MM
VELVETFRUIT      →  pure MR + position-gated SL (gate 0.80, thr −2,500, dur 300)
VEV_4000/4500    →  OBI MM
VEV_5000..5500   →  velvet-z stacked MR
                   + loose voucher SL (gate 0.80, thr −5,000, dur 500)
VEV_6000/6500    →  skip (dead)
```

## Files

```
Rubenstrats/Hagrid_v5/
├── Hagrid_v5.py
├── README.md
└── results/

traders/round3/Hagrid_v5.py
```
