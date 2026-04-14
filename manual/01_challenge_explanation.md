# IMC Prosperity 4 — Round 1 Manual Challenge: "An Intarian Welcome"

## Overview

This is the **manual trading challenge** for Round 1 of IMC Prosperity 4. You are given two **stale order books** (frozen snapshots) — one for **Dryland Flax** and one for **Ember Mushroom**. You must submit **one limit order per product** (choosing Buy or Sell, a price, and a quantity) to maximize your profit.

This challenge is completely separate from the algorithmic trading part of the round.

---

## Key Terminology

| Term | Meaning |
|------|---------|
| **Order Book** | A list of all outstanding buy (bid) and sell (ask) orders for a product |
| **Bid** | An order to **buy** at a specified price |
| **Ask** | An order to **sell** at a specified price |
| **Clearing Price** | The single price at which the auction executes all trades |
| **Limit Order** | An order specifying both a **price** and a **quantity** |
| **XIRECs** | The in-game currency of Prosperity 4 |

---

## The Two Order Books

### Dryland Flax

**Guaranteed buyback price: 30 XIRECs/unit | No trading fees**

| Bids (Buyers) |       | Asks (Sellers) |        |
|:--------------|:------|:---------------|:-------|
| Volume        | Price | Price          | Volume |
| 30,000        | 30    | 28             | 40,000 |
| 5,000         | 29    | 31             | 20,000 |
| 12,000        | 28    | 32             | 20,000 |
| 28,000        | 27    | 33             | 30,000 |

### Ember Mushroom

**Guaranteed buyback price: 20 XIRECs/unit | Fee: 0.10 XIRECs/unit (0.05 buy + 0.05 sell)**

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

---

## Auction Rules (How the Clearing Price Works)

This is **not** a continuous exchange where your order sweeps through multiple price levels. It is a **call auction** that works as follows:

### Step 1 — A Single Clearing Price is Chosen

The exchange picks the **one price** $P^*$ that:

1. **Maximizes total traded volume**, defined as:

$$
V(P) = \min\!\Big(\sum_{\text{bids} \geq P} \text{qty},\;\sum_{\text{asks} \leq P} \text{qty}\Big)
$$

2. If two prices tie on volume, the **higher price** wins.

### Step 2 — Execution at the Clearing Price

- Every bid with price $\geq P^*$ is eligible to buy.
- Every ask with price $\leq P^*$ is eligible to sell.
- **All trades happen at $P^*$** — not at individual order prices.

### Step 3 — Allocation (Who Gets Filled?)

If there are more eligible bids than asks (or vice versa), orders are allocated by:

1. **Price priority** — higher-priced bids fill before lower-priced bids.
2. **Time priority** — among bids at the same price, earlier orders fill first.

**You submit last**, so at any price level you join, you are **last in line**.

---

## What Happens After the Auction

There is **no continuous trading** for these products. Instead, the **Merchant Guild** automatically buys back any inventory you acquired:

- **Dryland Flax**: bought back at **30 XIRECs/unit**, no fees
- **Ember Mushroom**: bought back at **20 XIRECs/unit**, with a fee of **0.10 XIRECs/unit**

Your profit per unit is therefore:

$$
\pi = \text{Buyback Price} - P^* - \text{Fees}
$$

---

## Can You Sell? (Yes — But It's a Trap)

Despite the wiki saying *"Choose a **bid** price and quantity"*, the actual interface **does** let you choose between **Buy** and **Sell**. So selling (going short) is technically possible. Here's how it would work and why it doesn't help.

### How Selling Works

If you place a **sell** (ask) order and it executes, you end up with a **negative position** (short). The Merchant Guild then settles this by forcing you to **buy back** at the guaranteed buyback price. Your profit from selling would be:

$$\pi_{\text{sell}} = P^* - \text{Buyback Price} - \text{Fees}$$

This is only profitable if the clearing price $P^*$ lands **above** the buyback price.

### Why It Fails for Dryland Flax

The buyback price is **30**. The highest existing bid on the book is **30** (with 30k volume). There are **zero bids above 30**. No matter what sell order you place, $P^*$ can never exceed 30:

$$\pi_{\text{sell}} = 30 - 30 = 0 \quad \text{(break-even at best)}$$

### Why It Fails for Ember Mushroom

The buyback price is **20**. The highest existing bid is **20** (with 43k volume). Nothing above 20 exists. So at best:

$$\pi_{\text{sell}} = 20 - 20 - 0.10 = -0.10 \quad \text{(guaranteed loss)}$$

### Conclusion

The order books are structured so the clearing price can **never exceed** the buyback price. Selling always results in zero profit or a loss. **The optimal strategy is to Buy for both products.**

---

## The Core Strategic Problem

Your goal is to find the **bid price** $P_{\text{bid}}$ and **quantity** $Q$ for each product such that:

1. Your order shifts the clearing price to $P^*$ (which may differ from the original clearing price without your order).
2. You actually get filled — after all higher-priority orders are allocated.
3. Your per-unit profit $({\text{Buyback}} - P^* - \text{Fees})$ times the quantity you receive is maximized.

The tension: **bidding higher** increases your chances of being filled (and may increase total volume), but **reduces your profit per unit**. Bidding too low means you get nothing.

---

## Summary of What to Submit

For each product, enter:

- **Buy or Sell** (dropdown — but as shown above, Buy is always optimal)
- A **price** (integer, in XIRECs)
- A **quantity** (number of units)

Then click Submit. You can re-submit until the round ends — only your **last submission** counts.
