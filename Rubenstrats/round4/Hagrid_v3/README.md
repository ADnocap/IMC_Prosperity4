# Hagrid_v3 — VELVETFRUIT reverted to v6-style pure MR

## What changed

v2 portal landed at +25,341 (matched projection: friend 25,281 + 60).
But comparing v6 portal vs v2 portal, **VELVETFRUIT regressed
−460** (3,510 → 3,050). The friend's regime gating
(`|z|<0.3 → flatten to 0`, middle zone → flow-bias) costs edge that
v6's continuous MR captured.

v3 reverts only `_trade_velvet` to v6's pure MR:

- Continuous z-target: `target = clip(-K × z, ±MAX_FRAC) × limit` — no
  flatten zone, no flow bias
- Aggressive cross-spread take when `|z| ≥ 1.2` (cap MR_TAKE_MAX = 40)
- Passive 2-level layers, big=30 / small=10 (v6 sizing, not the
  voucher 25/8 × 3-level pattern)
- Position-gated SL kept (gate=80%, threshold=−2500, dur=300)

Voucher stacking on velvet_z is unchanged from v2.

## Per-asset comparison (portal)

| Asset | v6 | Friend | Hagrid_v2 | v3 expected |
|---|---|---|---|---|
| HYDROGEL | 610 | 610 | 610 | 610 |
| **VELVETFRUIT** | **3,510** | 3,050 | 3,050 | **~3,510** |
| VEV_4000 | 134 | 104 | 134 | 134 |
| VEV_4500 | 99 | 69 | 99 | 99 |
| VEV_5000 | 3,550 | 7,042 | 7,042 | 7,042 |
| VEV_5100 | 3,524 | 6,682 | 6,682 | 6,682 |
| VEV_5200 | 3,333 | 4,561 | 4,561 | 4,561 |
| VEV_5300 | 2,178 | 2,291 | 2,291 | 2,291 |
| VEV_5400 | 491 | 655 | 655 | 655 |
| VEV_5500 | 20 | 216 | 216 | 216 |
| **TOTAL** | **17,450** | **25,281** | **25,341** | **~25,800** |

## CSV replay (round 3, 3 days)

| | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| Hagrid_v2 | 20,666 | 22,297 | 2,460 | 45,424 |
| **Hagrid_v3** | **19,300** | **23,263** | **2,000** | **44,562** |

CSV total is slightly worse, but CSV's match-trades-all over-fills are
known to mislead. Portal is the truth — and on portal, v6's pure MR
made VELVETFRUIT +460 more than the friend's regime-gated MR.

## Risks

- CSV replay says v3 is slightly worse; if portal aligns with CSV
  rather than with v6's prior portal result, we lose a few hundred
  instead of gaining.
- VELVETFRUIT is ~12% of total PnL — even if the +460 estimate
  doesn't fully materialize, downside is bounded.

## Files

```
Rubenstrats/Hagrid_v3/
├── Hagrid_v3.py
├── README.md
└── results/

traders/round3/Hagrid_v3.py
```
