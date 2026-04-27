# Marks D Fallback — Verdict: KILL

**Date:** 2026-04-26
**Baseline:** `traders/round4/submission.py` (V2), R4 prosperity3bt replay = **+29,934** (D1 14,675 / D2 2,946 / D3 12,312)
**Verdict:** Mark-counterparty fallback layer is **net-negative** in every configuration tested. **Do not ship.** Keep the V2 submission as-is.

## Q1: Is the IV-scalp idle phase real on full 10K-tick days?

**YES, and far more extreme than expected.** See `analysis/round4/iv_scalp_idle_diagnostic.md`.

| Voucher | 3-day idle % | Longest idle run (ticks) | Where active ticks fall |
|---|---:|---:|---|
| VEV_5000 | 96.0% | 9576 | Decile 1 only (≤62% of D1) |
| VEV_5100 | 94.8% | 9451 | Decile 1 only |
| VEV_5200 | 94.0% | 9350 | Decile 1 only |
| VEV_5300 | 93.9% | 9317 | Decile 1 only |
| VEV_5400 | 94.5% | 9373 | Decile 1 only |
| VEV_5500 | 95.2% | 9453 | Decile 1 only |
| **All 6 simultaneously idle** | **93.9%** | — | Deciles 2-10 all 100% idle |

The flat phase observed in the portal day-3 graphLog is **not** a 1K-tick artifact — it's the dominant regime on 10K-tick days too. The IV-scalp gate (`switch_mean >= 1.0865`) fires once during warmup (deciles 1, when smile_a is still drifting and dev spikes), accumulates ~370 trigger fires per voucher, then `switch_mean` (EMA half-life ≈ 200) decays below threshold and **never recovers** because `dev = mid - bs_fair` shrinks once smile_a converges.

So the *opportunity* for a fallback exists: ~94% of ticks across all 6 vouchers are unowned by IV-scalp.

## Q2: Does a subordinate Mark fallback recover meaningful PnL during idle?

**NO.** Built `traders/round4/marks_d_fallback.py` (Mark take layer for HYDROGEL/VEV_4000/VEV_4500, subordinate to IV-scalp on SCALP_VOUCHERS, with proper position-limit clipping). Tested across `MARK_TAKE_SIZE × MARK_TAKE_COOLDOWN × {disable per product}` grid:

### Per-asset attribution (3-day totals, MARK_TAKE_SIZE=8, COOLDOWN=30)

| Variant | HYDROGEL | VEV_4000 | TOTAL | Δ vs base |
|---|---:|---:|---:|---:|
| baseline (submission.py) | **+8,861** | **+8,360** | **+29,934** | 0 |
| Mark on HY+VEV4000+VEV4500 | -2,314 | +8,232 | +18,631 | **-11,303** |
| Mark on VEV_4000+VEV_4500 only | +8,861 | +8,232 | +29,805 | -129 |
| Mark on HYDROGEL only (size 8) | -2,314 | +8,360 | +18,759 | -11,175 |

### VEV_4000-only sweep (HYDROGEL disabled)

Best is `MARK_TAKE_SIZE=3, MARK_TAKE_COOLDOWN=50/100`: total **+29,921** (delta -13). Every other (size, cd) combination is more negative. Even noise-equivalent best is not breaking even.

### HYDROGEL-only sweep (VEV_4000/4500 disabled)

Best is `MARK_TAKE_SIZE=1, COOLDOWN=200`: total **+29,443** (delta -491). Every combination loses, with size 5+ losing >2,000.

## Why it doesn't work

Diagnostic at `analysis/round4/marks_d_per_asset_test.py` shows ZERO `state.market_trades["VEV_4000"]` events reach the trader on D1 despite 164 VEV_4000 Mark trades in the CSV. Investigation:

1. **VEV_4000** spread is ~21 ticks (1243 bid / 1264 ask). Mark14↔Mark38 trades happen at the ask (1264). Our existing `_trade_vev_mm` penny-jumps with a SELL at 1263 — **better** than the 1264 ask. The backtester's `match_orders` therefore fills our SELL against Mark38's incoming buy BEFORE the Mark trade is reported in `state.market_trades`. The Mark fallback log stays empty. Net effect: tiny D3 perturbation only (-128), because penny-jumping already captures Mark14/38 informed flow on this strike.

2. **HYDROGEL** spread is ~16 ticks. Mark trades happen INSIDE the spread (e.g., 9960 trade with book 9948/9964), so they DO survive into `state.market_trades`. But by the time we react (next tick, +100 ts units), the H=200 drift has barely begun. Aggressive takes at top-of-book cross 1 tick of spread + suffer adverse selection from the rest of the book — the captured drift over the next few hundred ticks doesn't pay for the entry cost. Confirmed in `analysis/round4/marks_d_hydrogel_sweep.py`: even the smallest possible take size (1 lot, cooldown 200) loses 491 over 3 days.

3. The earlier marks_a/b/c variants (-4.5k to -10k each in their original tests) failed for the **same** reason, not the conflict-with-IV-scalp reason hypothesized in the user's prompt. Removing the conflict (subordinate gating in marks_d) doesn't recover value because the underlying take economics are bad.

## Bonus finding

Our existing strategy is *already capturing* the VEV_4000 Mark14/38 informed flow via penny-jumping (+8,360 over 3 days, virtually all of it from filling against Mark14↔Mark38 trades). Adding an explicit Mark take layer just reorganizes where that PnL is booked — at best a wash, at worst we cross our own quotes and lose to spread.

## Verdict

- **Q1 yes** — IV-scalp is idle 94% of ticks per voucher on 10K-tick days. The flat portal-graph phase is real.
- **Q2 no** — A subordinate Mark fallback cannot recover meaningful PnL in the current setup. The signal exists but the order-book mechanics destroy it.
- **Action:** Keep `traders/round4/submission.py` as the shipped V2. Do not introduce `submission_v3.py`.
- `traders/round4/marks_d_fallback.py` is preserved with a clear DO-NOT-SUBMIT header for reproducibility / future parameter exploration.
- `traders/round4/submission_instrumented.py` is preserved for future diagnostic runs (PnL byte-identical to submission.py; emits one `IVDIAG` line per (ts, voucher) pair).

## Files

- `analysis/round4/iv_scalp_idle_diagnostic.py` — offline replication of the in-trader gate state, computes idle % per voucher per day.
- `analysis/round4/iv_scalp_idle_diagnostic.md` — Q1 results.
- `analysis/round4/marks_d_per_asset_test.py` — per-asset attribution sweep.
- `analysis/round4/marks_d_size_sweep.py` — VEV_4000-only size×cooldown sweep.
- `analysis/round4/marks_d_hydrogel_sweep.py` — HYDROGEL-only size×cooldown sweep.
- `analysis/round4/marks_d_fallback.md` — this file.
- `traders/round4/marks_d_fallback.py` — DO-NOT-SUBMIT trader (kept for reproducibility).
- `traders/round4/submission_instrumented.py` — PnL-identical clone of submission.py with `IVDIAG` stdout prints.
