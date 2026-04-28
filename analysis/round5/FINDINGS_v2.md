# Round 5 — Deep Findings (v2)

This document captures the full structural model of R5 markets, derived from 3 days of historical data (`data/prosperity4/round5/`) and the hold-1 portal sub `545243`. It supersedes the surface-level EDA in `FINDINGS.md` and feeds directly into the MC sim Scenario design (next step).

## TL;DR

- **3 independent Poisson pulse processes** drive ALL bot taker activity. No per-asset trade processes — bots fire 5 or 40 products *together*.
- **The book is symmetric** around FV with **product-specific half-spread** `h`. L2 is 1-2 ticks beyond L1. L3 mostly empty.
- **Mids are bounded, not free random walks** (`obs_std/RW_expected ≈ 0.2–0.4` in every product, every day).
- **Two structural constraints** in the FV process: Pebbles `sum=50,000` (exact) and Snackpack `Choc+Vanilla=K_day` (drifts slowly within and between days). Plus a looser Snackpack triplet constraint.
- **No counterparty IDs** in R5. Pure microstructure again.

## 1. Bot taker model (FULLY characterized)

Three independent Poisson processes drive bot trades. Each pulse fires *all members* of one of three groups simultaneously, with shared direction and quantity.

### 1a. Pulse processes

| Pulse group | Members fired | Rate (per day) | Direction | Quantity | Cross-pulse overlap |
| --- | --- | --- | --- | --- | --- |
| **Vanilla (V)** | 40 products (everything except Pebbles + Microchips) | 244 | 50/50 BUY/SELL | uniform {1, 2, 3, 4} | ~2% with P, ~1.5% with M |
| **Pebbles (P)** | 5 PEBBLES_* | 215 | 50/50 | uniform {2, 3, 4, 5} | ~2% with V, ~2% with M |
| **Microchips (M)** | 5 MICROCHIP_* | 190 | 50/50 | uniform {1, 2, 3} | ~1.5% with V, ~2% with P |

### 1b. Within-pulse uniformity

Across 1,908 pulses spanning 3 days:
- 98.9% have direction-uniform members (the rest have minor 1-2-asset variations)
- 98.5% have quantity-uniform members
- 1,873 / 1,908 (98.2%) are *both* direction- and quantity-uniform

The 1.8% non-uniform pulses are coincident-pulse events (e.g. P fires + V fires same tick) where the two groups happen to have different qty/direction.

### 1c. Trade-price rule

**100% of SELL trades fire at exactly `bid_price_1`. 100% of BUY trades fire at exactly `ask_price_1`.** No exceptions across 35,385 trades. The bot is a pure aggressive taker with no price improvement.

### 1d. Inter-pulse arrivals

| Day | n_pulses | gap mean (ticks) | gap p50 | gap p90 | gap p99 | gap max |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 603 | 16.6 | 12 | 39 | 72 | 89 |
| 3 | 668 | 15.0 | 11 | 33 | 60 | 96 |
| 4 | 637 | 15.7 | 11 | 36 | 70 | 109 |

Gap distribution is consistent with a Poisson process at rate ~ 0.0625/tick (≈ 625/day total across all 3 pulse types).

## 2. Order book / MM model

The book is symmetric around FV every tick (modulo half-tick rounding). L1 bid = `FV − h`, L1 ask = `FV + h` where `h` is product-specific. L2 lifts by `δ ∈ {1, 2}` ticks.

### 2a. Per-category half-spread

Median half-spread (`h`) per category:

| Category | h (half-spread) | L1 spread | L2 lift | L1 depth | L2 depth |
| --- | --- | --- | --- | --- | --- |
| Robots | 3.0–4.0 | 6–8 | 1 | 6–7 | 10 |
| Microchips | 4.0–6.0 | 8–12 | 1 | 6–7 | 10 |
| Translators | 4.0–5.0 | 8–10 | 1 | 11 | 18 |
| Sleep Pods | 4.5–5.5 | 9–11 | 1 | 11 | 18 |
| Panels | 4.0–6.0 | 8–12 | 1 | 11–18 | 18–31 |
| Pebbles | 4.5–8.5 | 9–17 | 1–2 | 12–13 | 25 |
| Oxygen Shakes | 6.0–7.5 | 12–15 | 1–2 | 18 | 31 |
| Galaxy Sounds | 6.5–7.0 | 13–14 | 2 | 18 | 31 |
| UV Visors | 5.0–7.0 | 10–14 | 1–2 | 18 | 31 |
| Snackpacks | 8.0–9.0 | 16–18 | 2 | 30 | 50 |

Per-product `h` values to feed into the sim are in `analysis/round5/eda_per_product.csv` (column `spread_median`).

### 2b. L3 frequency

L3 shows up in 5–8% of ticks across products. Magnitude similar to L2 lift (1-2 ticks beyond L2). For sim purposes, **ignore L3** — it adds noise without changing first-order MM dynamics.

### 2c. Mid quantum

Every product has half-integer mids (fractions ∈ {0.0, 0.5}). Bid and ask prices are integers. Mid = (bid + ask) / 2.

## 3. FV process

### 3a. Per-asset diagnostics

For each product, on each day, computed:
- `σ_per_tick`: stdev of first differences (bid-ask bounce inflated)
- detrended AR(1) phi
- `obs_std/RW_expected`: observed mid stdev / `σ_per_tick × √N`

**Universal finding: `obs_std/RW_expected ∈ [0.10, 0.47]` for every product, every day.** A pure random walk would give a ratio of ~1.0. This means **every R5 product is mean-reverting / bounded**, not a free RW.

Two interpretations:
1. The FV is genuinely OU with a drift toward a category-specific mean (with day-to-day mean drift)
2. There's a soft barrier or external constraint keeping mids bounded

For sim purposes, treat as **OU with daily-resampled mean**: `dF = -θ(F - μ_t) dt + σ dW`, where μ_t is a slow random walk between days.

### 3b. Drift across days

Drift z-scores (drift_per_day / (σ × √N)) are all in `(-1.2, +1.3)` — *no product has statistically significant persistent drift across the 3 observed days*. The "drift products" identified in v1 EDA (MICROCHIP_OVAL, UV_VISOR_AMBER, PEBBLES_XS) had directional 3-day moves but per-day directions varied. They are likely OU processes whose daily-mean was sampled to one side of the long-run mean.

Full per-day-per-asset table: `fv_per_asset_per_day.csv`.

### 3c. ROBOT_DISHES anomaly

`ROBOT_DISHES` shows extreme cross-day σ variation: σ_per_tick = 17.78 across all 3 days but std = 10.2 between days. Looking at per-day values, one day has σ ≈ 30 and others ~10. Likely a single-day volatility event. Not a standing MR opportunity.

## 4. Cross-asset constraints

### 4a. Pebbles (exact constant-sum)

```
PEBBLES_XS + PEBBLES_S + PEBBLES_M + PEBBLES_L + PEBBLES_XL  =  50,000
```

| Day | sum mean | sum std | core-band hit-rate (`|deviation| ≤ 1.0`) |
| --- | --- | --- | --- |
| Day 2 | 49,999.91 | 2.82 | 92% |
| Day 3 | 49,999.97 | 2.76 | 92% |
| Day 4 | 49,999.94 | 2.82 | 92% |

The constraint is **exact in expectation**. Deviations of ±0.5/±1.0 are half-tick parity artifacts of mid quantum. Rare ±15-18 deviations (~2%) are transient book-imbalance events that revert within ticks.

**Innovations are uncorrelated** between the 4 free DoF (correlation ≈ 0 every day). For the sim:
- Generate 4 independent OU walks for any 4 of the 5 pebbles
- Derive the 5th deterministically: `mid_5 = round(50000 - sum(other 4), 0.5)`

### 4b. Snackpack pair: Choc + Vanilla

```
SNACKPACK_CHOCOLATE + SNACKPACK_VANILLA  ≈  K_day
```

| Day | K mean | K stdev within day | First-100-tick mean | Last-100-tick mean | Within-day drift |
| --- | --- | --- | --- | --- | --- |
| Day 2 | 20,025 | 42.5 | 20,011 | 19,973 | -38 |
| Day 3 | 19,927 | 31.6 | 19,954 | 19,870 | -84 |
| Day 4 | 19,870 | 48.2 | 19,868 | 19,991 | +123 |

K drifts both within and across days. Day-to-day Δ: -98 (d3-d2), -57 (d4-d3). For the sim:
- Model K as a slow random walk: `K_t = K_{t-1} + ε_t` with σ_K ≈ 0.4–0.6 per tick
- Generate one of (CHOC, VANILLA) as the "free" walk + derive the other from K
- The pair-trade strategy needs to track the slow K, not assume a fixed daily constant

### 4c. Snackpack triplet: PIS / STRAW / RASP

Looser constraint with day-varying eigenvector direction:
- Day 2: combo direction `[+0.49, +0.42, +0.76]`, smallest eigval 3,061
- Day 3: combo direction `[+0.40, +0.49, +0.78]`, smallest eigval 825
- Day 4: combo direction `[-0.78, -0.13, -0.62]`, smallest eigval 1,941

Sign flips on day 4 are just convention; magnitudes vary 2-4× between days. The constraint is real but the loadings rotate. For the sim:
- Two independent walks + one constrained walk, with **constraint loadings re-sampled per day**
- Or: three correlated walks with daily-recalibrated covariance

## 5. Other 8 categories — no hidden structure

PCA spectra all `≈ [1.0, 1.0, 1.0, 1.0, 1.0]` — flat eigvals confirm independence within each category. **No hidden basket alpha there**, just MM.

## 6. Implications for sim design

The sim Scenario layer must be substantially different from R3/R4:

| Feature | R3/R4 sim | R5 sim (required) |
| --- | --- | --- |
| FV generation | Per-asset, independent | **Joint** for all 50 with constraints |
| Bot taker process | Per-asset Poisson | **3 shared pulse processes** |
| FV process | RW or drift+RW | **OU per asset** (bounded) |
| Constraint enforcement | n/a | **Pebbles sum + Snackpack pair + triplet** |
| Per-asset MM | Custom per asset | **Symmetric h-spread**, parametrized by (h, depth_L1, depth_L2) |

**Architecture sketch:**

```
Scenario (one per session)
├─ tick():
│   1. advance "free factors": OU walks for the 50 - 3 = 47 effective DoF
│      (50 products − 1 Pebbles constraint − 1 Snack pair − 1 Snack triplet)
│   2. derive constrained mids from free factors (snap to half-integer)
│   3. roll 3 independent Poisson pulses (V, P, M)
│   4. for each fired pulse: pick direction, qty, fire on each member
│   5. emit per-asset book snapshots: bid_1 = FV - h, ask_1 = FV + h, plus L2
└─ owns: 50 FV state, 3 K-day-state values, RNG seed
```

The MM (us / other MMs) is layered on top: posts at FV ± h with depth, optionally penny-jumps. The current asset-by-asset Rust file structure can stay (one bot model per asset) but the FV needs to come from a shared scenario. Probably:

```
rust_simulator/
├── src/
│   ├── scenario.rs        # NEW: joint FV + pulse generation (R5)
│   ├── assets/
│   │   ├── mod.rs
│   │   ├── pebbles_xs.rs  # bot model only, FV read from scenario
│   │   ├── ...
│   │   └── snackpack_*.rs
```

## 7. Open items before sim design

- **OU vs constrained-RW choice**: which fits the per-asset data better in a backtest? Needs a short fit pass on the historical data.
- **K_day evolution model**: currently described as a slow RW. Need to estimate σ_K and decide whether it lives in the scenario state across days or resets.
- **Snackpack triplet representation**: pick 2 free + 1 derived, or model 3 correlated walks?
- **Per-asset μ in OU**: derive from observed daily means. Are these themselves slow walks across days, or stable?

## 8. Files

| File | Contents |
| --- | --- |
| `eda.py`, `eda_per_product.csv` | per-product summary stats |
| `basket_search.py`, `basket_search.json` | per-category PCA + best-pair fits |
| `snackpack_dive.py` | Choc/Vanilla pair structure + PCA |
| `pebbles_dive.py` | Pebbles sum constraint verification |
| `trade_event_structure.py` | pulse vs per-asset Poisson |
| `pulse_dive.py` | within-pulse uniformity + direction/qty distribution |
| `book_structure.py` | per-asset half-spread, depth, L2 lift |
| `fv_dynamics.py`, `fv_per_asset_per_day.csv` | FV process classification |
