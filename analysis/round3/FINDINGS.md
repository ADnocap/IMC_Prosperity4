# Round 3 — Master Findings & Strategy Doc

**Generated:** 2026-04-24
**Status:** Synthesis of 4 deep investigations + audit of existing R3 trader experiments.
**Goal:** close the gap from ~2k (current portal) to 60k+ (top teams).

The four supporting reports — read them for the underlying numbers:

- `options_analysis.md` — vol-surface / static-richness / put-call / monotonicity
- `p3_options_reference.md` — what P3 top teams (Timo 2nd, Chris 7th, Carter 9th, Eric P2 2nd) actually shipped for the options round
- `multi_tick_signals.md` — autocorrelation, OBI, microprice, optimal-hold, cross-product lead/lag
- `trades_signals.md` — market-trades flow analysis (bot identities anonymised in P4 — switched to anonymous flow)

This doc layers them and proposes a concrete next trader.

---

## TL;DR — why we are at 2k while the top is at 60k+

1. **Quote size is 60× too small.** `traders/round3/a.py` uses `R3_QUOTE_SIZE = 5` for everything. P3 top teams (Timo, Chris, Carter) **slam the full 300-lot voucher limit** the moment a signal fires. Our max gross voucher exposure is 5 × 10 = 50 lots; the legal cap is 3,000.
2. **Zero options model.** `a.py` MMs vouchers like spot products. The vouchers are systematically rich (multiple independent confirmations below). The single highest-EV change is **add a fitted Black–Scholes surface and short the rich strikes to limit**.
3. **Single-tick stateless logic.** No multi-tick signal, no inventory plan, no cross-product hedge, no trade-flow read. The L1-OBI signal alone has Sharpe 22–56 across products.
4. **Trader experiments already explored some of this.** `donnie.py` and `rugrat.py` have OBI-tiered VELVET sizing and voucher-leverage via BS delta. `belfort.py` has a dormant BS pricer. None are submitted; their ideas need to be merged into a single shipping trader.

**Realistic uplift estimate from compounded fixes** (additive on the matched-FV MC scale):

| Bucket | EV / round | Source |
|---|---|---|
| Short rich VEV_5300 + 5400 + 5500 to limit (delta-light) | +2,700 conservative / +18,600 if held to expiry | `options_analysis.md` |
| Hard-coded vol smile + IV-deviation scalping on ATM band | +5,000–15,000 | `p3_options_reference.md` (Timo/Chris numbers scaled to our underlying) |
| L1-OBI passive quote skew on all 10 products | +2,000–4,000 | `multi_tick_signals.md` (Sharpe 22–56) |
| HYDROGEL z>1 reversion overlay (H=200, 50–100 lot directional) | +500–1,500 | `multi_tick_signals.md` |
| HYDROGEL aggressive-BUY-cluster fade | +800–1,500 | `trades_signals.md` |
| Increase passive MM size from 5 → 30 on the active 10 assets | +2,000–4,000 | size scaling of current 2k baseline |

Even half of the union puts us at 15–25k. Stack the surface trade and we should clear 30k. The 60k bar requires the surface trade actually working at portal scale (which is what the P3 winners were doing).

---

## 1. The options book is the gap — and it's rich

### 1.1 Model-free evidence (`options_analysis.md`, `trades_signals.md`)

These observations don't require any pricing model:

- **Underlying is rangebound**: VELVETFRUIT_EXTRACT mid stays in [5198, 5300] over the entire 30K-tick history. Strikes ≥ 5300 finish OTM with very high probability under any sensible drift model.
- **Theta is empirically observable**: even with the underlying drifting +8.9 over 3 days, OTM voucher mids fell 3–5 XIRECs (VEV_5400 fell 4.74). That's pure decay, ~1.5 XIRECs/day per option, observable without a model.
- **Bot flow is one-sided on OTM strikes**: VEV_5400/5500/6000/6500 are **100% sells, 0% buys** in the trades data (`trades_signals.md`). Bots only dump these — nobody is bidding cheap optionality.
- **VEV_5300 has a structurally rich bid**: ~46 XIRECs above intrinsic, 20-unit avg depth, present continuously. 100% of historical VEV_5300 trades are seller-initiated. There is a permanent buyer waiting to overpay.

### 1.2 Model-based evidence (`p3_options_reference.md` + `options_analysis.md`)

- Bachelier-style IV ≈ 1.8 ticks/√tick vs realised σ ≈ 0.96 → options are ~2× rich on the near-ATM band [5000, 5500]. Caveat: depends on the assumed time-to-expiry; we don't have an explicit TTE in the wiki yet. However, the BS smile fit done in `analysis/round3/r3_smile_clean.py` shows a clean, shallow parabola (typical of Prosperity options books) — no instability.
- All 4 P3 top teams used **BS with `r=0` and `NormalDist().cdf` from stdlib**; nobody used Bachelier. Match their convention to make the numbers comparable across our data and theirs.
- **No bull-spread or butterfly arbitrage** — the strike ladder is monotone. This is consistent with both P3 and P2.

### 1.3 Concrete option trades (ranked by EV per round)

From `options_analysis.md`:

| Trade | EV decay-only | EV expiry-to-intrinsic | Spot delta cost |
|---|---|---|---|
| Short VEV_5300 to −300, delta-hedge | +1,320 | +13,800 | 81 |
| Short VEV_5400 to −300 (stack with 5300) | +1,410 | +4,800 | 39 |
| Short VEV_5200 to −300 | +1,020 | +13,200 | 135 |
| Short VEV_5500 to −300 | +840 | +1,800 | small |

Stacking 5300 + 5400 + 5500 = ~120 spot delta — well inside the 200-lot VELVETFRUIT spot cap. Stack everything and you breach (5200 alone uses 135 spot). **Priority: 5300, 5400, 5500 first; only add 5200 if spot capacity allows.**

VEV_6000 / VEV_6500 are dead at FV ≈ 0 with 1-tick spreads — current trader correctly skips them. Confirmed by both `options_analysis.md` and the sells-only flow signature in `trades_signals.md`. **Do not waste position room here.**

---

## 2. What top P3 teams actually shipped (`p3_options_reference.md`)

Cached source files are at `tmp/p3_research/` — read them. The single most important pattern, from Timo's `timo_trader.py:572-592`:

```python
# Fit done OFFLINE on Day 0 data (curve_fit on iv vs moneyness)
# Then HARD-CODED into the trader as 3 floats.
def smile_iv(self, m: float) -> float:
    a, b, c = 0.2589, 0.0023, 0.1492   # example coefficients
    return a*m*m + b*m + c

def fair_price(self, S, K, tte):
    m = math.log(K/S) / math.sqrt(tte)
    iv = self.smile_iv(m)
    return black_scholes_call(S, K, iv, tte, r=0)
```

Trade trigger is then EMA of `(market_mid − fair_price)` per strike; when the deviation exceeds the EMA by > 0.5 SeaShells, **slam the full remaining 300-limit position**. He claimed 100–150k SeaShells per round just from this.

**Conventions to copy:**

- BS with `r = 0`, `NormalDist().cdf` from `statistics` module.
- Pick a TTE convention (Timo: 365 days; Eric: 250) — what matters is that you fit the smile and price with the same TTE.
- Skip delta hedging in v1. Chris explicitly noted spread-cost on the underlying (~40k/round at his sizing) exceeded hedge value. We have a tighter underlying spread (~3 ticks on VELVETFRUIT) so the calculus might be different — verify in MC before deciding.
- **Universal sizing rule**: full 300 limit on signal. Not 30, not 50. 300.

Ranked port list (from the P3 report):

1. **Hard-code a fitted vol smile**, parabola in moneyness — 2–4h. Source: `tmp/p3_research/timo_trader.py:572-592`.
2. **Quote ±N ticks around theoretical with full size** — 1h. Source: `tmp/p3_research/carter_trader.py:933-952`.
3. **IV-deviation EMA scalping** with full-limit slam — 3–5h. Source: `tmp/p3_research/timo_trader.py:664-704`.
4. **Intrinsic-value MM on deep-ITM VEV_4000/4500** — 1h. Risk-free MM where C ≥ S − K must hold.
5. **Cross-strike monotonicity arb** — 1–2h. Source: `tmp/p3_research/carter_trader.py:803-886`. Low priority because our smile fit shows monotonicity already holds.

**Skip for v1:** delta hedging (revisit later), vega hedging, Bachelier model, Olivia/Camilla counterparty signals (those are R5 in P3, not R4).

---

## 3. Multi-tick signals on the spot products (`multi_tick_signals.md`)

### 3.1 The dominant signal: L1-OBI passive skew

Critical microstructure finding: **deep-MM bots quote perfectly symmetric L1+L2+L3 volumes**. Full-book OBI is identically 0 for 96–100% of ticks on HYDROGEL/VEV_4000/VEV_4500 and ~45% on VELVETFRUIT/ATM-VEVs. Computing OBI on the full book is therefore useless.

**The actionable signal is L1-only OBI**: `(bv1 − av1) / (bv1 + av1)`. It only fires when a real participant joins one side of the top of book.

Sharpe table (from `multi_tick_signals.md`, normalised to per-day frequency):

| Product | L1-OBI Sharpe | Edge per signal | Frequency |
|---|---|---|---|
| HYDROGEL_PACK | +56 | +4–5 ticks at H=1 | 180–310/day |
| VEV_4000 | +40 | +4–5 ticks at H=1 | 180–310/day |
| VEV_4500 | +38 | +4–5 ticks at H=1 | 180–310/day |
| VELVETFRUIT_EXTRACT | +22 | +0.3–0.4 ticks | 3K–6K/day |
| VEV_5000–5500 (ATM) | +22 | +0.3–0.4 ticks | 3K–6K/day |

**Implementation**: a single `skew_ticks` variable on top of penny-jump. When L1-OBI > +0.05, shift our quotes one tick away from penny-jump on the bid (we want to be at the front of the upward move) and skip the ask (we don't want to fade it). Symmetric on the other side.

This is the same signal `donnie.py` and `rugrat.py` already implement. Their tiered version (rugrat: |OBI| > 0.5 → size 30) is the right structure — it just needs to be on every product, not just VELVET.

### 3.2 HYDROGEL z-score reversion

H=50 z-score, threshold |z| > 1: prints +1.65 ticks at H=100, +3.68 ticks at H=200. Win rate 54%, Sharpe +11.4, ~5,400 signals/day. Use as a 50–100 lot directional overlay layered on top of the MM, NOT a take.

VELVETFRUIT has the same family of signal but weaker (+0.69 at H=200).

### 3.3 What is NOT a signal (don't waste code on these)

- **Cross-product lead-lag is dead.** Every off-zero lag correlation between VELVETFRUIT and the ATM VEVs is < 0.02. The vouchers update contemporaneously with the underlying, not lagged.
- **HYDROGEL ⊥ VELVETFRUIT.** Correlation @ lag 0 = 0.006. They are independent products.
- **No fat-tail "trend days".** Kurtosis ≈ 0 on N-tick returns; |R| at the 99th percentile is within 5% of the Gaussian √N · σ_1 expectation. Don't size up for a trend that won't come.
- **Microprice − mid as a TAKE signal loses money** (−2.86 ticks/sig on VEV_5000 — half-spread cost > the 5-tick drift). The exact same signal as a passive quote skew is profitable. **Use it to skew, not to take.**

---

## 4. Trades data — what's actually in there (`trades_signals.md`)

**Critical caveat first:** the R3 trades CSVs (and all of P4) have **`buyer` and `seller` fields completely empty**. IMC anonymised counterparties this competition. Per-bot strategies are impossible from raw data. Pivoted to anonymous-flow analysis (trade side reliably inferred — 100% of trades hit best bid or best ask exactly).

### 4.1 The signals that work

1. **HYDROGEL_PACK aggressive-BUY clusters → FADE**, +7 ticks reversion at H=500 beyond half-spread. n=126, strong t-stat. Best signal in the dataset. Aggressive HYDROGEL buyers are systematically wrong.
2. **VELVETFRUIT_EXTRACT aggressive-SELL clusters → FADE**, +1.7 ticks reversion at H=500. n=166. Smaller per-event but high-frequency.
3. **VELVETFRUIT trade events bias the ITM vouchers** (VEV_4000/4500/5000) by +0.4 to +0.75 ticks at H=500 (n=778). Sub-tick magnitude — **use as a quote-skew on the vouchers, not a directional take**.
4. **VEV_4000 SELL clusters → FADE** (~+3 ticks reversion, n=19) — small sample, suggestive only.

Implementation: maintain a per-product 50-tick same-side trade counter in `traderData` from `state.market_trades`. When HYDROGEL aggressive-BUY count ≥ 3, skew our quote down 2–3 ticks for the next ~100 ticks. Estimated +800–1,500 XIRECs/day on top of MM baseline.

### 4.2 What the trades data tells you about per-tick book turnover

≤ 1.1% per tick on every product. The MM book is very deep relative to taker flow. **Implication: passive quoting is the edge, taking is not** (matches the microprice-take finding above).

---

## 5. What's already in the experimental traders (audit)

| File | Idea added vs `a.py` | Status |
|---|---|---|
| `b.py` | Doubles quote size (5→10), tracks fill counts in traderData for elastic-rate measurement | Stress-test, not a real strategy |
| `belfort.py` | Spread-tiered MM (WIDE=15, TIGHT=5), Black-Scholes pricer behind dormant flag (`ENABLE_BS=False`); skips dead options | BS pricer present but disabled — was −170k in MC because vouchers decoupled in MC sim |
| `donnie.py` | OBI + microprice skew on VELVET (68.5% hit, corr +0.28); BS-delta-based voucher leverage on VEV_4000/4500 when VELVET saturates | Portal-only valid (MC decouples vouchers from spot); good template |
| `rugrat.py` | Tiered OBI (weak/medium/high); size 30 on |OBI|≥0.5 = 95% hit; forced unwind on inventory brake | Most aggressive sizing of the four, but only on VELVET + voucher leverage |

**Also in tree:** `tmp/portal_368660/` has a portal trader run (368660.py + .json + .log) — referenced in calibration commit, gives recent portal signal in case we want to compare PnL.

The right move is **not** to ship one of these as-is. The right move is to merge:

- `belfort.py`'s spread-tiered passive MM as the base layer
- `donnie.py`/`rugrat.py`'s tiered OBI signal as a quote skew on every product (not just VELVET)
- A new options-pricing module (currently missing from all of them) — this is the biggest gap
- New: the HYDROGEL aggressive-BUY-cluster fade from `trades_signals.md`

---

## 6. Proposed v1 trader (incremental from `a.py`)

Build order, biggest EV first, each step independently MC-testable:

### Step 1 — size up the existing penny-jump (1h)

`R3_QUOTE_SIZE: 5 → 30` on all 10 active assets. This alone should ≥ 4× the baseline — current trader is leaving most of the spread on the floor. Validate in MC first; if the soft-position-fraction still cleanly bleeds inventory, ship.

### Step 2 — port the OBI skew from rugrat to all 10 products (3h)

Tiered: |L1-OBI| < 0.15 = no skew; 0.15–0.5 = skew our better-side quote ±1 tick further out; ≥ 0.5 = skew ±2 and double the size on the favoured side (don't drop the unfavoured side, just lower its size). Source: copy `rugrat.py`'s tier logic.

### Step 3 — short the rich OTM vouchers to limit (4h)

For each of {VEV_5300, VEV_5400, VEV_5500}: if our position > −300 and best_bid is ≥ (estimated_FV + 1), sell aggressively to whatever depth is on the bid. Target full −300 within ~500 ticks of the round start. **Don't delta-hedge in v1** (per Chris's spread-cost finding; revisit if PnL volatility is too high).

Estimated FV for these strikes: in absence of a fitted smile (Step 5), use the conservative `max(intrinsic, 0.5)` — VEV_5300 intrinsic is 0 at S=5262, so any non-zero bid is rich. For VEV_5300, the bid sits ~46 XIRECs above intrinsic; that's the edge per share.

### Step 4 — HYDROGEL aggressive-BUY cluster fade (2h)

Maintain a 50-tick rolling count of aggressive HYDROGEL BUYS in `traderData`. When count ≥ 3, skew HYDROGEL ask down 3 ticks for the next 100 ticks. This is purely a quote-skew, not a take.

### Step 5 — fitted vol smile + BS pricer (4–6h)

Port Timo's parabolic-in-moneyness smile fit. Use 3-day data we already have to fit on Day 0+1, validate on Day 2. Hard-code coefficients into the trader. BS with `r=0`, NormalDist().cdf from `statistics` stdlib, TTE = round_progress in days (same convention everywhere).

Then: per-strike `theo_diff = market_mid − bs_fair`, EMA the diff, take **full 300-lot positions** when current diff exceeds EMA by > 0.5 XIRECs.

This step subsumes Step 3 (which becomes unnecessary once the smile is in) and is what gets us to the 30k+ band.

### Step 6 — HYDROGEL z-reversion overlay (2h)

50-tick z-score, |z| > 1 → 50-lot directional take with H=200 unwind. Sharpe +11.4, fits naturally on top of the MM.

---

## 7. Open questions that need answers before Step 5 ships

- **Time to expiry** — the wiki page didn't explicitly state TTE for VEV vouchers. Check the R3 wiki page or competition portal directly. Default assumption (matching most P3 setups): expiry at end of round, so TTE shrinks linearly across the round's 10K ticks.
- **Will MC decouple vouchers from VELVETFRUIT?** Yes (per `donnie.py`'s caveat) — the Rust simulator treats each asset independently, so any cross-asset strategy (including delta hedging and the BS pricer) will look worse in MC than at portal scale. **Decision rule: use MC for the per-asset MM/OBI changes, use portal subs for cross-asset validation.**
- **What's the actual portal P&L distribution at the top end?** Worth checking the leaderboard and asking what 60k+ teams are publicly saying. P3 winner Timo's 100–150k/round was on a different underlying; our cap is unclear. Set a 30k portal target for v1, evaluate from there.

---

## 8. Files (so future-you doesn't re-derive)

Inputs:

- Raw CSVs: `data/prosperity4/round3/prices_round_3_day_{0,1,2}.csv`, `trades_round_3_day_{0,1,2}.csv`
- Per-asset calibration: `calibration/<asset>/calibration.md` and `params.json`
- Existing trader: `traders/round3/a.py` (active) + `b.py` / `belfort.py` / `donnie.py` / `rugrat.py` (experiments)
- P3 reference code (cached): `tmp/p3_research/` (timo_trader.py, carter_trader.py, chris_trader.py, eric_trader.py)
- Last portal sub artefacts: `tmp/portal_368660/`

Analysis outputs (this round):

- `analysis/round3/options_analysis.md` + `.py` + `tmp/r3_options/options_findings.json`
- `analysis/round3/p3_options_reference.md`
- `analysis/round3/multi_tick_signals.md` + `.py` + `.json`
- `analysis/round3/trades_signals.md` + `trades_signal_mining.py` + 6 supporting CSVs
- `analysis/round3/r3_smile_clean.py` + `smile_coefs_day2.json` (BS smile fit on Day 2)
- `analysis/round3/velvet_signal_check.py` + `velvet_strong_signal.py` (basis of donnie/rugrat OBI work)
