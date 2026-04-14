# Solution: "An Intarian Welcome" — Optimal Bid Strategy

## Method

For each candidate bid price $P_{\text{bid}}$, we:

1. Add our order to the book and compute the new clearing price $P^*$.
2. Determine how many units we receive after allocation.
3. Calculate total profit $= \text{units} \times (\text{Buyback} - P^* - \text{Fees})$.

---

## Dryland Flax Analysis

**Buyback = 30 | Fees = 0**

### Cumulative Supply & Demand (without our order)

| Price $P$ | Cum. Bids $\geq P$ | Cum. Asks $\leq P$ | Volume $V(P)$ |
|:---------:|:-------------------:|:-------------------:|:--------------:|
| 27        | 75,000              | 0                   | 0              |
| 28        | 47,000              | 40,000              | **40,000**     |
| 29        | 35,000              | 40,000              | 35,000         |
| 30        | 30,000              | 40,000              | 30,000         |
| 31        | 0                   | 60,000              | 0              |

**Without us, clearing price = 28** (max volume = 40,000).

### Scenario Analysis

#### Bid at 28

- Volume at $P=28$: $\min(47k + Q,\; 40k) = 40k$ — unchanged.
- Clearing stays at 28. Allocation at 28:
  - 30k (bids @30) + 5k (bids @29) + 5k of 12k (existing bids @28) = 40k filled.
  - We are **last in time** at price 28 → **we get 0 units**.

$$\boxed{\text{Profit} = 0}$$

#### Bid at 29 (quantity $Q \geq 5{,}000$)

- Volume at $P=29$: $\min(35k + Q,\; 40k)$. With $Q \geq 5k$, this equals $40{,}000$.
- Volume at $P=28$: still $40{,}000$.
- **Tie** at 40k between prices 28 and 29 → tie-break = **higher price** → $P^* = 29$.
- Allocation at 29:
  - 30k (bids @30) + 5k (existing bids @29) = 35k filled by higher-priority orders.
  - Remaining supply: $40k - 35k = 5{,}000$ units → **we get 5,000**.

$$\boxed{\text{Profit} = 5{,}000 \times (30 - 29) = \textbf{5,000 XIRECs}}$$

#### Bid at 30 (quantity $Q \geq 10{,}000$)

- Clearing shifts to $P^* = 30$ (same tie-break logic).
- Allocation: 30k existing bids @30 fill first. We get $\min(Q, 10k)$.
- But profit per unit = $30 - 30 = 0$.

$$\boxed{\text{Profit} = 0}$$

### Dryland Flax — Optimal Order

| | |
|---|---|
| **Bid Price** | **29** |
| **Quantity** | **5,000** (or more — you'll only receive 5k regardless) |
| **Clearing Price** | 29 |
| **Units Received** | 5,000 |
| **Profit** | **5,000 XIRECs** |

---

## Ember Mushroom Analysis

**Buyback = 20 | Fees = 0.10 per unit**

### Cumulative Supply & Demand (without our order)

| Price $P$ | Cum. Bids $\geq P$ | Cum. Asks $\leq P$ | Volume $V(P)$ |
|:---------:|:-------------------:|:-------------------:|:--------------:|
| 12        | 103,000             | 20,000              | 20,000         |
| 13        | 96,000              | 45,000              | 45,000         |
| 14        | 86,000              | 80,000              | 80,000         |
| 15        | 86,000              | 86,000              | **86,000**     |
| 16        | 81,000              | 91,000              | 81,000         |
| 17        | 71,000              | 91,000              | 71,000         |
| 18        | 66,000              | 101,000             | 66,000         |
| 19        | 60,000              | 113,000             | 60,000         |
| 20        | 43,000              | 113,000             | 43,000         |

**Without us, clearing price = 15** (max volume = 86,000).

Note: At $P = 15$, cumulative bids $\geq 15$ is calculated as:
$$43k + 17k + 6k + 5k + 10k + 5k = 86{,}000$$
which exactly matches cumulative asks $\leq 15 = 86{,}000$.

### Scenario Analysis

For each bid price, we compute the new clearing price and our fill.

#### Bid at 15

- Cum. bids $\geq 15$ becomes $86k + Q$, but cum. asks $\leq 15 = 86k$.
- $V(15) = \min(86k+Q,\; 86k) = 86k$ — no change.
- Allocation: bids with price $> 15$ total $81k$. Existing bids @15 = $5k$. Total = $86k$. **We get 0.**

$$\text{Profit} = 0$$

#### Bid at 16 (with $Q \geq 10{,}000$)

- $V(16) = \min(81k + Q,\; 91k)$. With $Q \geq 10k$: $V(16) = 91k > 86k$ → **new max**.
- $P^* = 16$.
- Allocation: bids with price $> 16$ total $71k$. Existing @16 = $10k$ → $81k$ filled. We get $91k - 81k = 10{,}000$.

$$\text{Profit} = 10{,}000 \times (20 - 16 - 0.10) = 10{,}000 \times 3.90 = \textbf{39,000}$$

#### Bid at 17 (with $Q \geq 20{,}000$)

- $V(17) = \min(71k + Q,\; 91k)$. With $Q \geq 20k$: $V(17) = 91k$.
- Tie between $P=16$ and $P=17$ at $91k$ → higher price → $P^* = 17$.
- Allocation: bids with price $> 17$ total $66k$. Existing @17 = $5k$ → $71k$. We get $91k - 71k = 20{,}000$.

$$\text{Profit} = 20{,}000 \times (20 - 17 - 0.10) = 20{,}000 \times 2.90 = \textbf{58,000}$$

#### Bid at 18 (with $Q \geq 35{,}000$) ⭐

- $V(18) = \min(66k + Q,\; 101k)$. With $Q \geq 35k$: $V(18) = 101k$ → **new max**.
- $P^* = 18$.
- Allocation: bids with price $> 18$ total $60k$. Existing @18 = $6k$ → $66k$. We get $101k - 66k = 35{,}000$.

$$\text{Profit} = 35{,}000 \times (20 - 18 - 0.10) = 35{,}000 \times 1.90 = \textbf{66,500}$$

#### Bid at 19 (with $Q \geq 53{,}000$)

- $V(19) = \min(60k + Q,\; 113k)$. With $Q \geq 53k$: $V(19) = 113k$ → **new max**.
- $P^* = 19$.
- Allocation: bids with price $> 19$ total $60k$. We get $113k - 60k = 53{,}000$.

$$\text{Profit} = 53{,}000 \times (20 - 19 - 0.10) = 53{,}000 \times 0.90 = \textbf{47,700}$$

#### Bid at 20

- $P^* = 20$. Profit per unit $= 20 - 20 - 0.10 = -0.10$.
- **Net loss.** Do not bid here.

### Profit Comparison

| Bid Price | Clearing $P^*$ | Min Quantity Needed | Units Received | Profit/Unit | **Total Profit** |
|:---------:|:--------------:|:-------------------:|:--------------:|:-----------:|:----------------:|
| 15        | 15             | any                 | 0              | —           | 0                |
| 16        | 16             | 10,000              | 10,000         | 3.90        | 39,000           |
| 17        | 17             | 20,000              | 20,000         | 2.90        | 58,000           |
| **18**    | **18**         | **35,000**          | **35,000**     | **1.90**    | **66,500** ⭐     |
| 19        | 19             | 53,000              | 53,000         | 0.90        | 47,700           |
| 20        | 20             | 70,000              | 70,000         | −0.10       | −7,000           |

### Ember Mushroom — Optimal Order

| | |
|---|---|
| **Bid Price** | **18** |
| **Quantity** | **35,000** (or more — you'll only receive 35k regardless) |
| **Clearing Price** | 18 |
| **Units Received** | 35,000 |
| **Profit** | **66,500 XIRECs** |

---

## Final Submission

| Product | Bid Price | Quantity | Expected Profit |
|:--------|:---------:|:--------:|:---------------:|
| Dryland Flax | **29** | **5,000+** | **5,000** |
| Ember Mushroom | **18** | **35,000+** | **66,500** |
| | | **Total** | **71,500 XIRECs** |

---

## Intuition Summary

The key trade-off at each price level is:

$$\text{Total Profit}(P) = \underbrace{\text{Units you receive}(P)}_{\text{increases with } P} \;\times\; \underbrace{(\text{Buyback} - P - \text{Fees})}_{\text{decreases with } P}$$

The optimal bid price balances getting **enough volume** against **preserving margin**. For Ember Mushroom, $P = 18$ hits the sweet spot where the volume jump (to 35k units) more than compensates for the reduced per-unit margin.
