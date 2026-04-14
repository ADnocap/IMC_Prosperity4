# Calibration Comparison: My Analysis vs Teammate (round1-calibration branch)

## Agreements (both calibrations match)

| Finding | My result | Teammate result | Status |
|---|---|---|---|
| OSMIUM FV | RW σ=0.312 | RW σ=0.312 | **AGREE** |
| PEPPER FV | Drift +0.1/tick | Drift +0.1/tick | **AGREE** |
| OSMIUM Bot 1 bid | `floor(FV) - 10` (99.7%) | `floor(FV) - 10` (99.7%) | **AGREE** |
| OSMIUM Bot 1 ask | `ceil(FV) + 10` (100%) | `ceil(FV) + 10` (100%) | **AGREE** |
| PEPPER Bot 1 bid | `ceil(FV) - 10` (100%) | `ceil(FV) - 10` (100%) | **AGREE** |
| PEPPER Bot 1 ask | `floor(FV) + 10` (99.9%) | `floor(FV) + 10` (99.9%) | **AGREE** |
| PEPPER Bot 2 bid | `ceil(FV) - 7` (100%) | `ceil(FV) - 7` (100%) | **AGREE** |
| PEPPER Bot 2 ask | `floor(FV) + 7` (99.9%) | `floor(FV) + 7` (99.6%) | **AGREE** |
| Bot 1 volumes | OSM U(20,30), PEP U(15,25) | Same | **AGREE** |
| Bot 2 volumes | OSM U(10,15), PEP U(8,12) | Same | **AGREE** |
| Bid=ask vol per tick | 100% for all bots | 100% for all bots | **AGREE** |
| Presence | ~80% per side, iid | ~80% per side, independent | **AGREE** |
| Bot 3 rates | OSM 7.6%, PEP 4.7% | OSM ~8%, PEP ~5% | **AGREE** |

## Differences

### 1. Quantization: **Teammate is correct** → 1/1024

| | Mine | Teammate |
|---|---|---|
| Claim | 1/2048 | 1/1024 |
| Evidence | Max grid error = 0 for 1/2048 | Min |step| = 1/1024 exactly |

**Resolution**: Both 1/1024 and 1/2048 pass the "max grid error" test because every 1/1024 point is also on the 1/2048 grid. The minimum step size (1/1024 = 0.0009765625) is the definitive test: no FV steps smaller than 1/1024 exist. **Use 1/1024.**

### 2. OSMIUM Bot 2 formula: **Equivalent** (no practical difference)

| | Mine | Teammate |
|---|---|---|
| Bid | `round(FV) - 8` | `floor(FV - 0.5) - 7` |
| Ask | `round(FV) + 8` | `floor(FV - 0.5) + 9` |
| Match | 100% | 100% |

These formulas differ only at FV = X.5 (where Python `round()` uses banker's rounding but `floor(FV-0.5)` rounds down). In 999 ticks, FV never hit exactly X.5, so both are 100%.

Teammate's formulation is slightly better because:
- It makes the constant spread of 16 explicit: `(floor(FV-0.5)+9) - (floor(FV-0.5)-7) = 16` always
- It's unambiguous about tie-breaking

**For the simulator, use teammate's formulation.**

### 3. Proportional offsets: **My discovery, teammate missed** → matters for PEPPER

| FV level | Fixed (ceil-7/floor+7) bid | Proportional (K=1/2000) bid | Actual |
|---|---|---|---|
| 10,000 | 9993 | 9995 | **9995** |
| 11,000 | 10993 | 10994 | **10994** |
| 12,000 | 11993 | 11994 | both match |
| 13,000 | 12993 | 12993 | both match |

True formula for PEPPER (validated at 99%+ across 30,000 ticks, 3 days):
```python
K_BOT1 = 3/4000  # = 0.000750
K_BOT2 = 1/2000  # = 0.000500
bid = floor(FV * (1 - K))
ask = ceil(FV * (1 + K))
```

**Impact on simulator accuracy:**

| Scenario | Fixed offset accuracy | Proportional accuracy |
|---|---|---|
| Portal (1000 ticks, FV spans ~100) | 99.9% | 99.9% |
| CSV day 0 (10000 ticks, FV spans 1000) | 67-80% | **96-99%** |
| Across all 3 days (FV 10000-13000) | 3-80% | **99%** |

**When it matters**: If the competition uses 10,000 ticks/day (like the CSVs), PEPPER FV spans 1000 units and fixed offsets break down for later ticks. If it uses 2,000 ticks (current backtester default), FV spans only 200 units and fixed offsets are adequate.

**Recommendation**: Update the Rust simulator to use proportional offsets for PEPPER. This makes it correct regardless of ticks-per-day.

### 4. Trade bots: **Teammate analyzed, I didn't**

Teammate found:
- OSMIUM: trades on ~4.0% of ticks, quantity bimodal {2-6} and {7-10}
- PEPPER: trades on ~3.2% of ticks, quantity {3-8}
- These are already implemented in the Rust simulator

I didn't analyze the trades CSV. Teammate's work here is additional and valuable.

### 5. PEPPER Bot 3: Minor differences

| | Mine | Teammate |
|---|---|---|
| Bid offsets | {-5,-4,-3,+2,+3,+4} from round(FV) | {+3,-3} from round(FV) |
| Ask offsets | Similar | {-4,+2} from round(FV) |
| Volume pattern | Crossing U(3,8), Passive U(5,12) | Same (reversed from OSMIUM) |

My analysis found a wider range of offsets because I included all near-FV levels; teammate restricted to the most common. Both note the reversed volume pattern (crossing smaller than passive for PEPPER).

## Overall Assessment

| Area | Winner | Action needed |
|---|---|---|
| Quantization | **Teammate** | Fix to 1/1024 |
| OSMIUM formulas | **Tie** | Use teammate's floor(FV-0.5) notation |
| PEPPER formulas (narrow range) | **Tie** | Both work at FV~12000 |
| PEPPER formulas (wide range) | **Mine** | Update sim with proportional K |
| Trade bots | **Teammate** | Already implemented |
| Statistical rigor | **Tie** | Both use chi-squared, z-tests, etc. |
| Simulator implementation | **Teammate** | Already has working Rust sim |

## Recommended Actions

1. **Merge teammate's branch** — gets us the updated Rust simulator, trade bot modeling, and corrected quantization
2. **Update PEPPER bot formulas** in the Rust simulator from fixed offsets to proportional: `floor(FV * (1-K))` / `ceil(FV * (1+K))` with K_bot1=3/4000, K_bot2=1/2000
3. **Verify ticks-per-day** against the actual competition — if 10,000, the proportional formula is essential
