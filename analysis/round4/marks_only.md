# Mark-only standalone traders: do Mark IDs add value on ANY product?

## Question

Three integration variants on top of V2 (`marks_a_skew`, `marks_b_takes`,
`marks_c_widen`, `marks_d_fallback`) all LOST money. Hypothesis from
`marks_d_fallback.md`: by the time we *see* a Mark trade, our existing
penny-jump MM already filled at the same tick — so chasing the signal
just pays spread on stale information.

Is there ANY way Mark IDs add standalone alpha? If a pure Mark-only
trader can beat stratton-only on at least one product, that product is
a candidate for layering Marks ONTO stratton in a more targeted way.
Otherwise, kill the Mark path.

## Three standalone Mark-only variants (no IV-scalp, no stratton MM)

1. **`marks_only_takes`** — aggressive takes only. When a recent Mark
   trade matches a high-confidence signal, lift the ask (BUY) or hit the
   bid (SELL). Cooldown 25 ticks per product, take size 5.
2. **`marks_only_shadow`** — shadow Mark 14 (the smart passive MM, agg=0).
   Mark 14 buyer at price X => their bid was ~X. Quote 1 tick inside
   their inferred bid/ask. HYDROGEL + VEV_4000 only, size 15.
3. **`marks_only_fv`** — Mark 14 + Mark 01 trade-price EMA as fair value,
   then quote +/-1 around it (clamped inside book). EMA alpha 0.05.
   Size 10.

## Backtest results (prosperity3bt R4, 3 days × 10K ticks, --merge-pnl)

### Total PnL vs baselines

| Trader | Day 1 | Day 2 | Day 3 | **Total** | vs V2 (29,934) | vs Stratton (20,954) |
|---|---:|---:|---:|---:|---:|---:|
| V2 (submission)         | 14,675 | 2,946  | 12,312 | **29,934** | — | +8,980 |
| Stratton (submission.py without IV-scalp) | 14,100 | 406 | 6,448 | **20,954** | -8,980 | — |
| `marks_only_takes`      | -17,910 | -24,168 | -21,966 | **-64,044** | -93,978 | -84,998 |
| `marks_only_shadow`     | 5,188   | -2,262  | 457     | **3,382**  | -26,552 | -17,572 |
| `marks_only_fv`         | 2,846   | -1,826  | -1,158  | **-139**   | -30,073 | -21,093 |

All three lose money standalone. The "best" one (`marks_only_shadow`) is
positive on day 1, breakeven over 3 days, and dramatically worse than
either baseline.

### Per-asset breakdown vs stratton (3-day totals)

| Asset | Stratton | takes | shadow | FV | Best Mark variant | Beats stratton? |
|---|---:|---:|---:|---:|---|---:|
| HYDROGEL_PACK | **8,861** | -31,977 | 1,948 | -1,700 | shadow (1,948) | **NO** (-6,913) |
| VELVETFRUIT_EXTRACT | **3,788** | -10,680 | (none) | 1,552 | FV (1,552) | **NO** (-2,236) |
| VEV_4000 | **8,360** | -21,317 | 1,435 | 10 | shadow (1,435) | **NO** (-6,925) |
| VEV_5300 | **-65** | -70 | (none) | (none) | takes (-70) | **NO** (-5) |
| All others | 0 | 0 | 0 | 0 | tie | tie |
| **Total** | **20,944** | -64,044 | 3,383 | -138 | shadow | **NO** (-17,561) |

(Stratton total slightly higher in row sum than reported 20,954 — small
rounding/mod-ops in the per-asset attribution.)

## Discussion

### Variant 1 (takes) — catastrophic, as expected

Crossing the spread aggressively on a 1-tick-lagged signal pays the full
bid/ask spread on every entry. On HYDROGEL the spread is ~16 ticks,
which is comparable to the entire 200-tick predicted drift, so each take
has negative expected value before fees. On VEV_4000, spread is similarly
~16-20. The signal predicts ~9-tick drift; we pay ~10 to enter. This
echoes the `marks_b_takes` finding: -64K standalone is just the same
loss without the V2 MM cushion to dilute it.

### Variant 2 (shadow) — interesting on day 1, falls apart day 2-3

Day 1 +5,188 is the best single-day result of any Mark-only variant
across all three products tested in this experiment. But day 2 turns to
-2,721 on HYDROGEL. The mechanism: on day 1, Mark 14's bid/ask is a
genuinely informed quote we benefit from front-running by 1 tick. On
day 2 (which is the same FV path as R3 day 2 but with Mark 14 calibrated
to the FV start of R3 day 1), we end up trading INTO adverse selection
because Mark 14 itself is being adversely selected by Mark 38 (the dumb
taker) — our 1-tick improvement just makes us the *first* victim.

### Variant 3 (FV) — flat, no alpha

EMA of Mark 01/14 trade prices is essentially identical to mid-price
since these Marks are pulling their quotes from the same book. Day 1
slight positive on HYDROGEL+VELVET+VEV_4000, days 2-3 turn negative.
The EMA tracks price too closely to provide independent FV signal.

### Why doesn't shadow beat stratton on any product?

Stratton's HYDROGEL handler already penny-jumps the book aggressively
(+1 inside best bid/ask) with size 54 (HY_MM_BASE_SIZE). Mark 14's
bid/ask is *typically AT* best_bid/best_ask of the book at a given
moment — they ARE the makers behind the visible book level. So our
"1 tick inside Mark 14" reduces in practice to "1 tick inside best book"
which is exactly what stratton already does, but with smaller size (15
vs 54) and without the OBI skew. We're essentially a worse stratton.

The same logic applies to VEV_4000: stratton's `_trade_vev_mm` already
penny-jumps with OBI-tiered sizes up to (40, 3). Shadow at flat 15 is
just smaller stratton.

## Verdict — DEFINITIVELY KILL

No standalone Mark-only variant beats stratton-only on ANY product:

- HYDROGEL: best Mark variant (shadow) = 1,948 vs stratton 8,861 → -78%
- VELVETFRUIT: best Mark variant (FV) = 1,552 vs stratton 3,788 → -59%
- VEV_4000: best Mark variant (shadow) = 1,435 vs stratton 8,360 → -83%

The three variants all confirm what `marks_d_fallback.md` already
diagnosed: by the time `state.market_trades` exposes a Mark trade,
the price is already 1 tick stale and our existing penny-jump MM has
already captured the same edge by being on the book first. Mark IDs are
*descriptive* of what already happened, not *predictive* of what's about
to happen, on a horizon shorter than our quote latency.

**Action**: stop trying to layer Mark signals onto V2. Time spent on
Mark profiling is sunk cost — invest remaining R4 cycles into:

1. Day-3-specific tuning (fresh data, FV path differs from R3 day 1-2)
2. IV-scalp robustness (largest day 3 contribution: VEV_5000-5500 = ~6K)
3. Stratton OBI-skew refinement on HYDROGEL day 2 specifically (lost
   1,322 there in V2)

The shipped V2 (+29,934) stays the strongest candidate. Ship V2.
