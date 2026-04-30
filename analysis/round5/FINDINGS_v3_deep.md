# Round 5 — Deep-dive on the 8 "no-structure" categories

The original `FINDINGS.md` and `FINDINGS_v2.md` declared 8 of 10 categories
"no hidden structure" based on (a) per-category 5-asset PCA (eigvals flat) and
(b) a global Pearson correlation screen at |r| ≥ 0.7. That test surface misses
several classes of exploitable signal. This pass widens the net to:

1. Sub-basket pair / triplet constant-sums and constant-ratios
2. Optimal-weight (regression) pair shrinkage
3. Lagged cross-correlations within categories at lag ±{1, 5, 10, 50}
4. Engle–Granger cointegration on within-category pairs (ADF on OLS residuals)
5. Order-book imbalance (OBI) → future-return correlation at +1/+5/+50 ticks
6. Cross-category PCA stability for PC4–PC12 at cosine-0.7 threshold
7. Pulse-conditional drift (volume → next-100-tick mean return)
8. Distributional anomalies (kurtosis, bimodality, mid quantum, intraday)
9. Pair-residual distribution + AR(1) half-life

Script: `analysis/round5/deeper_dive.py`. Below: what's actually exploitable.

## TL;DR

| Finding | Status | Action |
| --- | --- | --- |
| **OBI → next-tick return, universal** | **NEW** | Build an OBI quote-skew layer (15+ products with r > 0.05) |
| **Heavy-tail jumpy products** (ROBOT_DISHES kurt=25, others kurt 17-19) | **NEW** | Per-asset MR with tight quotes captures snap-backs |
| **10 cointegrated within-category pairs** | NEW but slow | Real, but half-lives 800-2700 → too slow for limit=10 standalone |
| **4 candidate bimodal mids** | Tentative | Regime-switch test on day-by-day basis |
| Sub-basket constant-sums | Confirmed absent | Pebbles is unique |
| Cross-category PC4-PC10 | Confirmed unstable | FACTOR_MODEL.md was right |
| Intraday seasonality | Confirmed absent | No tick-of-day drift |
| Pulse-volume drift | Confirmed absent | Pulses are direction-balanced |

## 1. Order-book imbalance signal (BIG, missed)

`OBI = (bid_volume_1 - ask_volume_1) / (bid_volume_1 + ask_volume_1)` predicts
**next-tick** mid return universally. Top 15 products by `|corr(OBI, ret_+1)|`:

```
product                       r_+1     r_+5     r_+50
OXYGEN_SHAKE_GARLIC          +0.0652  +0.0269  +0.0085
GALAXY_SOUNDS_SOLAR_WINDS    +0.0636  +0.0286  +0.0072
UV_VISOR_YELLOW              +0.0611  +0.0287  +0.0102
UV_VISOR_AMBER               +0.0598  +0.0294  +0.0151
UV_VISOR_RED                 +0.0593  +0.0294  +0.0012
UV_VISOR_MAGENTA             +0.0592  +0.0312  +0.0154
GALAXY_SOUNDS_BLACK_HOLES    +0.0591  +0.0169  +0.0107
GALAXY_SOUNDS_PLANETARY_RINGS +0.0589  +0.0274  +0.0187
OXYGEN_SHAKE_CHOCOLATE       +0.0581  +0.0326  +0.0096
UV_VISOR_ORANGE              +0.0581  +0.0267  +0.0067
PANEL_1X2                    +0.0571  +0.0332  +0.0154
OXYGEN_SHAKE_EVENING_BREATH  +0.0551  +0.0253  +0.0091
OXYGEN_SHAKE_MINT            +0.0547  +0.0316  +0.0213
GALAXY_SOUNDS_DARK_MATTER    +0.0522  +0.0303  -0.0016
GALAXY_SOUNDS_SOLAR_FLAMES   +0.0522  +0.0220  +0.0000
```

All-positive correlations: *more bid volume than ask volume → mid moves up next
tick*. Decay from 0.06 → 0.03 → 0.01 over 1/5/50 ticks → it's a 1-2 tick effect.

Why this matters: at limit=10 we cannot run a take-strategy on this directly
(0.06 corr × σ_tick ~10 → ~0.6 ticks of expected edge per signal, less than
the 1-tick spread cost of a take). But as a **quote-skew signal** on top of
passive MM, it's free: place our_bid one tick higher when OBI is favourable,
one tick lower when adverse. Skip when |OBI| is small.

The signal applies broadly — UV_VISORS, GALAXY_SOUNDS, OXYGEN_SHAKES, PANELS
all hit |r| > 0.05. Approximately **20-30 of the 50 products** are likely
in the tradeable band; most plain-MM products in those categories qualify.

## 2. Heavy-tailed jump products

Kurtosis on tick-tick mid diffs (Gaussian = 3.0):

```
ROBOT_DISHES                  kurt = 24.9
OXYGEN_SHAKE_CHOCOLATE        kurt = 18.8
ROBOT_IRONING                 kurt = 17.8
OXYGEN_SHAKE_EVENING_BREATH   kurt = 17.2
```

These four show massive excess kurtosis vs the next-best (kurt ~3.1 across the
rest). Mechanism: rare large jumps that revert quickly. ROBOT_DISHES was
already flagged in `FINDINGS.md` as a "stationary candidate" (half-life
319 ticks). The other three are new.

Trading implication:
- **Conservative passive quotes wide of FV** (e.g. FV ± 1.5σ at MM_QTY=2)
- Wait for jump to push best-bid/ask towards us
- Capture spread + revert PnL on reversion
- Plain MR-EMA per-asset (current snackpack `KAPPA_OU` framework) should
  capture this once these 4 products are added to the trader universe.

## 3. Cointegrated pairs (real but slow)

Engle-Granger ADF on OLS residuals:

```
cat            pair                                              w    p     resid_std
microchips     MICROCHIP_SQUARE  ~ MICROCHIP_RECTANGLE         -2.15 0.007  861
microchips     MICROCHIP_OVAL    ~ MICROCHIP_TRIANGLE          +1.62 0.017  764
robots         ROBOT_VACUUMING   ~ ROBOT_LAUNDRY               +0.69 0.020  330
sleep_pods     SLEEP_POD_LAMB_WOOL ~ SLEEP_POD_NYLON           +0.40 0.022  359
uv_visors      UV_VISOR_AMBER    ~ UV_VISOR_MAGENTA            -1.41 0.023  496
robots         ROBOT_VACUUMING   ~ ROBOT_DISHES                -0.66 0.030  389
oxygen_shakes  OXYGEN_SHAKE_CHOCOLATE ~ OXYGEN_SHAKE_GARLIC    +0.38 0.030  428
sleep_pods     SLEEP_POD_POLYESTER ~ SLEEP_POD_COTTON          +0.96 0.031  473
galaxy_sounds  GALAXY_SOUNDS_DARK_MATTER ~ GALAXY_SOUNDS_PR    +0.19 0.037  298
translators    TRANSLATOR_ECLIPSE_CHARCOAL ~ T_VOID_BLUE       +0.29 0.041  314
```

Residual AR(1) phi values are 0.999+, **half-lives 800–2700 ticks**. With ±10
position limit, we'd hit the cap long before the spread reverts:

```
half_life = 800 ticks  → at signal kappa=4 contracts/σ, 1σ residual → 4 lots
                          we'd take ~200 ticks (25% of half-life) to fill
                          → average holding period during a 1σ event = 600 ticks
                          → reasonably tradeable
half_life = 2000 ticks → average holding 1500 ticks → too slow
```

Tradeable subset: top 4 (the SQUARE/RECTANGLE pair has half-life 836).

These are NOT structural constraints (unlike Pebbles). They're slow
mean-reverting price relationships. Use as a bias signal, not as a hard
constraint trade.

## 4. Bimodal candidates

Mid-level std/IQR ratio (>0.95 ≈ bimodal under standard heuristic):

```
OXYGEN_SHAKE_GARLIC           std/IQR = 1.20  range = 4510
TRANSLATOR_GRAPHITE_MIST      std/IQR = 1.16  range = 2371
MICROCHIP_CIRCLE              std/IQR = 1.07  range = 2428
OXYGEN_SHAKE_CHOCOLATE        std/IQR = 0.99  range = 2440
```

This is a screen, not a confirmation. Worth a per-day mid histogram + dip
test before committing to a regime-switching strategy.

## 5. Confirmations (FINDINGS was right)

- **No sub-basket constraints**: All within-category pairs and triplets have
  std ≥ 380. Compare to Pebbles full-basket std=2.8 — there's no second
  Pebbles hiding inside another category.
- **No cross-category factors beyond PC4**: PC5+ cosine similarities scatter
  in [0.05, 0.5] across days — pure noise.
- **No intraday seasonality**: bucket-of-day variation < 1.0 for all products.
- **No pulse-volume drift**: |corr(volume_t, ret_+100)| < 0.015 universally.
- **Half-integer mid quantum** confirmed (no off-grid mids).

## 6. What this means for snackpack.py and beyond

The snackpack trader stays the highest-edge **per-product** book in the round.
But the discoveries above suggest where the marginal next-best PnL lives:

**Path A — OBI quote-skew (lifts everything).** Add an OBI-aware quote layer
to a generic MM trader covering the ~25 products with |OBI corr| > 0.04.
Cost: minimal. Expected uplift: 0.06 × σ × n_fills per product per day.
For the 25 products at σ ≈ 10/tick and ~244 V-pulses/day, rough envelope:
0.06 × 10 × 244 / day = ~150 XIRECs / product / day from quote-skew alone =
~10-15K total over 3 days × 25 products. Unverified — needs MC backtest.

**Path B — Heavy-tail MR trader (tight 4-product book).** ROBOT_DISHES,
ROBOT_IRONING, OXYGEN_SHAKE_CHOCOLATE, OXYGEN_SHAKE_EVENING_BREATH. These 4
all have kurt > 17, which means the MR signal pays disproportionately well
on tail events. Build a `traders/round5/heavy_tail.py` with tight quotes and
position-limit-10 risk caps.

**Path C — Cointegrated pair MR (top 4 pairs by p-value).** Half-lives are
800-1300 ticks, so barely tradeable. Probably second priority after A and B.
The 4 pairs to consider:
- MICROCHIP_SQUARE / RECTANGLE  (p=0.007, half-life 836)
- MICROCHIP_OVAL / TRIANGLE     (p=0.017, half-life 1143)
- ROBOT_VACUUMING / LAUNDRY     (p=0.020, half-life 1152)
- SLEEP_POD_LAMB_WOOL / NYLON   (p=0.022, half-life ~1300)

## 7. Files

- `analysis/round5/deeper_dive.py` — full analysis script
- `/tmp/dive2.log` — raw output (last run)
