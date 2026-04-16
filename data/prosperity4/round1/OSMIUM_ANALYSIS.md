# OSMIUM (ASH_COATED_OSMIUM) Hidden Pattern Analysis

## Data: 3 days (d-2, d-1 for discovery; d0 for validation), 10k ticks/day, ~430 trades/day

---

## 1. Book Structure

The OSMIUM order book has a very clean, structured market maker:

| State | Frequency | Description |
|-------|-----------|-------------|
| **Symmetric (spread=16)** | 59% | MM quotes at FV-8 / FV+8, bv1 == av1 |
| Wide (spread=18/19) | 23% | L2 became L1 after one side got hit |
| Tight (spread 5-13) | 8% | Post-trade residual orders, brief |
| One-sided (bid or ask only) | 8% | One side fully depleted |
| Very wide (spread=21) | 2% | L2 gap of 3 on both sides exposed |

**FV extraction**: When the book is symmetric with spread=16, FV = (bid1 + ask1) / 2. This is always an integer.

L1 volumes in symmetric state are uniform in {10, 11, 12, 13, 14, 15} with no information content.

---

## 2. The Core Pattern: Mean-Reverting Integer Steps with 65% Reversal

FV changes in discrete steps of +/-1 (99% of moves), with ~1800 steps per day.

**After FV moves in one direction, the next move reverses with ~65% probability.**

### Reversal probability (consistent across all 3 days):

| Day | After step=-1, P(next=+1) | After step=+1, P(next=-1) |
|-----|--------------------------|--------------------------|
| d-2 | 0.659 | 0.667 |
| d-1 | 0.652 | 0.646 |
| **d0 (test)** | **0.659** | **0.658** |

### Markov chain (2-step memory adds nothing):

```
After (-1,-1): P(next=+1) = 0.65
After (-1,+1): P(next=-1) = 0.65
After (+1,-1): P(next=+1) = 0.65
After (+1,+1): P(next=-1) = 0.67
```

The pattern is purely 1-step: fade the last move.

### Step autocorrelation:

| Lag | AC (d-2) | AC (d-1) | AC (d0) |
|-----|----------|----------|---------|
| 1 | -0.323 | -0.290 | -0.316 |
| 2 | +0.113 | +0.066 | +0.077 |
| 3 | -0.041 | -0.042 | -0.014 |

---

## 3. Mean Reversion to ~10000

FV doesn't just reverse individual steps -- it reverts to a long-run center near 10000.

### Variance Ratio Test (RW = 1.0):

| Horizon | d-2 | d-1 | d0 |
|---------|-----|-----|-----|
| VR(2) | 0.759 | 0.759 | 0.785 |
| VR(5) | 0.597 | 0.600 | 0.628 |
| VR(10) | 0.550 | 0.542 | 0.566 |
| VR(20) | 0.527 | 0.495 | 0.531 |
| VR(50) | 0.484 | 0.402 | 0.495 |
| VR(100) | 0.435 | 0.378 | 0.466 |

All deeply below 1.0 = very strong anti-persistence.

### Ornstein-Uhlenbeck fit:

| Day | theta | mu (long-run mean) | Half-life (sym ticks) |
|-----|-------|-------------------|----------------------|
| d-2 | 0.0077 | 9998 | 90 |
| d-1 | 0.0135 | 10001 | 51 |
| d0 | 0.0063 | 10002 | 110 |

### Distance-dependent reversal probability:

When FV is far from 10000, reversal probability **increases**:

| FV distance | Avg P(reverse) | Sample sizes |
|-------------|---------------|--------------|
| 0-3 from 10000 | ~0.65 | Large |
| 5-7 from 10000 | ~0.65 | Medium |
| 8-11 from 10000 | ~0.70-0.75 | Smaller |
| 12+ from 10000 | ~0.75-0.90 | Small |

### FV range per day:

| Day | Start | End | Net | Min | Max | Range |
|-----|-------|-----|-----|-----|-----|-------|
| d-2 | 10000 | 9992 | -8 | 9988 | 10010 | 22 |
| d-1 | 9992 | 10002 | +10 | 9990 | 10012 | 22 |
| d0 | 10003 | 10008 | +5 | 9986 | 10015 | 29 |

FV carries over between days (d-2 end = 9992, d-1 start = 9992).

---

## 4. Edge Quantification

### Reversal signal accuracy (validated on d0):

| Horizon | Mean gain | Win rate | Sharpe |
|---------|-----------|----------|--------|
| 1 step | +0.331 | 65.9% | 14.3 |
| 2 steps | +0.250 | 25.0% | 9.0 |
| 3 steps | +0.260 | 57.1% | 7.9 |
| 5 steps | +0.248 | 54.5% | 6.1 |
| 10 steps | +0.304 | 41.4% | 5.4 |

### Distance-from-mean signal (d0, 10-step horizon):

| Condition | Avg 10-step return | n |
|-----------|-------------------|---|
| FV > 10003 | -0.242 | 1882 |
| FV < 9997 | +0.251 | 776 |
| FV > 10005 | -0.270 | 1161 |
| FV < 9995 | +0.180 | 522 |
| FV > 10007 | -0.258 | 681 |
| FV < 9993 | +0.239 | 331 |
| FV > 10010 | -0.254 | 264 |
| FV < 9990 | +0.543 | 92 |

### Combined signal:

When step-reversal and distance-from-mean agree: **66.2% accuracy** (n=928 on d0).

### Simulated PnL (d0 validation):

| Strategy | PnL | Trades |
|----------|-----|--------|
| Distance from 10000 fade | +938 | 1809 |
| Step reversal | +2,990 | 1191 |
| Combined MM (inside quotes) | +15,510 | 2642 |

---

## 5. FV Step Timing

- Mean time between FV changes: **~550 timestamps** (3.2 symmetric ticks)
- Median: 400 timestamps
- 69% of symmetric ticks have NO FV change (FV is sticky)
- Mean run length: ~1.5 steps before reversing direction
- Max run: 6-8 consecutive same-direction steps (rare)

---

## 6. Book State Transitions

```
Symmetric(16) --[trade hits L1]--> Wide(18 or 19)
                                     |
                                     +--> L2 gap was 2: spread=18
                                     +--> L2 gap was 3: spread=19
Wide(18/19) --[MM re-quotes]--> Symmetric(16)

Symmetric(16) --[trade eats full side]--> One-sided (bid or ask only)
One-sided --[MM re-quotes]--> Symmetric(16)

Trade execution --> Tight spread (5-13), brief residual
```

L2 structure: bid2 at FV-10 or FV-11, ask2 at FV+10 or FV+11 (gap of 2 or 3 from L1). L2 volumes ~20-30.

None of these transitions carry directional signal for FV.

---

## 7. What's NOT the Pattern

| Feature | Result |
|---------|--------|
| Volume encoding | No signal (uniform 10-15) |
| Cross-asset (PEPPER) | Zero correlation (0.000) |
| Book imbalance | Inconsistent across days |
| L2 depth | Not predictive |
| FFT / periodicity | No clean cycle |
| Trade flow direction | No persistent signal |
| One-sided book events | No directional info |

---

## 8. PEPPER ROOT Comparison

PEPPER is a **trending** asset, completely different from OSMIUM:

| Property | OSMIUM | PEPPER |
|----------|--------|--------|
| FV behavior | Mean-reverting | Trending (+1000/day) |
| Spread | 16 | 12-14 |
| OU half-life | 50-110 ticks | ~30,000+ ticks |
| Daily FV range | ~25 | ~500+ |
| VR(10) on clean FV | 0.55 | N/A (trending) |
| Cross-correlation | 0.000 | 0.000 |

---

## 9. Trading Strategy Implications

1. **Extract FV**: From symmetric spread-16 ticks, FV = (bid1 + ask1) / 2
2. **Track last FV step direction** and fade it (65% reversal)
3. **Track distance from ~10000** and skew quotes toward the mean
4. **Quote inside the spread**: With spread=16, placing orders at FV +/- 7 (or tighter) captures the reversal edge while still being competitive
5. **Position management**: When signals agree (step reversal + distance), take larger positions; when they conflict, reduce exposure
6. **No cross-asset hedging**: OSMIUM and PEPPER are independent
