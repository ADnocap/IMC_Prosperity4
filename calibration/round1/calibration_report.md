# Round 1 Calibration Report

## Data Sources

1. **Portal submission 103017**: `trader_hold1.py` (buy 1 unit, hold). 999 timestamps, day 0. FV extracted from PnL.
2. **CSV data**: 3 days × 10,000 ticks = 30,000 ticks per product (days -2, -1, 0). No PnL but PEPPER FV is deterministic.
- Products: **ASH_COATED_OSMIUM**, **INTARIAN_PEPPER_ROOT**

## Fair Value Processes

### ASH_COATED_OSMIUM
- **Type**: Pure Gaussian random walk
- **σ per step**: 0.3117
- **Drift**: 0.0 (mean step = 0.000016, not significant)
- **Starting value**: ~10002.7
- **Quantization**: 1/2048 (confirmed, max grid error = 0)
- **Normality**: skewness z=0.64, kurtosis z=-0.14 (both well within normal)
- **Autocorrelation**: None (all lags p > 0.05 after Bonferroni)
- **Comparison**: Similar to TOMATOES (σ=0.496) but lower volatility

### INTARIAN_PEPPER_ROOT
- **Type**: Deterministic linear drift
- **Drift**: +0.1 per tick (exactly, residual std = 0.0005 = quantization noise)
- **Starting value**: ~12000.0
- **FV formula**: `FV(t) = 12000 + 0.1 * (t / 100)`
- **Range**: 12000.1 → 12099.9 over 999 ticks
- **Quantization**: 1/2048 (0.1 is not on the 1/2048 grid, so drift alternates 204/2048 and 205/2048)

## Order Book Structure

Both products have identical structural architecture:
- **Bot 1** (outer wall): deepest level, large volume
- **Bot 2** (inner wall): defines the BBO, smaller volume
- **Bot 3** (noise): rare, single-sided, near FV

## ASH_COATED_OSMIUM Calibration

### Bot 1 (Outer Wall)

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `floor(FV) - 10` | 99.7% (791/793), 2 misses at frac≈1.0 boundary |
| Ask formula | `ceil(FV) + 10` | 100.0% (778/778) |
| Volume | `U(20, 30)`, same both sides | χ²=13.02, p=0.22 (uniform ✓) |
| Bid/ask vol match | 100.0% (628/628) | Identical RNG seed per tick |
| Spread | 21 (non-integer FV), 20 (integer FV) | |

**Miss analysis**: 2 bid misses at FV=9996.999023 (frac=0.999). The server likely rounds this to 9997 internally — floating-point boundary artifact, not a modeling error.

### Bot 2 (Inner Wall)

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `round(FV) - 8` | 100.0% (758/758) |
| Ask formula | `round(FV) + 8` | 100.0% (806/806) |
| Volume | `U(10, 15)`, same both sides | χ²=1.67, p=0.89 (uniform ✓) |
| Bid/ask vol match | 100.0% (618/618) | |
| Spread | 16 (normal), 15 or 17 at 0.5 boundaries | |

**FV fraction confirmation**: bid - floor(FV) transitions from -8 to -7 at frac=0.5, exactly matching `round()`.

### Bot 3 (Noise)

| Property | Value | Test |
|---|---|---|
| Presence | 7.6% of ticks | |
| Single-sided | 100% (0 both-sided events) | |
| Side split | 40 bid / 38 ask | z=0.23, p=0.82 (consistent with 50/50) |
| Offset from round(FV) | {-3: 23%, -2: 21%, +1: 23%, +2: 33%} | χ²=4.15, p=0.25 (uniform over 4 values) |
| Crossing vol | U(4, 10), mean=7.4 | |
| Passive vol | U(1, 5), mean=3.4 | |
| Duration | 87% single-tick, 7% two-tick | |

## INTARIAN_PEPPER_ROOT Calibration

### Bot 1 (Outer Wall)

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `ceil(FV) - 10` | 100.0% (804/804) |
| Ask formula | `floor(FV) + 10` | 99.9% (795/796), 1 miss at t=1000 |
| Volume | `U(15, 25)`, same both sides | χ²=15.31, p=0.12 (uniform ✓) |
| Bid/ask vol match | 100.0% (640/640) | |
| Spread | 19 (non-integer FV), 20 (integer FV) | |

**Miss analysis**: Single ask miss at t=1000 (FV=12001.0 exactly). Ask=12010 instead of 12011. All other 84 integer-FV timestamps match perfectly. Likely floating-point accumulation of 0.1 (classic `sum(0.1 for _ in range(10)) != 1.0`).

### Bot 2 (Inner Wall)

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `ceil(FV) - 7` | 100.0% (807/807) |
| Ask formula | `floor(FV) + 7` | 99.9% (772/773), 1 miss at t=1000 |
| Volume | `U(8, 12)`, same both sides | χ²=6.81, p=0.15 (uniform ✓) |
| Bid/ask vol match | 100.0% (619/619) | |
| Spread | 13 (non-integer FV), 14 (integer FV) | |

**Same t=1000 anomaly**: Both bots' asks are 1 lower at that single tick. Same floating-point root cause.

### Bot 3 (Noise)

| Property | Value | Test |
|---|---|---|
| Presence | 4.7% of ticks | |
| Single-sided | 100% | |
| Side split | 21 bid / 26 ask | z=-0.73, p=0.47 (consistent with 50/50) |
| Offset from round(FV) | {-5: 4%, -4: 28%, -3: 17%, +2: 23%, +3: 23%, +4: 4%} | |
| Crossing vol | U(3, 8), mean=5.3 | |
| Passive vol | U(5, 12), mean=8.3 | |

**Note**: PEPPER Bot 3 has REVERSED volume pattern vs OSMIUM — crossing orders are SMALLER (3-8), passive orders are LARGER (5-12). This is the opposite of OSMIUM and TOMATOES. Low sample size (n=47), needs validation with more data.

## Presence Model

### Key Finding: ~80% per-side Bernoulli

Each bot quotes on each side independently with ~80% probability per tick. This is different from TOMATOES where bots were always present.

| Product | Bot | Bid rate | Ask rate | Both (actual) | Both (if independent) |
|---|---|---|---|---|---|
| OSMIUM | Bot 1 | 79.4% | 77.9% | 62.9% | 61.8% |
| OSMIUM | Bot 2 | 75.9% | 80.7% | 61.9% | 61.3% |
| PEPPER | Bot 1 | 80.5% | 79.7% | 64.1% | 64.2% |
| PEPPER | Bot 2 | 80.8% | 77.4% | 62.0% | 62.5% |

### Independence Tests (χ², all p > 0.05)

- Bot bid/ask: OSMIUM Bot1 p=0.06, Bot2 p=0.27; PEPPER Bot1 p=0.98, Bot2 p=0.34
- Bot1 vs Bot2: OSMIUM p=0.59, PEPPER p=0.35
- **Conclusion**: All 4 channels (B1_bid, B1_ask, B2_bid, B2_ask) are independent

### No Autocorrelation

Lag-1 autocorrelation for all channels: |r| < 0.025, all p > 0.49. Presence is iid Bernoulli, no persistence.

### Run Length Distribution

- Present runs: mean ≈ 5 (consistent with geometric(p_stop=0.2), expected mean = 5)
- Absent runs: mean ≈ 1.2 (consistent with geometric(p_stop=0.8), expected mean = 1.25)

## KEY DISCOVERY: Proportional Offsets

The bots do NOT use fixed integer offsets from FV. They use **proportional offsets that scale with FV**:

```
bid = floor(FV * (1 - K))
ask = ceil(FV * (1 + K))
vol = randint(vol_lo, vol_hi)  # same both sides per tick
```

This was invisible in the portal data (narrow FV range), but became clear when cross-validating against the 30,000-tick CSV data spanning FV from 10,000 to 13,000.

### Discovered K Values (PEPPER_ROOT, validated across 30,000 ticks)

| Bot | K | 1/K | Bid formula | Ask formula | Match rate |
|---|---|---|---|---|---|
| Bot 1 | **3/4000 = 0.000750** | 1333.3 | `floor(FV * 0.999250)` | `ceil(FV * 1.000750)` | **99.9%** (23,975/23,987) |
| Bot 2 | **1/2000 = 0.000500** | 2000.0 | `floor(FV * 0.999500)` | `ceil(FV * 1.000500)` | **99.0%** (23,953/24,185) |

### Why Integer-Offset Formulas Worked on Portal Data

Within a narrow FV range (12,000-12,100), the proportional formula reduces to integer offsets:
- `floor(12050 * 0.999250)` = `floor(12050 - 9.04)` = `floor(12040.96)` = 12040 = `ceil(12050) - 10`
- The proportional offset (9.04) is close enough to an integer (9 or 10) that the rounding is consistent

Match rate comparison on CSV day 0:

| FV range | `ceil(FV)-10` | `floor(FV*0.99925)` |
|---|---|---|
| 12000-12100 (portal range) | **99.9%** | **99.9%** |
| 12100-13000 | 63.6% | **95.9%** |
| All 10000 ticks | 67.2% | **96.3%** |

### Implications for Effective Offsets at Different FV Levels

| FV level | Bot 1 offset (FV*0.00075) | Bot 2 offset (FV*0.0005) | Bot 2 spread |
|---|---|---|---|
| 10,000 | 7.5 | 5.0 | ~10 |
| 11,000 | 8.25 | 5.5 | ~11 |
| 12,000 | 9.0 | 6.0 | ~12 |
| 13,000 | 9.75 | 6.5 | ~13 |

## Summary Model

```python
# INTARIAN_PEPPER_ROOT
fv_process = "deterministic_drift"
fv_drift = 0.1  # per tick (confirmed across 3 days)
fv_start_day_minus2 = 10000  # +1000 per day from drift
fv_start_day_minus1 = 11000
fv_start_day_0 = 12000
fv_quantization = 1/2048

K_BOT1 = 3/4000  # = 0.000750
K_BOT2 = 1/2000  # = 0.000500

bot1_bid = lambda fv: math.floor(fv * (1 - K_BOT1))  # 99.9% match
bot1_ask = lambda fv: math.ceil(fv * (1 + K_BOT1))   # 99.9% match
bot1_vol = lambda: random.randint(15, 25)             # same both sides

bot2_bid = lambda fv: math.floor(fv * (1 - K_BOT2))  # 99.0% match
bot2_ask = lambda fv: math.ceil(fv * (1 + K_BOT2))   # 99.0% match (98.9% ask)
bot2_vol = lambda: random.randint(8, 12)              # same both sides

presence_per_side = 0.80  # iid Bernoulli, independent across bots/sides

# ASH_COATED_OSMIUM
# FV range is too narrow (~±30) to distinguish proportional from fixed offset.
# Using fixed offsets (validated at 99.7-100% on portal data).
# The proportional K values may be the same or different from PEPPER.
fv_process = "random_walk"
fv_sigma = 0.3117
fv_start = 10000  # approximate, stays near 10000
fv_quantization = 1/2048

bot1_bid = lambda fv: math.floor(fv) - 10  # 99.7% (equiv to proportional at FV≈10000)
bot1_ask = lambda fv: math.ceil(fv) + 10   # 100%
bot1_vol = lambda: random.randint(20, 30)

bot2_bid = lambda fv: round(fv) - 8        # 100%
bot2_ask = lambda fv: round(fv) + 8        # 100%
bot2_vol = lambda: random.randint(10, 15)

presence_per_side = 0.80  # iid Bernoulli
```

## Cross-Product Comparison

| Feature | OSMIUM | PEPPER | TOMATOES (tutorial) |
|---|---|---|---|
| FV process | RW σ=0.312 | Drift +0.1/tick | RW σ=0.496 |
| Bot 1 K | ~0.00105 (uncertain) | **3/4000** (confirmed) | ~0.0008 (narrow FV) |
| Bot 2 K | ~0.0008 (uncertain) | **1/2000** (confirmed) | ~0.0007 (narrow FV) |
| Bot 1 vol | U(20,30) | U(15,25) | U(15,25) |
| Bot 2 vol | U(10,15) | U(8,12) | U(5,10) |
| Presence | ~80% per side | ~80% per side | ~100% |
| Bot 3 rate | 7.6% | 4.7% | 6.3% |

## Open Questions

1. **Does PEPPER drift vary across sessions?** The drift was exactly +0.1/tick on all 3 observed days. Likely fixed, but could vary per round.
2. **OSMIUM K values**: FV too narrow to confirm. If using same K as PEPPER (3/4000), Bot 1 at FV=10000 gives offset=7.5, but we measured offset≈10.5. So OSMIUM likely has DIFFERENT K values. Need wider FV range to confirm.
3. **Position limits**: Not yet determined. Need to check wiki or experiment.
4. **The ~80% presence**: Consistent across all 30,000 ticks and both products. Very likely a server parameter.
5. **FV starting values for competition**: OSMIUM stays near 10,000. PEPPER accumulates +1000/day. What will Round 1 day's starting FV be?
6. **Position limits**: Not in the data files. Check the portal wiki for Round 1 limits.
