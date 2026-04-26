# HYDROGEL_PACK Deep-Dive (Round 3)

**Goal.** Diagnose why HYDROGEL loses in MC for v3 (trial #301: HYDROGEL -1,099 vs VELVETFRUIT +4,462) and prescribe a HYDROGEL-only param search.

**Data.** 3 days x 10K ticks; 1,010 trades. Median spread 16. mid_std 25.3/37.6/31.6 across days 0/1/2 -- **day 1 is noisier**. Script `hydrogel_deep.py` -> `hydrogel_deep.json`.

## 1. rev_z window sweep -- v3 has the wrong window

v3 uses `w=50, |z|>2.4, hold=359`. Sweep:

| w | H | n | mean ticks/sig | Sharpe/sig | 3-day consistent |
|---|---|---|---|---|---|
| **500** | **1000** | 13,120 | **+14.79** | **+0.398** | **YES** |
| 500 | 200 | 14,036 | +8.37 | +0.360 | YES |
| 500 | 500 | 13,624 | +9.46 | +0.318 | YES |
| 200 | 200 | 15,525 | +6.76 | +0.293 | YES |
| 50 | 200 (v3) | ~16,200 | +3.68 | +0.155 | YES |

**Refines `signal_decay.md` Sec 8** (only ranked w=50). w=500/H=1000 is 2.6x Sharpe, 4x mean vs v3. HYDROGEL reversion lives at ~500-tick scale (sigma=1.92 RW drifts 40-60 ticks before reverting); w=50 over-fires on noise. Hold=359 OK; trigger window is the bug.

## 2. OBI x rev_z agreement -- gold filter

cor(OBI, rev_z(50)) per day: -0.024/+0.011/-0.024 -- uncorrelated globally. But when both fire (`|z|>2.4 & |OBI|>0.05`, ~30-50/day), they **agree 97-100%** and agree-only PnL is +3.5/+5.0/+5.0 ticks/sig at H=100. At `|z|>1`, both fire ~190/day, agree 81-83%, agree-only PnL **+5.8/+6.8/+5.5 at H=200, all 3 days**.

Most important finding: **rev_z alone is fragile (Sec 6); OBI-agreement gate removes bad fires.**

## 3. BUY cluster fade -- DOES NOT REPLICATE

`trades_signals.md` claimed BUY clusters (>=3 lifts/50 ticks) fade +7 ticks at H=500 (n=126). Re-implementation with strict per-day stratification + non-overlapping triggers:

| variant | triggers (3d) | mean H=500 | days positive |
|---|---|---|---|
| k=3, w=50 | 64 | **-4.28** | 1/3 |
| k=4, w=50 | 28 | -13.7 | 1/3 |
| k=3, w=25 | 33 | -1.6 | 1/3 |

Signal flips sign across days (day 1 +15; days 0/2 -15). Original n=126 had overlapping double-counts; after dedupe sample drops to ~65 and per-day picture is noise. **Not a real signal; do not implement.**

## 4. Wide-spread MM placement -- penny-jump is correct

Post at `best_bid+skew`, exit at mid+5:

| skew | buy edge/fill | sell edge/fill |
|---|---|---|
| 1 (penny-jump) | **+6.86** | **+6.86** |
| 4 | +3.94 | +3.86 |
| 8 (at mid) | +0.02 | -0.01 |

Penny-jump strictly best (each deeper tick costs ~1). v3 placement is fine.

## 5. OBI-tier confidence-scaled sizing

L1-OBI buckets, per-day H=1 mid drift (replicates `multi_tick_signals.md` Sec 2):

| bucket | day0 | day1 | day2 | n/day |
|---|---|---|---|---|
| OBI<-0.3 | -3.92 | -3.68 | -3.99 | 67 |
| (-0.3,-0.05) | -3.85 | -4.08 | -3.82 | 81 |
| \|OBI\|<=0.05 | -0.02 | +0.00 | -0.02 | 9,686 |
| (0.05,0.3) | +4.05 | +4.55 | +4.28 | 85 |
| OBI>0.3 | +3.87 | +3.92 | +4.32 | 79 |

Confidence-scaled passive-skew PnL (size=ceil(LIMIT*|OBI|), capped):

| size_max | total 3d (mid-tick-points) |
|---|---|
| 50 | 57,663 |
| 100 | 113,774 |
| 200 | ~227,000 |

Upper bound. 10-30% capture -> +5-20K XIRECs/day on HYDROGEL alone vs current MC -1,099. **OBI signal is plenty large; we aren't sizing or skewing on it.**

## 6. v3 rev_z loses on historical CSV too

Replay v3 (w=50, |z|>2.4, take 140 crossing spread, hold 359):

| day | n | mean/unit | win | total @ 140 |
|---|---|---|---|---|
| 0 | 25 | +0.88 | 52% | +3,080 |
| 1 | 25 | -15.42 | 28% | **-53,970** |
| 2 | 24 | +6.71 | 54% | +22,540 |
| **3d** | **74** | **-2.6** | 45% | **-28,350** |

Day 1 alone bleeds. mid_std=37.6 -- when asset trends, `rev_z50` enters wrong-way ~70%. **Not an MC artifact**; loses on real data because 16-tick spread cost exceeds per-sig drift unless w>=500 AND OBI confirms.

Alternatives: (200,2.0,200,140) = -33K; (50,1.5,200,140) = -9K. Aggressive `rev_z` taking does not work.

## 7. Recommended HYDROGEL strategy

**Drop v3 rev_z take entirely.** Replace with:

**A) OBI passive skew** (workhorse). When `|L1_OBI|>0.05`: skew `best+1` MM 1-2 ticks in OBI direction. Confidence-size `min(LIMIT, ceil(LIMIT*|OBI|*k_conf))`. Hold via natural MM cycling (<=5 ticks).

**B) rev_z + OBI gate.** w=**500** (not 50), `|z|>1.5 & |OBI|>0.05 & sign(-z)==sign(OBI)`. Take 50-100 lots (not 140). Hold 200-500. Edge +5-7 ticks/fill, 30-50 fills/day, all 3 days.

**C) MM core stays penny-jump** -- already correct.

---

## Concrete HYDROGEL-only param search

| param | range | rationale |
|---|---|---|
| `OBI_THRESH` | 0.05 - 0.15 (log) | q3/q4 boundary at 0.05 captures full edge |
| `OBI_SKEW_TICKS` | 1 - 4 | shift quote in OBI direction |
| `OBI_SIZE_K_CONF` | 0.5 - 2.0 | size=ceil(LIMIT*\|OBI\|*k) |
| `OBI_HOLD_TICKS` | 1 - 10 | half-life ~1-25 ticks |
| `REVZ_WINDOW` | **200 - 1000** | NOT 50 (Sec 1) |
| `REVZ_THRESH` | 1.0 - 2.5 | 1.5 with gate is best (Sec 2) |
| `REVZ_OBI_GATE` | 0.03 - 0.10 | OBI agreement required |
| `REVZ_TAKE_SIZE` | 30 - 100 | NOT 140; we hold longer |
| `REVZ_HOLD_TICKS` | 200 - 800 | aligned with w=500 |
| `MM_SPREAD_MIN` | 2 - 6 | min spread to penny-jump |
| `MM_SOFT_POS_FRAC` | 0.4 - 0.8 | inventory bleed threshold |

**Hard removals:** `HYDROGEL_REVZ_50_*` (Sec 1), BUY-cluster fade (Sec 3), aggressive microprice take (`multi_tick_signals.md` Sec 3).

**Est MC uplift:** OBI skew at 10% of the 200K upper bound = +20K mid-tick-points = ~+2K XIRECs/eval. Shifts HYDROGEL from -1,099 to net positive without touching other assets.

## Caveats

- "Implied PnL" assumes our quote captures the full drift; real fill rate <100%. Upper bounds.
- Day 1 (mid_std 37) is harder; HYDROGEL strategy must survive it -- why `rev_z50` blows up.
- Cluster signal n too small to be reliable; refutes the specific `trades_signals.md` finding, not the idea.
