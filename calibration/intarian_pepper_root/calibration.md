# INTARIAN_PEPPER_ROOT Calibration

Round 1/2 product. Deterministic linear drift at +0.1 per tick.

**Source data**: portal hold-1 submission 103017 (day 0, R1) + 30,000-tick CSV dataset (R1 days −2, −1, 0) + portal hold-1 submission 274082 (R2 day 1, confirming drift continues across rounds). Raw extract at `data/fv_and_book.json`. R2 server FV trace at `data/r2_day1_fv.json`.

## Fair Value process

| Property | Value |
|---|---|
| Type | Deterministic linear drift |
| Drift | +0.1 per tick (exactly; residual std = 0.0005 ≈ quantization noise) |
| Quantization | 1/1024 (~0.001) |
| Starting value | 10,000 on R1 day −2, +1000 per day, **13,000 at R2 day 1** |
| Variance | ~0 (essentially deterministic) |
| Position limit | 80 |

**R2 continuation finding**: PEPPER drift continues across round boundaries without reset. Confirmed via hold-1 submission 274082 — R2 day 1 starts at ~13,000, not 10,000. Codified as the `--ipr-start-fv 13000` flag on `prosperity4mcbt`. See `analysis/round2/check_pepper_start.py` for the validation script.

## KEY DISCOVERY — Proportional offsets

The bots do **NOT** use fixed integer offsets from FV. They use **proportional offsets that scale with FV**:

```python
bid = floor(FV * (1 - K))
ask = ceil(FV * (1 + K))
vol = randint(vol_lo, vol_hi)   # same both sides per tick
```

This is invisible in any single day of portal data (narrow FV range) but becomes clear when cross-validating against the 30,000-tick CSV spanning FV 10,000 → 13,000.

### Discovered K values (validated across 30,000 ticks)

| Bot | K | Bid formula | Ask formula | Match rate |
|---|---|---|---|---|
| Bot 1 | **3/4000 = 0.000750** | `floor(FV * 0.999250)` | `ceil(FV * 1.000750)` | **99.9%** (23,975/23,987) |
| Bot 2 | **1/2000 = 0.000500** | `floor(FV * 0.999500)` | `ceil(FV * 1.000500)` | **99.0%** (23,953/24,185) |

### Why simple integer offsets work on narrow-range portal data

At FV ≈ 12,000 the proportional formula collapses to integer offsets that match the apparent `ceil(FV) - 10` / `floor(FV) + 10` pattern. But across the full 10,000 → 13,000 CSV range, fixed offsets drop to 67% match. The proportional formula holds across the full range.

| FV level | Bot 1 effective offset | Bot 2 effective offset |
|---|---|---|
| 10,000 | 7.5 | 5.0 |
| 11,000 | 8.25 | 5.5 |
| 12,000 | 9.0 | 6.0 |
| 13,000 | 9.75 | 6.5 |

**Implication**: the Rust simulator uses proportional K values to stay correct across the full session, not just the first portal-UI-backtest ticks.

## Bot 1 — Outer Wall

| Property | Value | Confidence |
|---|---|---|
| Formula | `floor(FV * (1 − 3/4000))` / `ceil(FV * (1 + 3/4000))` | 99.9% |
| Volume | `U(15, 25)`, same both sides per tick | χ² uniform p=0.12 |
| Presence | 80% per side, iid Bernoulli | |
| Spread | 19 (non-integer FV), 20 (integer FV) | |

Single ask miss in portal data at t=1000 (FV=12001.0 exactly): ask=12010 instead of 12011. Both Bot 1 and Bot 2 asks are 1 lower at that tick — classic floating-point accumulation (`sum(0.1 for _ in range(10)) ≠ 1.0`).

## Bot 2 — Inner Wall

| Property | Value | Confidence |
|---|---|---|
| Formula | `floor(FV * (1 − 1/2000))` / `ceil(FV * (1 + 1/2000))` | 99.0% |
| Volume | `U(8, 12)`, same both sides per tick | χ² uniform p=0.15 |
| Presence | 80% per side, iid Bernoulli | |
| Spread | 13 (non-integer FV), 14 (integer FV) | |

## Bot 3 — Noise

| Property | Value |
|---|---|
| Presence | ~5% of ticks |
| Single-sided | 100% |
| Offsets | {+3, −3} (bid), {−4, +2} (ask) most common; wider range also observed (low n) |
| Crossing volume | `U(3, 8)`, mean 5.3 |
| Passive volume | `U(5, 12)`, mean 8.3 |

**Note**: PEPPER Bot 3 has REVERSED volume pattern vs OSMIUM — crossing orders are smaller, passive orders are larger.

## Trade bots

- Trades on ~3.2% of ticks
- Quantity {3–8}

## Presence model (shared with OSMIUM)

All four channels independent iid Bernoulli at 80% per tick. See `../ash_coated_osmium/calibration.md` for the full independence-test write-up.

## Scripts

- `scripts/calibrate.py` — brute-force formula search + statistical validation (template for deterministic-drift assets)
- `scripts/calibrate_per_day.py` — brute-force per-day, leveraging PEPPER's deterministic FV
- `scripts/find_fv_start.py` — optimal FV-start search per day via Bot 2 bid match rate
