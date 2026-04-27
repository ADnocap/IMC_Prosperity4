# Harry_potter_v6 — v5 with position-gated stop-loss

v4 portal: +17,450. v5 portal: +9,967 (−7,483 from SL firing during normal
MR build-up drawdowns). v6 fixes that with a position gate that prevents
false fires.

## Why v5's SL failed on portal

Mean-reversion has a specific PnL signature: **you go into drawdown
WHILE building the position; the reversion pays later**. v5's SL at a
flat −2,500 MTM threshold fired mid-buildup on several assets, unwound
winning positions, and re-entered at worse prices after the reversion
had already started. Every one of v4's winning MR assets (VELVETFRUIT,
VEV_5000/5100/5200) regressed by 1.7-2.5k each.

CSV showed v5 +232 better than v4 because day 2 had persistent drift
that genuinely needed cutting. That was an overfit to one day's pattern.

## Two fixes I tried for v6

### 1. Duration filter (tried first, dropped)

Require MTM below threshold for N consecutive ticks before firing.
Hypothesis: single-tick spikes during build-up wouldn't count, only
sustained drawdown would.

Result: strictly worse. Waiting for the drawdown to persist just means
firing at a WORSE MTM. Every duration (100-1500) + threshold (-2000 to
-5000) combo scored 38-48k vs v4's 50,816. Dropped.

### 2. Position gate (shipped)

Fire only when BOTH (a) `|pos| >= 80% × limit` AND (b) MTM below
threshold for 300 consecutive ticks.

The key insight: on profitable MR runs, **positions usually revert
before saturating the limit**. MR's drawdown-while-accumulating phase
happens at mid-size positions, not at max. By requiring |pos| ≥ 160
on VELVETFRUIT (80% of 200), we filter out those normal drawdowns
entirely.

On the sanity-flip anti-strategy, positions DO saturate (bad signal
keeps pushing target to the limit) and MTM stays bad. SL fires and
caps the loss.

Result: **identical 50,816 on CSV regardless of threshold / duration /
pause within the gate**. The gate never fires on profitable data. On
the anti-strategy, the loss caps at −67,268 (vs v4's −72,601).

## The parameter settings don't matter (within reason)

Every tested combo scored exactly 50,816 on CSV:

| Gate | Dur | Thr | Pause | CSV | Sanity flip |
|---|---|---|---|---|---|
| 0.5 | 300 | −2500 | 500 | 50,816 | −67,268 |
| 0.8 | 300 | −2500 | 500 | 50,816 | −67,268 |
| 0.8 | 1 | −2500 | 500 | 50,816 | −67,268 |
| 0.8 | 300 | −500 | 500 | 50,816 | n/a |
| 0.95 | 300 | −2500 | 500 | 50,816 | n/a |

The gate is what prevents false fires. Within the gate, the SL mechanics
are effectively free — set them however is sensible.

Shipped: **gate=0.80, dur=300, thr=−2500, pause=500**. Conservative
enough that false fires are very unlikely even if portal behavior
differs slightly from CSV.

## Expected portal result

Goal: match v4's +17,450. The SL is insurance, not alpha. If the
portal session is normal (like 370288 was), v6 = v4. If the session
has a runaway drift that saturates the limits, v6 caps the damage.

## Key lesson

**Don't trust CSV replay alone for risk-management features.** CSV day
2 had persistent drift that was atypical; v5 was tuned to that specific
pattern and broke on portal. The position gate is conceptually right
because it describes what "stuck" actually means: you hit the limit
AND the signal isn't releasing you. Under that framing, the SL is a
tautological safety net — fires only when the strategy has genuinely
failed to revert at max position.

## Files

```
Rubenstrats/Harry_potter_v6/
├── Harry_potter_v6.py
├── README.md
└── results/

traders/round3/Harry_potter_v6.py
```

## If v6 ships identical to v4 on portal, further ideas

- Scale-in pacing: ramp target position smoothly over ticks instead of
  hitting 85% in one go — reduces adverse-selection cost during builds.
- Partial unwind instead of full pause: when SL fires, reduce target by
  factor (e.g., halve it) instead of flattening + pausing.
- Correlated pause: if 3+ VEVs trigger within 200 ticks, pause the
  whole VEV basket (correlated drift → basket-level stuck state).
