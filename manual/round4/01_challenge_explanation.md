# VANILLA JUST ISN'T EXOTIC ENOUGH

**Tradable Good: AETHER CRYSTAL**

For this trading round only, you have the opportunity to trade the beautiful Aether Crystal, along with a collection of option contracts based on it. Each contract has a contract size of **3,000**. Some of these contracts are more "exotic" than others. With the right strategy, they offer the potential for substantial additional profit.

---

## OFFICIAL WIKI CLARIFICATION

> Please note that a 'week' here refers to 5 trading days and that the 'standard' number of trading days per year is 252. So "2 weeks" means 10 trading days, and "3 weeks" represents 15 trading days. Time stepping:
>
> ```python
> TRADING_DAYS_PER_YEAR = 252
> STEPS_PER_DAY = 4
> STEPS_PER_YEAR = TRADING_DAYS_PER_YEAR * STEPS_PER_DAY
> def steps_for_weeks(weeks): return int(round(weeks * 5 * STEPS_PER_DAY))
> ```
>
> So "T+14" / "T+21" in the on-screen table actually mean **2-week (40 steps)** and **3-week (60 steps)** maturities.
>
> The underlying `AETHER_CRYSTAL` is simulated as **GBM with zero risk-neutral drift** and **annualised volatility = 251%**, on a **discrete 4-steps-per-trading-day grid**.
> **The knock-out is monitored on this discrete grid only** — there is no continuous-monitoring barrier check.
>
> Final score = **average PnL across 100 simulations**, marked to expiry. Held to expiry; no intraday trading.
>
> The "Price" column displayed in the table is **purely cosmetic** ("investment cost") — it is unrelated to PnL and should be ignored.
>
> The challenge is **standalone** (no relationship to Round 1 manual or to the algo book).

**Sanity check**: σ_year = 2.51, T_3w = 15/252 ⇒ σ·√T = 2.51·√(15/252) = 0.6125. Backing this out from the AC_50_P / AC_50_C mid (12.025): the ATM Black-Scholes formula `mid = 50·(2N(σ√T/2) − 1)` gives σ·√T = 0.6125 too. ✅ Market quotes are consistent with the wiki's stated vol.

---

Carefully review the details of all available contracts to understand the full range of possibilities. You may trade as many contracts as you wish, limited only by the available volume per contract. Enter your orders (side and volume) directly in the table and remember to submit them. This is a one-time opportunity and does not affect your algorithmic trading activities. Enter your submission below and click Submit to confirm.

---

# AVAILABLE OPTION CONTRACTS

*Enter your orders directly in the table. Orders are limited by the available volume.*

## Underlying

| OPTION | EXPIRY | SIZE (Bid) | BID | ASK | SIZE (Ask) | BUY/SELL | VOLUME | PRICE |
|--------|--------|------------|-----|-----|------------|----------|--------|-------|
| **AC** | N/A | 200 | 49.975 | 50.025 | 200 | Choose | Volume | + 0.71 |

**Description:** Aether Crystals (**AETHER-CRYSTAL**) are precision-grown minerals formed under controlled electromagnetic conditions. Each crystal stores and stabilizes ambient energy fluctuations, making them invaluable in advanced communication systems, architectural harmonics, and precision instrumentation.

---

## Option Contracts

### AC_50_P
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 12 |
| Ask | 12.05 |
| Size (Ask) | 50 |
| Price | + 2.71 |

**Description:** AC_50_P is an Aether Crystal **PUT Option** contract with a **Strike Price of 50 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_50_C
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 12 |
| Ask | 12.05 |
| Size (Ask) | 50 |
| Price | - 0.45 |

**Description:** AC_50_C is an Aether Crystal **CALL Option** contract with a **Strike Price of 50 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_35_P
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 4.33 |
| Ask | 4.35 |
| Size (Ask) | 50 |
| Price | + 0.42 |

**Description:** AC_35_P is an Aether Crystal **PUT Option** contract with a **Strike Price of 35 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_40_P
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 6.5 |
| Ask | 6.55 |
| Size (Ask) | 50 |
| Price | 0.00 |

**Description:** AC_40_P is an Aether Crystal **PUT Option** contract with a **Strike Price of 40 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_45_P
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 9.05 |
| Ask | 9.1 |
| Size (Ask) | 50 |
| Price | - 0.48 |

**Description:** AC_45_P is an Aether Crystal **PUT Option** contract with a **Strike Price of 45 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_60_C
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 8.8 |
| Ask | 8.85 |
| Size (Ask) | 50 |
| Price | + 0.42 |

**Description:** AC_60_C is an Aether Crystal **CALL Option** contract with a **Strike Price of 60 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_50_P_2
| Field | Value |
|-------|-------|
| Expiry | T + 14 |
| Size (Bid) | 50 |
| Bid | 9.7 |
| Ask | 9.75 |
| Size (Ask) | 50 |
| Price | + 0.71 |

**Description:** AC_50_P_2 is an Aether Crystal **PUT Option** contract with a **Strike Price of 50 XIRECs** and a **Time To Expiry of 14 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_50_C_2
| Field | Value |
|-------|-------|
| Expiry | T + 14 |
| Size (Bid) | 50 |
| Bid | 9.7 |
| Ask | 9.75 |
| Size (Ask) | 50 |
| Price | + 0.71 |

**Description:** AC_50_C_2 is an Aether Crystal **CALL Option** contract with a **Strike Price of 50 XIRECs** and a **Time To Expiry of 14 Solvenarian Days** (starting from Round 1, on Intara).

---

### AC_50_CO (Chooser Option)
| Field | Value |
|-------|-------|
| Expiry | T + 14/21 |
| Size (Bid) | 50 |
| Bid | 22.2 |
| Ask | 22.3 |
| Size (Ask) | 50 |
| Price | + 0.71 |

**Description:** AC_50_CO is an Aether Crystal **CHOOSER Option** contract with a **Strike Price of 50 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara). After 14 Solvenarian Days, the buyer chooses the side (PUT or CALL). At that point, the contract automatically converts to the side that is "in the money". After the remaining 7 Solvenarian Days, the contract expires like a standard PUT or CALL option.

---

### AC_40_BP (Binary Put)
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 50 |
| Bid | 5 |
| Ask | 5.1 |
| Size (Ask) | 50 |
| Price | + 0.71 |

**Description:** AC_40_BP is an Aether Crystal **BINARY PUT Option** contract with a **Strike Price of 40 XIRECs** and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara). If the value of the Aether Crystal at expiry is **below 40 XIRECs**, the contract **pays a fixed amount of 10 XIRECs**. If the value is at or above 40 XIRECs at expiry, the contract **expires worthless**.

---

### AC_45_KO (Knock-Out Put)
| Field | Value |
|-------|-------|
| Expiry | T + 21 |
| Size (Bid) | 500 |
| Bid | 0.15 |
| Ask | 0.175 |
| Size (Ask) | 500 |
| Price | + 0.71 |

**Description:** AC_45_KO is an Aether Crystal **KNOCK-OUT PUT Option** contract with a **Strike Price of 45 XIRECs**, a **Barrier Price of 35 XIRECs**, and a **Time To Expiry of 21 Solvenarian Days** (starting from Round 1, on Intara). If the value of the Aether Crystal **ever falls below 35 XIRECs, the contract is knocked out and expires worthless**. If the barrier is never breached, the contract expires with the same payoff as a standard put option with a Strike Price of 45 XIRECs.

---

## Summary Table (Quick Reference)

| Option | Type | Strike | Barrier | Expiry | Bid | Ask | Bid Size | Ask Size | Contract Size |
|--------|------|--------|---------|--------|-----|-----|----------|----------|---------------|
| AC | Underlying | — | — | N/A | 49.975 | 50.025 | 200 | 200 | 3,000 |
| AC_50_P | Put | 50 | — | T+21 | 12 | 12.05 | 50 | 50 | 3,000 |
| AC_50_C | Call | 50 | — | T+21 | 12 | 12.05 | 50 | 50 | 3,000 |
| AC_35_P | Put | 35 | — | T+21 | 4.33 | 4.35 | 50 | 50 | 3,000 |
| AC_40_P | Put | 40 | — | T+21 | 6.5 | 6.55 | 50 | 50 | 3,000 |
| AC_45_P | Put | 45 | — | T+21 | 9.05 | 9.1 | 50 | 50 | 3,000 |
| AC_60_C | Call | 60 | — | T+21 | 8.8 | 8.85 | 50 | 50 | 3,000 |
| AC_50_P_2 | Put | 50 | — | T+14 | 9.7 | 9.75 | 50 | 50 | 3,000 |
| AC_50_C_2 | Call | 50 | — | T+14 | 9.7 | 9.75 | 50 | 50 | 3,000 |
| AC_50_CO | Chooser | 50 | — | T+14/21 | 22.2 | 22.3 | 50 | 50 | 3,000 |
| AC_40_BP | Binary Put | 40 | — | T+21 | 5 | 5.1 | 50 | 50 | 3,000 |
| AC_45_KO | Knock-Out Put | 45 | 35 | T+21 | 0.15 | 0.175 | 500 | 500 | 3,000 |

---

## Key Notes

- **Contract size:** 3,000 (per contract)
- **Volume limits:** Limited by available bid/ask sizes shown
- **Trading:** One-time opportunity, does not affect algorithmic trading activities
- **Submission:** Enter side (Buy/Sell) and volume directly in the table, then click Submit
- **Currency:** XIRECs
- **Time unit:** Solvenarian Days (starting from Round 1, on Intara)
