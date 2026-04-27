# Harry_potter_v7 — OBI-enhanced MR

v6 portal: +17,450 (identical to v4 — SL insurance never fired).
Next: squeeze more alpha by layering v3's proven OBI signal on top of
v4's proven MR signal.

## The layered signal design

MR's passive quote layers size the **big side** toward `diff = target − pos`
— already aligned with the mean-reversion bet. v7 tilts that big-side
size further by OBI confluence:

```
if diff_after > 0:   # MR wants to buy
    mult = clip(1 + OBI_FACTOR * obi, [0.3, 1.8])
    b_each = int(big_each * mult)   # OBI>0 amplifies, OBI<0 shrinks
    a_each = small_each             # untouched
elif diff_after < 0: # MR wants to sell
    mult = clip(1 + OBI_FACTOR * (-obi), [0.3, 1.8])
    a_each = int(big_each * mult)
    b_each = small_each
else:
    # No strong MR target — pure OBI bias on both small sides
```

`OBI_FACTOR = 1.0` tuned by CSV sweep. At OBI = ±1 the MR-favored side
hits the 1.8x clip or shrinks to 0.3x. Signal interpretation:

- MR says "price is below fair, buy" (z < 0, target > pos).
- OBI = +0.6 (strong buying pressure, expect rise) → **confluence** →
  amplify bid size: both signals point to "buy now".
- OBI = −0.6 (selling pressure, expect fall) → **conflict** → shrink bid
  size: MR wants to buy but the tape says it'll get cheaper, wait.

Because OBI is forward-tick information (corr 0.3–0.5 with next mid
move) and MR is a static deviation-from-mean signal, they should be
additive when aligned.

## CSV results (3 days × 10k ticks, match-trades worse)

| Version | Day 0 | Day 1 | Day 2 | Total | Δ vs v4 |
|---|---|---|---|---|---|
| v4 (MR only) | 19,372 | 24,040 | 7,404 | 50,816 | — |
| v6 (+ SL insurance) | 19,372 | 24,040 | 7,404 | 50,816 | 0 |
| **v7 (+ OBI tilt)** | **20,174** | **27,900** | 6,725 | **54,798** | **+3,982 (+7.8%)** |

Day 1 jumps by +3,860 (OBI confluence paying off during smooth trends).
Day 2 drops by −679 (OBI tilt occasionally amplifies wrong direction
during drift — the position gate still catches it if it gets severe).

## Per-asset contribution (3-day sum)

| Asset | v4 | v7 | Δ |
|---|---|---|---|
| HYDROGEL | 6,869 | 6,869 | 0 (OBI MM pathway unchanged) |
| VELVETFRUIT | 12,461 | 10,794 | −1,667 |
| VEV_4000 | 6,948 | 6,948 | 0 (OBI MM pathway unchanged) |
| VEV_4500 | −34 | −34 | 0 |
| **VEV_5000** | 3,636 | **7,336** | **+3,700** |
| VEV_5100 | 3,899 | 4,507 | +608 |
| **VEV_5200** | 4,792 | **10,006** | **+5,214** |
| VEV_5300 | 2,980 | 4,966 | +1,986 |
| VEV_5400 | 1,285 | 2,901 | +1,616 |
| VEV_5500 | 690 | 505 | −185 |

VEV_5000 and VEV_5200 double-or-more under OBI tilt. VELVETFRUIT
trades away a little edge (its OBI signal is weaker, corr 0.33 vs
VEV_4000's 0.48). Near-ATM VEVs benefit most because their OBI is
strong and their MR positions are large.

## OBI_FACTOR sweep summary

| Factor | Grand total | Δ vs v4 | Sanity flip |
|---|---|---|---|
| 0.0 (v4) | 50,816 | — | −72,601 |
| 0.1 | 51,577 | +761 | |
| 0.3 | 52,668 | +1,852 | −72,282 |
| 0.5 | 51,827 | +1,011 | −74,646 |
| 0.7 | 51,888 | +1,072 | |
| **1.0 (shipped)** | **54,798** | **+3,982** | **−74,612** |
| 1.5 | 50,765 | −51 | −69,856 |

Factor=1.0 wins on CSV; factor=1.5 starts hurting as the tilt amplifies
drawdowns. Sanity flip at factor=1.0 is −74,612 (vs v4's −72,601) — the
stronger tilt slightly amplifies the anti-strategy's loss too, but v6's
position-gated SL still bounds it.

## Portal projection

v4 CSV 50,816 → portal 17,450. Naïve linear extrapolation:
v7 CSV 54,798 → portal ≈ **~18,900 (+1,400-1,600 over v4)**.

OBI was proven on portal in v3 (+572 on VELVETFRUIT, tiny gains on
VEVs). Applying it on top of MR's large positions should compound more
than that — VEV_5200's +5.2k CSV gain suggests OBI has real leverage
when MR is already loaded into the trade.

## Caveats

- Day 2 regresses slightly because OBI can disagree with MR during
  drifting regimes. Position-gated SL (from v6) is the backstop.
- Sanity flip gets ~2k worse. This means if the portal behaves
  opposite to historical, v7's tilt doubles down on the wrong
  direction more eagerly. Expected cost on an adversarial session.
- VELVETFRUIT −1,667 is surprising. Hypothesis: its OBI signal is
  weaker, so the tilt introduces more noise than lift. Could be
  addressed with per-asset OBI_FACTOR (stronger on high-OBI-signal
  assets like VEV_5200/VEV_4000, weaker on VELVETFRUIT). Saved for v8+.

## Files

```
Rubenstrats/Harry_potter_v7/
├── Harry_potter_v7.py
├── README.md
└── results/

traders/round3/Harry_potter_v7.py
```

## Next: v8 — HYDROGEL MR with multi-level execution

HYDROGEL sits at 610 portal despite 200-share limit and similar AR(1)
to VELVETFRUIT (both ~0.998). Spread is 15 vs VELVETFRUIT's 5, so
passive inside-the-spread fills are slower. Idea: post at bid+1, +3,
+5, +7 simultaneously to capture more of the flow across HYDROGEL's
wide bot spread. Tested earlier with VELVETFRUIT-style execution and
it failed (HYDROGEL dropped to 615 CSV). v8 tries a custom execution
profile sized for wide spreads.
