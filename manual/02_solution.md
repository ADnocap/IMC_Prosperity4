# Solution: "An Intarian Welcome" — Optimal Bid Strategy

## Method

For each candidate bid price $P_{\text{bid}}$ and quantity $Q$, we:

1. Add our order to the book and compute the new clearing price $P^*$.
2. Determine how many units we receive after allocation.
3. Calculate total profit $= \text{units} \times (\text{Buyback} - P^* - \text{Fees})$.

**Key insight**: By bidding 1 unit below the volume that would create a tie at a higher price, we can keep the clearing price low while getting price priority for a large fill.

---

## Dryland Flax Analysis

**Buyback = 30 | Fees = 0**

### Order Book

| Bids (Buyers) |       | Asks (Sellers) |        |
|:--------------|:------|:---------------|:-------|
| Volume        | Price | Price          | Volume |
| 30,000        | 30    | 28             | 40,000 |
| 5,000         | 29    | 31             | 20,000 |
| 12,000        | 28    | 32             | 20,000 |
| 28,000        | 27    | 33             | 30,000 |

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

#### Bid at 29, qty 5,000+

- $V(29) = \min(35k + Q,\; 40k) = 40k$ (ties with $V(28) = 40k$).
- Tie-break → higher price → $P^* = 29$.
- Allocation: 30k @30, then 5k @29 (existing, time priority) = 35k filled. Remaining: 5k → we get 5,000.

$$\text{Profit} = 5{,}000 \times (30 - 29) = \textbf{5,000 XIRECs}$$

#### Bid at 30, qty 9,999 ⭐

By bidding at **30** we jump above the 5k @29 bids (price priority). The critical trick: **9,999 not 10,000**.

With our order:

| Price | Cum. Bids $\geq P$ | Cum. Asks $\leq P$ | $V(P)$ |
|:-----:|:-------------------:|:-------------------:|:------:|
| 28    | 56,999              | 40,000              | 40,000 |
| 29    | 44,999              | 40,000              | 40,000 |
| 30    | 39,999              | 40,000              | 39,999 |

$V(28) = V(29) = 40{,}000 > V(30) = 39{,}999$ → no tie at 30. Tie between 28 and 29 → $P^* = 29$.

Allocation at $P^* = 29$:
1. Existing bids @30: 30,000
2. **Our bid @30: 9,999** (price priority over @29 bids)
3. Existing @29: 1 unit (40k - 39,999)

We get **9,999 units** at clearing price 29.

$$\boxed{\text{Profit} = 9{,}999 \times (30 - 29) = \textbf{9,999 XIRECs}}$$

**Why 9,999 not 10,000**: At 10k, CumBid $\geq 30$ = 40k = CumAsk $\leq 30$, so $V(30) = 40k$ ties with $V(28)$ and $V(29)$. Tie-break → highest price → $P^* = 30$. Profit per unit = $30 - 30 = 0$.

#### Bid at 30, qty 10,000+ (THE TRAP)

- $V(30) = \min(30k + Q,\; 40k) = 40k$, tying $V(28)$ and $V(29)$.
- Tie-break → highest → $P^* = 30$. Profit/unit $= 0$.

$$\text{Profit} = 0$$

### Dryland Flax — Optimal Order

| | |
|---|---|
| **Bid Price** | **30** |
| **Quantity** | **9,999** |
| **Clearing Price** | 29 |
| **Units Received** | 9,999 |
| **Profit** | **9,999 XIRECs** |

---

## Ember Mushroom Analysis

**Buyback = 20 | Fees = 0.10 per unit**

### Order Book

| Bids (Buyers) |       | Asks (Sellers) |        |
|:--------------|:------|:---------------|:-------|
| Volume        | Price | Price          | Volume |
| 43,000        | 20    | 12             | 20,000 |
| 17,000        | 19    | 13             | 25,000 |
| 6,000         | 18    | 14             | 35,000 |
| 5,000         | 17    | 15             | 6,000  |
| 10,000        | 16    | 16             | 5,000  |
| 5,000         | 15    | 17             | 0      |
| 10,000        | 14    | 18             | 10,000 |
| 7,000         | 13    | 19             | 12,000 |

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

### Scenario Analysis

#### Bid at 16, qty 10,000

- $V(16) = \min(81k + 10k,\; 91k) = 91k$ → new max. $P^* = 16$.
- Allocation: bids >16 total 71k. Existing @16 = 10k → 81k. We get $91k - 81k = 10{,}000$.

$$\text{Profit} = 10{,}000 \times (20 - 16 - 0.10) = 10{,}000 \times 3.90 = \textbf{39,000}$$

#### Bid at 17, qty 20,000 (naive approach)

- $V(17) = \min(71k + 20k,\; 91k) = 91k$, ties with $V(16) = 91k$.
- Tie-break → $P^* = 17$.
- We get $91k - 71k = 20{,}000$ at price 17.

$$\text{Profit} = 20{,}000 \times (20 - 17 - 0.10) = 20{,}000 \times 2.90 = \textbf{58,000}$$

#### Bid at 17, qty 19,999 ⭐ (the N-1 trick)

With our order:

| Price | Cum. Bids $\geq P$ | Cum. Asks $\leq P$ | $V(P)$ |
|:-----:|:-------------------:|:-------------------:|:------:|
| 15    | 105,999             | 86,000              | 86,000 |
| 16    | 100,999             | 91,000              | **91,000** |
| 17    | 90,999              | 91,000              | 90,999 |
| 18    | 66,000              | 101,000             | 66,000 |

$V(16) = 91{,}000 > V(17) = 90{,}999$ → **no tie**. $P^* = 16$.

Allocation at $P^* = 16$:
1. @20: 43,000 → 43,000
2. @19: 17,000 → 60,000
3. @18: 6,000 → 66,000
4. @17 existing: 5,000 → 71,000
5. **@17 us: 19,999** → 90,999
6. @16 existing: 1 unit (to reach 91,000)

We get **19,999 units** at clearing price **16**.

$$\boxed{\text{Profit} = 19{,}999 \times (20 - 16 - 0.10) = 19{,}999 \times 3.90 = \textbf{77,996.10 XIRECs}}$$

**Why 19,999 not 20,000**: At 20k, CumBid $\geq 17$ = 91k = CumAsk $\leq 17$, so $V(17) = 91k$ ties with $V(16)$. Tie-break → $P^* = 17$. Margin drops from 3.90 to 2.90, losing ~19k profit.

#### Bid at 18, qty 35,000

- $V(18) = \min(66k + 35k,\; 101k) = 101k$ → new max. $P^* = 18$.
- We get $101k - 66k = 35{,}000$ at price 18.

$$\text{Profit} = 35{,}000 \times (20 - 18 - 0.10) = 35{,}000 \times 1.90 = \textbf{66,500}$$

### Profit Comparison

| Bid Price | Clearing $P^*$ | Quantity | Units Received | Profit/Unit | **Total Profit** |
|:---------:|:--------------:|:--------:|:--------------:|:-----------:|:----------------:|
| 15        | 15             | any      | 0              | —           | 0                |
| 16        | 16             | 10,000   | 10,000         | 3.90        | 39,000           |
| 17 (naive)| 17             | 20,000   | 20,000         | 2.90        | 58,000           |
| **17 (N-1)** | **16**      | **19,999** | **19,999**   | **3.90**    | **77,996.10** ⭐  |
| 18        | 18             | 35,000   | 35,000         | 1.90        | 66,500           |
| 19        | 19             | 53,000   | 53,000         | 0.90        | 47,700           |
| 20        | 20             | 70,000   | 70,000         | −0.10       | −7,000           |

### Ember Mushroom — Optimal Order

| | |
|---|---|
| **Bid Price** | **17** |
| **Quantity** | **19,999** |
| **Clearing Price** | 16 |
| **Units Received** | 19,999 |
| **Profit** | **77,996.10 XIRECs** |

---

## Final Submission

| Product | Bid Price | Quantity | Clearing Price | Expected Profit |
|:--------|:---------:|:--------:|:--------------:|:---------------:|
| Dryland Flax | **30** | **9,999** | 29 | **9,999.00** |
| Ember Mushroom | **17** | **19,999** | 16 | **77,996.10** |
| | | | **Total** | **87,995.10 XIRECs** |

---

## Intuition Summary

The key trade-off at each price level is:

$$\text{Total Profit}(P) = \underbrace{\text{Units received}(P)}_{\text{increases with } P} \;\times\; \underbrace{(\text{Buyback} - P^* - \text{Fees})}_{\text{decreases with } P}$$

The critical optimization is the **N-1 trick**: when bidding at price $P$ with quantity $Q$ would create a tie between $V(P)$ and $V(P-1)$ (pushing $P^*$ up via tie-break), bidding $Q-1$ units instead breaks the tie in your favor, keeping $P^*$ one level lower. You sacrifice 1 unit of fill but preserve a much higher per-unit margin.

- **Dryland Flax**: Bid at 30 for price priority over @29 bids, but 9,999 qty to avoid pushing clearing to 30.
- **Ember Mushroom**: Bid at 17 for price priority over @16 bids, but 19,999 qty to avoid tying at 17 — clearing stays at 16 with margin of 3.90 instead of 2.90.
