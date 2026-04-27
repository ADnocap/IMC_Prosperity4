# Harry_potter_v5 — v4 + per-asset stop-loss

v4 shipped the breakthrough (+17,450 portal). v5 targets v4's two known
weak points — day-2 underperformance from VELVETFRUIT drift, and no
tail-risk cap on runaway regimes.

## Attempted fix #1 (dropped): drift-adaptive EMA

Hypothesis: track a fast EMA alongside the slow one; in drifting
regimes the fast one diverges, so blend FV toward it and shrink target
position. Should stop us from fighting a real trend.

Tested with blend caps at 0.3, 0.5, 1.0 and DRIFT_BLEND_Z in [2, 4, 6].
**Every variant underperformed v4 on CSV**, ranging from -800 to -10,000
grand total. The reason:

- Even on "drift" days, the price eventually reverts. v4's slow-EMA
  anchor captures that reversion; fast-EMA blending shrinks the
  position right when the signal is about to pay off.
- On calm days, the fast EMA chases short-term noise and gives false
  "regime shift" signals that pull us off the edge.

Dropped. Slow EMA is itself the alpha.

## Attempted fix #2 (shipped): per-asset stop-loss

Track session cash flow per asset via `state.own_trades`:

```
bought  ->  cash -= price * qty
sold    ->  cash += price * qty
MTM PnL = cash + position * mid
```

When MTM PnL on any MR asset drops below `STOP_LOSS_THRESHOLD`, pause
MR on that asset for `STOP_PAUSE_TICKS` and unwind position passively
(post one-side inside-the-spread quote on the reducing side).

Tuned:

| Threshold | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| v4 (no SL) | 19,372 | 24,040 | 7,404 | 50,816 |
| −2,000 | 17,706 | 21,262 | 8,495 | 47,463 (too tight) |
| **−2,500** | **19,148** | **23,144** | **8,757** | **51,048** ← shipped |
| −3,000 | 19,084 | 23,197 | 8,757 | 51,038 |
| −3,500 | 18,258 | 23,248 | 8,757 | 50,264 |
| −4,000 | 18,184 | 21,889 | 8,757 | 48,830 (too loose) |

**Day 2 jumps from 7,404 → 8,757 (+18%)** — exactly the improvement we
wanted. Days 0 and 1 cost marginally (the SL triggers occasionally on
short drawdowns that would have recovered). Net: +232.

## Sanity flip — confirms the stop-loss works

Flipping the MR target direction (the known anti-strategy):

- v4 sanity flip: −72,601
- v5 sanity flip: −53,168

The stop-loss caps the anti-strategy's maximum damage from −72k to
−53k. That's 27% less tail loss, which is the right direction — the SL
is genuinely bounding downside when the strategy is wrong.

## Implementation detail — cash-flow accounting

`state.own_trades` is keyed by symbol and populated after each tick's
fills. Each `Trade` has `buyer`, `seller`, `price`, `quantity`,
`timestamp`. We track `cash_<asset>` and `ot_ts_<asset>` in
`traderData`; dedupe by timestamp so we don't double-count trades that
appear across multiple ticks.

`t.buyer == "SUBMISSION"` means we bought; `t.seller == "SUBMISSION"`
means we sold. Quantity is always treated as `abs(int(quantity))` for
the cash calculation.

## Pause window mechanics

Once triggered, `pause_until_<asset>` is set to `current_ts + 1000`
(= 1,000 ticks of pause). During the pause we post only a one-sided
passive quote on the reducing side (sell at best_ask-1 if long, buy at
best_bid+1 if short) capped at 30 contracts/tick.

Pause window at 500 ticks under-unwinds; at 2,000 ticks over-pauses
and misses re-entries. 1,000 is the sweet spot (tested).

## Portal projection

v4 CSV : portal = 50,816 : 17,450 → ratio 0.343.
v5 CSV 51,048 → portal projection ≈ 17,530 (~+80 over v4).

Modest absolute improvement, but the tail-risk reduction is real
insurance. A drifting-day portal run where v4 would have hit a −5k to
−10k tail might cost us only −1k to −2k with v5.

## Staged

```
Rubenstrats/Harry_potter_v5/
├── Harry_potter_v5.py
├── README.md
└── results/

traders/round3/Harry_potter_v5.py
```

## What to look for in the portal result

- Main case: PnL similar to v4 (~17-18k).
- Drift-day case: if the session has a persistent drift, v5 should
  outperform v4 meaningfully because the SL keeps our losing asset
  from bleeding.
- Watch for: whether SL triggers fire at all. If session PnL is
  mostly positive, SL won't trigger and v5 = v4.

## Open-question next steps

- Partial unwind rather than full pause: when MTM worsens, reduce
  target by a factor instead of flattening to zero.
- Re-entry logic: after a stop-loss pause, require a z-score sign
  flip before re-entering instead of just waiting 1,000 ticks.
- Correlated stop-loss: the 6 near-money VEVs move together; if all
  are triggered in quick succession, pause the whole basket.
