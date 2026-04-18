---
name: MC replay large gains are often sim artifacts
description: When MC replay shows 5x+ PnL jumps vs simulate/CSV/portal, treat as artifact; trust simulate regression instead
type: feedback
---

In MrPing_v6 (option-2 merge of v3 tight MAKE + additive signals), MC replay heavy showed ACO mean jumping from 6,617 → 91,944 (13x). CSV match-all showed only +96 vs v3. Simulate mode regressed -1,249. Portal submission 239xxx scored 10,037 vs step4's 10,665 — **-628 regression**, confirming the MC jump was artifact.

**Why:** MC replay uses real FV but stochastic bot quotes. Tight quotes at fv±1 catch stochastic bot flow that doesn't exist on portal. Real portal trades are fixed; our tight quotes get adversely filled at marginal edge.

**Why:** Trust three backtest signals, weighted:
1. Simulate mode regression = red flag we ignored at our peril (-1,249 foreshadowed -628 portal loss)
2. CSV match-all delta is the most realistic fill-rate estimate (was ~0 → true delta ~0 → portal regressed slightly)
3. MC replay jumps of 5x+ are almost always artifacts unless CSV also shows meaningful movement

**How to apply:** Before submitting, require that at LEAST TWO of {simulate mode, CSV match-all, MC replay median at heavy} agree on direction. If simulate regresses but MC replay jumps, do NOT submit. Pick the smaller, consistent delta as the realistic estimate.
