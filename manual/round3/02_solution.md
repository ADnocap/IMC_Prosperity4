# R3 Manual — Celestial Gardeners' Guild: Solution

Solver: `manual/round3/verify.py`.
Reserves: uniform on `{670, 675, …, 920}` (51 values). Buyback: `920`. Bids: **integers**, `b1 < b2`.

All profits below are **per 51-reserve grid** (sum over one counterparty per reserve price). Total XIRECs scale linearly with the actual counterparty count `N`, but the ranking of bid pairs is `N`-invariant.

---

## 1. Integer "N−1 trick" beats 5-grid bids

Because reserves live on the 5-grid and the trade condition is **strict** (`b > r`):

| Bid       | Reserves captured                | Margin | Profit contribution |
| --------- | -------------------------------- | ------ | ------------------- |
| `b = 750` | `{670, …, 745}` = **16** reserves | 170    | 2,720               |
| `b = 751` | `{670, …, 750}` = **17** reserves | 169    | **2,873**           |
| `b = 755` | `{670, …, 750}` = **17** reserves | 165    | 2,805               |

**Bidding 1 above a grid point gets the same count as bidding ON the next grid point, at a better margin.** Use `b = 5k + 1` for `k ∈ {134, 135, …, 183}`. This is the R3 analog of the R1 "N−1 trick".

---

## 2. Unpenalized optimum (symmetric Nash)

Ignoring the penalty (i.e., assuming `b2 ≥ avg_b2`), profit per 51 reserves is:

```
Π(b1, b2) = #{r < b1} · (920 − b1)  +  #{b1 ≤ r < b2} · (920 − b2)
```

On the "integer just above a grid point" sub-lattice this reduces to:

```
Π(k, m) = k · (254 − 5k)  +  m · (254 − 5k − 5m)
```

where `k` = reserves captured by `b1`, `m` = reserves added by `b2`, `b1 = 666 + 5k`, `b2 = 666 + 5(k+m)`.

Stationary point: `k = m = 17` → **`b1 = 751`, `b2 = 836`**, profit **4,301** per 51.

```
Solver confirms (exhaustive grid search on integers):
  b1 = 751  (captures 17 reserves × margin 169 = 2,873)
  b2 = 836  (captures 17 reserves × margin  84 = 1,428)
  total: 4,301 / 51
```

### Why this is a symmetric Nash

If every team plays `b2 = 836`, then `avg_b2 = 836`, penalty = 1, profit = 4,301. A unilateral shade down (`b2 < 836`) triggers the cubic and loses money; a unilateral shade up (`b2 > 836`) drops per-unit margin with no offsetting capture bonus. **`(751, 836)` is the Pareto-best symmetric equilibrium**.

---

## 3. The coordination problem: multiple symmetric equilibria

Crucially, `(751, 836)` is **not the only** symmetric Nash. For ANY `b2* ∈ [836, 919]`:

- If everyone plays `b2 = b2*`, then `avg_b2 = b2*`, penalty = 1.
- Deviating to `b2 < b2*` triggers the cubic → loss.
- Deviating to `b2 > b2*` trades a fat margin for a thin one with no penalty benefit.

**Every one of these is a self-consistent Nash.** They are just Pareto-ranked: lower `b2*` gives higher payoff. The game has the same structure as a Schelling coordination game — the field can get stuck at a worse equilibrium simply because "everyone bids high to be safe."

### Best-response to field `avg_b2` (integer bids)

| Assumed `avg_b2` | `b1*`   | `b2*`   | Profit/51 |
| ---------------: | :-----: | :-----: | --------: |
| 750              | **751** | **836** | 4,301     |
| 800              | **751** | **836** | 4,301     |
| 836              | **751** | **836** | 4,301     |
| 850              | 756     | 851     | 4,263     |
| 870              | **766** | **871** | **4,109** |
| 880              | 771     | 881     | 3,987     |
| 900              | 781     | 900     | 3,657     |
| 910              | 786     | 910     | 3,456     |

Best response always puts `b2` at `avg_b2` exactly (tie case, penalty = 1) or `avg_b2 + 1`, and moves `b1` accordingly. Below `avg_b2 ≈ 836`, Nash is unchanged at `(751, 836)`.

---

## 4. Iterated best response with a behavioral crowd

Real teams will not all solve the game. Historical patterns from P2 R4 (turtles) and P3 R4 (suitcases), structurally identical crowd-dependent games, show:

- ~25–35% of teams land on or near the analytical optimum (solver users).
- ~25% bid "safely high" near the buyback (focal points at 900, 910).
- ~40–50% scatter between those two clusters.

Modelling: fraction `f` of the field plays our answer; `(1 − f)` sits at a fixed behavioral mean `avg_beh`.

```
Solver %      behavioral_avg      fixed-point (b1, b2)      field avg
  10%            820                 (751, 836)               821.6
  10%            870                 (766, 871)               870.1
  10%            900                 (781, 900)               900.0
  50%            820                 (751, 836)               828.0
  50%            870                 (766, 871)               870.5
  50%            900                 (781, 900)               900.0
 100%            any                 (751, 836)               836.0
```

- If the behavioral crowd is genuinely near the rational optimum (~820), **the field self-corrects to `(751, 836)`**.
- If there's a non-trivial mass sitting at high focal points (~870), the equilibrium drags up to **`(766, 871)` / `(771, 871)`** regardless of solver fraction.
- A "scared" field clustering near 900 locks the equilibrium at **`(781, 900)`**.

---

## 5. Robustness table

Per-51 profit for candidate bids across field-average scenarios:

| Candidate       | avg 800 | avg 820 | avg 836 | avg 850 | avg 870 | avg 880 | avg 890 | avg 900 | worst | mean  |
| --------------- | ------: | ------: | ------: | ------: | ------: | ------: | ------: | ------: | ----: | ----: |
| (751, 836)      |   4,301 |   4,301 |   4,301 |   3,699 |   3,174 |   3,027 |   2,938 |   2,892 | 2,892 | 3,579 |
| (751, 871)      |   4,049 |   4,049 |   4,049 |   4,049 |   4,049 |   3,513 |   3,143 |   2,953 | 2,953 | 3,732 |
| **(771, 871)**  |   4,109 |   4,109 |   4,109 |   4,109 |   4,109 |   3,662 |   3,354 |   3,196 | **3,196** | **3,845** |
| (776, 871)      |   4,099 |   4,099 |   4,099 |   4,099 |   4,099 |   3,695 |   3,413 |   3,266 | 3,266 | 3,848 |
| (751, 901)      |   3,443 |   3,443 |   3,443 |   3,443 |   3,443 |   3,443 |   3,443 |   3,443 | 3,443 | 3,443 |
| **(781, 900)**  |   3,657 |   3,657 |   3,657 |   3,657 |   3,657 |   3,657 |   3,657 |   3,657 | **3,657** | 3,657 |
| (850, 900)      |   2,720 |   2,720 |   2,720 |   2,720 |   2,720 |   2,720 |   2,720 |   2,720 | 2,720 | 2,720 |

Exhaustive over ALL integer `(b1, b2)` pairs:

- **Mean-maximizer: `(776, 871)`** — mean profit 3,848 / worst 3,266
- **Max-min: `(781, 900)`** — worst 3,657 / flat across all scenarios

---

## 6. Recommendation

### Primary pick: `b1 = 771`, `b2 = 871`

1. **Symmetric Nash** under any behavioral mix centred around `avg_b2 ≈ 870` (the realistic field expectation from P2/P3 analogs).
2. **Within 3 XIRECs of the exhaustive mean-maximizer** (`(776, 871)`), but lands on the cleaner "5k+1" capture boundary.
3. **Dominates `(751, 836)` across every scenario** with `avg_b2 ≥ 850` — and the penalty term makes the crossover pay off violently if the field drifts.
4. **Ties cleanly** with any other analyst who reaches `b2 = 871`.

Expected profit (per 51 reserves): **≈ 4,100** if field lands near `avg_b2 ≈ 870`. Between 3,196 (avg=900) and 4,109 (avg ≤ 870).

### Aggressive alternative: `b1 = 751`, `b2 = 836`

Play this only if you're confident the field will coordinate on the Pareto-best equilibrium (lots of solver users, few "safe" bidders). Upside **+200** per 51 vs primary; downside **−1200** per 51 if field drifts to `avg_b2 = 900`.

### Conservative / max-min: `b1 = 781`, `b2 = 900`

Flat **3,657** per 51 across all field scenarios. Pay ~450 per 51 in expectation vs primary for a guaranteed floor. Use if Discord/chat indicates the field is heavily clustered at `900+`.

---

## 7. Decision procedure

1. **Submit `(771, 871)` immediately** as the default — robust to a moderately-aggressive field and ties cleanly with other analysts.
2. **Before round close**, check Discord / leaderboard / chat for field tendency:
   - If chatter suggests **"everyone's going 900+"** → switch to **`(781, 900)`**.
   - If chatter suggests **most teams under 850** → switch to **`(751, 836)`** to capture the Pareto-best Nash.
3. Resubmission is free — last submission locks in.

---

## 8. Structural notes

- This problem is the direct successor to the **P2 R4 "Sea Shells / Turtles"** manual and the **P3 R4 "Residue Rocks"** manual — both were one- or two-bid auctions against uniform-reserve counterparties with a crowd-dependent penalty on the lower bid. In both seasons, the historical crowd average landed **20–60 XIRECs above the analytical optimum**, and winning strategies matched the field rather than trying to exploit the Pareto-best Nash.
- The cubic in the penalty is harsh: shading `(avg_b2 − b2) ≈ (920 − b2)/3` cuts the second-bid PnL by ~70%. **Do not try to out-shade the field** unless you know their distribution.
- Bids **must** be integers of the form `5k + 1` (or adjacent) to avoid wasting a free XIREC on margin. There is no reason to bid on the 5-grid itself.
