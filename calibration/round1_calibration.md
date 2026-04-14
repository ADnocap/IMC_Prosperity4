# Round 1 Calibration

Submission 103017 (trader_hold1.py) used to extract true FV.

> **IMPORTANT — PEPPER uses proportional offsets, not fixed integers.**
> Cross-validation across 30,000 ticks (3 days, FV 10000→13000) revealed the true formulas:
> - Bot 1: `bid = floor(FV * (1 - 3/4000))`, `ask = ceil(FV * (1 + 3/4000))` → **99.9%** match
> - Bot 2: `bid = floor(FV * (1 - 1/2000))`, `ask = ceil(FV * (1 + 1/2000))` → **99.0%** match
>
> The fixed `ceil(FV)-10` / `floor(FV)+10` formulas below are equivalent at FV≈12000
> but diverge at other FV levels (67% accuracy at FV 12100–13000).
> The Rust simulator uses the proportional formulas.
> See `calibration/round1/calibration_comparison.md` for full analysis.

## ASH_COATED_OSMIUM

### Fair Value
- **Process**: Gaussian random walk, N(0, 0.312²) per tick
- **Quantization**: 1/1024 (~0.001)
- **Start**: ~10,000 (stationary, no drift)
- **Autocorrelation**: 0.0 (pure random walk)

### Bot 1 (Outer Wall)
- **Presence**: ~80% per side, independent. Both sides ~63%, one side ~31%, absent ~6%.
- **Formula**:
  ```
  bid = floor(FV) - 10
  ask = ceil(FV) + 10
  ```
- **Spread**: 20 (when FV is integer: 21), always ≥ 20
- **Volume**: U(20, 30), **same** bid and ask per tick
- **Accuracy**: 99.7% bid, 100% ask

### Bot 2 (Inner Wall)
- **Presence**: ~80% per side, independent. Both sides ~62%, one side ~33%, absent ~5%.
- **Formula**:
  ```
  bid = floor(FV - 0.5) - 7    # equivalently: round-down-at-half(FV) - 8
  ask = floor(FV - 0.5) + 9    # equivalently: round-down-at-half(FV) + 8
  ```
  Note: `floor(FV - 0.5)` rounds FV to nearest int, breaking ties downward.
- **Spread**: 16 always
- **Volume**: U(10, 15), **same** bid and ask per tick
- **Accuracy**: 100% both sides

### Bot 3 (Noise)
- **Presence**: ~8% of ticks, single-sided
- **Offsets from FV**: {-3, -2, +1, +2} (bid), {-3, -2, +1, +2} (ask)
- **Volume**: small (1-10)
- Low-impact, can approximate or ignore initially

### Trade Bots
- Trades occur on ~4.0% of ticks (mostly 1 trade per tick)
- Quantity: bimodal {2-6} and {7-10}

---

## INTARIAN_PEPPER_ROOT

### Fair Value
- **Process**: Deterministic linear drift, +0.1 per tick (+100/1000 ticks, +1000/day on portal 10k ticks)
- **Quantization**: 1/1024 (~0.001)
- **Start**: ~10,000 on day -2, increases ~1000/day
- **Variance**: near-zero (σ ≈ 0.0005), essentially deterministic

### Bot 1 (Outer Wall)
- **Presence**: ~80% per side, independent. Both sides ~64%, one side ~32%, absent ~4%.
- **Formula**:
  ```
  bid = ceil(FV) - 10
  ask = floor(FV) + 10
  ```
  Note: **opposite** rounding from ASH (ceil for bid, floor for ask).
- **Spread**: 19 or 20 depending on FV fractional part
- **Volume**: U(15, 25), **same** bid and ask per tick
- **Accuracy**: 100% bid, 99.9% ask (1 miss at FV=integer boundary)

### Bot 2 (Inner Wall)
- **Presence**: ~80% per side, independent. Both sides ~62%, one side ~34%, absent ~4%.
- **Formula**:
  ```
  bid = ceil(FV) - 7
  ask = floor(FV) + 7
  ```
- **Spread**: 13 or 14 depending on FV fractional part
- **Volume**: U(8, 12), **same** bid and ask per tick
- **Accuracy**: 100% bid, 99.6% ask

### Bot 3 (Noise)
- **Presence**: ~5% of ticks, single-sided
- **Offsets**: {+3, -3} (bid), {-4, +2} (ask)
- **Volume**: small (3-12)

### Trade Bots
- Trades occur on ~3.2% of ticks
- Quantity: {3-8}

---

## Key Differences from Tutorial (TOMATOES/EMERALDS)

1. **Bots are NOT always present** — each side appears independently ~80% of the time
2. **ASH is stationary but more volatile** (σ=0.31 vs TOMATOES σ=0.50, but wider bot spreads)
3. **IPR has deterministic drift** — FV is almost perfectly predictable (+0.1/tick)
4. **Different rounding rules** — ASH uses floor/ceil, IPR uses ceil/floor (swapped!)
5. **Bot 1 spread is wider** (20 vs 16 for TOMATOES)
6. **Different volume ranges** per product
