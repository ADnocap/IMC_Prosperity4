# IMC Prosperity 4 — Round 2 Challenges: "Growing Your Outpost"

## Manual challenge — "Invest & Expand"

> **Budget: 50,000 XIRECs**

### Structure

Allocate % across three pillars — total ≤ 100%:

- **Research** — trading edge
- **Scale** — market breadth
- **Speed** — hit rate

**PnL = (Research × Scale × Speed) − Budget_Used**

### Pillar formulas (x ∈ [0, 100] is the % allocated to each pillar)

- **Research(x)** — logarithmic, 0 → 200,000.
  `research(x) = 200_000 * ln(1 + x) / ln(1 + 100)`
- **Scale(x)** — linear, 0 → 7.
  `scale(x) = 7 * x / 100`
- **Speed** — rank-based multiplier ∈ [0.1, 0.9], linearly interpolated by rank across all teams (ties share rank). Highest investment gets 0.9, lowest gets 0.1.

### Solver notes

- Research has diminishing returns (log). Scale is linear. Speed is rank-based — you only need to out-invest _some_ teams, not all.
- Because PnL is a **product** of the three, putting 0 into any pillar collapses gross PnL to 0. Every team should allocate > 0 to every pillar.
- Ignoring Speed competition (i.e. assuming a fixed multiplier `s`), the Lagrangian over `r + sc + sp ≤ 100` with objective `200000 * ln(1+r)/ln(101) * (7*sc/100) * s` gives:
  - Interior optimum has `∂/∂r = ∂/∂sc` which from the shapes favors heavy Research early (log elbow is steep near 0), then meaningful Scale, then just enough Speed to rank well.
  - Because Research saturates fast (most of the log value is captured by x ≈ 30–50), the extra percentage above that is better spent on Scale or Speed.
- Speed is a game-theoretic decision. Observation from P3 equivalents: most teams under-allocate to the ranked pillar. A moderate allocation (e.g. 20–30%) typically lands comfortably in the top half.

A sketch starting point to refine with `verify.py`:

- Research 50%, Scale 25%, Speed 25%
- Check gross: 200000 _ ln(51)/ln(101) _ 7*0.25 * 0.9 = 200000 _ 0.852 _ 1.75 \* 0.9 ≈ 268,380
- Minus Budget_Used: see the "budget ambiguity" note above.

A `verify.py` solver in this folder should:

1. Sweep `(r, sc, sp)` on a grid subject to `r + sc + sp ≤ 100`
2. For each combo, compute gross PnL under a few **assumed Speed multipliers** (e.g. 0.5, 0.7, 0.9) to visualize robustness
3. Pick the allocation that dominates under reasonable Speed assumptions

### Submission

Enter percentages in the Manual Challenge Overview window on the portal and click Submit. Resubmit as often as you want; only the **last** distribution is locked in at round close.
