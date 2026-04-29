# R5 Factor Model — Findings

PCA on tick-tick mid diffs, all 50 assets, days 2/3/4 (~30k joint ticks).

## Method

Two complementary decompositions:
- **CORR-PCA** — z-score each asset's diffs (unit variance), then eigendecompose
  the correlation matrix. Reveals **co-movement structure** independent of vol scale.
- **COV-PCA** — eigendecompose the raw diffs covariance. Each PC weights assets by
  the dollar variance they contribute. Useful for **dollar-neutral hedging**, but
  numerically dominated by the highest-variance assets.

For each PC, we measure: (a) variance explained, (b) per-day stability via cosine
similarity of the day-only PCA's eigenvector vs the full-3-day PCA's, (c) loading
concentration by category.

## Stability of components

A component is "real" if its loading vector is **stable across days**. Cutoff: cosine
similarity >0.85 with the all-3-day reference.

```
PC#  | day2  day3  day4  | verdict
PC 1 | 0.997 0.998 0.997 | OK     (snackpack triplet)
PC 2 | 0.992 0.998 0.997 | OK     (pebble basket)
PC 3 | 0.992 0.997 0.995 | OK     (snackpack CHOC/VAN pair)
PC 4 | 0.893 0.944 0.936 | OK     (weak broad factor)
PC 5 | 0.222 0.375 0.686 | UNSTABLE
PC 6 | 0.690 0.341 0.062 | UNSTABLE
PC 7+ | mostly <0.5      | NOISE
```

**Only 4 stable factors exist in R5 mid-diffs.** They're entirely concentrated in
the two categories that we already know carry baked-in constraints (snackpacks,
pebbles) plus a small mixed factor.

## The 4 stable factors

### CORR-PC1 (5.6% variance) — Snackpack triplet
```
SNACKPACK_STRAWBERRY  -0.589
SNACKPACK_RASPBERRY   +0.570
SNACKPACK_PISTACHIO   -0.570
(rest of universe)    ≈ 0
```
This is exactly the triplet 1-factor model already fit by
`analysis/round5/snackpack_triplet_factor.py`. PCA recovered it from scratch.

### CORR-PC2 (4.0%) — Pebble basket
```
PEBBLES_XL  +0.701
PEBBLES_M   -0.366
PEBBLES_L   -0.354
PEBBLES_XS  -0.351
PEBBLES_S   -0.347
(rest)      ≈ 0
```
The basket constraint `XS+S+M+L+XL = 50000` forces the sum to be flat → variance
must move along the orthogonal complement. The first principal direction within
that complement is XL vs the other-4-equal-weighted, mirrored. (Sign of XL is
arbitrary; what matters is the direction.)

### CORR-PC3 (3.8%) — Snackpack CHOC/VAN pair
```
SNACKPACK_CHOCOLATE  +0.705
SNACKPACK_VANILLA    -0.704
(rest)               ≈ 0
```
Equal-magnitude opposite-sign on the K_day pair. This is the dispersion factor
**around** the slow OU pair sum. CHOC + VAN ≈ K_day but CHOC − VAN can move
freely; PC3 captures that free direction.

### CORR-PC4 (2.4%) — Weak broad mixed factor
```
PANEL_2X4              -0.225
UV_VISOR_YELLOW        -0.224
OXYGEN_SHAKE_EVENING_BREATH  -0.220
OXYGEN_SHAKE_MORNING_BREATH  -0.220
UV_VISOR_MAGENTA       -0.218
GALAXY_SOUNDS_DARK_MATTER -0.216
OXYGEN_SHAKE_MINT      -0.203
... (10 assets at ~0.2, rest ~0)
```
A broad common move across some galaxy_sounds + uv_visors + oxygen_shakes +
panels. Stability is borderline (0.89/0.94/0.94 across days). Treat with caution.
The variance contribution is small (1.17 in z-units, ~2.4% of total), and the
loadings are not category-pure, so this is more "common noise across ~10 assets"
than a clean tradeable factor.

## What does this mean for trading?

### The model in dollar terms (COV-PCA)

```
PC1  16.0%  PEBBLES_XL  -0.89  vs PEBBLES_{M,L,XS,S} +0.22 each   (pebble basket)
PC2   6.0%  MICROCHIP_SQUARE -1.00 (single-asset, dominated by σ)
PC3   4.4%  ROBOT_DISHES     -1.00 (single-asset, dominated by σ)
PC4   3.2%  PEBBLES_XS -0.72, PEBBLES_S +0.65                     (pebble pair)
```

COV-PC2 and PC3 are **artefacts of high single-asset variance**, not real factor
structure. We should hedge them away by **per-asset position-limit caps** (which
we already have at ±10), not by treating them as portfolio factors.

The two real dollar-factors that need explicit neutralization:
- **Pebble basket factor** (COV-PC1 / CORR-PC2)
- **Snackpack CHOC/VAN pair** (CORR-PC3, equivalent to K_day pair)

The snackpack triplet (CORR-PC1) is also explicit, but the existing
`snackpack_triplet` block in `calibration/r5/scenario_params.json` already models
it — we can reuse those loadings directly.

### Per-asset idio share under K=5 factor model (CORR-PCA)

```
worst-fit (most idiosyncratic) — factor model captures essentially nothing:
  PANEL_2X2                 0.992
  MICROCHIP_RECTANGLE       0.986
  ROBOT_IRONING             0.986
  UV_VISOR_ORANGE           0.981
  SLEEP_POD_COTTON          0.976  (etc.)

best-fit (well-explained by factors):
  PEBBLES_XL                0.005
  SNACKPACK_STRAWBERRY      0.033
  SNACKPACK_CHOCOLATE       0.038
  SNACKPACK_VANILLA         0.039
  SNACKPACK_RASPBERRY       0.082
  SNACKPACK_PISTACHIO       0.094
  PEBBLES_M / L             ≈0.72   (still mostly idio inside the basket)
```

40 of the 50 assets have idio_share > 0.90 — they're **independent random
processes** for our purposes. Factor neutralization is a no-op for them; the
right strategy on those is per-asset OU mean-reversion or vanilla MM.

## Strategy framework

For the user's "factor-neutral residual-alpha" trader, the right design is:

**1. Identify factor portfolios with explicit loadings.**

```
F_pebble   = +0.701 PEB_XL  -0.366 PEB_M  -0.354 PEB_L  -0.351 PEB_XS  -0.347 PEB_S
F_choc_van = +0.705 SP_CHOC -0.704 SP_VAN
F_triplet  = -0.589 SP_STRAW +0.570 SP_RASP -0.570 SP_PIS  (use existing fit)
```

**2. For each asset, define an alpha signal.** Per-asset OU-mean-reversion to
daily_mu (estimated as EMA of mid):

```
alpha_i = (fair_value_i - mid_i) / sigma_i        (in units of "z-stds long")
```

where `fair_value_i = EMA(mid_i, half_life = 1000 ticks)` and `sigma_i` is the
per-asset diff std from calibration.

**3. Construct desired raw position.** Scale alpha by an aggression knob, clip
to ±10:

```
raw_pos_i = clip(alpha_i × KAPPA, -10, +10)
```

**4. Project onto null space of factor loadings (factor-neutral).**

Solve for adjustment vector `a` such that, for each factor `k`:
    Σ_i  L[k, i] × (raw_pos_i + a_i) = 0      ← exposure neutralized
subject to the adjustment minimising ‖a‖² (smallest perturbation).

Closed form: `a = -L⁺ (L raw_pos)`, where `L⁺` is the Moore–Penrose pseudo-
inverse of the K×N loading matrix. After clipping to ±10 we re-project; convergence
in 3–5 passes.

**5. Dollar-neutral?** The user also asks for **dollar-neutral**. Add the
"market" row `(1, 1, ..., 1)` to L so the projection also forces Σ pos_i × price_i
to be zero. Use the dollar-weighted version: row = (price_1, price_2, ..., price_N).

**6. Execute via penny-jump quotes** sized to (target_pos − current_pos), capped
by remaining position-limit budget.

## What gets rejected

- **Trading PC2/PC3 of cov-PCA** — they're single-asset artefacts (MICROCHIP_SQUARE,
  ROBOT_DISHES). Already hedged by ±10 per-asset limits.
- **Trading PC5+** — unstable across days. Adding them as constraints would just add
  noise to the projection.
- **Trying to fit a 10-factor "industry" model** (one per category) — the
  per-day stability check kills it. PC4 is the only mixed factor and it explains
  only 2.4% of variance with borderline stability. The categories (other than
  pebbles & snackpacks) don't co-move tightly.

## Theoretical pointer

This is closer to **Stock & Watson's principal-components** approach (latent
factor extraction from data, no characteristic sorts) than to Fama–French's
sorted-portfolio approach. We don't have observable characteristics (size, B/M)
to sort on; with only 50 assets and no fundamentals, statistical PCA + the known
constraint structure is the right tool. The neutralization step (project onto
null space of L) is the standard portfolio-construction operation in BARRA-style
risk models — it makes the trader's PnL path independent of the factor returns
modulo trading frictions.
