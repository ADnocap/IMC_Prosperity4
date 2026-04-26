# Round 3 — Final Submission Plan

**Generated:** 2026-04-26.
**Status:** All analysis + searches done. Two ready submission candidates.

---

## Summary of every R3 trader built (chronological)

| File | Source | MC mean | MC Sharpe | Portal | Notes |
|---|---|---|---|---|---|
| `traders/round3/a.py` | Initial penny-jump MM | ~+2k | ~0.5 | ~+2k baseline | The starting point. |
| `traders/round3/{hanna,chester,manny,naomi,denham,wigwam,saurel,bodnick,madden,kimmie,toby,emma}.py` | Manual experiments | -134k to +14k | varied | most regressed | Various trial-and-error from FINDINGS.md ideas. |
| `traders/round3/harry_potter_v4.py` | Teammate's portal sub 370288 | -61k MC | n/a | **+17,449** | EMA-MR baseline. |
| `traders/round3/stratton.py` | Search-2 OOS winner #233 | +10,884 | **1.81** | **+17,449** | **Currently shipped.** |
| `traders/round3/jordan.py` | Search-3 OOS winner #300 | +5,884 | 1.61 | not shipped | Adds rev_z50 + OBI skew + bigger BASE_MM. |
| `traders/round3/porush.py` | Search-4 OOS winner #119 | **+11,774** | 1.54 | not shipped | New HYDROGEL handler (porush-style OBI confidence sizing). |
| `traders/round3/rothschild.py` | Cross-strike spread MR | -10k → +7,526 (no static tilt) | n/a | not shipped | MC mis-evaluates (independent voucher FVs). 3 vert pairs. |
| `traders/round3/wolf.py` ⭐ | porush + cross-strike + MAF | +6,157 (CS noise) | n/a | not shipped | **Final submission candidate.** |

(v5 search ran but its new VEL/V4K confidence-sized handlers added MC variance > alpha. Abandoned.)

---

## What we ship to the portal

### Primary: `traders/round3/wolf.py`

The kitchen-sink trader. Stack of everything that worked:

- **HYDROGEL handler** = porush (search-4 winner). Big confidence-sized OBI passive skew (size up to 97 lots when |OBI|>0.12) + small rev_z+OBI gate take (22 lots when |z|>2 and OBI agrees). Search-4 OOS HYDROGEL contribution: **+4,848** (vs jordan -1,041, +5,889 swing).
- **VELVETFRUIT, VEV_5000, VEV_5100** = stratton MR (jordan/porush params). Tiny inventory tilt (MR_K=0.045), passive penny-jump MM with OBI skew on level 0.
- **VEV_4000, VEV_4500** = stratton OBI-tiered MM with BASE_MM_SIZE=37 floor.
- **VEV_5200, VEV_5300, VEV_5400, VEV_5500** = cross-strike-aware. When CS spread MR signal fires, drive position to spread target. Otherwise fall through to MR/MM.
- **Cross-strike spread MR** (3 pairs, sizes from final_audit.md sec 7):
  - 5200/5400 size 30 (workhorse — historical 3d replay +11,265 across 436 trades)
  - 5300/5400 size 40 (+4,540 across 101 trades)
  - 5300/5500 size 20 (+3,470 across 176 trades)
- **MAF bid = 500** (R3 — final_audit.md sec 6: 33% of R2 uplift).

MC quick (seed 20260401, 100 sessions): mean **+6,157**, std 14,941. Note MC mis-evaluates the CS layer (independent voucher FV processes in Rust sim) so portal upside is +2-3.5k/day per audit historical replay.

### Backup: `traders/round3/porush.py`

If we want a more MC-conservative submission, porush is the search-4 OOS winner without the cross-strike layer. OOS mean **+11,774**, Sharpe 1.54, p05 -57. No portal-only bets.

---

## Honest portal expectations

Calibration anchor: stratton MC +10,884 → portal **+17,449** (1.62× MC→portal uplift).

| Scenario | Wolf portal estimate | Notes |
|---|---|---|
| Pessimistic | ~12k | MC=portal exactly, CS layer dead |
| Realistic | **+18-22k** | Stratton-like 1.62× ratio + small CS contribution |
| Optimistic | +25-30k | CS alpha transfers fully (+6-10k extra) + voucher MM bot interaction |

Top-team band (60k+) requires more breakthroughs we haven't found.

---

## What we explored that didn't pan out

- **Delta-hedged short-vol portfolio**: spot 200 cap binds at full size, hedge spread cost 5 ticks (not 3) — net PnL only +166 to +1,033/day. Killed.
- **Outright OTM voucher shorting**: rich vs flat-vol benchmark BUT cheap vs fitted smile. Per-strike walk-forward shows VEV_5200 short loses -1,900/day. Killed.
- **HYDROGEL aggressive-BUY-cluster fade** (from `trades_signals.md`): doesn't replicate with non-overlapping triggers; original n=126 was double-counted. Not a real signal.
- **HYDROGEL rev_z50 with size 140 cross-spread take** (v3 attempt): loses on real data too (-28K over 3 days). Wrong window — should be 500.
- **VEL OBI confidence sizing (v5 search)**: 152+ trials show -17K p05 tail. Adds MC variance > alpha.
- **VEV_4000/4500 deeper OBI sizing (v5 search)**: same problem. Sizing of 120+ lots blows up on bad signals.
- **Cross-product directional bets**: lead-lag corr dead at every tested lag.
- **Trend regimes**: never; always mean-reverting or noise.
- **Volume-conditioned filters**: uplift tiny, not actionable.

---

## All analysis files (for reference)

- `analysis/round3/FINDINGS.md` + `FINDINGS_v2.md` — top-level synthesis
- `analysis/round3/options_analysis.md` — vol surface
- `analysis/round3/p3_options_reference.md` — what P3 winners did
- `analysis/round3/multi_tick_signals.md` — autocorr/OBI/microprice
- `analysis/round3/trades_signals.md` — flow patterns (some refuted later)
- `analysis/round3/cross_strike.md` — butterflies/vert spreads
- `analysis/round3/signal_decay.md` — alpha half-life
- `analysis/round3/delta_hedged_options.md` — delta hedge analysis
- `analysis/round3/hydrogel_deep.md` — HYDROGEL deep dive
- `analysis/round3/final_audit.md` — pre-submission audit

---

## Action items

1. Submit **`traders/round3/wolf.py`** to portal — primary candidate.
2. If portal result < stratton's +17,449, fall back to porush.py for the next sub.
3. Compare HYDROGEL contribution on portal vs MC OOS to validate the porush handler design.
