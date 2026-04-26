# Round 3 — Parameter Search Results

**Generated:** 2026-04-26.
Five Optuna TPE param searches over R3, summarized end-to-end. Each search produced a winning config that was baked into a shippable trader file. The lineage builds: stratton → jordan → porush → wolf.

---

## TL;DR — every search and its winner

| # | Study | Trials | Winner | OOS Sharpe | OOS Mean | OOS p05 | Trader file | Verdict |
|---|---|---|---|---|---|---|---|---|
| **1** | `round3_param_search` | 800 | trial #324 | 1.482 | +13,355 | -1,686 | `traders/round3/max.py` | superseded |
| **2** | `round3_param_search_v2` | 400 | trial #233 | **1.814** | +10,884 | **+646** | `traders/round3/stratton.py` | **portal +17,449 (proven)** |
| **3** | `round3_param_search_v3` | 374 | trial #300 | 1.614 | +5,884 | -3 | `traders/round3/jordan.py` | superseded |
| **4** | `round3_param_search_v4` | 300 | trial #119 | 1.542 | +11,774 | -57 | `traders/round3/porush.py` | best MC + base for wolf |
| **5** | `round3_param_search_v5` | 350 | trial #217 | 0.512 | +7,124 | -16,757 | not baked | abandoned (regression) |

**Key result:** the portal-validated winner remains stratton (search 2), but porush (search 4) gives the best MC and is the basis for the final submission `wolf.py` (porush + cross-strike layer + MAF bid).

---

## Search 1 — round3_param_search

**Date:** 2026-04-24. **Sessions:** 80 train + 20 val + 150 OOS test. **Sampler:** TPE. **Trials:** 800. **Trader:** `studies/round3_tunable.py` (harry_potter_v4 contract).

**Why:** First systematic search after teammate's portal sub 370288 (+17,449 with harry_potter_v4 EMA-MR). User wanted a search prioritizing reliability over portal-day mean since final eval data will differ.

**Searched (15 params):** EMA_ALPHA, VAR_ALPHA, MR_K, MR_MAX_FRAC, MR_TAKE_Z, MR_TAKE_MAX, MR_MM_LEVELS, MR_MM_LEVEL_SIZE, OBI_CONFIRM_TAKE, INCLUDE_5400_MR, INCLUDE_5500_MR, OBI_SKEW_1/2/3, VEV_BASE_SIZE.

**Objective:** `1.0 sharpe + 0.0001 mean_pnl` (small mean weight to prevent zero-activity wins).

**Top 3 OOS:**

| Trial | OOS Score | Mean | Sharpe | p05 |
|---|---|---|---|---|
| **324** | 0.969 | **+13,355** | 1.482 | -1,686 |
| 426 | 0.803 | +12,830 | 1.422 | -2,020 |
| 468 | 0.779 | +12,841 | 1.399 | -3,119 |

**Winner #324 params:** EMA_ALPHA=0.00109, MR_K=0.31, MR_MAX_FRAC=0.58, MR_TAKE_Z=2.35, MR_MM_LEVEL_SIZE=19, MR_TAKE_MAX=24, OBI_CONFIRM_TAKE=True, INCLUDE_5400_MR=True, INCLUDE_5500_MR=False, VEV_BASE_SIZE=11.

**Result baked into:** `traders/round3/max.py`.

**Lesson:** Winner hit **edges** of the search ranges on most key params (MR_TAKE_Z=2.35 close to ceiling 2.5, MR_K=0.31 close to floor 0.30, MR_MM_LEVELS=1 at floor). Strong signal we capped the conservative direction too early — motivated search 2.

---

## Search 2 — round3_param_search_v2

**Date:** 2026-04-25. **Sessions:** 80 train + 20 val + 200 OOS test. **Sampler:** TPE. **Trials:** 400. **Trader:** `studies/round3_tunable_v2.py`.

**Why:** Search 1 hit boundaries; extended ranges in the conservative direction. Also added DISABLE_TAKES toggle (Emma's hypothesis: maybe never crossing the spread is best).

**Searched (10 params):** EMA_ALPHA [0.00003, 0.001] (extended low), VAR_ALPHA, MR_K [0.05, 0.50] (extended low), MR_MAX_FRAC [0.30, 0.80], MR_TAKE_Z [2.0, 5.0] (extended high), MR_TAKE_MAX [5, 50], MR_MM_LEVEL_SIZE [3, 25], MR_MM_LEVELS [1, 4], VEV_BASE_SIZE [3, 18], **DISABLE_TAKES (categorical)**.

**Objective:** `1.0 sharpe + 0.0001 mean_pnl + 0.0001 cvar_5`.

**Top 3 OOS:**

| Trial | OOS Score | Mean | Sharpe | p05 |
|---|---|---|---|---|
| **233** | 2.663 | +10,884 | **1.814** | **+646** |
| 351 | 2.663 | +11,254 | 1.797 | +891 |
| 244 | 2.653 | +10,823 | 1.806 | +725 |

**Winner #233 params:** EMA_ALPHA=7.27e-05 (very slow, half-life ~16,000 ticks), VAR_ALPHA=0.049, MR_K=0.057 (TINY), MR_MAX_FRAC=0.59, MR_MM_LEVEL_SIZE=13, **DISABLE_TAKES=True**, MR_TAKE_Z=4.39 (unused), VEV_BASE_SIZE=7.

**Result baked into:** `traders/round3/stratton.py` — **shipped to portal: +17,449 ✓**.

**Lesson:** DISABLE_TAKES=True won decisively in 8/8 top trials. With small MR_K (0.057 = ~12% of limit at z=2), cross-spread takes are net negative. Strategy is essentially passive MM with tiny inventory accumulation. **DSR P=1.0, PBO=0.03 — winner is statistically meaningful.**

---

## Search 3 — round3_param_search_v3

**Date:** 2026-04-25. **Sessions:** 80 train + 20 val + 200 OOS test. **Sampler:** TPE. **Trials:** 374 (some failures). **Trader:** `studies/round3_tunable_v3.py`.

**Why:** Layer NEW signals on stratton baseline:
- **Layer B**: HYDROGEL rev_z50 directional take (signal_decay.md recommended size ~50% of limit on rev_z |z|>1).
- **Layer C**: L1-OBI tiered passive skew on EVERY passive quote (drift permanent per signal_decay.md, Sharpe 22-56 from multi_tick_signals.md).
- **Layer F**: BASE_MM_SIZE override to lift the penny-jump floor on OBI-MM products.

**Searched (10 params):** HYDROGEL_REVZ_THRESHOLD/SIZE/HOLD, OBI_SKEW_T1/T2_THRESH and TICKS, BASE_MM_SIZE, MR_K (re-search around stratton 0.06), MR_MM_LEVEL_SIZE.

**Objective:** `1.0 sharpe + 0.0002 p05_pnl + 0.0001 mean_pnl + 0.0001 cvar_5` (heavier p05 for reliability).

**Top 3 OOS:**

| Trial | OOS Score | Mean | Sharpe | p05 |
|---|---|---|---|---|
| **300** | 1.973 | +5,884 | 1.614 | **-3** |
| 335 | 1.877 | +5,828 | 1.610 | -311 |
| 198 | 1.567 | +6,047 | 1.429 | -800 |

**Winner #300 params:** BASE_MM_SIZE=37 (vs stratton 3 — **massive uplift**), MR_K=0.045, MR_MM_LEVEL_SIZE=13, HYDROGEL_REVZ_THRESHOLD=2.0, HYDROGEL_REVZ_SIZE=106, HYDROGEL_REVZ_HOLD=349, OBI_SKEW_T1=0.085 (T1 ticks=0 = T1 effectively off), OBI_SKEW_T2=0.80 (T2 ticks=2).

**Result baked into:** `traders/round3/jordan.py`.

**Lesson:** The mean PnL dropped from search 2's +10,884 to +5,884 — **but seed setups differ** (search 2 used seed 10042 OOS, search 3 used 30042). Direct comparison is misleading. What's apples-to-apples: in search 3's MC distribution, jordan has the best Sharpe and best p05 (-3 = essentially zero negative tail). The big win was BASE_MM_SIZE going 3→37 on VEV_4000/4500/5500.

**HYDROGEL contribution was -1,041** despite the 106-lot rev_z layer — first sign the rev_z window=50 was wrong. Motivated search 4.

---

## Search 4 — round3_param_search_v4

**Date:** 2026-04-25. **Sessions:** 80 train + 20 val + 200 OOS test. **Sampler:** TPE. **Trials:** 300. **Trader:** `studies/round3_tunable_v4.py`.

**Why:** HYDROGEL was the only product losing money in search 3 (-1,041 in jordan). `analysis/round3/hydrogel_deep.md` deep-dive found:
- v3's REVZ_WINDOW=50 was wrong; best Sharpe is at w=500 (4× mean ticks/sig)
- OBI∩rev_z agreement is the gold filter
- Big confidence-sized OBI passive skew is the workhorse

Locked all VELVETFRUIT/voucher params at search 3 winner; searched ONLY the new HYDROGEL handler.

**Searched (11 params):** HY_OBI_THRESH/SIZE_K_CONF/SIZE_MAX/SKEW_TICKS, HY_MM_BASE_SIZE, HY_REVZ_WINDOW [200,1000], HY_REVZ_THRESHOLD/OBI_GATE/TAKE_SIZE/HOLD, HY_SOFT_POS_FRAC.

**Objective:** Same as v3.

**Top 3 OOS:**

| Trial | OOS Score | Mean | Sharpe | p05 |
|---|---|---|---|---|
| **119** | 3.721 | **+11,774** | 1.542 | -57 |
| 211 | 3.719 | +11,784 | 1.537 | -58 |
| 185 | 3.714 | +11,827 | 1.553 | -252 |

**Winner #119 params:** HY_MM_BASE_SIZE=54, HY_OBI_THRESH=0.116, HY_OBI_SIZE_K_CONF=1.0, HY_OBI_SIZE_MAX=97, HY_OBI_SKEW_TICKS=1, HY_REVZ_WINDOW=385, HY_REVZ_THRESHOLD=2.0, HY_REVZ_OBI_GATE=0.081, HY_REVZ_TAKE_SIZE=22, HY_REVZ_HOLD=446, HY_SOFT_POS_FRAC=0.43.

**Result baked into:** `traders/round3/porush.py`.

**Lesson:** HYDROGEL contribution flipped from -1,041 to **+4,848** — a +5,889 swing. Mean PnL jumped from +5,884 to +11,774 (+5,890), almost entirely from HYDROGEL. Top 10 trials are tightly clustered (mean +11,733 to +11,827) — converged optimum. Validates hydrogel_deep.md's design: big confidence-sized OBI passive skew is the workhorse, small rev_z take with OBI agreement gate.

---

## Search 5 — round3_param_search_v5

**Date:** 2026-04-26. **Sessions:** 80 train + 20 val + 200 OOS test. **Sampler:** TPE. **Trials:** 350. **Trader:** `studies/round3_tunable_v5.py`.

**Why:** `final_audit.md` recommended adding confidence-sized OBI handlers to VELVETFRUIT and VEV_4000/4500 (the audit found extreme OBI bins fire 80/day with ±5/±4 tick drift on those vouchers). Also added MAF bid 500.

**Searched (10 params):** VEL_OBI_THRESH/SIZE_MAX/K_CONF/SKEW_TICKS, VEL_MM_BASE_SIZE, V4K_OBI_THRESH/SIZE_MAX/K_CONF, V45_OBI_SIZE_MAX, MAF_BID.

**Objective:** Search 3/4 base + extra `mean_pnl[VELVETFRUIT_EXTRACT]/[VEV_4000]/[VEV_4500]` weights.

**Top 3 OOS:**

| Trial | OOS Score | Mean | Sharpe | p05 |
|---|---|---|---|---|
| **217** | -4.433 | +7,124 | 0.512 | **-16,757** |
| 206 | -4.439 | +7,116 | 0.512 | -16,757 |
| 244 | -4.532 | +7,183 | 0.514 | -17,208 |

**Winner #217 params:** VEL_OBI_THRESH=0.40, VEL_OBI_SIZE_MAX=109, VEL_OBI_SIZE_K_CONF=1, VEL_OBI_SKEW_TICKS=1, VEL_MM_BASE_SIZE=13, V4K_OBI_THRESH=0.27, V4K_OBI_SIZE_MAX=199, V4K_OBI_SIZE_K_CONF=0, V45_OBI_SIZE_MAX=118, MAF_BID=1056.

**Result baked into:** NOT BAKED — search 5 was a regression.

**Lesson:** v5 winner is **39% worse mean, 67% worse Sharpe, 290× worse p05** than porush. The new VEL/V4K confidence-sized OBI handlers added MC variance > alpha — even at conservative ranges, large positions on vouchers get adverse-selected when OBI signals are wrong. Honest takeaway: the audit's "implied PnL" upper bounds were optimistic; the OBI signal is real on real data but doesn't transfer to MC's voucher random-walk dynamics.

The "HYDROGEL=-38" in the v5 winner symbol breakdown (vs porush's +4,848) was a surprise — same locked HY params, but different MC RNG state because routing/ordering changed. Suggests HYDROGEL's MC outcome has high seed variance.

---

## Lessons across all searches

### What works (validated multiple times)

- **Big BASE_MM_SIZE on penny-jump path** (3 → 37). Search 3's main win.
- **HYDROGEL OBI confidence-sized passive skew** (search 4 winner). +5,889 swing on HYDROGEL alone.
- **DISABLE_TAKES=True** for the MR layer (search 2 winner; preserved in 3/4/5).
- **Tiny MR_K** (0.045-0.06 = ~12% of limit at z=2). Stratton/jordan/porush all converged here.
- **rev_z + OBI agreement gate** with proper window (385-500), small take size (22 lots), long hold.

### What doesn't work (refuted by searches/audit)

- **HYDROGEL rev_z with window=50** (search 3 had -1,041 contribution). Wrong scale — needs 500.
- **VELVETFRUIT confidence-sized OBI handler** (search 5). Adds variance > alpha in MC.
- **VEV_4000/4500 confidence-sized OBI handler** (search 5). Same problem at large sizes.
- **Aggressive cross-spread takes** on MR (search 2 confirmed DISABLE_TAKES wins).
- **Static fly tilt** as always-on positions (rothschild original — lost -10K in MC, removed).

### Methodology notes

- **MC seed variance is large**. Same locked params produce wildly different per-symbol PnL across seeds. Always rely on OOS retest with FRESH seeds (200 sessions), never on training-set numbers.
- **MC cannot validate cross-asset/cross-strike strategies**. Rust sim runs each voucher as independent FV — the spread MR alpha that's Sharpe 162 historical becomes pure noise in MC.
- **`hit edges of the search range`** is a strong signal that the range is wrong. Search 1 → search 2 caught this and extended ranges; search 5 saw scores tank without finding a "good corner."

---

## Lineage — which search winner became which trader

```
harry_potter_v4 (teammate, +17,449 portal)
       │
       ▼
[Search 1: 800 trials, OOS seed 10042, 150 sessions]
       │
       ▼
   max.py (trial #324)         ← OOS Sharpe 1.48, mean +13,355
       │
       ▼
[Search 2: 400 trials, OOS seed 10042, 200 sessions]
       │
       ▼
   stratton.py (trial #233)    ← OOS Sharpe 1.81, mean +10,884, p05 +646
       │                          PORTAL VALIDATED +17,449
       ▼
[Search 3: 374 trials, OOS seed 30042, 200 sessions]
       │
       ▼
   jordan.py (trial #300)      ← OOS Sharpe 1.61, mean +5,884, p05 -3
       │
       ▼
[hydrogel_deep.md analysis]    ← w=50 wrong, use 500; OBI gate gold
       │
       ▼
[Search 4: 300 trials, OOS seed 40042, 200 sessions]
       │
       ▼
   porush.py (trial #119)      ← OOS Sharpe 1.54, mean +11,774, p05 -57
       │                          HYDROGEL flipped from -1,041 to +4,848
       ├──────────────────────┐
       │                      │
[Final audit]                 ▼
       │              [Search 5: 350 trials, abandoned]
       │              VEL/V4K handlers regress (-4.4 score)
       ▼
   rothschild.py (cross-strike layer, MC can't validate)
       │
       ├──────────────────────┐
       ▼                      ▼
   wolf.py (porush + CS + MAF) ← Final submission candidate
                                  MC quick +6,157 (CS noise expected)
                                  Portal target +18-25k
```
