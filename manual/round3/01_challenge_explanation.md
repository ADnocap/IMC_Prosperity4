# IMC Prosperity 4 — Round 3 Manual Challenge: "The Celestial Gardeners' Guild"

## Overview

Round 3 takes place on **Solvenar**, the kickoff of the *Great Orbital Ascension Trials* (GOAT). All teams start GOAT with **zero PnL** (leaderboard reset).

The manual is a **two-stage sealed-bid auction** against counterparties ("Gardeners") who each hold one unit of *Ornamental Bio-Pods*. Each Gardener has a private **reserve price** drawn from a uniform distribution on a 5-grid between **670** and **920**. You submit **two bids**; acquired Bio-Pods auto-settle the next day at the fair price **920**.

This is a classic shading game with a twist: the **second bid is penalized if it falls below the average of all players' second bids**. That couples your optimal bid to what the rest of the field does.

---

## Key Terminology

| Term                | Meaning                                                                |
| ------------------- | ---------------------------------------------------------------------- |
| **Reserve price r** | The minimum price at which a given counterparty is willing to sell     |
| **First bid `b1`**  | Your "cheap" bid — trades only with counterparties where `b1 > r`      |
| **Second bid `b2`** | Your "generous" bid — trades with leftover counterparties where `b2 > r` |
| **`avg_b2`**        | Mean of all participating teams' second bids (unknown to us)           |
| **Buyback = 920**   | Fixed price at which acquired Bio-Pods settle next day                 |
| **XIRECs**          | In-game currency                                                       |

---

## The Counterparty Population

- Each counterparty has a reserve price drawn **uniformly** from the 5-grid:
  `{670, 675, 680, …, 915, 920}` — **51 possible values**.
- Equivalently: `P(r = 670 + 5k) = 1/51` for `k ∈ {0, 1, …, 50}`.
- A counterparty with `r = 920` never trades at any bid ≤ 920 (strict inequality), so there are effectively **50 trade-eligible reserves** for any bid in range.

---

## Auction Rules

For each counterparty with reserve `r`, given your bids `b1, b2` and the field's `avg_b2`:

1. **First bid wins if `b1 > r`** → you trade at price `b1`, gross profit per unit = `920 − b1`.
2. **Else, if `b2 > r`** (i.e., `b1 ≤ r < b2`) → you trade at price `b2`, with PnL multiplier:
   - If `b2 ≥ avg_b2`: **multiplier = 1** (no penalty).
   - If `b2 < avg_b2`: **multiplier = `((920 − avg_b2) / (920 − b2))^3`** (cubic penalty).
3. **Else** (`r ≥ b2`): **no trade**.

The penalty only applies to trades captured by the second bid. First-bid trades never get penalized.

### Why the penalty is a cubic

Writing `δ = avg_b2 − b2` (how much we shade below the crowd) and `Δ = 920 − b2` (our per-unit margin at the second bid):

```
multiplier = (1 − δ/Δ)^3
```

- Small shading (`δ/Δ ≈ 0`): multiplier ≈ `1 − 3δ/Δ` → roughly linear.
- Big shading (`δ/Δ → 1`): multiplier → 0 → trade value collapses.

The cube means shading by ~1/3 of your margin already costs ~70% of your second-bid PnL. You either bid **at or above** `avg_b2`, or accept a sharp haircut.

---

## The Core Trade-off

Your profit per counterparty (averaged over the reserve distribution) is:

```
E[profit] = P(r < b1) · (920 − b1)
          + P(b1 ≤ r < b2) · (920 − b2) · multiplier(b2, avg_b2)
```

- **Raise `b1`** → capture more counterparties at the cheap bid, but thinner margin.
- **Raise `b2`** → capture more extra counterparties, but thinner margin + need to stay above the crowd to avoid penalty.
- **Lower `b2`** → fat margin if no penalty, but if the field's `avg_b2` is higher, the cubic punishes you.

Because reserves are strict-greater-than, **integer bids just above a grid point dominate grid-aligned bids** (same count of eligible counterparties, one fewer XIREC paid per unit). Example: `b1 = 751` captures the same 17 reserves (`{670, 675, …, 750}`) as `b1 = 755`, but pays 4 XIRECs less per unit. The analog of the R1 **N-1 trick**.

---

## What the Field Does — Why Game Theory Matters

We don't observe `avg_b2`. Every team's optimal `b2` depends on a guess of every other team's `b2`. Like P2 R4 and P3 R4 (structurally identical "second-bid beauty-contest" games), the equilibrium depends on how the population splits between:

- **Solver users** who converge to the same analytical optimum → tight cluster.
- **"Safe" bidders** who pick round focal points close to buyback (e.g. 900, 895, 850) → push `avg_b2` up.
- **Under-shaders** who bid barely above the reserve midpoint → pull `avg_b2` down.
- **Textbook/"equal-split" bidders** who ignore the coupling.

If the field is **tight around the analytical optimum**, everyone plays `b2 ≈ 836`, `avg_b2 ≈ 836`, no one gets penalized, symmetric Nash.

If the field has a **long right tail** (a non-trivial share bidding 900+), `avg_b2` drifts into the 850–880 range, and anyone still playing the pure analytical optimum gets a huge cubic haircut.

The solver (`verify.py`) explores both regimes and recommends a robust bid pair.

---

## Submission

1. Go to the Manual Challenge Overview on the portal.
2. Enter your **two bids** (integers, in XIRECs).
3. Click Submit. Resubmit freely until round close — only the **last submission** locks in.

Everything you acquire is auto-sold at 920 the next day; no algorithmic follow-through required.
