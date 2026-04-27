# Hagrid_v4 — best-of-everything

The synthesis of every R3 lesson learned across 12 portal submissions.

## The full ledger (12 portal subs, per-asset PnL)

| Sub | Strategy | TOTAL | HYD | VEL | V4000 | V4500 | V5000 | V5100 | V5200 | V5300 | V5400 | V5500 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 367534 | v1 BS vol-arb | **−139** | 610 | 249 | 0 | 0 | −338 | −296 | −128 | −132 | −83 | −20 |
| 368721 | v2 penny-jump MM | 1,469 | 610 | 585 | 134 | 99 | 25 | 12 | 5 | 0 | 0 | 0 |
| 369488 | v3 OBI-tilt MM | 1,465 | 610 | 573 | 134 | 99 | 35 | 12 | 1 | 0 | 0 | 0 |
| **370288** | **v4 MR (own-z)** | **17,450** | 610 | **3,510** | 134 | 99 | 3,550 | 3,524 | 3,333 | 2,178 | 491 | 20 |
| 371284 | v5 v4+inst SL | 9,967 | 610 | 998 | 134 | 99 | 1,684 | 1,859 | 1,475 | **2,597** | 491 | 20 |
| 371991 | v6 v4+gated SL | 17,450 | 610 | 3,510 | 134 | 99 | 3,550 | 3,524 | 3,333 | 2,178 | 491 | 20 |
| 372704 | v7 v6+OBI tilt | 17,404 | 610 | 3,464 | 134 | 99 | 3,550 | 3,524 | 3,333 | 2,178 | 491 | 20 |
| 373233 | v8 v7+HYD MR | 10,069 | **−6,726** | 3,464 | 134 | 99 | 3,550 | 3,524 | 3,333 | 2,178 | 491 | 20 |
| 386072 | Friend velvet-z | 25,281 | 610 | 3,050 | 104 | 69 | **7,042** | **6,682** | **4,561** | 2,291 | **655** | **216** |
| 470781 | Hagrid_v1 | 19,780 | 610 | 3,050 | 134 | 99 | 1,481 | 6,682 | 4,561 | 2,291 | 655 | 216 |
| 471519 | Hagrid_v2 | 25,341 | 610 | 3,050 | 134 | 99 | 7,042 | 6,682 | 4,561 | 2,291 | 655 | 216 |
| **472445** | **Hagrid_v3** | **25,801** | 610 | **3,510** | 134 | 99 | 7,042 | 6,682 | 4,561 | 2,291 | 655 | 216 |

## What worked (kept in v4)

| Pattern | Asset(s) | Contribution |
|---|---|---|
| OBI MM with single-layer + tiered sizing | HYDROGEL, VEV_4000, VEV_4500 | +843 |
| Pure MR + slow EMA + z-target (own-z) | VELVETFRUIT | +3,510 |
| Voucher-stacking on velvet_z, sized by delta | VEV_5000..5500 | +21,448 |
| Position-gated SL (gate=80%, dur=300, thr=−2,500) | VELVETFRUIT only | 0 cost on profitable runs |

## What failed (excluded from v4)

| Pattern | Sub | Failure mode |
|---|---|---|
| BS vol-arb (σ=0.018) | v1 | Portal MTMs at bot's σ; no edge to capture |
| OBI tilt added to MM size | v3 | Signal too small at portal scale; flat |
| Instantaneous SL @ −2,500 | v5 | Fired during MR build-up drawdowns; killed reversions |
| OBI tilt added to MR layers | v7 | Size-saturated; flat |
| MR on HYDROGEL | v8 | Drift regime; no reversion → −7,335 |
| SL on stacked vouchers | Hagrid_v1 | VEV_5000 stack target ≥ gate; fired mid-build (−5,561) |
| Friend's regime gating on VELVET | Hagrid_v2 | Flatten zone forces premature unwinds (−460) |

## The ceiling lesson

If we cherry-picked the best portal result for each asset across all 12 subs, total = **+26,107**. Hagrid_v3 already hits **+25,801** — gap is **+306**, all on VEV_5300 from a v5 fluke (not reproducible). So Hagrid_v3 sits at the proven ceiling. v4's lift comes only from new dial bumps, not from new strategy patterns.

## Hagrid_v4 changes (three small same-direction bumps)

| Knob | v3 | v4 | Mechanism | Estimate |
|---|---|---|---|---|
| `VOUCHER_STACK_FRAC` | 0.90 | **0.95** | Tighter pack on stacked vouchers — VEV_5000 target 257 → 271, headroom to limit 300 | +400 |
| `PASSIVE_BIG` | 25 | **30** | More MM size on stacked vouchers' big side per layer | +200 |
| `STACK_TAKE_MAX` | 80 | **100** | Faster aggressive ramp at z-open ⇒ more time at target ⇒ more reversion-time fills | +100 |

All other settings unchanged. No new architecture.

### Headroom check

VOUCHER_STACK_FRAC 0.95 × 300 × (|Δ|+0.3) targets:

| Voucher | Δ | v3 target | v4 target | Limit |
|---|---|---|---|---|
| VEV_5000 | 0.654 | 257 | **271** | 300 ✓ |
| VEV_5100 | 0.577 | 237 | **249** | 300 ✓ |
| VEV_5200 | 0.437 | 199 | **210** | 300 ✓ |
| VEV_5300 | 0.273 | 154 | **163** | 300 ✓ |
| VEV_5400 | 0.129 | 116 | **122** | 300 ✓ |
| VEV_5500 | 0.055 | 96 | **101** | 300 ✓ |

All safely under limits.

### SL gate intact

The position-gated SL on VELVETFRUIT (gate=160) still fits inside the
MR_MAX_FRAC=0.85 cap (max position 170). Voucher SL still disabled
(per Hagrid_v2 fix).

## CSV replay (round 3, 3 days)

| Strategy | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| Hagrid_v3 | 19,300 | 23,263 | 2,000 | 44,562 |
| **Hagrid_v4** | **18,330** | **24,712** | **1,314** | **44,356** |

CSV total slightly lower (−206), but **CSV has consistently misled
us this round** — it predicted Hagrid_v2 > Hagrid_v3 (45,424 > 44,562)
but portal showed v3 > v2 (25,801 > 25,341). The CSV's
match-trades-all over-fills don't reflect portal taker capacity.

## Portal projection

```
Hagrid_v3 portal              25,801
+ STACK_FRAC bump (5% pack)     +400
+ PASSIVE_BIG bump              +200
+ STACK_TAKE_MAX bump           +100
                              ───────
Hagrid_v4 estimate            ~26,500
```

## Risks

1. **All three knobs move toward "more aggressive."** If portal taker
   liquidity is the binding constraint (not our orders), the bumps
   buy nothing. Downside: ~0.
2. **Tighter packing means bigger drawdowns** when the signal flips
   while loaded. Position-gated SL on the spot is the backstop, but
   it doesn't apply to vouchers.
3. **VOUCHER_STACK_FRAC 0.95 and PASSIVE_BIG 30 compound**: between
   them and STACK_TAKE_MAX 100, all three lift quote-side
   exposure. If anything regresses, expect it on the most
   delta-heavy voucher (VEV_5000).

## Architecture summary (final)

```
HYDROGEL_PACK    →  OBI MM (single layer, OBI-tiered sizing)
VELVETFRUIT      →  pure MR + slow EMA + z-target (K=0.55, MAX=0.85)
                    + 2-level passive 30/10
                    + cross-spread take @ |z|≥1.2 (cap 40)
                    + position-gated SL (gate 80%, dur 300, thr −2500)
VEV_4000         →  OBI MM (wide spread, take loses)
VEV_4500         →  OBI MM
VEV_5000..5500   →  velvet-z stacked MR
                    target = sign × 0.95 × 300 × min(1, |delta|+0.3)
                    + 3-level passive 30/8 with flow-skew
                    + cross-spread take @ |velvet_z|≥1.2 (cap 100)
                    + flow-bias in middle zone (FLOW_PRODUCTS only)
                    + flatten in close zone (|z|<0.3)
                    + NO SL
VEV_6000/6500    →  skip (deep OTM, dead)
```

## Files

```
Rubenstrats/Hagrid_v4/
├── Hagrid_v4.py
├── README.md
└── results/

traders/round3/Hagrid_v4.py
```
