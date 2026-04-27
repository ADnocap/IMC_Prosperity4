# Harry_potter_v8 — HYDROGEL on MR with single-level execution

v7 portal: +17,404. Essentially flat vs v4's +17,450. The deterministic-
portal finding revealed that our passive-size tilts were saturating at
bot/taker flow capacity — bigger orders at the same price don't get
more fills.

v8's bet: HYDROGEL has 200-share position limit and similar mean
reversion to VELVETFRUIT (AR(1) φ ≈ 0.998), but contributes only ~610
on portal via OBI MM. Move it to full MR — with the right execution
profile.

## The size-saturation lesson

Earlier MR-on-HYDROGEL tests used VELVETFRUIT's 2-level size-30
execution and produced 615 CSV total (vs OBI MM's 6,484). I attributed
that to "wide-spread asset can't fill inside layers"; actually the
issue was **over-saturation**. HYDROGEL's taker-flow capacity per
tick at penny-jump prices caps at ~12-15. Posting 30 ties up order
headroom without filling more; adding bid+2, bid+3 reaches farther
into the spread where taker flow is even thinner.

## v8 config

Per-asset passive-layer config (each `(offset, big_size)`):

| Asset | Config | Why |
|---|---|---|
| HYDROGEL | `[(1, 15)]` | Single level, size matched to taker capacity |
| VELVETFRUIT | `[(1, 30), (2, 30)]` | Same as v7 — tight spread has room for 2 levels |
| VEV_5000..5500 | `[(1, 30), (2, 30)]` | Same as v7 |

Size sweep (HYDROGEL single level):

| Size | HYD PnL | Grand |
|---|---|---|
| 10 | 6,227 | 54,156 |
| 12 | 6,249 | 54,178 |
| **15** | **14,387** | **62,316** |
| 17 | 10,288 | 58,217 |
| 20 | 12,640 | 60,569 |
| 30 | 7,102 | 55,031 |

Sharp peak at 15 — that's HYDROGEL's real taker capacity. Slightly
below or above both underperform.

Multi-level variants:

| Config | HYD | Grand |
|---|---|---|
| `[(1,15)]` (shipped) | 14,387 | 62,316 |
| `[(1,15), (2,10)]` | 13,872 | 61,801 |
| `[(1,15), (3,10)]` | 13,843 | 61,772 |
| `[(1,15), (2,12), (3,10)]` | 11,972 | 59,901 |
| `[(1,30), (3,25), (5,20), (7,15)]` | 54 | 47,983 (worst) |

Adding price levels past bid+1 gains nothing — taker flow doesn't reach
those prices often enough. The "multi-level across wide spread"
intuition was wrong; the wide spread is the bot's spread, not a pool
of orderable price levels.

## CSV results

| Version | Day 0 | Day 1 | Day 2 | Total | Δ vs v4 |
|---|---|---|---|---|---|
| v4 (MR VEV+VELV only) | 19,372 | 24,040 | 7,404 | 50,816 | — |
| v6 (+ SL insurance) | 19,372 | 24,040 | 7,404 | 50,816 | 0 |
| v7 (+ OBI tilt on MR) | 20,174 | 27,900 | 6,725 | 54,798 | +3,982 |
| **v8 (+ HYDROGEL on MR)** | **19,320** | **34,708** | **8,287** | **62,316** | **+11,500 (+23%)** |

Day 1 leads the lift (+6,808 over v7): HYDROGEL day-1 MR captured
10,666 vs v7's 3,857. Day 0 slightly regresses on HYDROGEL but net
positive. Day 2 gets +1,562 — MR on HYDROGEL handles day 2's conditions
better than OBI MM did.

## Per-asset (3-day sum)

| Asset | v7 | v8 | Δ |
|---|---|---|---|
| **HYDROGEL_PACK** | 6,869 | **14,387** | **+7,518** |
| VELVETFRUIT_EXTRACT | 10,794 | 10,794 | 0 |
| VEV_4000 | 6,948 | 6,948 | 0 |
| VEV_4500 | −34 | −34 | 0 |
| VEV_5000 | 7,336 | 7,336 | 0 |
| VEV_5100 | 4,507 | 4,507 | 0 |
| VEV_5200 | 10,006 | 10,006 | 0 |
| VEV_5300 | 4,966 | 4,966 | 0 |
| VEV_5400 | 2,901 | 2,901 | 0 |
| VEV_5500 | 505 | 505 | 0 |

The entire lift comes from HYDROGEL. Other assets' behavior is
deterministically identical — v8 only changed HYDROGEL's strategy.

## Portal projection

v4 CSV 50,816 → portal 17,450 (ratio 0.343). Apply naively:
v8 CSV 62,316 → **portal ~21,400 (+4,000 over v4)**.

CSV-to-portal ratio for HYDROGEL specifically: v7's HYD CSV 6,869 →
portal 610 (ratio 0.089 — much lower than overall 0.343). If
HYDROGEL's ratio is consistent at ~0.089, v8's CSV 14,387 → portal
~1,280 on HYDROGEL (+670 over v7's 610). Other assets unchanged.
**Minimum portal estimate: v4's 17,450 + 670 = ~18,100.**

Best case (HYDROGEL MR scales like VELVETFRUIT's MR did on portal,
which was much more efficient than CSV predicted): portal could be
closer to +21k.

## Sanity check

Sanity flip at v8: **−85,896** (vs v7's −74,612, v4's −72,601). The
anti-strategy is now building losing positions on HYDROGEL too, so
the tail loss is ~11k bigger. Position-gated SL is still firing and
bounding the damage, but the alpha-to-tail ratio is slightly worse:

| Version | Alpha | Tail | Ratio |
|---|---|---|---|
| v4 | 50,816 | −72,601 | 1:1.43 |
| v7 | 54,798 | −74,612 | 1:1.36 |
| v8 | 62,316 | −85,896 | 1:1.38 |

Similar risk profile; the absolute tail is bigger because we're
running MR on more assets, but gain scales faster than tail.

## Caveats / risks

1. **Portal HYDROGEL is likely not 14k** — the 610 portal-PnL for OBI
   MM on HYDROGEL suggests HYDROGEL has much less taker flow on portal
   than CSV implies. Expect v8 HYDROGEL to add a few hundred to a few
   thousand on portal, not the full 14k CSV gain.
2. **Size 15 is tuned tight** — if portal's taker flow differs from
   CSV's, the optimum could be 12 or 18 instead. Hard to test without
   submitting.
3. **Day 1 heavy concentration**: 10,666 of HYDROGEL's 14,387 came
   from CSV day 1. If portal session doesn't match day 1's dynamics,
   HYDROGEL gain is smaller.

## Files

```
Rubenstrats/Harry_potter_v8/
├── Harry_potter_v8.py
├── README.md
└── results/

traders/round3/Harry_potter_v8.py
```

## Next ideas if v8 underperforms

- Pick size per-day by observed trade rate (adaptive) instead of
  hardcoded 15.
- Try MR on VEV_4000 and VEV_4500 with single-level small sizes.
- Revisit v5's pure-passive unwind for the inventory-heavy assets.
