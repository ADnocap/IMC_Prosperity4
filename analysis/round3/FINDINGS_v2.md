# Round 3 — Findings v2 (post deeper-quant analysis)

**Generated:** 2026-04-25
**Status:** Synthesis of three new analyses (delta-hedged-options, signal-decay, cross-strike) on top of `FINDINGS.md`.
**Goal:** define the next trader and the next param search after `max.py` / `stratton.py` topped out at ~10–13k MC and ~17k portal.

The three new reports — read them for the underlying numbers:

- `delta_hedged_options.md` — spot-cap and spread-cost analysis of short-vol-with-delta-hedge
- `signal_decay.md` — per-signal alpha half-life, AND-gate compounding, vol/trend regimes, Kelly sizing
- `cross_strike.md` — butterflies, vertical spreads, theta carry, cross-strike OBI

---

## TL;DR — the picture changed

The v1 strategy (FINDINGS.md) was: short the rich OTM strikes outright, optionally delta-hedge later. The new analysis kills the directional short-vol thesis and replaces it with **cross-strike relative-value mean reversion**, which is naturally delta-light and has the best Sharpe in the dataset.

The four key updates vs v1:

1. **Outright short-vol with delta hedge: weak.** Best PnL +166 to +1,033/day (`delta_hedged_options.json`). Spot 200 cap binds at full-book size (need 364 delta neutralised), hedge spread cost is 5 ticks not 3, and per-day std (3k) > mean (166). N=3 is not edge.
2. **Per-strike rich list flips vs the smile.** Earlier "all OTM are rich" was vs flat-vol. Vs the fitted parabolic smile, **VEV_5400 is the cheapest leg** (z = −0.73) and 5300/5500 are the rich ones (z = +0.36/+0.35). This breaks the "short 5300+5400+5500 to limit" plan from v1.
3. **The 5300/5400 vertical spread is the single best signal in the dataset**: pooled mean deviation +3.51, std 1.05, half-life 9.3 ticks, **daily Sharpe 162, EV per day 7,575**, replicated stably across all 3 days. Naturally delta-light (~0.20 spread delta).
4. **HYDROGEL has a real directional signal worth sizing into.** L1-OBI mean PnL is **flat in horizon** at +3.5 ticks per signal out to H=200 (Sharpe 2.08 at H=1, drift is permanent). Combined with `rev_z50` `|z|>1` → AND-gate adds +0.4 ticks on tail VEVs. Signal_decay recommends sizing HYDROGEL to ~50% of limit on rev_z50, vs current MR_K=0.06 (= ~12% at z=2) — we are under-sized by ~4×.

Realistic uplift estimate (additive on the matched-FV historical scale):

| Bucket | EV / day | Confidence | Source |
|---|---|---|---|
| 5300/5400 vert spread MR (full pos 300) | 7,575 | high (S=162, 3-day stable) | `cross_strike.json` |
| 5200/5400 vert spread MR (full pos 300) | 5,927 | high (S=126, 3-day stable) | `cross_strike.json` |
| 5300/5500 vert spread MR | 3,415 | medium (S=110, day-2 sign-flip) | `cross_strike.json` |
| Theta-carry: short 5300 / long 5500 (pos 100) | ~330 (decay) / ~4,000 (expiry) | structural | `cross_strike.json` |
| Sell 5300/5400/5500 fly @ N=100 | ~600 | structural rich +6 z=4 | `cross_strike.json` |
| Buy 5200/5300/5400 fly @ N=100 | ~400 | structural cheap −4 z=3 | `cross_strike.json` |
| HYDROGEL rev_z50 directional @ pos 100 | 1,500–3,000 | medium-high (S 11.4) | `signal_decay.json` |
| L1-OBI passive skew on all 10 products | 2,000–4,000 | high (Sharpe 22–56) | prior `multi_tick_signals.md` |
| Stratton-style passive MM baseline (kept) | ~10,000 | proven (portal +17k) | `stratton.py` |

Stack the cross-strike block (~17k) on top of stratton's 10k MR baseline → realistic 25–35k/round. Top teams' 60k+ likely also includes a working IV-deviation slam that requires a more variable smile than R3 has (smile residual std 0.01 = 3.85 in price), so capping our ambition at the 30k band is honest.

---

## 1. Why the v1 plan to short rich OTM strikes does not work on R3 data

`delta_hedged_options.json:203-208`:

| Strike | Per-day PnL unhedged (3 days) | Notes |
|---|---|---|
| VEV_5200 | **−1,900** | Underlying drifted +9, calls 101→119 |
| VEV_5300 | −600 | High vega, exposed to vol ticks |
| VEV_5400 | +200 | Low delta, theta dominates |
| VEV_5500 | +100 | Lowest delta, smallest credit too |

The per-strike mean richness vs the smile (`cross_strike.json:634-677`):

| Strike | Mean residual | Std residual | z-richness |
|---|---|---|---|
| 5000 | +0.15 | 1.46 | +0.10 |
| 5100 | +0.12 | 3.56 | +0.03 |
| 5200 | +0.79 | 4.08 | +0.19 |
| 5300 | **+1.28** | 3.56 | **+0.36** |
| 5400 | **−2.22** | 3.03 | **−0.73** |
| 5500 | +0.56 | 1.57 | +0.35 |

VEV_5400 is structurally **cheap** vs the smile — so the v1 plan to "short 5300+5400+5500 to limit" was actually shorting a cheap leg. Replacing 5400 with the long side of a spread fixes this.

Hedge math (`delta_hedged_options.json:176-188`):
- Avg spot spread = 5 ticks (not 3 as v1 assumed), round-trip on 100 spot = 500 XIRECs.
- Full short on 4 strikes × 300 = 364 spot delta vs 200 cap → **only 55% neutralizable**.
- Vega exposure at full book = 200,000 per 1.0 vol unit → 2,000 XIRECs per 1% vol move > daily alpha. Vega is the dominant residual risk, and we have no way to hedge it.

Decision: **drop directional outright short-vol**. Pivot to cross-strike spreads where deltas net naturally and vegas partially cancel.

---

## 2. The new core trade: cross-strike vertical-spread MR

`cross_strike.json:202-545`. Top 5 spreads ranked by daily Sharpe of the "trade deviation back to BS-smile fair" strategy:

| Pair (low / high) | Pooled dev | Std | Half-life (ticks) | EV / day | Daily Sharpe |
|---|---|---|---|---|---|
| 5300 / 5400 | +3.51 | 1.05 | 9.3 | **7,575** | **162** |
| 5200 / 5400 | +3.01 | 1.26 | 10.2 | 5,927 | 126 |
| 5300 / 5500 | +0.73 | 0.94 | 7.6 | 3,415 | 110 |
| 5100 / 5500 | −0.44 | 0.95 | 3.2 | 7,687 | 100 |
| 5100 / 5400 | +2.34 | 1.18 | 6.3 | 5,974 | 104 |

Strategy: for each pair compute `dev(t) = market_spread(t) - smile_theoretical(t)`. EMA-smooth `dev` over a few ticks. When `dev > +k·σ` → **short** the spread (sell K_low, buy K_high). When `dev < −k·σ` → **long**. Unwind on mean-reversion or after H ≈ 30 ticks (3× half-life).

Why this is the right move structurally:
- Spread delta is the difference of strike deltas. For 5300/5400: Δ_5300 − Δ_5400 ≈ 0.39 − 0.20 = **0.19**. At full pos 300 in the spread → 57 spot delta, easily inside 200 cap.
- Vega partially cancels: 5300 vega 258, 5400 vega 186 → spread vega ≈ 72 (vs 258 outright). 75% reduction in vol risk.
- The mispricing is **structural**, not noise: per-day deviations are +3.84/+4.30/+2.38 on 5300/5400 with std ~1 — the market consistently overprices low-strike vs high-strike inside the smile.

---

## 3. Theta carry + butterfly structural trades

`cross_strike.json:546-587`. Carry-style: enter on day 0, hold to expiry.

| Trade | Credit | Daily theta | EV at pos 300 to expiry |
|---|---|---|---|
| Short 5300 / Long 5500 vertical | 40.1 | +3.27 | **+12,036** |
| Short 5300 / Long 5400 vertical | 30.8 | +1.48 | +9,242 |
| Short 5400 / Long 5500 vertical | 9.3 | +1.79 | +2,793 |

The 5300/5500 vertical earns +3.27/day per unit, has ~0.31 delta (at pos 100 → 31 spot, trivial to hedge). At pos 100 we collect ~+330/day from decay alone, and the price walks back toward intrinsic on top of that.

Butterflies (`cross_strike.json:28-200`) — none have negative value (no instant arb), but two are persistently mispriced:

| Triple | Pooled mean | Theo mean | Pooled deviation | Trade |
|---|---|---|---|---|
| 5200/5300/5400 | 17.98 | 21.99 | **−4.01** (z ≈ −3) | BUY fly: +1×5200 − 2×5300 + 1×5400 |
| 5300/5400/5500 | 21.50 | 15.21 | **+6.29** (z ≈ +4) | SELL fly: −1×5300 + 2×5400 − 1×5500 |

Both flies are stable across all 3 days. Notice the BUY-fly trade is `+1×5200 −2×5300 +1×5400` — it is short 2× of 5300 and long 5400, which is consistent with our finding that 5400 is cheap and 5300 is rich.

---

## 4. HYDROGEL is sizable directional

`signal_decay.md` recommendations:
- **HYDROGEL on `rev_z50` `|z|>1`**: size to ~100 lots (50% of limit), hold 200–500 ticks. Mean PnL +2.4 to +4.1 ticks at H=200..1000. Sharpe per signal 0.10–0.15, but ~5,400 signals/day → daily Sharpe ~10. Current trader (stratton MR_K=0.06) sizes to ~24 lots at z=2 — under-sized by ~4×.
- **L1-OBI on all products**: at H=1, mean +3.5 ticks per signal, drift is **permanent** (not exponential decay). The right play is full-quote-size passive skew, not a take.
- **AND-gate `l1_obi & rev_z50` on tail VEVs (5400, 5500)**: adds +0.17 to +0.38 ticks vs single-signal. Worth implementing on those two strikes.

What does NOT work (`signal_decay.md`):
- Cross-product lead-lag at multi-tick horizons — dead, |corr| < 0.01 at L=5..500.
- Volume-conditioned signal selection — uplift +0.01 to +0.03, not actionable.
- Trend regimes — never; always mean-reverting or noise.

---

## 5. Cross-strike OBI signal (timing the entries)

`cross_strike.json:678-727`. The signal `OBI(K_low) − OBI(K_high)` predicts next-tick spread move with corr **+0.43 to +0.48**, replicated all 3 days.

| Pair | Avg corr | Conditional drift on \|combo\|>0.5 |
|---|---|---|
| 5300/5400 | +0.43 | +0.35 / −0.36 ticks |
| 5200/5300 | +0.48 | +0.39 / −0.38 ticks |
| 5200/5400 | +0.36 | +0.36 / −0.33 ticks |

Use this to time entries on the spread MR trade — wait for `OBI_lo − OBI_hi` to confirm the direction we want to fade. Eliminates ~40% of false positives.

---

## 6. The MC vs portal reliability problem (still real)

The MC backtester treats each voucher's FV as an **independent Brownian motion** — the voucher mids don't follow VELVETFRUIT. This means:

- **Cross-strike strategies CANNOT be validated in MC.** A 5300/5400 vertical spread would see uncorrelated noise instead of a mean-reverting structural mispricing. MC will assign random PnL to the trade.
- **Outright delta hedging CANNOT be validated in MC** for the same reason.
- **MC IS valid for**: per-product passive MM, L1-OBI skew, HYDROGEL rev_z50 (single product), stratton-style MR.

Decision rule for v3:
- **MC-validatable layer**: per-product MM, L1-OBI skew, HYDROGEL rev_z, stratton-style MR baseline. **This is what the param search optimises.**
- **Belief layer (portal-validated only)**: cross-strike spread MR, fly trades, theta carry. **Hard-code the structural defaults from `cross_strike.json`** and validate by sending the trader to the portal.

---

## 7. Proposed v3 trader structure

Building on stratton:

```
TRADER LAYERS (additive, each independently toggleable for ablation)

Layer A — Stratton baseline MR (KEEP)
  - VELVETFRUIT, VEV_5000-5400 → EMA z-score MR with MR_K=0.06
  - HYDROGEL, VEV_4000/4500/5500 → OBI MM
  - Already worth ~10k portal

Layer B — HYDROGEL rev_z50 directional (NEW — MC-validatable)
  - z = (mid - MA50) / sigma50
  - When |z| > 1 → take 50-100 lots in MR direction
  - Hold horizon H = 200 ticks (unwind via aging counter in traderData)
  - Param: REVZ_THRESHOLD, REVZ_SIZE, REVZ_HOLD

Layer C — L1-OBI skew on all 10 products (NEW — MC-validatable)
  - When L1-OBI > 0.15 → quote one tick away from penny-jump on the better side
  - When L1-OBI > 0.5 → quote two ticks + double size on the favoured side
  - Per-product enable; expected highest impact on HYDROGEL/VEV_4000/4500 (Sharpe 38-56)

Layer D — Cross-strike vertical spread MR (NEW — portal-validated only)
  - For each pair in {(5300,5400), (5200,5400), (5300,5500)}:
    - Compute market spread = mid(K_low) - mid(K_high)
    - Compute theoretical spread from BS smile (hard-coded coefs from cross_strike.json:9-21)
    - dev = market - theo, EMA over 5 ticks
    - When dev > k*sigma_dev AND OBI_lo - OBI_hi confirms → enter spread
    - Unwind when dev returns to 0 OR after 30 ticks
  - Position sizing: bound by per-strike 300 cap and remaining inventory from Layers A/B

Layer E — Static structural overlay (NEW — portal-validated only)
  - Establish at session start (or whenever inventory allows):
    - +N×5400 / -N/2×5300 / -N/2×5500 (sell rich 5300/5400/5500 fly), N up to 100
    - +N×5200 / -N×5300 + N already implicit from D, do NOT double-up
  - Persistent positions; carried for theta/expiry

Layer F — Penny-jump base MM (KEEP from a.py)
  - Always-on passive quote at best±1 with size 30 on every product
  - Inventory-skew via SOFT_POS_FRAC=0.6
```

Layer A + B + C is what goes into the param search (MC can score it). Layers D + E are belief-driven — hard-coded reasonable defaults from the cross-strike analysis, validated only by portal subs.

---

## 8. Two new param searches to launch

### Search v3 — multi-horizon directional sizing on top of stratton

Stratton optimised passive MM under MR_K=0.06 (tiny). Search v3 keeps the stratton skeleton but **layers in HYDROGEL rev_z50 sizing** and **per-product OBI skew tiers**, with Sharpe + p05 objective for reliability.

Params to search (10 total):

| Param | Range | Reason |
|---|---|---|
| HYDROGEL_REVZ_THRESHOLD | [0.5, 2.0] | When does rev_z fire |
| HYDROGEL_REVZ_SIZE | [20, 150] | Position taken on signal (limit 200) |
| HYDROGEL_REVZ_HOLD | [50, 500] | Unwind horizon |
| OBI_TIER1_THRESHOLD | [0.10, 0.30] | First skew tier |
| OBI_TIER2_THRESHOLD | [0.30, 0.70] | Second skew tier (full skew) |
| OBI_SKEW_TICKS | [1, 3] | How far to lean quotes |
| MR_K (stratton) | [0.04, 0.15] | Re-search around 0.06 — the sweet spot may be a touch larger now that we add directional layers |
| MR_MM_LEVEL_SIZE | [10, 30] | Passive size — search up since we're more confident |
| BASE_MM_SIZE | [10, 50] | Penny-jump baseline |
| AND_GATE_TAIL_VEV | {true, false} | Whether to AND-gate l1_obi & rev_z on 5400/5500 |

Objective: `1.0*sharpe + 0.0001*mean_pnl + 0.0002*p05_pnl` (heavier on tail than v2).

### Search v4 — cross-strike vertical-spread MR (NOT MC-validatable)

This one is trickier — MC can't score it. Two options:

**Option A**: Search on a CSV-replay backtester instead of MC. We have 3 days of data; train on day 0+1, OOS on day 2. Run a deterministic replay that matches our orders against the historical book. Param search on (k_sigma, hold_horizon, ema_span, position_size). Honest OOS but only 1 path.

**Option B**: Bypass param search entirely, hard-code reasonable defaults from `cross_strike.json` (k_sigma=2, hold=30 ticks, position=300, ema_span=5), and validate by submitting to the portal directly. Portal returns ground truth and is also 1 path. Faster, but no exploration.

**Recommendation**: do Option B for the portal sub; if it improves we can build a CSV-replay search later.

---

## 9. What we explicitly skip

- **Outright short-vol with delta hedge**: marginal +166 to +1,033/day net (`delta_hedged_options.json:226-236`), spot cap binds at full size, vega risk dominates. Revisit only if we have a vol-of-vol signal.
- **Cross-product directional bets** (HYDROGEL → VELVET, VELVET → VEV): cross-corr dead at every tested lag.
- **Bachelier vol model**: P3 winners all used BS, our smile fit is parabolic-in-log-moneyness, sticking with that.
- **Olivia/Camilla counterparty signals**: P3 R5 only, not in P4.
- **Volume-conditioned filters**: uplift +0.01–0.03 ticks, not actionable.

---

## 10. Files

Inputs (carried over):
- Raw CSVs: `data/prosperity4/round3/prices_round_3_day_{0,1,2}.csv`, `trades_round_3_day_{0,1,2}.csv`
- Smile coefs (per-day refit done in cross_strike.py): `analysis/round3/smile_coefs_day2.json` + `cross_strike.json:2-27`
- Existing winners: `traders/round3/max.py`, `traders/round3/stratton.py`

New analysis (this round):
- `analysis/round3/delta_hedged_options.{md,py,json}`
- `analysis/round3/signal_decay.{md,py,json}`
- `analysis/round3/cross_strike.{md,py,json}`

Built and shipped:

- `studies/round3_tunable_v3.py` — Layer A+B+C+F (MC-searchable). Defaults give MC mean +11,000 / std 6,555 (matches stratton +10,768 / 6,815 within 1 std).
- `studies/round3_param_search_v3.yaml` — 11 params, 400 trials, p05-heavy reliability objective. **Running 2026-04-25 12:51** in `tmp/optimizer/round3_param_search_v3_20260425_125137/`.
- `traders/round3/rothschild.py` — Layer D (cross-strike vert MR on 5300/5400 + 5300/5500). Static fly tilt disabled in v1 after it cost ~10k in MC. Defaults give MC mean +7,526 / std 6,785 — the -3.5k vs stratton is expected cross-strike scalp noise on independent voucher FVs in MC; portal should flip positive on the real MR alpha.

Validation paths:

- `tunable_v3` → standard MC + 200-session OOS retest after search completes.
- `rothschild` → portal sub only (MC cannot validate cross-strike). Compare portal PnL vs stratton's +17,449 baseline.
