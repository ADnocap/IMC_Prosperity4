# V4 (theta carry) and V5 (R3 OBI handlers) — both KILLED

**Date:** 2026-04-27. **Verdict:** keep V2 (`submission_v2.py`,
+29,934 R4 historical replay) as the shipped candidate. Neither
prototype beats it.

## Summary table — R4 prosperity3bt --merge-pnl, D1+D2+D3, 10K ticks/day

| Trader | D1 | D2 | D3 | Total | Δ vs V2 |
|---|---:|---:|---:|---:|---:|
| **V2 (shipped)** | 14,675 | 2,946 | 12,312 | **29,934** | 0 |
| V4-A: short 5300 / long 5500 vert ±100 | 14,229 | 2,158 | 12,028 | 28,416 | -1,518 |
| V4-B: short 5300 / long 5400 vert ±50  | 14,238 | 2,058 | 11,354 | 27,650 | -2,284 |
| V4-C: short 5300 only -50              | 14,272 | 2,148 | 12,469 | 28,888 | -1,046 |
| V4-D: short 5300 only -25              | 14,458 | 2,336 | 12,200 | 28,994 |   -940 |
| V4-E: short 5300 only -10              | 14,539 | 2,428 | 11,899 | 28,866 | -1,068 |
| V5: VELVET-OBI + VEV4K deep-OBI        | 14,181 | 3,136 | 10,323 | 27,640 | -2,294 |

Both prototypes shipped as DO-NOT-SHIP files with their toggles defaulted
to False. Re-enabling toggle = reproduces the negative result.

## V4 — static theta carry on options that don't expire during the round

**Hypothesis** (from R3 final_audit sec 7): selling rich strikes (per
cross_strike z-scores) and holding all session collects deterministic
theta decay. R3 audit estimated +12,036 at pos 300 to expiry on
short-5300/long-5500 vert (=+981 over 3-day session).

**Result:** All 5 vert/single-leg variants lose. Best (V4-D) is -940.

**Why:** R3 audit's theta numbers were computed mid-to-mid, ignoring entry/
exit half-spread. On R4 data, the long legs (5500, 5400) trade at-or-below
BS-fair (negative carry to be long them) — adding the long leg costs
spread without compensating theta. The single-leg short-5300 (V4-C/D/E)
is the only structurally positive variant but still loses ~1k vs V2
because:
1. V2's IV-scalp on VEV_5300 already captures most of the rich-strike
   reversion (V2 D3 VEV_5300 = +665) — overlaying a static short caps
   IV-scalp's upside without adding new alpha.
2. The gate-closed flatten code in `_iv_scalp_orders` is bypassed when
   L3 owns the strike, so we lose IV-scalp's dynamic close-back when it
   would be profitable.

## V5 — R3 audit's two un-shipped OBI handlers

**Hypothesis:** R3 final_audit estimated +2-4k/day on VELVET via a
dedicated `_trade_velvet_obi` (asymmetric size on |OBI|>=0.30) and
+1-2.5k/day on VEV_4000 via `_trade_deep_itm_obi` (size 100-150 vs
stratton's tiny VEV_BASE_SIZE=3).

**Result:** Total -2,294. Per-asset:
- VELVET: -2,326 (handler structurally worse than stratton MR)
- VEV_4000: +26 (flat — V2 already captures this)
- VEV_4500: 0 (no-trade strike, neither handler matters)

**Why:**
1. **VELVET handler loses to stratton MR.** Naked OBI confidence-MM has
   no inventory-pull protection. On D3 (drift day), wrong-side accumulation
   is unbounded by z-target. Stratton's MR_K * z * limit term protects
   against drift; the OBI handler doesn't.
2. **VEV_4000 deep-OBI doesn't add.** Per `marks_d_fallback.md` the
   VEV_4000 +8,360 in V2 IS the OBI signal — captured implicitly via
   penny-jumping at best±1. Re-implementing as an explicit OBI handler
   just re-routes the same fills through different code paths. The R3
   audit's "5-30% capture" projection assumed V2 was capturing 0%; the
   diagnostic shows V2 already captures ~all of it.
3. **VEV_4500 is dead.** 1 trade per 30K ticks per `trades_signals.md`.
   Any handler reads ~zero fills.

The R3 audit's projections were upper-bound estimates assuming V2 was
not capturing the OBI signal at all. Diagnostic from marks_d_fallback
already showed that's wrong on VEV_4000.

## Cumulative R4 search status

| Mechanism | Variants | All result | Conclusion |
|---|---:|---|---|
| Mark counterparty layer | 4 (a/b/c/d) + 3 (only_*) + 2 (v3) = **9** | All lose | KILL |
| Cross-strike spread MR | 1 + threshold sweep + 1 fix attempt | All lose post-spread | KILL |
| Static theta carry | **5** (v4 a-e) | All lose | KILL |
| R3 OBI handlers | **1** (v5) | Lose | KILL |
| IV-scalp param tune | 141 trials | V2 = optimum | KEEP V2 |
| smile_a sweep | 13 trials | V2 = optimum | KEEP V2 |

V2 has been beaten on by a total of **160+ trials and 11+ structural
variants**, and remains the best.

## What remains untried at this point

1. **Full V2-level joint param re-search** (10+ params across stratton,
   porush, IV-scalp jointly, 400+ trials, MC-validated). High effort,
   uncertain reward — V2 was already locally optimal under partial
   searches.
2. **Manual challenge improvements** — Aether Crystal exotics. Algo
   side appears near-saturated.
3. **Market-impact / latency aware execution** — none of our prototypes
   modeled realistic queue position. Probably small edge given 1-tick
   penny-jump dominance.
