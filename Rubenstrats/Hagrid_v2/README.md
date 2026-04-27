# Hagrid_v2 — Hagrid_v1 minus voucher SL

## What changed

Hagrid_v1 portal: **+19,780**. Friend's: **+25,281**. Deficit −5,501,
all on VEV_5000 (1,481 vs 7,042).

Cause: VEV_5000 is the only voucher whose stack target exceeds the
position-gated SL threshold:

| Voucher | Δ | Target = 0.9 × 300 × (Δ+0.3) | Gate (80%×300=240) |
|---|---|---|---|
| **VEV_5000** | 0.654 | **257** | **fires (≥240)** |
| VEV_5100 | 0.577 | 237 | safe |
| VEV_5200 | 0.437 | 199 | safe |
| VEV_5300 | 0.273 | 154 | safe |
| VEV_5400 | 0.129 | 116 | safe |
| VEV_5500 | 0.055 | 96 | safe |

Once at +257, the gate armed, MTM dropped below −2,500 during the
normal MR build-up drawdown for 300 ticks, and the SL paused MR + did
a passive unwind — exactly the v5 → v6 failure mode replayed.

**Single-line fix**: drop the SL check from `_trade_voucher`. Friend's
strategy has no voucher SL and works fine.

The SL is **kept** on VELVETFRUIT (spot) where:
- max position = 0.85 × 200 = 170, vs gate 160 — gate can arm
- but σ ≈ 15 (low), so MTM rarely reaches −2,500 in practice

## Expected portal

Hagrid_v2 should match the friend on every stacked voucher (no
divergence mechanism left), and slightly beat them on VEV_4000 / 4500
OBI MM:

```
Friend total                 25,281
+ VEV_4000 OBI MM advantage      ~30
+ VEV_4500 OBI MM advantage      ~30
                            ─────────
Hagrid_v2 estimate            ~25,340
```

vs v6's +17,450 → +7,890 lift.

## CSV replay (round 3, 3 days)

| | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| Hagrid_v1 | 20,666 | 22,297 | 2,460 | 45,424 |
| **Hagrid_v2** | **20,666** | **22,297** | **2,460** | **45,424** |

Identical — CSV's VEV_5000 day-2 path didn't trigger SL in either
version. The fix only matters on portal sessions where VEV_5000's MR
build-up takes the SL path.

## Files

```
Rubenstrats/Hagrid_v2/
├── Hagrid_v2.py
├── README.md
└── results/

traders/round3/Hagrid_v2.py
```
