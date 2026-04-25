# P3/P2 Options-Round Reference: What Top Teams Actually Did

Research distilled from four reference repos so we can stop leaving 60k+ on the table in
P4 R3. P3 R3/R4 had `VOLCANIC_ROCK` (spot) + 5 `VOLCANIC_ROCK_VOUCHER_<K>` calls (strikes
9500/9750/10000/10250/10500). P2 R4 had `COCONUT` (spot, limit 300) + `COCONUT_COUPON`
(K=10000 call, limit 600). Same shape as our `VELVETFRUIT_EXTRACT` + 10 `VEV_<K>` calls.

Sources (saved to `tmp/p3_research/`):
- TimoDiehm — 2nd place P3 (`timo_trader.py`, `timo_README.md`)
- chrispyroberts — 7th place P3 (`chris_round4.py`, `chris_README.md`)
- CarterT27 — 9th place P3 (`carter_trader.py`, `carter_README.md`)
- ericcccsliu — 2nd place P2 (`eric_round4_v4.py`, `eric_README.md`)

---

## 1. Pricing model — Black-Scholes, unanimously

Every team used vanilla **Black-Scholes call** (Bachelier was not used). Identical
implementations across repos:

```python
# timo_trader.py:574-577 (also identical in chris_round4.py:22-30, eric_round4_v4.py:71-79,
# carter_trader.py:712-728)
def bs_call(S, K, TTE, s, r=0):
    d1 = (math.log(S/K) + (r + 0.5*s**2) * TTE) / (s * TTE**0.5)
    d2 = d1 - s * TTE**0.5
    return S * _N.cdf(d1) - K * math.exp(-r * TTE) * _N.cdf(d2), _N.cdf(d1)
```

`r=0` everywhere. `NormalDist().cdf` from `statistics` (stdlib, no scipy).
**No one used Bachelier even though tick-counts are tiny** — BS works fine because they
re-fit IV from the market every tick rather than trusting a calendar-time σ.

### Time-to-expiry convention

- **Timo (P3, expiry day 7):** `tte = 1 - (DAYS_PER_YEAR - 8 + DAY + ts//100/10_000)/DAYS_PER_YEAR`
  i.e. fraction of year, days_left explicit (`timo_trader.py:644`).
- **Chris:** `tte = (days_left/365) - timestamp / 365e6` (`chris_round4.py:259`).
  `timestamps_per_year = 365e6` (one year = 365 days × 1M ts).
- **Eric (P2):** `tte = starting_tte - timestamp/1e6/250` with `starting_tte = 247/250`
  (`eric_round4_v4.py:1430-1433`). Year = 250 trading days.

The exact convention doesn't matter — **what matters is using the same one when
back-fitting IV and when computing fair price**, so cancellations happen.

---

## 2. Implied volatility — three approaches

### 2a. Bisection IV (Chris, Eric)

```python
# chris_round4.py:67-86 — 200-iter bisection between 0.001 and 1.0
def implied_volatility(call_price, spot, strike, time_to_expiry, max_iterations=200, tolerance=1e-10):
    low_vol, high_vol = 0.001, 1.0
    volatility = (low_vol + high_vol) / 2.0
    for _ in range(max_iterations):
        estimated_price = bs_call(spot, strike, time_to_expiry, volatility)
        diff = estimated_price - call_price
        if abs(diff) < tolerance: break
        elif diff > 0: high_vol = volatility
        else: low_vol = volatility
        volatility = (low_vol + high_vol) / 2.0
    return volatility
```

Carter uses Newton's method on vega instead (`carter_trader.py:746-770`) — faster,
~50 iters. Both approaches are O(microseconds) so latency is irrelevant.

### 2b. Vol-smile parabola (Timo — winning approach)

Timo's edge came from **fitting a parabola in moneyness offline**, hard-coded into
the trader as 3 coefficients:

```python
# timo_trader.py:583-587
def get_iv(St, K, TTE):
    m_t_k = np.log(K/St) / TTE**0.5  # moneyness
    coeffs = [0.27362531, 0.01007566, 0.14876677]  # fitted offline
    iv = np.poly1d(coeffs)(m_t_k)
    return iv
```

This gives a "fair IV" `v̂` for any (S, K, TTE), which feeds BS to give a "fair price".
He then trades **deviations from this fair price**, scalping the per-tick mispricing
(see Section 5).

Chris uses essentially the same idea but with **two parabolas** (separate ask/bid sides)
fitted offline to the moneyness range [-0.35, 0.35] (`chris_round4.py:186-197`):

```python
self.ask_params = {'a': 0.2386, 'b': -0.00196, 'c': 0.1516}
self.bid_params = {'a': 0.1436, 'b': -0.00155, 'c': 0.1504}
```

### 2c. Rolling-mean IV per strike (Carter, Chris)

Both keep a deque of the last N=20 IV observations per voucher and use the mean as
the "fair vol":

```python
# carter_trader.py:912-924
self.past_volatilities[voucher_symbol].append(current_implied_vol)
if len(...) > 20: self.past_volatilities[voucher_symbol].pop(0)
volatility = statistics.mean(self.past_volatilities[voucher_symbol])
theoretical_price = bs_call(rock_mid, strike, tte, ..., volatility)
```

Eric (P2) uses a window of 6 only (`eric_round4_v4.py:56`) with a known `mean_volatility =
0.15959997370608378` and trades **z-score of IV vs the rolling std** (Section 5d).

**Takeaway for us:** Timo's offline-fit smile is what won. We have CSV data — we can
fit `iv = a*m^2 + b*m + c` once across all 10 strikes, hard-code the coeffs, and price
every voucher off that single curve.

---

## 3. Trade triggers — five distinct flavours

### 3a. Pure MM around fitted price (Carter, Chris)

```python
# carter_trader.py:933-952 — 1-tick spread quotes around theoretical
buy_price = int(theoretical_price)
make_orders.append(Order(voucher_symbol, buy_price, limit - voucher_position))
sell_price = int(theoretical_price + 1)
make_orders.append(Order(voucher_symbol, sell_price, -limit - voucher_position))
```

Uses the FULL position limit on each side (200 each way for P3 vouchers). This is the
simplest and most directly portable to our `a.py`.

Chris's variant (`chris_round4.py:310-415`) is more elaborate: places `bid =
floor(fair+eps), ask = ceil(fair-eps)`, **takes the book if it's mispriced past
fair**, then MMs on top.

### 3b. IV-deviation scalping (Timo — the winner)

```python
# timo_trader.py:670-692 — open if abs(theo_diff - mean_theo_diff) >= THR_OPEN+adj
THR_OPEN, THR_CLOSE = 0.5, 0
LOW_VEGA_THR_ADJ = 0.5  # tighten threshold for low-vega options
IV_SCALPING_THR = 0.7   # only scalp if EMA of |dev| >= 0.7 (i.e. enough movement)
IV_SCALPING_WINDOW = 100

if (current_theo_diff - option.wall_mid + option.best_bid - mean_theo_diff
        >= (THR_OPEN + low_vega_adj)) and option.max_allowed_sell_volume > 0:
    option.ask(option.best_bid, option.max_allowed_sell_volume)
elif (current_theo_diff - option.wall_mid + option.best_ask - mean_theo_diff
        <= -(THR_OPEN + low_vega_adj)) and option.max_allowed_buy_volume > 0:
    option.bid(option.best_ask, option.max_allowed_buy_volume)
```

Two-state EMA of the per-strike `theo_diff = wall_mid - bs_fair`. If the current diff
deviates from its EMA by > 0.5 SeaShells, **slam the full remaining position limit**
across the spread. Close back to flat at THR_CLOSE = 0. Only activate scalping if the
EMA of `|dev|` is large enough (`IV_SCALPING_THR = 0.7`) — i.e. don't trade vouchers
that are pinned.

### 3c. IV z-score (Eric)

```python
# eric_round4_v4.py:1087-1130
vol_z_score = (volatility - mean_volatility) / np.std(past_coupon_vol)
if vol_z_score >= zscore_threshold:    # 21 (!)
    target = -LIMIT[COUPON]            # slam to short limit
elif vol_z_score <= -zscore_threshold:
    target = LIMIT[COUPON]
```

Z-threshold of 21 is gigantic — meaning he basically only fires on extreme outliers.
This stat-arb-on-IV approach made him 145k on COUPON in P2.

### 3d. Cross-strike arbitrage (Carter)

```python
# carter_trader.py:816-885 — exploit |spread - strike_diff| > threshold
if abs(spread - strike_diff) > self.arbitrage_threshold * strike_diff:
    if spread > strike_diff * (1 + threshold):
        # sell expensive, buy cheap voucher
```

Box-spread style. Cheap to implement, works because two vouchers at strikes K1 < K2
should satisfy `C(K1) - C(K2) ≤ K2 - K1`. Worth checking on our 10-strike chain.

### 3e. Underlying mean reversion driven by IV signal (Timo, Carter, Chris)

Timo trades the underlying VR mean-reversion **separately** from options scalping
(`timo_trader.py:746-761`). EMA dev > 15 → sell, < -15 → buy, slam full size. This
contributed ~100k once across rounds.

Carter uses **option-implied "fair" rock price** to take VR positions
(`carter_trader.py:971-1033`):

```python
avg_strike = sum(strikes) / len(strikes)
theoretical_price = bs_call(rock_mid, avg_strike, tte, r, vol)
if rock_mid < theoretical_price - 0.5: buy rock
elif rock_mid > theoretical_price + 0.5: sell rock
```

(This was the buggy one that "accidentally" went 2nd in the world.)

---

## 4. Hedging — mostly skipped

- **Timo**: explicitly **does not delta-hedge** (`timo_README.md:607`). Quote: "the delta
  exposure from scalping was relatively small, and explicit delta hedging would have been
  prohibitively expensive bid-ask spreads."
- **Chris**: implements full delta-hedge but **disabled it** with `dont_hedge=True`
  (`chris_round4.py:417-420`). Discovered hedge spread cost was ~40k per round
  (`chris_README.md:245`), more than it saved.
- **Carter**: disabled rock trading entirely in R4 (his README:153).
- **Eric** (P2): **partial delta hedge** with COCONUT after each COUPON trade
  (`eric_round4_v4.py:1021-1065`). `target_coconut_position = -delta * coupon_position`,
  then hedge the diff. He explicitly notes (`eric_README.md:165`) that with delta ~0.53
  and limit ratios 300/600, full hedging at max coupon position is impossible — he
  intentionally ran the residual delta exposure for vega edge.

**Takeaway:** Don't bother with delta hedging in v1. Bid-ask spread cost on the
underlying eats the hedge value. Add only if our tick-by-tick PnL shows large
delta-driven swings.

---

## 5. Position sizing

| Team | Per-voucher limit | Sizing rule |
|---|---|---|
| Timo | 200 | `max_allowed_sell_volume` (full remaining headroom) on threshold breach |
| Chris | 200 | `max_size = 200`, `bid_size = max_size - pos`, full size both sides |
| Carter | 200 | `limit - position` and `-limit - position`, full size both sides |
| Eric | 600 (P2) | Slam to `±LIMIT[COUPON]` on z-score breach |

**Universal pattern:** when the signal fires, **use the full remaining position limit**.
Nobody sizes down. Our current `R3_QUOTE_SIZE = 5` is *60x too small* for the 300-limit
vouchers.

---

## 6. Multi-tick / state

All four traders persist state across ticks via `traderData`:

- IV history per strike (rolling 6/20/100 window)
- EMA of per-strike `theo_diff`
- Past delta history per strike
- Rolling underlying-price window (Chris uses 5-tick for spread estimate)

Timo's IV-scalping carries the full position across many ticks until `theo_diff` mean-
reverts back through `THR_CLOSE = 0`. **Not a single-tick MM strategy.** Hold time is
typically tens to hundreds of ticks.

---

## 7. Trades-data signals

Olivia (an insider counterparty in P3 R5 / P2 R5) is exploited by every team. Not
relevant for R3 — counterparties are revealed in R5 only. **Skip for now.** But note
Timo's `INFORMED_TRADER_ID = 'Olivia'` constant (`timo_trader.py:51`) — when R5 lands,
plumb counterparty-tracking infra in early.

---

## 8. PnL per round on options (per their writeups)

| Team | Round | Approach | PnL |
|---|---|---|---|
| Timo | P3 R3 | IV scalping + MR | "100-150k SeaShells per round, providing strong and stable profits" (timo_README.md:614) |
| Chris | P3 R3 | Smile + MM | "expected ~80k from voucher products" (chris_README.md:184) |
| Eric | P2 R4 | IV z-score + partial delta hedge | 145k (`eric_README.md:169`) |

Top expectations were **80–150k just from options**. Our current ~2k is leaving 75k+
on the table per session.

---

## Top 5 Actionable Ideas to Port into `traders/round3/a.py`

Ranked by EV per hour of implementation effort.

### 1. Fit a vol smile from R3 CSVs and hard-code the parabola coefficients

Use `analysis/round3/r3_smile_clean.py` data to fit `iv = a*m^2 + b*m + c` where
`m = log(K/S) / sqrt(TTE)`. Hard-code three floats. Use this `iv_hat(K, S, TTE)` to
compute a BS theoretical price for every active voucher every tick. Snippet to copy
verbatim from `tmp/p3_research/timo_trader.py:572-592`. **2-4 hours.**

### 2. Replace penny-jump MM with quote-around-theoretical MM

Per voucher: post `Order(voucher, int(theo), +remaining_buy_room)` and
`Order(voucher, int(theo)+1, -remaining_sell_room)`. This is Carter's full strategy
(`carter_trader.py:933-952`) — 20 lines, uses full 300 position limit. Even with no
smile (just rolling-mean IV per strike) this should clear 30-50k. **1 hour.**

### 3. Add IV-deviation scalping over MM

Track EMA of `theo_diff = wall_mid - bs_fair` per voucher (window ~20). When current
deviation exceeds EMA by > 0.5 SeaShells, slam the full remaining position limit
across the spread (Timo's `THR_OPEN = 0.5`). Close on revert. Direct port of
`tmp/p3_research/timo_trader.py:664-704`. This was Timo's winning edge. **3-5 hours.**

### 4. Deep-ITM MM on VEV_4000/VEV_4500

These behave like the underlying with constant offset (call ≈ S - K). Easy edge:
quote 1 tick inside `S - K + small_premium` on both sides. Carter's vol-surface
fits poorly to deep-ITM, but **straight intrinsic-value MM** works. **1 hour.**

### 5. Cross-strike arb check (cheap free money)

For every pair (K1, K2) with K1 < K2, if `C(K1) - C(K2) > K2 - K1 - epsilon`, sell
K1 / buy K2. Direct port of `tmp/p3_research/carter_trader.py:803-886`. With 10
strikes there are 45 pairs to check per tick — still microseconds. **1-2 hours.**

### Skip for v1

- **Delta hedging.** Timo, Chris, Carter all disabled it. Spread cost > hedge value.
  Re-evaluate only if tick-by-tick PnL shows >5k/session swings from delta.
- **Vega hedging across strikes.** Nobody did this. Too complex for the edge available.
- **Bachelier model.** Nobody used it. BS with re-fit IV per tick handles it.
- **Olivia / counterparty signals.** R5 only.

---

## Appendix: file locations of key snippets

| Pattern | Best implementation | Lines |
|---|---|---|
| BS call + delta + vega | `tmp/p3_research/chris_round4.py` | 22-86 |
| Bisection IV | `tmp/p3_research/chris_round4.py` | 67-86 |
| Newton-method IV | `tmp/p3_research/carter_trader.py` | 746-770 |
| Smile parabola (offline-fit, hard-coded) | `tmp/p3_research/timo_trader.py` | 572-592 |
| Two-side smile parabola | `tmp/p3_research/chris_round4.py` | 186-197 |
| IV-deviation scalping (full code) | `tmp/p3_research/timo_trader.py` | 664-704 |
| IV z-score trigger | `tmp/p3_research/eric_round4_v4.py` | 1067-1132 |
| Delta hedge (Eric, partial, ENABLED) | `tmp/p3_research/eric_round4_v4.py` | 904-1065 |
| Cross-strike arb | `tmp/p3_research/carter_trader.py` | 803-886 |
| Quote-around-theoretical MM | `tmp/p3_research/carter_trader.py` | 933-952 |
| Underlying MR using option-implied fair | `tmp/p3_research/carter_trader.py` | 971-1033 |
| Underlying MR via EMA dev | `tmp/p3_research/timo_trader.py` | 746-761 |
