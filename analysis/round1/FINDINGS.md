# Market Findings — OSMIUM + PEPPER (R1 + R2 data)

Scope: consolidated picture of these two products, verified across **6 days** of data:
  - R1: `data/prosperity4/round1/*_day_{-2,-1,0}.csv`
  - R2: `data/prosperity4/round2/*_day_{-1,0,1}.csv` (delivered 2026-04-17)

Supersedes the deleted `OSMIUM_ANALYSIS.md` + analysis scripts — those were outdated and partially wrong.

Scripts: `analysis/round1/osmium_scan.py`, `analysis/round1/pepper_scan.py` reproduce R1 results. The R2 data confirms every signal parameter within ±1 percentage point — **no re-calibration needed**.

Key R2-specific: R2 PEPPER day 1 starts at 13,000 and ends at 13,999 (same +0.1/tick drift, continuous from R1). Our `--ipr-start-fv 13000` MC flag is correct for the final-eval scoring day.

---

## ASH_COATED_OSMIUM

### Bot book (calibrated, high confidence)
- **Bot1** (outer): `floor(FV) - 10` / `ceil(FV) + 10`, vol `U(20,30)`. 80% present per side, independent.
- **Bot2** (inner): `round(FV) - 8` / `round(FV) + 8`, vol `U(10,15)`. 80% present per side, independent.
- **Bot3** (noise): 7.6% of ticks, single-sided, offsets `{-3, -2, +1, +2}` from `round(FV)`. Crossing vol `U(4,10)`, passive vol `U(1,5)`.
- Symmetric spread = 16 holds on **~59%** of ticks.

### FV dynamics
- Mean-reverting. Observed steps (at symmetric ticks) are integer ±1 in 99% of non-flat ticks; ~1800 non-zero moves per day.
- Step AR(1) coefficient: **−0.32** → next move is biased toward reversal.
- OU pullback to long-run mean ≈ 10,000, half-life ~90 ticks (varies ~50–110 across days).

### Verified signals

| Signal | Accuracy | Notes |
|---|---|---|
| **Unconditional reversal after any move** | 65.9% | same as prior analysis, verified on day 0 |
| **Conditional reversal given non-zero next move** | **82–88%** | n=293–324 per day; much stronger than the headline 66% |
| **L2 price-gap pattern** (bid_gap, ask_gap) | **86–89% of non-flat next moves** | `(2,3)` → UP, `(3,2)` → DOWN. Persists across all 3 days, n≈1800–1900 per pattern per day. **New finding, not in prior docs.** |

**Why L2 gap works**: it reveals the fractional part of true FV. For FV=10000.3: Bot1 uses floor/ceil (9990 / 10011) and Bot2 uses round (9992 / 10008). Bid gap = 9992−9990 = 2; ask gap = 10011−10008 = 3. Pattern `(2,3)` means fractional < 0.5 → true FV sits closer to the UP rounding threshold → small move pushes `round(FV)` up → detected as +1.

Expected one-tick PnL per unit long held during `(2,3)` state ≈ **+0.22** (driven by 30% non-flat, 87% of those up).

### Signals we ruled out
| Probe | Result |
|---|---|
| OBI at non-16 spread ticks with threshold 0.3 / 0.5 / 0.7 | Weak (52–54% next-direction accuracy). Prior claim of "85% current-direction accuracy then 68% reversal" does not reproduce cleanly on raw day-0 next-move data. |
| L1 volume magnitude at symmetric ticks (bv1 = av1 = 10..15) | Uniform, no predictive power for next move. |
| Presence/absence of a trade in next 100/300/500ts window | Move rate is ~31% with trade and ~31% without — trade occurrence carries no directional signal. |
| Trade aggressor direction (price vs L1) | Weak (55% fade after buy-aggressor, no signal after sell-aggressor). Overlaps with last-FV-move signal. |
| Trade clustering (multi-trades same ts) | 99% of ticks have exactly 1 trade. Only 3–6 ticks/day have 2 trades. No signal. |
| Short inter-trade gap (<200ts) | Sample too small (n=23–38/day), no clean effect. |
| Bot1 asymmetry (`_detect_bot1_asym` in `a.py`) | Turns out to be a rounding artifact of `ceil(FV)+10` vs `floor(FV)-10` when FV is non-integer. **Zero predictive power.** Currently unused-but-present in `a.py`. |

### Strategy attempts that did NOT help vs baseline a.py (~19.3k PnL MC)
| Attempt | Result |
|---|---|
| Size caps 40 → 60 → 80 | No change. Elastic takers sample `qty ∈ {2..10}`, cap never binds. |
| MR-based quote price shift (FV±6 when signal positive) | Lost ~150 PnL. Tighter quotes = smaller edge per fill at same fill rate. |
| MR-based size bias (55/25 instead of 40/40) | No change. Elastic quantity caps at 10; 25 ≥ 10 so no constraint fires. |
| L2-gap signal → pull one side (ask on `(2,3)`) | Lost ~720 PnL. Sacrificing ask fills costs 7/unit edge, signal pays only ~0.22/unit/tick over ~5-tick state duration. |
| PEPPER ask tier at FV+6 (penny-jump Bot2) | Lost ~120 PnL. Bot2 rebuild costs FV+7, so round-trip is −1/unit. |
| PEPPER threshold lowering (60→40) | No change. Position rarely drops below 60 once maxed. |

### Strategic limits of passive MM here
1. **Elastic taker events fire at fixed 4% rate and pick sides 50/50 randomly.** No matter what we post, fill rate is ~0.04/tick per side and direction is uncorrelated with FV moves.
2. **Elastic quantities max at 10**, so any posted size ≥ 10 is equivalent.
3. **Crossing Bot2's 16-wide spread** costs 8/unit, but the L2-gap signal only pays ~0.22/unit/tick over ~5 ticks = 1.2 max. **Aggressive taking on this signal is strictly −6.8 EV.**
4. Consequence: **any reversal/mean-reversion signal is automatically captured by natural MM dynamics** (we accumulate long when FV drops, short when FV rises, so position aligns with reversal by construction). Explicit signal overlays are redundant.

### Where portal reality may diverge from sim (unmeasured, worth watching)
- Real elastic takers may be *informed* (hit our ask preferentially before FV jumps up). If so, **pulling ask on `(2,3)` state would be net positive on the portal even though it's negative in sim** (the sim assumes dumb random takers).
- Portal trade CSV rows have empty `buyer`/`seller` fields; we've only verified the book-level signals. There may be trade-level features we haven't measured.

### Cross-check vs winning Prosperity 3 / Prosperity 2 teams (grep of Timo 2nd, Carter 9th, Chris 7th, Eric 2nd P2, Mark guide)
| Winner technique | Do we have it? | Notes |
|---|---|---|
| FV from volume-filtered bot anchors (Bot1/Bot2) | ✓ yes | `_fv()` in `a.py` already does weighted Bot1/Bot2 anchoring. |
| Penny-jump wall, skip size-1 stubs | ✓ yes | `_find_wall_bid/_ask` skips Bot3 via len-based + 5-tick distance test. |
| `clear_position_order` (Eric's +3% on RESIN) | ✓ yes, inline | Lines 237–259 of `a.py`: when `pos_after > 0`, match all bids ≥ FV. More greedy than Eric's variant (we match at each bid's price, not at FV). |
| `adverse_volume` filter on taking (cap take size) | ~ partial | Our take already bounded by position room; we don't explicitly cap by *counterparty size*. In our sim Bot1 caps ≤ 30 and Bot3 crossing ≤ 10, so no bad actor to filter out. |
| Soft-position-limit skew (shift away-side by 1 when past N) | ~ broken | `a.py`'s skew is gated on `mode != 0` (the Bot1-asym signal, which is noise). Effectively never fires. **Worth replacing with unconditional soft-limit skew.** |
| `reversion_beta` β-shift of fair value (Eric STARFRUIT) | ~ partial | `a.py` tracks `sig_mode` and `prev_raw` but the raw signal is rounding noise. We could replace with `β=-0.32` on log returns. Eric footnote: "very very likely overfit, delta was small". |
| Reserve 20% of limit for signal-driven aggressive takes (Timo) | ✗ no | Not worth on OSMIUM: crossing Bot2's 16-wide spread costs 8, vs ~0.22/unit/tick signal gain. Negative EV. |
| Microprice / multi-level OBI | ✗ no winner uses it | Empty in Mark's indicator guide; grep across all 5 winner repos = 0 hits. Our existing obi-shift at spread≠16 is already more than any winner ship-code. |

**Agent's honest assessment**: our code has more signal than the top-team R1 shipped code. The only clean delta is the **broken soft-limit skew** (it's gated on a dead signal). Replacing it with an unconditional `if pos > 40: ask -= 1` pattern is worth a 30-minute MC check.

---

## INTARIAN_PEPPER_ROOT

### Bot book (confirmed via proportional-offset calibration)
- Bot1: `floor(FV·(1−3/4000))` / `ceil(FV·(1+3/4000))`, vol `U(15,25)`.
- Bot2: `floor(FV·(1−1/2000))` / `ceil(FV·(1+1/2000))`, vol `U(8,12)`.
- 80% presence per side, independent. Same ~80% pattern as OSMIUM.

### FV dynamics
- Deterministic drift **+0.1/tick exactly**. Verified via linear fit of L1 mid across all 3 days: slope = **+0.1000/tick**, residual std ~1.1–1.3 (= book spread noise, not FV noise).
- Drift is constant across first half vs second half of each day → no timed modulation.
- FV start: `10,000` day −2 → `11,000` day −1 → `12,000` day 0. R1 day 0 ended near 13,000; R2 day 0 starts from ~13,000 (confirmed by hold-1 submission 274082).

### Trade characteristics
- 332–344 trades/day, mean size ~5.2, median 5. No bursts.
- Aggressor split ≈ 50/50 (buy_vol ≈ sell_vol) despite the deterministic up-drift.
- No inside-spread or through-spread trades in the data.

### Signals we've considered
- L2 gap patterns dominated by (3,3) (~75% of symmetric ticks), with small (2,3) / (3,2) populations. Unlike OSMIUM, the proportional-offset formula means the rounding-boundary signal is diluted.
- No evident exploitable pattern beyond the drift itself.

### Current strategy and its ceiling
- Sweep asks with vol ≤ 15 each tick (skips Bot1 wall, takes Bot2 + Bot3).
- Passive bid at best-bid + 1 for remaining room.
- Sell tiers at FV+8 (vol 10, pos ≥ 60) and FV+9 (vol 15, pos ≥ 75).
- Result: ~79.3k PnL, final pos = 80 every session, std = 82.
- **Theoretical max = drift × 80 × 10000 ticks = 80k**. We're at 99% of ceiling.

### What won't help
- MM cycling below pos=60 at FV+6: loses to Bot2 rebuild cost.
- Lowering tier-1 threshold: doesn't fire (pos stays at 80).
- Taking Bot1: marginal 3-4 ticks of earlier position-fill = ~30 XIRECs.

---

## Bottom line

- **PEPPER: solved**, at 99% of theoretical ceiling. Leave `a.py`'s PEPPER code alone.
- **OSMIUM: 19.3k MC mean is near the sim's passive-MM ceiling.** The L2-gap signal is real (86–88% on real data, 69–71% in sim) but no passive exploit converts it because elastic fills are direction-random and Bot2's spread is too wide to cross.
- **Strongest open lead**: the real portal may have informed elastic flow, in which case defensive use of the L2-gap signal (pull fills on the wrong side) would show up as positive PnL on the portal while testing neutral-to-negative in MC. Worth a portal experiment, not worth more sim iteration.
- **Everything in the "Strategy attempts that did NOT help" table should not be re-tried** without a concrete new reason. This is the anti-repetition ledger.
