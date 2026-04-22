# IMC Prosperity 4 — Round 2: "Growing Your Outpost"

Working notes and strategic analysis. Continue in Claude Code.

## Round format

* Round 2 is the **second and final qualifier** for Phase 2. Threshold: cumulative net PnL ≥ 200,000 XIRECs across R1 + R2.
* Duration: 72 hours.
* Same two products as Round 1: `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT`.
* Position limits: ±80 on both.
* Two independent components this round:
  1. Algorithmic trading with a new **Market Access Fee (MAF)** auction layered on top.
  2. Manual challenge: **Invest & Expand**, allocating a 50,000 XIREC budget across Research / Scale / Speed.

## Algorithmic challenge

### What changes versus Round 1

Products, position limits, and market dynamics are unchanged. The new mechanic is the MAF: an optional sealed bid auction for **25% more quotes** injected into the existing orderbook distribution.

Extra quotes slot in *between* existing levels (example from spec: a new `(ask, 5, $8)` appears between the existing `$7` and `$9` asks). So the benefit is a denser book, not purely more volume at the same levels.

### MAF auction mechanics

* Top 50% of bids (above the median) are accepted.
* Accepted bidders pay their bid, subtracted from Round 2 PnL only.
* Rejected bidders pay nothing, do not get extra access.
* Truly blind: bids are only compared at final simulation time, not during testing.
* During testing, everyone sees 80% of generated quotes (lightly randomised per submission).

### Valuation framework

Let `V` be expected incremental Round 2 PnL from extra access. Under a first price sealed bid auction with top 50% accepted:

```
E[net] = P(bid b in top 50%) × (V − b)
```

* Rational cap: `b ≤ V`. Bidding above V turns a win into a loss.
* Rational floor: the smallest bid that clears the median with high probability.

### Estimating V for our algo

Run our R1 algo on:
1. The native R2 data (80% flow, no extra access).
2. A modified orderbook where we synthetically inject 25% more quotes, sampled from the empirical price/volume distribution of existing quotes.

PnL delta between (1) and (2) is our V estimate. **Do this before submitting.**

Capacity constraint check: if we sit on position limits much of the round, extra flow is wasted. Compute `% of timesteps at |pos| = 80` from R1 logs. High saturation → V is small → bid low.

### Estimating the median bid

Two opposing forces:

* Most teams are not quants. Many will bid 0, 1, 100, or anchor to round PnL magnitude. Heavy left tail.
* Sophisticated teams will try to bid just above the median, crowding the right side.

**Working prior**: median lands in the 500 to 2,000 XIREC range. Bidding 2,500 to 4,000 is probably safely above median while leaving headroom against a plausible V of 5k to 15k.

### Threshold interaction

The fee deducts from Round 2 only, not total qualifier PnL. Implication:

* **If already clear of 200k after R1**: MAF matters less. Can overbid for insurance without risking qualification.
* **If behind after R1**: Round 2 PnL must be maximised. Bid conservatively but still win access.

### Algo refinement checklist

The 80% flow randomisation per submission means single run PnL has genuine noise. Do not overfit.

Priorities for refinement:

* Volatile product (likely `INTARIAN_PEPPER_ROOT`): test EMA fair value or microprice weighted mid vs raw midprice. Add OBI or depth imbalance as directional tilt. Watch for intraday regime changes.
* Stable product (likely `ASH_COATED_OSMIUM`): if a static fair exists, quote tight with inventory skew. If getting run over, quotes are too aggressive near the fair.
* Check order fill asymmetry in R1 logs: systematic fill bias on one side indicates a biased fair estimate.

## Manual challenge: Invest & Expand

### Problem statement

Allocate percentages `(x_R, x_S, x_T)` across Research / Scale / Speed, subject to `x_R + x_S + x_T ≤ 100` and each `x_i ∈ [0, 100]`.

```
PnL = R(x_R) × S(x_S) × T(x_T) − 500 × (x_R + x_S + x_T)
```

where:

```
R(x) = 200_000 × ln(1 + x) / ln(101)      # concave, saturates
S(x) = 0.07 × x                            # linear
T    ∈ [0.1, 0.9]                          # rank based across all players
```

Budget cost: 500 XIRECs per percentage point, max 50,000 XIRECs.

### Structural properties

**Research** is concave and saturates fast:

| x_R | R(x_R)  | % of cap |
|-----|---------|----------|
| 10  | 104,000 | 52%      |
| 25  | 141,000 | 71%      |
| 50  | 162,000 | 81%      |
| 100 | 200,000 | 100%     |

Diminishing returns kick in aggressively past x_R ≈ 25.

**Scale** is linear, no diminishing returns. Every % adds 0.07 to the multiplier. Once Research is mostly done, marginal capital goes to Scale more productively.

**Speed** is a rank tournament: 0.1 to 0.9 range, 9x swing. Dominates effect size but is a function of *rank*, not investment level. Pure game theory.

### R vs S tradeoff at fixed z = x_R + x_S

Maximising `R(x_R) × S(x_S)` subject to `x_R + x_S = z`:

```
dR/dx_R × S = dS/dx_S × R
⇒ (200000 / ln(101)) × 1/(1+x_R) × 0.07 × x_S = 200000 × ln(1+x_R) / ln(101) × 0.07
⇒ x_S / (1 + x_R) = ln(1 + x_R)
⇒ (z − x_R) = (1 + x_R) × ln(1 + x_R)
```

Numerical solutions:

| z   | x_R | x_S | ratio R:S |
|-----|-----|-----|-----------|
| 70  | 17  | 53  | 24 : 76   |
| 80  | 19  | 61  | 24 : 76   |
| 90  | 22  | 68  | 24 : 76   |

Stable 22 to 25% on Research, rest on Scale.

### The Speed tournament

Symmetric Nash is unstable: if everyone picks same `x_T`, everyone ties at multiplier ≈ 0.5, and any unilateral deviation upward moves you into a higher rank bucket. Upward pressure on `x_T`.

Escalation caps where marginal Speed gain equals marginal R+S loss. Rough calc: 0.5 → 0.7 multiplier (1.4x gross) justifies giving up ~15% of Scale (1.2x reduction). So shifting points into Speed is productive up to a point.

**Working prior on equilibrium**: savvy players cluster `x_T` in 30 to 45. Top rank bracket probably needs 50+. Naive players bimodally distributed (near 0 or 60+).

### Suggested allocations

**Balanced (recommended default)**: `x_R = 20, x_S = 45, x_T = 35`
* Speed assumption: 0.65 (above median)
* Gross: 131,930 × 3.15 × 0.65 ≈ 270,000
* Net after 50k budget: ~220,000

**Aggressive Speed**: `x_R = 18, x_S = 37, x_T = 45`
* Speed assumption: 0.8 (top tier)
* Gross: 124,450 × 2.59 × 0.8 ≈ 258,000
* Net: ~208,000

**Conservative Speed**: `x_R = 25, x_S = 55, x_T = 20`
* Speed assumption: 0.4 (below median, many teams cluster high)
* Gross: 141,240 × 3.85 × 0.4 ≈ 217,600
* Net: ~167,000

Default pick: **balanced**. Robust across Speed realisations.

### Sensitivity caveat

Outcome is highly non robust to actual Speed multiplier. Scan Discord / Reddit / community channels a few hours before lockout to refine the `x_T` prior based on where other players are clustering.

## Action items for Claude Code session

### Algorithmic

1. Pull R1 + R2 data zips into `C:\Users\rsl25\Projects\IMC Trading challenge\data\`.
2. Build `backtest.py` wrapper around Jmerle's backtester (check github.com/jmerle for P4 update).
3. Script to measure capacity saturation: `% of timesteps at |pos| = limit` per product from R1.
4. Build a synthetic "extra quotes" injector that samples from the empirical price/volume distribution and inserts 25% more quotes at intermediate levels.
5. Run R1 algo on (native R2) vs (R2 + injected quotes). Compute V = ΔPnL.
6. Decide MAF bid: target just above the assumed median (2.5k to 4k as starting guess), capped at V.
7. Refinement pass on the algo itself:
   * EMA vs microprice vs raw mid for volatile product.
   * OBI tilt on volatile product.
   * Inventory skew on stable product.
   * Fill asymmetry diagnostics.

### Manual

8. Implement optimisation function:

```python
import numpy as np
from scipy.optimize import minimize

def pnl(alloc, T_mult):
    x_R, x_S, x_T = alloc
    R = 200_000 * np.log(1 + x_R) / np.log(101)
    S = 0.07 * x_S
    cost = 500 * (x_R + x_S + x_T)
    return -(R * S * T_mult - cost)  # negative for minimisation

def optimal_allocation(T_mult_assumption):
    result = minimize(
        pnl,
        x0=[20, 45, 35],
        args=(T_mult_assumption,),
        bounds=[(0, 100)] * 3,
        constraints={'type': 'ineq', 'fun': lambda a: 100 - sum(a)}
    )
    return result.x, -result.fun
```

9. Produce a sensitivity table: optimal (x_R, x_S, x_T) and net PnL for Speed multipliers in {0.1, 0.3, 0.5, 0.7, 0.9}.
10. Monitor community signals on Speed clustering and update `x_T` before lockout.

### Decision log

Track decisions in `decisions.md` for post round review:

* MAF bid submitted: ___
* V estimate used: ___
* Median prior used: ___
* Manual allocation submitted: (x_R, x_S, x_T) = ___
* Speed multiplier assumed: ___
* R1 closing PnL: ___
* Threshold gap before R2: ___

## Open questions

* Is the trades data counterparty tagged in P4? (Would enable flow following à la Olivia in P3.)
* Is there a Phase 2 reset mechanic beyond the leaderboard? (Spec says "leaderboard resets for Phase 2" but unclear if qualifying carries forward.)
* Has jmerle updated the open source backtester for Prosperity 4?

## References

* Prosperity 3 writeups with R2 basket arbitrage context (not directly applicable but good for general P4 infrastructure):
  * github.com/TimoDiehm/imc-prosperity-3
  * github.com/chrispyroberts/imc-prosperity-3
  * github.com/Sylvain-Topeza/imc-prosperity-3
* jmerle's backtester: github.com/jmerle/imc-prosperity-3-backtester
