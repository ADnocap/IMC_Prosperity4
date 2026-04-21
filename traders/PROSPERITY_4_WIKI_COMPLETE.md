# IMC Prosperity 4 - Complete Wiki & Reference Guide

## Table of Contents
1. [Competition Overview](#1-competition-overview)
2. [Timeline & Round Structure](#2-timeline--round-structure)
3. [Scoring & Prizes](#3-scoring--prizes)
4. [Algorithmic Challenge - How It Works](#4-algorithmic-challenge---how-it-works)
5. [DataModel / API Specification](#5-datamodel--api-specification)
6. [Tutorial Round Details](#6-tutorial-round-details)
7. [Products & Position Limits](#7-products--position-limits)
8. [Order Matching Engine](#8-order-matching-engine)
9. [Manual Trading Challenges](#9-manual-trading-challenges)
10. [Conversion / Arbitrage Mechanics](#10-conversion--arbitrage-mechanics)
11. [Code Templates & Examples](#11-code-templates--examples)
12. [Strategy Hints & Tips](#12-strategy-hints--tips)
13. [Tools & Resources](#13-tools--resources)
14. [Eligibility & Rules](#14-eligibility--rules)

---

## 1. Competition Overview

**Prosperity 4** is IMC Trading's flagship annual global trading challenge for STEM university students. It is a 16-day online simulation where participants develop Python trading algorithms and solve manual trading puzzles to maximize profit in virtual markets.

**Theme**: Outer space. Participants are sent to planet **Intara** to establish a trading outpost. The in-game currency appears to be called **XIRECs** (replacing "SeaShells" from prior years).

**Scale**: Over 3 years, Prosperity attracted 48,000+ players across 28,000+ teams. Prosperity 3 alone had 22,600 players across 12,600+ teams from 500+ universities.

**Team Size**: 1-5 members per team. Solo participation allowed. Team composition locks after Round 2.

---

## 2. Timeline & Round Structure

| Phase | Dates | Duration |
|-------|-------|----------|
| **Registration Open** | March 16 - April 13, 2026 | |
| **Tutorial Round** | March 16 - April 13, 2026 | ~28 days |
| **Round 1** | April 14-17 | 72 hours |
| **Round 2** | April 17-20 | 72 hours |
| **Intermission** | April 20-24 | 4 days |
| **Round 3** | April 24-26 | 48 hours |
| **Round 4** | April 26-28 | 48 hours |
| **Round 5** | April 28-30 | 48 hours |

**Key Points**:
- 5 active competition rounds total
- Rounds 1-2 are 72 hours; Rounds 3-5 are 48 hours
- 4-day intermission between Round 2 and Round 3
- Each round has BOTH an algorithmic challenge AND a manual trading challenge
- New products are introduced progressively each round
- All previous round products remain tradeable in later rounds
- Final results processed within 2 weeks of Round 5 completion

---

## 3. Scoring & Prizes

### Scoring Mechanics
- **PnL (Profit and Loss)** calculated after each round closes
- Scores delivered via email notification
- Leaderboard updated when round results process
- Algorithms trade **independently** (no player-to-player direct interaction)
- Algorithms compete against **Prosperity trading bots**
- Algorithmic and manual scores are **independent** - they don't influence each other
- Submitted trades cannot be modified once rounds close

### Prize Pool: $50,000 USD

| Place | Prize |
|-------|-------|
| 1st (IMC Global Trading Talent of the Year) | $25,000 |
| 2nd | $10,000 |
| 3rd | $5,000 |
| 4th | $3,500 |
| 5th | $1,500 |
| Best Manual Trader | $5,000 |

---

## 4. Algorithmic Challenge - How It Works

### Core Concept
Teams write and upload a Python trading algorithm (a `Trader` class) that trades against a marketplace of bots on a virtual exchange. The goal is to earn as much profit as possible.

### Execution Flow
1. At each **timestamp**, the simulation calls your `Trader.run()` method
2. Your method receives a `TradingState` object containing all market data
3. Your method returns orders, conversions, and optional persistent state
4. The matching engine processes your orders against the order book
5. Position limits are enforced; PnL is tracked
6. All orders expire after one timestep (no persistent orders)

### Submission
- Upload a single Python `.py` file containing a `Trader` class
- The class must have a `run()` method
- At round close, the algorithm is evaluated against bot participants
- The PnL from this evaluation determines your score/ranking

### Simulation Order (per timestep)
1. Deep-liquidity market makers submit orders first
2. Takers submit
3. Competitor algorithms (your code) execute
4. Other bots submit
5. All orders expire at end of timestep

---

## 5. DataModel / API Specification

### Complete `datamodel.py` (Prosperity 4)

```python
import json
from typing import Dict, List
from json import JSONEncoder
import jsonpickle

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int


class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: int):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float,
                 exportTariff: float, importTariff: float,
                 sugarPrice: float, sunlightIndex: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sugarPrice = sugarPrice
        self.sunlightIndex = sunlightIndex


class Observation:
    def __init__(self, plainValueObservations: Dict[Product, ObservationValue],
                 conversionObservations: Dict[Product, ConversionObservation]) -> None:
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

    def __str__(self) -> str:
        return ("(plainValueObservations: " + jsonpickle.encode(self.plainValueObservations) +
                ", conversionObservations: " + jsonpickle.encode(self.conversionObservations) + ")")


class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __str__(self) -> str:
        return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"

    def __repr__(self) -> str:
        return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"


class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}   # price -> quantity (positive)
        self.sell_orders: Dict[int, int] = {}   # price -> quantity (negative)


class Trade:
    def __init__(self, symbol: Symbol, price: int, quantity: int,
                 buyer: UserId = None, seller: UserId = None,
                 timestamp: int = 0) -> None:
        self.symbol = symbol
        self.price: int = price
        self.quantity: int = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    def __str__(self) -> str:
        return ("(" + self.symbol + ", " + self.buyer + " << " + self.seller + ", " +
                str(self.price) + ", " + str(self.quantity) + ", " + str(self.timestamp) + ")")

    def __repr__(self) -> str:
        return ("(" + self.symbol + ", " + self.buyer + " << " + self.seller + ", " +
                str(self.price) + ", " + str(self.quantity) + ", " + str(self.timestamp) + ")")


class TradingState(object):
    def __init__(self,
                 traderData: str,
                 timestamp: Time,
                 listings: Dict[Symbol, Listing],
                 order_depths: Dict[Symbol, OrderDepth],
                 own_trades: Dict[Symbol, List[Trade]],
                 market_trades: Dict[Symbol, List[Trade]],
                 position: Dict[Product, Position],
                 observations: Observation):
        self.traderData = traderData        # String you returned last iteration (persistent state)
        self.timestamp = timestamp          # Current simulation timestamp
        self.listings = listings            # Dict of Symbol -> Listing
        self.order_depths = order_depths    # Dict of Symbol -> OrderDepth (current order book)
        self.own_trades = own_trades        # Dict of Symbol -> List[Trade] (your trades since last iteration)
        self.market_trades = market_trades  # Dict of Symbol -> List[Trade] (all market trades since last)
        self.position = position            # Dict of Product -> Position (your current positions)
        self.observations = observations    # Observation object (conversion data, external signals)

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)


class ProsperityEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
```

### Key Data Types
- `Time = int` - Timestamp (integer, increments each iteration)
- `Symbol = str` - Trading symbol identifier
- `Product = str` - Product name
- `Position = int` - Current position in units
- `UserId = str` - Identifies a trader/bot
- `ObservationValue = int` - External observation value

### TradingState Fields Explained
| Field | Type | Description |
|-------|------|-------------|
| `traderData` | `str` | The string you returned in the previous `run()` call. Use for persistent state (e.g., JSON-serialized data). Empty on first call. |
| `timestamp` | `int` | Current simulation timestamp |
| `listings` | `Dict[Symbol, Listing]` | All tradeable symbols with their product and denomination info |
| `order_depths` | `Dict[Symbol, OrderDepth]` | Current order book for each symbol. `buy_orders`: price->positive qty. `sell_orders`: price->negative qty. |
| `own_trades` | `Dict[Symbol, List[Trade]]` | Your trades that occurred since the last iteration |
| `market_trades` | `Dict[Symbol, List[Trade]]` | All market trades (between any participants) since last iteration |
| `position` | `Dict[Product, Position]` | Your current net position in each product |
| `observations` | `Observation` | Contains `plainValueObservations` and `conversionObservations` for cross-market data |

### ConversionObservation Fields
| Field | Type | Description |
|-------|------|-------------|
| `bidPrice` | `float` | Foreign market bid price |
| `askPrice` | `float` | Foreign market ask price |
| `transportFees` | `float` | Cost to transport goods between markets |
| `exportTariff` | `float` | Tariff for exporting from local market |
| `importTariff` | `float` | Tariff for importing to local market |
| `sugarPrice` | `float` | External sugar commodity price (signal) |
| `sunlightIndex` | `float` | Environmental sunlight index (signal) |

---

## 6. Tutorial Round Details

**Available**: March 16 - April 13, 2026 (before competition starts)

### Tutorial Products

| Product | Position Limit | Fair Value | Behavior |
|---------|---------------|------------|----------|
| **EMERALDS** | 80 | ~10,000 | **Stationary** - Mid-price oscillates around 10,000 with ~16 spread. Classic market-making candidate. |
| **TOMATOES** | 80 | Varies (drifts) | **Non-stationary / Drifting** - Shows directional drift. Requires adaptive strategies: drift-aware market making, trend following, or momentum models. |

### Tutorial Data Files
Historical CSV data capsules are provided:
- `prices_round_0_day_-1.csv` - Price data for day -1
- `prices_round_0_day_-2.csv` - Price data for day -2
- `trades_round_0_day_-1.csv` - Trade data for day -1
- `trades_round_0_day_-2.csv` - Trade data for day -2

### Purpose
- Practice writing and submitting algorithms
- Familiarize yourself with the platform GUI
- Learn the datamodel and order matching
- Test strategies with backtesting before live rounds

---

## 7. Products & Position Limits

### Prosperity 4 Tutorial Round (CONFIRMED)

| Product | Position Limit |
|---------|---------------|
| EMERALDS | 80 |
| TOMATOES | 80 |

### Prosperity 3 Products (Reference - Similar Structure Expected)

Products were introduced progressively across rounds:

**Round 0 (Tutorial) & Round 1:**
| Product | Position Limit | Character |
|---------|---------------|-----------|
| RAINFOREST_RESIN | 50 | Fixed fair value at 10,000. Pure market making. |
| KELP | 50 | Slow random walk. Market making with adaptive fair value. |
| SQUID_INK | 50 | Highly volatile, mean-reverting with 100+ swings per step. |

**Round 2 (added):**
| Product | Position Limit | Character |
|---------|---------------|-----------|
| CROISSANTS | 250 | Basket constituent |
| JAMS | 350 | Basket constituent |
| DJEMBES | 60 | Basket constituent |
| PICNIC_BASKET1 | 60 | = 6 Croissants + 3 Jams + 1 Djembe |
| PICNIC_BASKET2 | 100 | = 4 Croissants + 2 Jams |

**Round 3 (added):**
| Product | Position Limit | Character |
|---------|---------------|-----------|
| VOLCANIC_ROCK | 400 | Underlying asset for options |
| VOLCANIC_ROCK_VOUCHER_9500 | 200 | European call option, strike 9500 |
| VOLCANIC_ROCK_VOUCHER_9750 | 200 | European call option, strike 9750 |
| VOLCANIC_ROCK_VOUCHER_10000 | 200 | European call option, strike 10000 |
| VOLCANIC_ROCK_VOUCHER_10250 | 200 | European call option, strike 10250 |
| VOLCANIC_ROCK_VOUCHER_10500 | 200 | European call option, strike 10500 |

**Round 4 (added):**
| Product | Position Limit | Character |
|---------|---------------|-----------|
| MAGNIFICENT_MACARONS | 75 | Cross-market arbitrage with foreign exchange, transport fees, tariffs |

**Round 5**: All previous products remain. Trader IDs become visible (copy-trading becomes possible). Additional complexity may be introduced.

### Expected Prosperity 4 Round Types (Based on Pattern)
- **Round 1**: Market Making (stationary + moving fair value products)
- **Round 2**: ETF/Basket Arbitrage (baskets vs. constituents)
- **Round 3**: Options Trading (vouchers/options on underlying)
- **Round 4**: Location/Cross-Market Arbitrage (with conversions, fees, tariffs)
- **Round 5**: Information revelation + all products (copy-trading, sentiment)

---

## 8. Order Matching Engine

### How Orders Are Matched

1. **Position limit check FIRST**: Before any matching, the engine checks if ALL your orders for a product could be filled simultaneously. If that would exceed your position limit, ALL orders for that product are canceled entirely.

2. **Order depth priority**: Your orders are first matched against the existing order book (bot orders).
   - Better-priced orders are matched first (price-time priority)
   - If your order can be completely filled from the order depth, market trades are not considered

3. **Market trade matching** (if order depth insufficient): If the order book cannot fully fill your order, remaining quantity is matched against that timestamp's market trades.
   - Each market trade's buyer and seller are assumed willing to trade with you at the trade's price and volume
   - **Critical**: Market trades are matched at YOUR order's price, not the market trade's price
   - Example: Your sell order at 9 + market trade at 10 = you sell at 9

4. **Order book depth**: 3 levels of depth visible to traders

5. **All orders expire**: Every order expires at the end of its timestep. There are no persistent/GTC orders.

### Position Limit Enforcement Rule
> "If for a product your position would exceed the limit, assuming ALL your orders would get filled, all your orders for that product get canceled."

This means you must be careful: if you have position +40 in a product with limit 50, and you submit buy orders totaling 20 units, ALL your buy orders for that product are canceled (since 40+20=60 > 50), even if individually some would be fine.

---

## 9. Manual Trading Challenges

Each round includes a manual trading challenge separate from the algorithmic challenge. These test analytical thinking, game theory, and creative problem-solving. Manual challenge PnL contributes independently to ranking.

### Typical Manual Challenge Types (from Prosperity 3)

| Round | Challenge | Description |
|-------|-----------|-------------|
| 1 | **FX/Currency Arbitrage** | Given a conversion matrix between currencies, find the optimal sequence of 5 trades to maximize profit. Approached as a graph traversal optimization problem. |
| 2 | **Containers** | 10 containers available, can open up to 2 (first free, second costs 50,000). Each has a multiplier and some inhabitants. Payoff = (10,000 x multiplier) / (inhabitants + your share of all openings). Game theory + Nash equilibrium. |
| 3 | **Reserve Price / Sealed-Bid Auction** | Bid on items across two stages with penalty scaling. Penalty formula: p = ((320 - avg_bid)/(320 - your_bid))^3 |
| 4 | **Suitcases** | Similar to Containers. Select suitcases with multipliers. Strategy: pick high-multiplier, low-popularity options. |
| 5 | **News Trading / Portfolio Optimization** | Make trading decisions based on news/sentiment. Fee structure with quadratic costs: Fee(x) = 120 * x^2 where x is portfolio allocation fraction. |

**Note**: Prosperity 4 will have NEW manual challenges, but they will likely test similar skills (expected value, optimization, game theory, arbitrage detection).

---

## 10. Conversion / Arbitrage Mechanics

In certain rounds, products can be traded across multiple exchanges (local vs. foreign). This involves:

### Conversion Costs
- **Transport Fees**: Fixed cost per unit transported between markets
- **Import Tariff**: Fee for bringing goods into local market
- **Export Tariff**: Fee for sending goods to foreign market
- **Storage Fees**: Per-timestamp holding cost (e.g., 0.1 per timestamp in Prosperity 3 for Macarons)

### Conversion Pricing
- **Buying from foreign market**: Pay the ask price + transport fees + import tariff
- **Selling to foreign market**: Receive the bid price - transport fees - export tariff

### Strategy
Build effective conversion prices by:
1. Foreign ask + transport + import tariff = effective buy price
2. Foreign bid - transport - export tariff = effective sell price
3. Compare these to local order book top-of-book
4. Trade when local price diverges sufficiently from effective foreign price

### ConversionObservation Signals
The `sugarPrice` and `sunlightIndex` fields in `ConversionObservation` provide additional signals that may correlate with product fair values (e.g., sunlight affecting crop yields for agricultural products).

---

## 11. Code Templates & Examples

### Minimal Starter Template

```python
from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List

class Trader:
    def run(self, state: TradingState):
        result = {}
        for product in state.order_depths:
            orders: List[Order] = []
            # Your trading logic here
            result[product] = orders
        traderData = ""     # Serialized state to persist between iterations
        conversions = 0     # Number of cross-market conversions to execute
        return result, conversions, traderData
```

### Basic Market-Making Example (for stationary products like EMERALDS)

```python
from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json

class Trader:
    def run(self, state: TradingState):
        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # Calculate mid price from best bid/ask
            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                mid_price = (best_bid + best_ask) / 2
            else:
                continue

            # Get current position
            position = state.position.get(product, 0)

            # For stationary products like EMERALDS (fair value ~10,000)
            fair_value = 10000  # Adjust per product

            LIMIT = 80  # Position limit for tutorial products

            # Buy orders: take any sell orders below fair value
            for ask_price in sorted(order_depth.sell_orders.keys()):
                ask_volume = order_depth.sell_orders[ask_price]  # Negative
                if ask_price < fair_value and position < LIMIT:
                    buy_qty = min(-ask_volume, LIMIT - position)
                    orders.append(Order(product, ask_price, buy_qty))
                    position += buy_qty

            # Sell orders: take any buy orders above fair value
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                bid_volume = order_depth.buy_orders[bid_price]  # Positive
                if bid_price > fair_value and position > -LIMIT:
                    sell_qty = min(bid_volume, position + LIMIT)
                    orders.append(Order(product, bid_price, -sell_qty))
                    position -= sell_qty

            # Place passive market-making orders
            spread = 2
            if position < LIMIT:
                orders.append(Order(product, int(fair_value - spread), LIMIT - position))
            if position > -LIMIT:
                orders.append(Order(product, int(fair_value + spread), -(position + LIMIT)))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData
```

### Run Method Return Value
The `run()` method must return a **3-tuple**:
```python
return result, conversions, traderData
```
- `result`: `Dict[Symbol, List[Order]]` - Orders to place for each product
- `conversions`: `int` - Number of cross-market conversions to execute (0 if not applicable)
- `traderData`: `str` - Any string you want persisted and returned as `state.traderData` next iteration. Use `json.dumps()` / `json.loads()` or `jsonpickle` for complex state.

---

## 12. Strategy Hints & Tips

### General Philosophy
- Start from **generative assumptions** about how prices behave
- Do proper **exploratory data analysis** on provided CSV data
- Resist the temptation to **blindly overfit** to historical data
- Build **generalizable frameworks**, not hard-coded edge cases
- Use sensible tools like **linear regression** rather than black-box models
- Backtest result of ~35K historically correlated to ~9K live (top 10%)

### Five-Component Trading System Framework
1. **Alpha Engine**: What's mispriced and why? (mid-price estimation, signal detection)
2. **Risk Engine**: Control exposure, unrealized losses, concentration
3. **Inventory Management**: Track positions with soft limits before hard caps
4. **Execution Engine**: Order placement, sizing, cancellation, timing
5. **Portfolio Management**: Allocate capital across strategies/assets

### Per-Product-Type Strategies

**Stationary Products** (like EMERALDS, RAINFOREST_RESIN):
- Market making around a fixed or slowly-moving fair value
- Buy below fair value, sell above
- Manage inventory to stay near zero

**Drifting Products** (like TOMATOES, KELP):
- Adaptive fair value estimation (VWAP, EMA, regression)
- Drift-aware market making
- Short-horizon trend following

**Volatile/Mean-Reverting Products** (like SQUID_INK):
- Detect extreme moves (>3 standard deviations from rolling window)
- Bet on reversion to mean
- Use volatility thresholds and stop-losses

**Basket/ETF Products** (like PICNIC_BASKETs):
- Calculate synthetic basket value from constituent prices
- Trade when basket price diverges from synthetic value (z-score based)
- Consider hedging basket position with constituent orders

**Options/Vouchers**:
- Black-Scholes pricing with rolling implied volatility
- Arbitrage between different strike prices
- IV scalping, gamma scalping, mean reversion on IV

**Cross-Market Arbitrage Products** (like MACARONS):
- Compare local prices to effective foreign prices (including all fees/tariffs)
- Execute conversions when profitable spread exists
- Watch for storage costs eating into profits

### Round 5 Special: Copy Trading
- In final rounds, trader IDs may become visible
- Look for informed traders (e.g., "Olivia" in Prosperity 3) who consistently buy at lows and sell at highs
- Statistical analysis of trade timing and profitability can identify these bots
- Replicate their trades as regime signals

### Key Pitfalls
- Position limits are checked assuming ALL orders fill simultaneously - be conservative
- Orders expire every timestep - no persistent orders
- The market doesn't care about your strategy labels - all orders combine into net exposure
- Memory and computation efficiency matter in the sandbox
- Environment variables from backtesting won't exist in submission environment

---

## 13. Tools & Resources

### Official Resources
- **Prosperity Website**: https://prosperity.imc.com/
- **Wiki**: https://imc-prosperity.notion.site/prosperity-4-wiki (requires login/JavaScript)
- **Discord**: https://discord.gg/SABeB8uKxd
- **E-learning Center**: Available on the wiki (trading terminology, Python skills)
- **Contact**: prosperity@imc.com

### Community Backtesting Tools
- **Prosperity 4 Backtester**: https://github.com/kevin-fu1/imc-prosperity-4-backtester
  - Install: `pip install prosperity4btx`
  - Run: `python -m prosperity4bt <algorithm_file> <round>`
  - Run specific day: `python -m prosperity4bt <algorithm_file> 0--2`
- **Prosperity 3 Backtester** (by jmerle): https://github.com/jmerle/imc-prosperity-3-backtester
  - Install: `pip install prosperity3bt`

### Visualization Tools
- **IMC Prosperity Visualizer**: https://jmerle.github.io/imc-prosperity-visualizer/
- **IMC Prosperity 3 Visualizer**: https://jmerle.github.io/imc-prosperity-3-visualizer/
- **Community Dashboard**: http://ctdash.xyz/vis/

### Reference Repositories (Previous Winners/Top Teams)
- **2nd Place Prosperity 3**: https://github.com/TimoDiehm/imc-prosperity-3
- **9th Place Prosperity 3**: https://github.com/CarterT27/imc-prosperity-3
- **7th Place Prosperity 3**: https://github.com/chrispyroberts/imc-prosperity-3
- **2nd Place Prosperity 2**: https://github.com/ericcccsliu/imc-prosperity-2
- **9th Place Prosperity 2**: https://github.com/jmerle/imc-prosperity-2
- **13th Place Prosperity 2**: https://github.com/pe049395/IMC-Prosperity-2024
- **Prosperity 4 Strategy Guide**: https://github.com/MarkBrezina/Ctrl-Alt-DefeatTheMarket

### Recommended IDEs
- Visual Studio Code
- Anaconda / Spyder

---

## 14. Eligibility & Rules

### Who Can Participate
- University students (undergraduate and postgraduate) worldwide
- Engineering, management, medical, law, arts, commerce, science students
- Must be 18+ (top 25 teams must prove enrollment)
- Free to enter

### Who Cannot Participate
- Previous Top 10 finishers from prior Prosperity editions
- IMC employees or employees of competitor firms
- Prize eligibility limited to residents of: EMEA, North America, South America, India, Australia, or Hong Kong

### Important Rules
- Team composition locks after Round 2
- Top 25 teams must provide proof of university enrollment
- Terms & conditions: https://prosperity.imc.com/docs/terms-and-conditions.pdf
- Privacy policy: https://prosperity.imc.com/docs/privacy-policy.pdf

---

## Appendix: Activity Log Format

The submission environment generates activity logs that match the format produced by community backtesters. These logs contain:
- Timestamp-by-timestamp execution records
- Orders placed and matched
- Position changes
- PnL tracking
- Standard output (print statements) from your algorithm

The official visualizer tools can parse these logs for debugging and analysis.

---

*This document compiled from the IMC Prosperity 4 wiki, official IMC announcements, community backtester repositories, and top-team writeups from Prosperity 2-3. Product details for Rounds 1-5 of Prosperity 4 will only be revealed when each round opens.*
