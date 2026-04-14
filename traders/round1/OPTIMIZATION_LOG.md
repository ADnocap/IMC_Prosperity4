# Round 1 Optimization Log

Baseline: original a.py = **10,919** mean PnL (1000 ticks, 1000 sessions)
Current best: g2.py = **11,191** mean PnL (1000 ticks, 2000 sessions)

## Improvements Applied (10,919 → 11,137 = +218)

| Change | Delta | Cumulative | Detail |
|--------|-------|------------|--------|
| Remove inventory skew | +87 | 11,006 | No skew beats soft=50/max=2. Validated by Frankfurt Hedgehogs (2nd P3) — skew reduces edge per fill on random walks |
| Improved FV estimation | +45 | 11,051 | Multi-source weighted (Bot 2 weight 2, Bot 1 weight 1). Bot 3 filtering via distance-from-mid heuristic |
| Fix ref_bid/ref_ask logic | +29 | 11,080 | When Bot 2 absent + Bot 3 present, old code penny'd Bot 3 (1 tick edge) instead of Bot 1 (9 tick edge) |
| PEPPER selective buying | +22 | 11,102 | Skip Bot 1 asks (vol>15) when remaining>20. Bot 2 is ~3 ticks cheaper |
| PEPPER never buy Bot 1 | +35 | 11,137 | Always skip Bot 1. Saves ~240 spread cost vs ~30 drift loss from slower fill |
| Volume imbalance (OBI) on FV | +54 | 11,191 | OBI = (bid_vol - ask_vol) / total. Coeff=2.0 shifts FV toward heavier side. Indirectly detects Bot 3 crossing orders via volume asymmetry |

## OSMIUM Techniques Tested — No Improvement

### FV Estimation
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Micro-price / weighted mid (g1.py) | 11,136 (0) | 2000 | wmid = (bid*ask_vol + ask*bid_vol)/(bid_vol+ask_vol). No benefit over volume-based offsets |
| Fractional FV from Bot 1 spread (g3.py) | 11,138 (0) | 2000 | Use Bot 1 spread 20 vs 21 to narrow FV range. Improvement too small (~0.25/trade) |
| EMA α=0.15 | 11,109 (0) | 1000 | No benefit with improved estimator; lag hurts on random walk |
| EMA α=0.3 | 11,014 (0) | 500 | Same |
| EMA α=0.5 | 11,013 (0) | 500 | Same |
| Reversion beta -0.1 | 11,145 (0) | 1000 | Our FV has zero autocorrelation (true random walk, unlike P3 KELP) |
| Reversion beta -0.2 | 11,145 (0) | 1000 | Same |
| Reversion beta -0.3 | 11,145 (0) | 1000 | Same |
| Wall-mid FV (Frankfurt) | 10,799 (-338) | 1000 | Less precise than volume-based (±0.5 vs ±0.25 error) |
| Filtered-mid FV (Linear Utility) | 10,881 (-256) | 2000 | Similar to wall-mid; our calibrated offsets are more precise |

### Quoting Width / Style
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Penny+2 / FV±6 | 10,690 (-447) | 1000 | Less edge per fill, same fill rate (already best bid/ask) |
| Join Bot 2 / FV±8 | 8,197 (-2940) | 1000 | Bot has order priority at same price, we get zero fills |
| Frankfurt overbid (penny best visible) | 10,799 (-338) | 1000 | Pennies Bot 3 near FV → tight quotes, low edge |
| Fixed spread FV±7 (no ref detection) | 10,938 (-199) | 2000 | Doesn't adapt to Bot 2 presence/absence |
| Linear Utility penny/join zones | 10,881 (-256) | 2000 | Join zone gives tighter quotes than penny-jumping Bot 2 |
| Multi-level 70/30 split | 7,517 (-3620) | 1000 | Backup level never fills (taker demand < primary capacity) |
| Wide fallback FV±3 (vs FV±1) | 11,015 (0) | 500 | Fallback rarely triggers |

### Inventory Management
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| No skew (current best) | **11,137** | 2000 | Maximizes edge per fill; position limits handle extremes naturally |
| Skew only at pos ±75 | 11,086 (-51) | 1000 | Even minimal skew hurts by shifting quotes behind Bot 2 |
| Skew only at pos ±70 | 11,063 (-74) | 1000 | Same |
| Original skew soft=50 max=2 | 10,999 (-138) | 1000 | Worst — reduces edge AND loses fills when bid moves behind Bot 2 |
| Step skew at pos ±20 | 10,595 (-542) | 500 | Aggressive early skew destroys edge |
| Retreat 0.02/lot (A-S) | 11,143 (-7) | 2000 | Introduces bias on zero-drift random walk |
| Retreat 0.04/lot | 11,080 (-70) | 2000 | Worse with more retreat |
| Retreat 0.10/lot | 11,039 (-111) | 2000 | Monotonically hurts |
| Linear Utility soft_pos=40 | 10,881 (-256) | 2000 | Skew from pos 40 reduces edge |

### Taking Logic
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Expand buy taking to fv_r+1 | 11,077 (-60) | 1000 | Takes Bot 3 passive asks at ~-0.5 edge (negative EV) |
| Expand both sides ±1 | 11,077 (-60) | 1000 | Same |
| Adverse volume filter (vol≤9) | 10,881 (-256) | 2000 | Misses Bot 3 crossing at vol=10 (legitimate take) |
| Position-dependent taking ±50 | failed | 1000 | Code error, but analysis shows no bot levels at expanded thresholds |

### Clear Phase (0-edge inventory flattening)
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Clear at fv_r (Linear Utility) | ~0 effect | 1000 | No bot bids/asks AT fv_r — Bot 2 is at FV±8, Bot 3 at ±{1,2,3} |

## PEPPER Techniques Tested

| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Skip Bot 1 when remaining>20 (a.py) | 11,102 | 2000 | Good — saves spread on first ~60 units |
| Skip Bot 1 when remaining>10 | 11,128 (+26) | 2000 | Better — more selective |
| **Never buy Bot 1** (c.py) | **11,137 (+35)** | 2000 | Best — saves ~3/unit × 80 units = 240, drift loss ~30 |
| Skip Bot 1 when remaining>50 | 10,993 (-109) | 500 | Too aggressive early, sweeps Bot 1 too soon |
| Sweep all (no selective) | 10,964 (-138) | 500 | Baseline — pays full spread on Bot 1 |
| Cycling sell/rebuy (b.py) | 10,208 (-894) | 2000 | Selling destroys drift exposure, huge variance |

### Volume Imbalance (OBI) Coefficient Sweep
| OBI_COEFF | Result | Sessions | Detail |
|-----------|--------|----------|--------|
| 0.0 (c.py) | 11,137 | 2000 | No OBI adjustment |
| 0.2 | 11,170 (+33) | 2000 | |
| 0.5 | 11,176 (+39) | 2000 | |
| 1.0 | 11,183 (+46) | 2000 | |
| **2.0** | **11,191 (+54)** | **2000** | **Peak — captures Bot 3 detection signal without over-adjusting** |
| 3.0 | 11,183 (+46) | 2000 | Starting to degrade |
| 5.0 | 11,157 (+20) | 2000 | Over-adjusting |
| 8.0 | 11,146 (+9) | 2000 | Noise dominates |

### PEPPER First-Tick Aggressive (g3.py)
| Technique | Result | Sessions | Why |
|-----------|--------|----------|-----|
| Sweep all on tick 0, selective after | 11,138 (0) | 2000 | First-tick Bot 1 spread cost ≈ drift gain from faster fill. Wash. |

## Alternative Full Strategies Tested

| Strategy | Total | OSMIUM | PEPPER | Detail |
|----------|-------|--------|--------|--------|
| **g2.py (new best)** | **11,191** | **~3,676** | **~7,515** | c.py + OBI signal (coeff=2.0) on FV |
| c.py | 11,137 | 3,622 | 7,515 | Volume-based FV, no skew, never Bot 1 |
| a.py | 11,102 | 3,620 | 7,483 | Same OSMIUM, PEPPER thresh=20 |
| e.py (fixed spread) | 10,935 | 3,452 | 7,483 | No ref level adaptation |
| d.py (Linear Utility) | 10,881 | 3,398 | 7,483 | Filtered-mid, adverse vol, penny/join, soft skew |
| c.py (Frankfurt) | 10,799 | 3,316 | 7,483 | Wall-mid, overbid |
| b.py (cycling) | 10,208 | 3,388 | 6,821 | PEPPER sell/rebuy variant |

## PnL Decomposition (c.py OSMIUM, per 1000-tick session)

| Source | Fills/session | Avg edge | PnL | Share |
|--------|--------------|----------|-----|-------|
| Passive (takers hit our quotes) | 82 | 7.39 | 3,088 | 85% |
| Taking (we hit Bot 3 crossing) | 40 | 1.96 | 548 | 15% |
| **Total OSMIUM** | 122 | — | **3,636** | 100% |

- Best bid/ask 92% of ticks
- 98.6% of taker events fill against us
- Position |pos| > 60 on 15% of ticks, > 70 on 7.4%
- Bottleneck: taker arrival rate (8.2%/tick), not quote competitiveness

## Theoretical Ceiling

OSMIUM: ~82 passive × 5 units × 7.4 edge + ~40 taking × 5 × 2.0 = ~3,434. Actual 3,622 (above estimate due to wider fills when Bot 2 absent at 9-10 edge). Running at ~98% of ceiling.

PEPPER: 80 × 100 drift - 80 × ~5 spread = 7,600. Actual 7,515 (close). Limited by spread cost.

Combined ceiling: ~11,250. Current g2.py at 11,191 = **99.5% of ceiling**.

## Strategy File Index

| File | Description | PnL |
|------|-------------|-----|
| **g2.py** | **Best: c.py + OBI signal (coeff=2.0)** | **11,191** |
| c.py | Volume-based FV, no skew, never Bot 1 PEPPER | 11,137 |
| a.py | Same OSMIUM as c.py, PEPPER thresh=20 | 11,102 |
| g1.py | Micro-price (weighted mid) FV variant | 11,136 |
| g3.py | Fractional FV refinement + first-tick aggressive PEPPER | 11,138 |
| e.py | Fixed spread FV±7, no ref detection | 10,935 |
| d.py | Linear Utility (filtered-mid, take/clear/make) | 10,881 |
| f1.py | Frankfurt OSMIUM + never Bot 1 PEPPER | ~10,800 |
| f2.py | Linear Utility OSMIUM + never Bot 1 PEPPER | ~10,880 |
| b.py | PEPPER cycling sell/rebuy variant | 10,208 |
