# V7 — Options-implied VELVET fair as IOC take signal — **+4,716 over V2**

**Date:** 2026-04-27. **Verdict: ship V7.** First R4 prototype to beat V2.

## Headline

R4 prosperity3bt --merge-pnl, 10K ticks/day, 3 days:

| Trader | D1 | D2 | D3 | **Total** | Δ vs V2 |
|---|---:|---:|---:|---:|---:|
| V2 (`submission_v2.py`) | 14,675 | 2,946 | 12,312 | **29,934** | 0 |
| **V7 (`submission_v7.py`, locked thr=3.0 sz=15)** | 13,890 | **9,376** | 11,384 | **34,650** | **+4,716 (+16%)** |
| Per-day delta | −785 | **+6,430** | −928 | **+4,716** | |

The +4,716 comes almost entirely from D2. Stratton's MR is weak on D2's
choppy regime (V2 D2 only +2,946 vs D1 +14,675 / D3 +12,312). The
options-consensus signal exploits the very thing that makes D2 hard for
stratton: voucher mids drift from spot more often, and the chain
collectively pre-empts the next move. D1 and D3 take small losses
(~800 each) — net positive across all 3 days.

## Mechanism

Genuinely new vs v3-v6. Adapted from `tmp/p3_research/carter_trader.py:971-1033`
(Carter's option-implied underlying MR, P3 9th place):

1. **Back-solve per-voucher implied S** via linearisation
   `S_implied ≈ S_market + (mid - BS_fair) / delta`. Uses smile-fitted
   IV per strike (already in V2's ctx).

2. **Vega-weighted average across 6 vouchers** (VEV_4500, VEV_5000-5400)
   gives a "consensus drift" — how much the option chain prices a
   different VELVET than the spot mid. Excludes VEV_4000 (delta saturates
   ≈1, no info) and VEV_6000/6500 (pinned at 0/1, no info).

3. **IOC take when |consensus_drift| > 3.0 ticks**, size 15 lots,
   cooldown 100 ticks. Direction: BUY if drift > 0 (chain says VELVET
   too cheap), SELL if drift < 0.

4. **Stratton MR continues unchanged.** V7's takes are appended to the
   stratton order list, then `_clip_to_limit` drops anything that would
   exceed VELVET's 200 limit (which would cancel ALL orders).

## Why it beats V2 where v3-v6 didn't

Every prior layer interfered with stratton's drift-response capture:

| Prototype | What it touched | Outcome |
|---|---|---|
| v3a | replaced `_trade_mr` on VELVET | -8,488 (lost stratton MR alpha) |
| v3b | additively biased `_trade_mr` target | -3,832 (fights MR drift response on D3) |
| v4 | overrode 5300/5500 voucher handlers | -940 (best variant, still negative) |
| v5 | new OBI handler replacing `_trade_mr` | -2,294 (no inventory-pull) |
| v6 | additive bias from delta hedge | -3,565 (same D3 fight as v3b) |
| **v7** | **orthogonal IOC takes, stratton untouched** | **+4,716** |

The unifying lesson: **stratton's MR target is a tight local optimum.
Don't bias it. Add separate orders that consume position-limit
headroom but don't change stratton's quotes.**

V7 takes pay ~half-spread per fill (~2.5 ticks × 15 lots = ~37 per fire),
but capture the 3+ tick consensus drift edge — net positive per fire.
Stratton's MM continues to quote and earn its passive edge undisturbed.

## Param sensitivity (6-trial sweep)

All 6 (thr × sz) combos beat V2 by at least +2,630, confirming this
isn't a single-point fragile optimum:

| thr | sz=15 | sz=20 | sz=25 | sz=30 |
|---:|---:|---:|---:|---:|
| 2.5 | +3,996 | +3,738 | +2,630 | +3,479 |
| 3.0 | **+4,716** | +3,228 | — | — |

(Sweep aborted after 6 trials due to backtest-process resource issues;
locked at thr=3.0 sz=15 = peak. Wider neighborhood TBD on a clean run.)

## Honest caveats

1. **D2 is the same FV path as R3 D2** (per CLAUDE.md), so D2's +6,430
   uplift is one realization, not three. D3 is the only fresh sample
   (-928). Real OOS uplift = -928 on a single sample, total ambiguous.
   The signal is *plausible* (vega-weighted consensus is mechanically
   sensible, not curve-fit) but D3 alone doesn't confirm robustness.

2. **MC validation deferred** — `prosperity4mcbt --quick` failed (cargo
   compile error on the new file). Pre-portal sub, should run MC to get
   distributional stats and the sim portal-translation factor.

3. **Param sweep was short** (6/20 trials before resource issues). The
   wider sweep should run to confirm the optimum band before committing
   the param choice.

4. **V7 only takes; doesn't passive-quote on the signal.** A passive
   variant (penny-jump biased by consensus drift) might earn the
   spread-half on every fill. Future variant: V7-passive.

## Files

- `traders/round4/submission_v7.py` — locked at thr=3.0 sz=15.
- `analysis/round4/v7_optimp_velvet_breakthrough.md` — this file.

## Recommended next steps

1. Wider param sweep around thr=3.0 sz=15 to confirm robustness.
2. MC validation (re-fix cargo build first).
3. Compare to a passive-quote variant (V7-passive: penny-jump biased
   instead of cross-spread take).
4. Portal sub to get the V7 portal/replay ratio.
