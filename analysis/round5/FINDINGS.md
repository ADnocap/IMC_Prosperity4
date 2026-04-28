# Round 5 EDA — Findings

**Inputs:** 3 days of pre-round-close data (`data/prosperity4/round5/{prices,trades}_round_5_day_{2,3,4}.csv`), 30,000 ticks across 50 products, 35,385 trade rows. Position limit is 10 per product.

**Trader IDs:** Gone. Every R5 trade row has empty `buyer` and `seller` — Mark <NN> disclosure was R4-only. Pure microstructure again.

## TL;DR

Two of the ten categories embed exploitable hidden constraints. The other eight are vanilla products that need plain MM. Snackpacks have the best risk-adjusted MM Sharpe even ignoring the constraint structure.

| Category | Hidden structure? | Strategy bucket |
| --- | --- | --- |
| **Pebbles** | **YES** — sum of 5 mids ≈ 50,000.0 with std 2.8 | **5-product basket arb** |
| **Snackpacks** | **YES** — Choc+Vanilla constant per day; Pis/Straw/Rasp triplet has 3-asset constraint | **Pair / triplet trades + MM** |
| Sleep Pods | No (eigvals ≈ flat) | Plain MM |
| Galaxy Sounds | No | Plain MM |
| Microchips | No | Plain MM (one drift product, one volatile) |
| Robots | No (one stationary candidate: ROBOT_DISHES) | Plain MM |
| UV-Visors | No (one drift product) | Plain MM |
| Translators | No | Plain MM |
| Panels | No (despite size-ladder naming, sum is not constrained) | Plain MM |
| Oxygen Shakes | No | Plain MM |

## 1. Pebbles — constant-sum basket

```
PEBBLES_XS + PEBBLES_S + PEBBLES_M + PEBBLES_L + PEBBLES_XL  =  50,000  (essentially)
```

| metric | value |
| --- | --- |
| sum mean | 49,999.94 |
| sum std (over 30K ticks) | **2.80** |
| sum range | [49,981.5, 50,016.5] |
| 89% of ticks | sum ∈ {49,999.0, 49,999.5, 50,000.0, 50,000.5, 50,001.0} |
| ~2% of ticks | sum deviates by ±14 to ±18 (transient book imbalances) |
| pebble mid quantum | half-integer (fractions ∈ {0.0, 0.5}) |

**Verification:** PCA on level covariances yields a smallest eigenvalue 1.57 (vs next eigval 187,287 — a **5-order-of-magnitude gap**) with eigenvector `[+0.4472, +0.4472, +0.4472, +0.4472, +0.4472]` — the constraint is literally `1·XS + 1·S + 1·M + 1·L + 1·XL = const`. Per-day total stats are stable (std 2.76 / 2.82 / 2.82 across days 2/3/4).

**Trading implication:** Each pebble's fair value is deterministic given the other four. If `mid_XL > 50,000 − (XS_mid + S_mid + M_mid + L_mid)`, XL is overpriced and there's a basket short opportunity. With pos limit 10 per product, the maximum balanced basket trade is ±10 of any product offset against ±10 distributed across the rest.

The ~2% of ticks where sum deviates by ±14–18 are likely the most profitable taking opportunities — they revert quickly. The ±0.5 noise is the half-tick rounding floor (since each mid is a half-integer, `(a/2 + b/2) - (c+d+e)` parities can flip ±0.5).

## 2. Snackpacks — pair + triplet structure

PCA eigvals on returns: `[2.78, 1.91, 0.20, 0.08, 0.03]` — two large + three small ⇒ **two independent constraints**.

### 2a. Choc ↔ Vanilla pair

```
SNACKPACK_CHOCOLATE  +  SNACKPACK_VANILLA  ≈  K_day  (drifts day to day)
```

| day | sum mean | sum std |
| --- | --- | --- |
| Day 2 | 20,025.04 | **42.5** |
| Day 3 | 19,926.89 | **31.6** |
| Day 4 | 19,870.09 | **48.2** |

Individual mids have σ ≈ 200; the pair sum has σ ≈ 30–50 within a single day. **Pair-trade Sharpe is enormous.** Daily baseline drifts by ~75 between days but is locally stable within a day.

### 2b. Pistachio / Strawberry / Raspberry triplet

3-asset constraint is looser than the Choc/Vanilla pair but still real. Smallest eigenvector in level space: `[+0.642, +0.292, +0.709]` (PIS / STRAW / RASP) with combo std ≈ 63. Cleanest integer combo found: `STRAW + RASP - 2·PIS = -1,792.7 ± 659` (not as clean as one would hope; the optimal weighted basket should be used directly).

### 2c. Plain MM bonus

Even ignoring the constraints, snackpacks have the **best risk-adjusted MM edge** in the universe:

| product | spread_median | σ_per_tick | spread_over_sigma |
| --- | --- | --- | --- |
| SNACKPACK_PISTACHIO | 16 | 5.24 | **3.05** |
| SNACKPACK_VANILLA | 17 | 6.51 | **2.61** |
| SNACKPACK_CHOCOLATE | 17 | 6.58 | **2.59** |
| SNACKPACK_STRAWBERRY | 18 | 8.13 | **2.21** |
| SNACKPACK_RASPBERRY | 17 | 8.09 | **2.10** |

For comparison, the rest of the universe sits at spread_over_sigma ∈ [0.39, 1.33]. Snackpacks pay 2–3× as much half-spread per unit risk.

## 3. Per-product behavior summary (other 8 categories)

Per-product table is in `eda_per_product.csv`. Highlights:

- **44 of 50 products are random walks** (no drift, no mean reversion within the data window).
- **3 drift products:** `MICROCHIP_OVAL` (-1711/day), `PEBBLES_XS` (-1588/day), `UV_VISOR_AMBER` (-1099/day). All three drift *down*, all three started day 2 above their day-4 mean. Could be a competition feature (one-time supply shock) or a smoothly decaying random-walk.
- **2 volatile-RW:** `MICROCHIP_SQUARE` (σ=20.7/tick), `PEBBLES_XL` (σ=30.3/tick — twice the next-highest pebble).
- **1 stationary candidate:** `ROBOT_DISHES` (half-life 319 ticks, mid_std 557 over a mean of 10,018 — local MR rather than full constraint). Tradeable as MR if the half-life holds out-of-sample.

### Spread × σ MM ranking (best plain-MM Sharpe, top 10)

| product | spread_med | σ_per_tick | spread_over_sigma |
| --- | --- | --- | --- |
| SNACKPACK_PISTACHIO | 16 | 5.24 | 3.05 |
| SNACKPACK_VANILLA | 17 | 6.51 | 2.61 |
| SNACKPACK_CHOCOLATE | 17 | 6.58 | 2.59 |
| SNACKPACK_STRAWBERRY | 18 | 8.13 | 2.21 |
| SNACKPACK_RASPBERRY | 17 | 8.09 | 2.10 |
| GALAXY_SOUNDS_SOLAR_WINDS | 14 | 10.54 | 1.33 |
| PANEL_1X2 | 12 | 9.05 | 1.33 |
| OXYGEN_SHAKE_MINT | 13 | 9.88 | 1.32 |
| OXYGEN_SHAKE_MORNING_BREATH | 13 | 10.10 | 1.29 |
| GALAXY_SOUNDS_PLANETARY_RINGS | 14 | 10.88 | 1.29 |

### MM Sharpe bottom (be careful — narrow spread or high vol)

| product | spread_med | σ_per_tick | spread_over_sigma |
| --- | --- | --- | --- |
| ROBOT_DISHES | 7 | 17.78 | 0.39 |
| PEBBLES_XL | 17 | 30.31 | 0.56 |
| MICROCHIP_SQUARE | 12 | 20.71 | 0.58 |
| PEBBLES_XS | 9 | 15.05 | 0.60 |
| MICROCHIP_RECTANGLE | 8 | 13.13 | 0.61 |
| MICROCHIP_TRIANGLE | 9 | 14.50 | 0.62 |
| MICROCHIP_OVAL | 8 | 12.48 | 0.64 |
| ROBOT_LAUNDRY | 7 | 9.82 | 0.71 |
| ROBOT_MOPPING | 8 | 11.15 | 0.72 |
| ROBOT_VACUUMING | 7 | 9.24 | 0.76 |

Robots and Microchips have thin spreads and high vol — plain MM there is a coin flip after queue position. Pebbles XS/XL are inside the basket (the constraint dominates anyway).

## 4. Cross-category screening

Pearson return correlations |r| ≥ 0.7 across the entire 50×50 universe: **all four pairs are intra-snackpack** (CHOC↔VANILLA -0.92, STRAW↔RASP -0.92, PIS↔STRAW +0.91, PIS↔RASP -0.83). No cross-category alpha.

## 5. Recommended strategy buckets

1. **Bucket A — Pebbles basket arb (highest priority).** Treat the 5 pebbles as one position. Maintain target = "fair share" against the constant-sum constraint. Take any deviation > 0.5 (most occur), capture the rare ±15 jumps. Expected: best PnL contributor of any single category.

2. **Bucket B — Snackpacks pair + triplet + MM.** Two layers:
   - Pair MR on `CHOC + VANILLA = K_day`. Recompute K each day (or rolling EMA). At |z| ≥ some threshold, take the cross-spread.
   - Triplet basket on PIS/STRAW/RASP using the eigvec weights as the hedge ratio.
   - On top, plain passive MM at the wide snackpack spreads (16–18 ticks) for the queue rebate.

3. **Bucket C — Plain MM on the other 8 categories.** Tier by spread_over_sigma. Top: GALAXY_SOUNDS, OXYGEN_SHAKES, SLEEP_PODS, TRANSLATORS, UV_VISORS, PANELS. Avoid: ROBOTS and MICROCHIPS (or use very tight quote sizes).

4. **Bucket D — Specials.** ROBOT_DISHES has a 319-tick MR half-life — try a passive z-score MR layer on top of MM. The 3 drift products (MICROCHIP_OVAL, UV_VISOR_AMBER, PEBBLES_XS) need momentum-aware FV (EMA + drift), but PEBBLES_XS is part of bucket A so the basket handles it.

## 6. Open questions before shipping

- The 3 drift products: is the drift really linear, or a one-shot regime shift around a specific timestamp? Worth replaying `prices_round_5_day_{2,3,4}.csv` against an EMA-FV trader to see.
- ROBOT_DISHES MR half-life is 319 ticks — is that a true constraint or just slow drift? Re-check on day 2 alone vs day 4 alone.
- Snackpack pair K_day drifted -75 between days 2/3 and another -57 between days 3/4. Is this an active drift (compute once per day = stale by close) or random across-day-noise (redrawn every day)?
- The wiki said *"some categories embed strong patterns"* — we found two. Worth a final sanity sweep using non-linear PCA / cointegration on the other 8 categories to make sure we're not missing one.

## Files

- `eda.py` — main per-product + correlations pass
- `basket_search.py` — 10-category PCA + best-pair sweep
- `snackpack_dive.py` — Choc/Vanilla pair characterization, PCA factor loadings
- `pebbles_dive.py` — Pebbles constant-sum verification + snackpack triplet eigvec
- `eda_per_product.csv` — per-product stats table
- `eda_correlations.json` — full correlation matrices + ladder fits
- `basket_search.json` — per-category PCA signatures + best-pair fits
