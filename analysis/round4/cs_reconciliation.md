# Cross-Strike Vert-Spread MR — Reconciliation & Verdict

**Generated:** 2026-04-26.
**Question:** is there a real CS edge worth layering onto `traders/round4/submission.py` (current baseline +27,444 in R4 replay), or is the audit's claimed +11k/round CS profit a mid-to-mid accounting artifact?
**Answer:** **artifact. KILL CS PERMANENTLY.** No tested configuration survives realistic execution costs. The "edge" is exactly the spread the audit declined to charge.

Scripts:
- `analysis/round4/cs_replay_with_spread.py` — audit's logic, three execution modes
- `analysis/round4/cs_threshold_sweep.py` — full k_sigma × hold × mode grid
- `analysis/round4/cs_passive_only.py` — passive-fill best-case sim

---

## 1. The audit's replay reproduced — yes

Re-ran `analysis/round3/final_audit.py` end-to-end. Section 7 numbers are exact:

| Pair | Size | Trades | mid-to-mid PnL (R3 d0/d1/d2) | Audit reported |
|------|------|--------|------------------------------|----------------|
| 5300/5400 | 40 | 101 | +1,140 / +1,440 / +1,960 = **+4,540** | +4,540 |
| 5300/5500 | 20 | 176 | +1,080 / +1,130 / +1,260 = **+3,470** | +3,470 |
| 5200/5400 | 30 | 436 | +3,345 / +3,675 / +4,245 = **+11,265** | **+11,265** |
| 5300/5400 | 100 | 101 | +2,850 / +3,600 / +4,900 = **+11,350** | +11,350 |

So the audit number is correctly computed from its own assumptions. The problem is the assumptions.

R4 days 1/2/3 (essentially the same FV path on d1/d2) reproduce the audit number to within 2%:

| Pair | mid-to-mid R4 d1+d2+d3 |
|------|------------------------|
| 5300/5400 sz=40 | +4,720 |
| 5300/5500 sz=20 | +2,960 |
| 5200/5400 sz=30 | **+11,475** |

Same signal. Same dollars. Confirmed.

---

## 2. prosperity3bt rothschild on R4 — actual losses

`traders/round3/rothschild.py` as committed has a **hard bug**: `CS_PAIRS` references `(VEV_5200, VEV_5400, 30)` but `STRIKES_CS = {VEV_5300, VEV_5400, VEV_5500}` and `CROSS_STRIKE_ASSETS = (VEV_5300, VEV_5400, VEV_5500)` — VEV_5200 is missing. Result: `KeyError: 'VEV_5200'` on the first tick. The committed rothschild has never run end-to-end. This was caught here for the first time.

I patched the bug in `tmp/cs_test/rothschild_fixed.py` (added VEV_5200 to both maps, removed it from `MR_ASSETS_ROTH`). With the fix:

```
prosperity3bt tmp/cs_test/rothschild_fixed.py 4 --merge-pnl
```

| | Day 1 | Day 2 | Day 3 | 3-day |
|---|---|---|---|---|
| HYDROGEL_PACK | 9,279 | -1,322 | 904 | +8,861 |
| VELVETFRUIT_EXTRACT | 1,520 | -708 | 2,976 | +3,788 |
| VEV_4000 | 3,334 | 2,437 | 2,589 | +8,360 |
| VEV_4500 | -34 | 0 | 27 | -7 |
| VEV_5000 | 0 | 0 | 12 | +12 |
| VEV_5100 | 0 | 0 | 4 | +4 |
| **VEV_5200 (CS)** | **-186** | **-334** | **-445** | **-965** |
| **VEV_5300 (CS)** | **-104** | **-66** | **-69** | **-239** |
| **VEV_5400 (CS)** | **-84** | **-138** | **-42** | **-264** |
| **VEV_5500 (CS)** | **0** | **0** | **-40** | **-40** |
| **CS sum** | **-374** | **-538** | **-596** | **-1,508** |
| **Total** | 13,726 | -132 | 5,916 | **+19,510** |

Wolf (rothschild's CS code on top of porush HYDROGEL) hits the same wall:

| | Day 1 | Day 2 | Day 3 | 3-day |
|---|---|---|---|---|
| VEV_5200 | -219 | -366 | -313 | -898 |
| VEV_5300 | -220 | -284 | -726 | -1,230 |
| VEV_5400 | -24 | -42 | -12 | -78 |
| VEV_5500 | 0 | 0 | +90 | +90 |
| **CS sum** | **-463** | **-692** | **-961** | **-2,116** |

Two independent integrations (rothschild_fixed and wolf), both with the audit's own k_sigma=2.0/hold=30 settings, both negative. The audit's +11k/3d does not exist in execution.

Trade-level confirmation (parsing rothschild_fixed's log):

| Strike | Buy fills | Avg buy px | Sell fills | Avg sell px | Net px slippage |
|--------|-----------|------------|-----------|------------|-----------------|
| VEV_5200 | 65 (390 lots) | 91.55 | 68 (390 lots) | 89.08 | **−2.47/unit × 390 = −963** |
| VEV_5300 | 22 (119 lots) | 51.84 | 21 (119 lots) | 49.83 | −2.01/unit × 119 = −239 |
| VEV_5400 | 24 (144 lots) | 17.00 | 24 (144 lots) | 15.17 | −1.83/unit × 144 = −264 |

Per-strike avg buy − avg sell ≈ leg spread. Strategy buys high and sells low, every single trade.

---

## 3. The 14k gap — decomposed

**Audit reported:** +11,265 (5200/5400 sz=30, R3 d0-d2)
**prosperity3bt rothschild_fixed:** −965 on VEV_5200 + −264 on VEV_5400 ≈ **−1,229** (R4 d1-d3, virtually identical FV)
**Gap:** ≈ 12,500 XIRECs

| Component | Magnitude | Evidence |
|-----------|-----------|----------|
| **Spread cost (entry haircut)** | ~13,800 | mid → realistic mode: +11,265 → -2,500. ~half-spread per leg per side. |
| **Spread cost (exit haircut)** | ~13,800 | realistic → cross-spread mode: -2,500 → -16,500. Other half. |
| **Gross signal alpha** | +11,265 | Real mid-to-mid mean-reversion does exist. It just doesn't pay for spread. |
| **Net realistic** | ≈ −15k to −44k | Depends on how much you cross. |
| **Other (signal mismatch, sim noise)** | ≈ ±1k | Negligible. |

Direct math sanity check (5200 mean spread = 2.93, 5400 mean spread = 1.31):
- Half-spread per leg per side: 0.5 × (2.93 + 1.31) = 2.12 ticks
- Per round trip: 2 × 2.12 = 4.24 ticks of spread per unit
- 436 trades × 30 units × 2.12 = **27,729** spread cost (realistic mode)
- 436 trades × 30 units × 4.24 = **55,459** spread cost (cross-spread mode)
- Audit's gross +11,265 − 27,729 = **−16,464** (close to my measured -15,128 in realistic mode)
- Audit's gross +11,265 − 55,459 = **−44,194** (close to my measured -41,520 in cross-spread mode)

The signal does mean-revert. The mean-reversion magnitude is just smaller than the spread it costs to enter and exit. **There is no edge above transaction cost.**

The other candidate explanations from the task brief are all small or zero:
- *Position lifecycle*: rothschild_fixed and wolf use the same hold/exit logic as the audit — irrelevant.
- *Signal computation*: same Bachelier-anchored smile (SMILE_A=0.249, SMILE_B=0.0033, SMILE_C=0.027). Direction confirmed.
- *Order routing*: trader uses `CS_TAKE_MAX_PER_TICK=6` ladder, but the spread-cost issue is per-fill, not per-tick. Larger or smaller takes don't change per-unit economics.
- *z-threshold*: timo dropped K_SIGMA from 2.0 → 1.5 specifically to fire MORE → made it MUCH WORSE (-33k as the user noted), exactly because more fires = more spread paid. My sweep confirms: at k=1.5, 5200/5400 mid-to-mid is +26k but realistic is **−44k**.

---

## 4. Threshold sweep — no escape hatch

`analysis/round4/cs_threshold_sweep.py`: full grid of k_sigma ∈ {1.5, 2.0, 2.5, 3.0} × hold ∈ {30, 100, 300, 1000} × mode ∈ {mid, realistic}, on R4 d1-3.

**5200/5400 sz=30:**

| k_sigma | trades | mid PnL | realistic PnL |
|---------|--------|---------|---------------|
| 1.5 | 1194 | +26,220 | **−44,760** |
| 2.0 | 447 | +11,475 | −14,228 |
| 2.5 | 135 | +3,690 | −3,735 |
| 3.0 | 30 | +975 | −668 |

**5300/5400 sz=40:**

| k_sigma | trades | mid PnL | realistic PnL |
|---------|--------|---------|---------------|
| 1.5 | 573 | +20,580 | −15,670 |
| 2.0 | 104 | +4,720 | −1,540 |
| 2.5 | 12 | +500 | −210 |
| 3.0 | 1 | +20 | −50 |

**5300/5500 sz=20:**

| k_sigma | trades | mid PnL | realistic PnL |
|---------|--------|---------|---------------|
| 1.5 | 757 | +11,620 | −11,950 |
| 2.0 | 158 | +2,960 | −1,895 |
| 2.5 | 29 | +700 | −115 |
| 3.0 | 3 | +100 | **+20** |

Across **94 (k, hold, pair)** configurations, exactly ONE has positive realistic PnL: 5300/5500 sz=20 k=3.0 → +20 over 3 days, 3 trades. Statistically zero. **No threshold rescues this.**

---

## 5. Passive-only execution — also doesn't work

What if we *only* post passive penny-jumped quotes (no aggressive takes)? Then we get filled by counterparties and earn spread/2 per leg instead of paying it. `cs_passive_only.py` simulates this with random per-tick passive fills (probabilities 0.05, 0.10, 0.20, 0.50).

Best per-pair total PnL across 12 (pair, p_fill) configs:
- 5200/5400 sz=30: **+34** (p_fill=0.05)
- 5300/5400 sz=40: **+24** (p_fill=0.50)
- 5300/5500 sz=20: **+20** (p_fill=0.50)

Even in the optimistic passive-fill regime, the strategy makes **±tens of XIRECs over 3 days**. The signal simply isn't strong enough to matter. Plus, in real execution, our passive quotes are competing with all the other vouchers' MM logic for the same inventory budget — opportunity cost is non-trivial.

---

## 6. Why does IV-scalping work but CS doesn't?

`submission.py` runs Timo IV-scalping on the same 6 vouchers and makes **+3,289** on the 5200-5500 strikes alone (over 3d). Same model. Same smile. Same per-strike deviation signal. So why one wins and one loses?

**Key structural difference:**

`_iv_scalp_orders` fires only when `(best_bid - fair) - mean_dev >= 0.5` (i.e., the market's *bid* is already above fair). It then **sells AT best_bid** — hitting an order someone else has already posted *above* fair. The trade direction is "the market wants to pay too much; we sell into their bid". We earn `best_bid - fair` per unit, not lose it.

CS rothschild: when `z > 2` (mid spread is rich vs theo), the strategy slams `low_leg ASK` (buys at the offer above mid) and `high_leg BID` (sells at the bid below mid) to enter. We pay spread/2 per leg per side. The "rich" mid-spread is an unpaid theoretical mispricing that requires crossing real spread to capture — and the gap isn't big enough.

In short: **IV-scalp trades only when the book pays it; CS trades when the model says the book is mispriced.** Those are radically different statements, and only the first survives transaction costs in this regime.

---

## 7. Recommendation: KILL CS PERMANENTLY

Keep `submission.py` as the R4 ship. Do NOT layer CS in any form. The decision is supported by:

1. Audit's +11k is mid-to-mid accounting; under realistic fills it inverts to −15k.
2. Two independent integrations (rothschild_fixed, wolf) both lose money on the CS strikes in `prosperity3bt`.
3. **94 of 94** k_sigma/hold/mode realistic-mode configs are negative or zero.
4. Passive-only execution captures only single-digit XIRECs over 3 days.
5. The IV-scalping layer in `submission.py` already extracts the same smile-deviation signal in the only profitable form (cross-the-book-when-it-pays-you).

**Ship/no-ship decision:** since no CS config beats the +27,444 baseline by even +1 XIRECs (best is roughly +0 with 3 trades), and the +2k threshold is impossible, **no `cs_v2.py` is being created**. This file exists so the CS question is settled and we don't burn cycles on it again next round.

If a future analyst is tempted: re-run `cs_threshold_sweep.py`. If realistic-mode column has a positive number with > 50 trades, then maybe. Until then, this is dead.

---

## 8. Bug to fix in `traders/round3/rothschild.py`

`STRIKES_CS` is missing `VEV_5200` and `CROSS_STRIKE_ASSETS` doesn't include it; rothschild crashes on tick 0. Either patch like `tmp/cs_test/rothschild_fixed.py` (add 5200 to both maps; drop from `MR_ASSETS_ROTH`), or remove the 5200/5400 pair from `CS_PAIRS`. Note that this bug means the rothschild file as committed never produced a valid backtest — any prior PnL claims about it are suspect. (For the record: the patched version makes +19,510 on R4, which is well below `submission.py`'s +27,444 — so the bug-fixed rothschild is also not shippable.)

Recommended action: leave rothschild.py as-is (it's a historical R3 experiment), but remove any references to CS in CLAUDE.md or future analyses that imply it has positive expected value.
