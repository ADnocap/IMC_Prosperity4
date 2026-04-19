# R2 Manual — Invest & Expand: Solution

Solver: `manual/round2/verify.py`.  Budget: **50,000 XIRECs** (portal-confirmed).  Inputs: integer percentages; total `r + sc + sp ≤ 100`.

## Problem summary

- `Research(r)  = 200,000 · ln(1+r) / ln(101)`   — concave log, saturates fast
- `Scale(sc)    = 7 · sc / 100`                  — linear
- `Speed_mult(sp) ∈ [0.1, 0.9]`                  — rank-based across submitters, **ties share the best rank**
- `Net   = Research · Scale · Speed_mult − 500 · (r + sc + sp)`

## The Speed rank rule is the game

Per spec: *"equal investments share the same rank. [70, 70, 70, 50, 40, 40, 30] → ranks [1, 1, 1, 4, 5, 5, 7]"*. All three 70s get the top multiplier 0.9, not split.

**Implication**: if you match the top cluster exactly, you share their multiplier. Bidding *one higher* than a cluster is strictly worse — same multiplier (still rank 1), pays 500 extra XIRECs. The optimal strategy against a spike opponent distribution is **to tie it, not beat it**.

## Game-theoretic fixed point

### Iterated best response (with tie-aware multipliers)

We model opponents as a mixture of P3-Container-style behavioral classes (doc-sketch, textbook 33, speed-king 50, budget-saver 10, solver Gaussian μ=35, random/uniform) plus a "solver crowd" that converges to our current answer. Starting from `(16, 50, 34)`:

| Solver fraction | IBR fixed point |
|---|---|
| 10% | **(16, 50, 34)** |
| 20% | **(16, 50, 34)** |
| 30% | **(16, 50, 34)** |
| 50% | **(16, 50, 34)** |

Immediate convergence at every level. **`(16, 50, 34)` is a Nash equilibrium** — no unilateral deviation is profitable when other solvers pick it.

### Why sp=34 and not, say, 40?

- 34 is *exactly 1 above the textbook focal "33"*. Any team that does the Lagrangian analysis with a fixed Speed multiplier ends up with `r + sc ≈ 67` and `sp ≈ 33`. Going to 34 decisively beats that crowd for rank 1.
- Ties with any solver crowd at 34 still yield rank 1 (mult 0.9). No need to go higher.
- sp=50 (the "speed-is-king" focal) only helps if enough opponents cluster there. In a Behavioral mix, 10% do, so you'd be paying 16% extra budget for marginal rank improvement — negative EV.

## P3 historical context

Structurally identical challenges from P3:
- **R2 Containers**: pick 1–2 of 10, payoff scales *inversely* with how many teams chose the same one
- **R4 Suitcases**: same crowd-sensitivity structure

Known pattern across both: ~60–70% of teams clustered on the "obvious" focal points. Winners differentiated — either picking less popular high-mult options (Containers) or tying optimally (our case). This justifies the behavioral mixture used in the solver.

## Exhaustive search (post-fix)

- **Mean-maximizer** across 9 opponent scenarios: `(16, 50, 34)` — mean Net **259,467**
- **Max-min** (best worst-case): `(13, 38, 49)` — worst Net **168,919**

## Candidate table

| Allocation | worst | mean | Notes |
|---|---:|---:|---|
| **(16, 50, 34)** — Nash + mean-max | 99,447 | **259,467** | Ties textbook-33 + solvers, top-mult in 5/9 scenarios |
| (16, 49, 35) | 106,563 | 258,278 | 1% more speed costs 1k, gains tie with "35" solvers |
| (16, 48, 36) | 113,613 | 256,832 | Trades mean for worst |
| (16, 47, 37) | 120,514 | 255,100 | Best vs pure Behavioral mix |
| (15, 46, 39) | 133,611 | 250,784 | Balanced hedge |
| (14, 45, 41) | 145,087 | 244,975 | Aggressive-field hedge |
| (13, 38, 49) — max-min | **168,919** | 211,262 | Beats Gaussian(40) field |
| (17, 50, 33) — tie textbook | −6,160 | 221,518 | Collapses if solvers go to 34 |
| (50, 25, 25) — spec sketch | −20,182 | 76,621 | Strictly dominated |

## Recommendation

### Primary pick: `r = 16, sc = 50, sp = 34`

1. **Nash-equilibrium** under the full behavioral-mixture IBR.
2. **Mean-maximizer** across all 9 opponent scenarios.
3. Beats the textbook-33 cluster (worth ~20% of the field) decisively.
4. Ties with any other optimizer who reaches the same answer — no cost to share rank 1.

**Only risk**: opponents cluster at sp > 34 (e.g., a lot of "40+" believers). In that case we drop to a lower rank. But every scenario we tested where that happens, the alternative `(15, 46, 39)` gains only ~10–20k worst-case while losing ~8k mean.

### Conservative alternative: `r = 15, sc = 46, sp = 39`

Use if you see Discord/chat chatter suggesting the field is leaning toward sp=40+. Reasonable hedge with 134k worst-case vs 99k.

### Safety pick: `r = 13, sc = 38, sp = 49`

Only if you want a guaranteed floor — worst case 169k even against Gaussian(40) aggressive fields. Mean drops 48k vs primary.

## Why the previous recommendation `(16, 49, 35)` moved

In the first pass I had a bug in the spike-CDF that treated ties as half-weight (F(k)=0.5) instead of full rank-1 tie (F(k)=1.0). After the fix, the Nash equilibrium collapsed to exactly `(16, 50, 34)` — matching the textbook focal point is strictly better than beating it by 1%.

## Decision procedure

1. **Submit `(16, 50, 34)` immediately** as the default.
2. **Revisit after** Discord/leaderboard chatter reveals field tendency:
   - If "most teams going 40+": switch to `(15, 46, 39)`.
   - If "most teams going 25–33": hold or switch to `(18, 57, 25)` aggressive-Scale variant.
3. Resubmit is free — last submission locks in.
