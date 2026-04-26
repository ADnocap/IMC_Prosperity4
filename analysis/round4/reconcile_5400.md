# VEV_5400 reconciliation: rich vs intrinsic, cheap vs smile

**Date:** 2026-04-26
**Sources:** `analysis/round3/options_analysis.md` §4-5, `analysis/round3/FINDINGS_v2.md` §1-2, `analysis/round3/cross_strike.{md,json}`.

## Verdict: both findings are correct against different benchmarks

The two reports use different fair-value reference points and both numbers check out:

| Benchmark | 5400 mid | Fair | Residual | Source |
|---|---:|---:|---:|---|
| Intrinsic max(0, S−K) at S=5250 | 15.95 | 0.00 | **+15.95 RICH** | options_analysis §4 |
| Bachelier @ σ=0.96/tick (calibrated realized) | 15.95 | 5.64 | **+10.31 RICH** | options_analysis §3 |
| BS @ pooled smile IV ≈ 0.251 | 15.95 | 17.96 | **−2.01 CHEAP** | cross_strike pooled |
| BS @ avg IV of 5300/5500 (0.258) | 15.95 | 19.26 | **−3.31 CHEAP** | sanity check |

Sanity check (re-derived, not from JSON): 5300 mid 46.76 → IV 0.255, 5500 mid 6.64 → IV 0.260. Fair-vol-interpolated 5400 = 19.26. Observed 15.95 ⇒ **−3.3 cheap** vs neighbors. Smile residual std = 3.03 ⇒ z ≈ −1.1, in line with FINDINGS_v2's z = −0.73.

The smile fit is **not** an artifact of fat-residual strikes — even removing the smile and just using neighbors-only linear interpolation gives the same answer. 5400 is genuinely cheap relative to 5300/5500.

## Trading hierarchy

The two trades **do not conflict** — they target different risk premia and can coexist in one position:

- **Outright theta short (options_analysis Idea 3):** captures the per-day mid decay of ~+1.5/day on 5400 (~+1,410 over 3 days at full size). The bet is that the mid drifts toward intrinsic = 0 as TTE shrinks. Risk: vega blow-up if implied vol pops.
- **5300/5400 vert spread (FINDINGS_v2):** SELL 5300 / BUY 5400 to fade the relative-value mispricing. Spread mean dev +3.51, std 1.05, half-life 9.3 ticks. Sharpe 162. Bet is on smile snap-back, not on outright vol direction. Vega largely cancels (258 vs 186 → net 72), delta cancels (0.39 − 0.20 = 0.19).

The vert spread is **strictly better** by Sharpe (162 vs ~1 for outright) and naturally vega-light. The outright short is a structural carry that bleeds vega risk you cannot hedge.

## Recommended R4 position

**Combined position:** SHORT 5300 (−300), LONG 5400 (+300), plus optional SHORT 5500 (−100) for the "sell 5300/5400/5500 fly" structural rich (cross_strike.md trade #2). This makes the net 5400 position **LONG +300**, NOT short. Outright theta-short on 5400 alone is dominated and should be skipped — its EV (~1,400) is replaced by the much higher-Sharpe spread (~7,575/day per cross_strike).

Per-strike net inventory at full size:
- 5300: −300 (vert spread short leg)
- 5400: +300 from vert + +200 from fly = capped at +300
- 5500: −100 (fly short wing)

Spot delta to hedge ≈ −300·0.39 + 300·0.20 − 100·0.08 = −65 spot ⇒ buy ~65 VELVETFRUIT (well inside 200 cap).

## Confidence: HIGH

Three independent angles converge on "5400 is cheap relative to 5300/5500":
1. Pooled parabolic smile residual: −2.22 (z −0.73)
2. Linear-IV-interp from neighbors: −3.31
3. BS at average-of-neighbors IV: −3.31

**Falsifier:** if a tighter per-day refit (using only the day we are trading) puts 5400's residual within ±1 of the smile, the spread MR signal is dead and we revert to outright theta-short. Specifically: refit the per-day smile on R4 day-3 fresh data (`data/prosperity4/round4/prices_round_4_day_2.csv`); if `mean_residual(5400)` flips positive or the abs value drops below 1.0, abandon the long-5400 spread leg. The R3 per-day fits gave −2.74 / −1.42 / −2.50 (all three days negative), so this is a robust prior — but R4 day-3 is fresh data and could differ.
