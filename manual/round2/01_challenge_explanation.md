# IMC Prosperity 4 — Round 2 Challenges: "Growing Your Outpost"

## Overview

Round 2 is the final trading round on Intara. There are **no new products** — we keep trading `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT` with the same position limits. The novelty is two new game-theoretic mechanics:

1. **Algorithmic**: a Market Access Fee (MAF) sealed-bid auction for +25% quote volume
2. **Manual**: allocate an investment budget across three growth pillars (Research × Scale × Speed)

The threshold to unlock the next round is a net PnL of **≥ 200,000 XIRECs** across R1+R2.

---

## 1. Algorithmic challenge — "Limited Market Access"

### Products & limits (unchanged from R1)

| Product | Position limit |
|---------|---------------:|
| `ASH_COATED_OSMIUM`    | 80 |
| `INTARIAN_PEPPER_ROOT` | 80 |

### Market Access Fee (MAF)

- **What you get**: if your bid is accepted, during the final R2 simulation you see order books with **+25% volume** vs the default book. The extra quotes are interleaved into the existing price distribution (example below).
- **Who wins**: the **top 50% of all submitted bids** (strictly above the median) are accepted. Ties on the median side lose — see IMC's example: bids `[10, 20, 15, 19, 21, 34]` → median 19.5 → accepted `[20, 21, 34]`.
- **Cost**: a **one-time fee** equal to your bid, subtracted from your R2 PnL only if you win. Losers pay nothing.
- **Blind auction**: bids are only compared at the final sim. In testing you cannot see whether your bid would win — IMC serves all testers a **randomized 80% subset** of the full quote set.
- **Scope**: MAF is R2-only. `bid()` is ignored in R1 and R3–R5.

### Python API

Add a `bid()` method to the `Trader` class returning an int:

```python
class Trader:
    def bid(self):
        return 15  # XIRECs

    def run(self, state: TradingState):
        ...
```

See `traders/round2/a.py` — currently seeded with `MAF_BID = 0` as a placeholder.

### Example order book with extra access

No extra access:
```
(ask, 10, $9)
(ask, 10, $7)
(bid, 10, $5)
(bid,  5, $4)
```

With extra access (+25%):
```
(ask, 10, $9)
(ask,  5, $8)    <- new level slotted into the distribution
(ask, 10, $7)
(bid, 10, $5)
(bid,  5, $4)
```

### Game theory

To win you only need to be **in the top 50%**, not the highest. Bidding high guarantees a seat but over-pays; bidding low saves XIRECs but risks the median. Sensible bid = (estimated profit uplift from +25% access) × shading factor. Without knowing N or the bid distribution across teams, shade conservatively on first submission and tune after observing the R1 leaderboard PnL distribution.

### Tuning workflow

1. Establish a baseline R2 PnL in MC with default liquidity (`prosperity4mcbt traders/round2/a.py --heavy`).
2. Estimate uplift from the extra 25% quote volume. In the MC sim this can be approximated by scaling the quote-generator bot volumes by 1.25 locally — **flag: the Rust sim does not currently model this, so we'd need to add a `--extra-flow` mode or hand-edit the sim parameters.**
3. Set `MAF_BID` to a fraction of that uplift (start ~30–50% as a shade).
4. Revisit after seeing competitive signals (Discord chatter, own-team leaderboard position).

---

## 2. Manual challenge — "Invest & Expand"

> ✅ **Budget confirmed: 50,000 XIRECs** (verified from portal UI on 2026-04-19). Ambiguity resolved.

### Structure

Allocate % across three pillars — total ≤ 100%:
- **Research** — trading edge
- **Scale**    — market breadth
- **Speed**    — hit rate

**PnL = (Research × Scale × Speed) − Budget_Used**

### Pillar formulas (x ∈ [0, 100] is the % allocated to each pillar)

- **Research(x)** — logarithmic, 0 → 200,000.
  `research(x) = 200_000 * ln(1 + x) / ln(1 + 100)`
- **Scale(x)** — linear, 0 → 7.
  `scale(x) = 7 * x / 100`
- **Speed** — rank-based multiplier ∈ [0.1, 0.9], linearly interpolated by rank across all teams (ties share rank). Highest investment gets 0.9, lowest gets 0.1.

### Solver notes

- Research has diminishing returns (log). Scale is linear. Speed is rank-based — you only need to out-invest *some* teams, not all.
- Because PnL is a **product** of the three, putting 0 into any pillar collapses gross PnL to 0. Every team should allocate > 0 to every pillar.
- Ignoring Speed competition (i.e. assuming a fixed multiplier `s`), the Lagrangian over `r + sc + sp ≤ 100` with objective `200000 * ln(1+r)/ln(101) * (7*sc/100) * s` gives:
  - Interior optimum has `∂/∂r = ∂/∂sc` which from the shapes favors heavy Research early (log elbow is steep near 0), then meaningful Scale, then just enough Speed to rank well.
  - Because Research saturates fast (most of the log value is captured by x ≈ 30–50), the extra percentage above that is better spent on Scale or Speed.
- Speed is a game-theoretic decision. Observation from P3 equivalents: most teams under-allocate to the ranked pillar. A moderate allocation (e.g. 20–30%) typically lands comfortably in the top half.

A sketch starting point to refine with `verify.py`:
- Research 50%, Scale 25%, Speed 25%
- Check gross: 200000 * ln(51)/ln(101) * 7*0.25 * 0.9 = 200000 * 0.852 * 1.75 * 0.9 ≈ 268,380
- Minus Budget_Used: see the "budget ambiguity" note above.

A `verify.py` solver in this folder should:
1. Sweep `(r, sc, sp)` on a grid subject to `r + sc + sp ≤ 100`
2. For each combo, compute gross PnL under a few **assumed Speed multipliers** (e.g. 0.5, 0.7, 0.9) to visualize robustness
3. Pick the allocation that dominates under reasonable Speed assumptions

### Submission

Enter percentages in the Manual Challenge Overview window on the portal and click Submit. Resubmit as often as you want; only the **last** distribution is locked in at round close.
