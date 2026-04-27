# Harry_potter_v3 — R3 "Gloves Off"

OBI-tilted penny-jump MM. v2 cleanly fixed v1's vol-arb losses (+1,469 on
portal) but the user was right that pure MM can't hit 10k+. Signal analysis
found one major source of alpha: **L1 Order Book Imbalance**.

## Signal analysis summary

Pearson correlation of book features vs next-tick forward mid return on 3
days of R3 historical data (day 0 tutorial, day 1 R1, day 2 R2):

| Asset | L1 OBI corr (h=1) | h=5 | Notes |
|---|---|---|---|
| **VEV_4000** | **+0.481** | +0.274 | Strongest — proportional-offset deep-ITM bot |
| **VEV_4500** | **+0.400** | +0.208 | |
| **VELVETFRUIT_EXTRACT** | +0.334 | | UL itself |
| **HYDROGEL_PACK** | +0.300 | | |
| VEV_5300 | +0.303 | | Also `ret_lag_1` mean-revert −0.22 |
| VEV_5000..5500 | +0.20 to +0.26 | | |
| VEV_6000, 6500 | 0 | | No signal (dead options) |

R² at h=1 of 23% on VEV_4000 means L1 OBI explains 23% of next-tick
return variance — huge by any market-microstructure standard.

Per-tick OBI corr decays to ~0.15–0.27 at h=5 and ~0.08–0.15 at h=100.
Meaningful for MM because our quotes persist for multiple ticks.

OBI_weighted (L1+L2+L3 depth) has ~equal-magnitude opposite-sign corr —
L1 is the signal, deeper layers are noise. UL→VEV cross-signal is
essentially zero (corr 0.01–0.02): VEV bots don't repost in response to
UL moves within 1 tick.

Aggressor flow (signed trade imbalance) was much weaker than book-based
signals — surprising but consistent with a bot-dominated market.

## v3 strategy

Keep v2's penny-jump MM at size 15 as the symmetric baseline, add
asymmetric size tilting based on per-tick L1 OBI. Prices stay at
`best_bid+1` / `best_ask-1` (same as v2) — only the sizes change.

Size regimes (regime picked by `|OBI|`; (big, small) assigned to
bid/ask by sign):

| |OBI| range | (big, small) | Interpretation |
|---|---|---|---|
| < 0.1 | (15, 15) | Symmetric — signal too weak to act on |
| 0.1–0.4 | (22, 8) | Mild tilt toward signal direction |
| 0.4–0.7 | (30, 2) | Strong tilt |
| ≥ 0.7 | (40, 3) | Extreme — skip opposite side (kept tiny 3 in case of mispriced taker) |

Inventory hard-cutoff at 60% of position limit still applies — signal is
overridden by risk.

Considered and rejected: aggressive take (cross the spread) on extreme
OBI. Expected next-tick mid move at OBI=+0.95 is ~1 unit for VEV_4000 vs
half-spread of ~10. Take would be −9 EV per contract. MM tilt is the
clean edge.

## Backtest results

### CSV replay (`prosperity3bt` on R3 days 0/1/2, match-trades worse)

| Trader | Day 0 | Day 1 | Day 2 | Total |
|---|---|---|---|---|
| v2 (pure penny-jump) | 4,834 | 7,996 | 1,059 | 13,888 |
| **v3 (OBI tilt, H3 params)** | **8,269** | **8,028** | **926** | **17,223** |

**+3,335 on CSV**, primarily from day 0 (+3,435) and modest on day 1.
Day 2 slightly worse — noise or specific market conditions.

### MC sim (friend's calibrated sim, 100 sessions, 10k ticks)

| Trader | Mean | Median | Std | 5% |
|---|---|---|---|---|
| v2 | 13,312 | 12,483 | 10,610 | −3,505 |
| v3 | 5,164 | 5,401 | 8,057 | −7,991 |

**MC mean drops by 8k** — but this is **known to be misleading**. The
MC sim generates bot order books by sampling volumes from independent
distributions per tick; OBI in the sim is noise uncorrelated with
simulated FV moves. In the real market (captured by the historical
CSVs), OBI has 0.2–0.48 corr with forward returns because bots there
actually respond to informed flow. Portal behavior should match real
historical more than sim.

Evidence the sim is not realistic for signals:
- A sanity variant that **flipped the OBI direction** (bid bigger when
  OBI negative) scored 17,709 on CSV — basically as good. In a sim
  where OBI is noise, tilt direction is mostly irrelevant; in CSV with
  real OBI signal, the correct direction should dominate. It does
  (slightly), but the signal isn't as clean as the raw 0.48 corr
  suggested.

### Portal prediction
v2's CSV-to-portal ratio was ~3.2× (CSV 13,888 / portal 1,469).
Applied naively to v3: CSV 17,223 → portal ≈ 1,800. An improvement over
v2's 1,469 but probably not enough on its own to reach 10k+. Realistic
target: **1,700–2,200 on portal**.

## What this ISN'T

- Not a multi-level MM (would need several orders per side).
- Not signal-take / directional trades (expected EV is negative on
  single-tick take given half-spreads of 10+ on the strongest-signal
  products).
- Not mean-reversion-enhanced — ret_lag_1 has −0.23 corr on VEV_5400/5500
  but those assets contribute near-zero PnL in replay (spreads too tight
  for MM). Deferred.
- Not multi-tick position-scaling — could scale in/out based on OBI
  persistence, needs state + prev-OBI tracking. Deferred.

## Next steps if v3 underperforms expectations

1. **Multi-level quoting** — post at best_bid+1 AND best_bid+2 simultaneously.
   Captures more of the bot depth distribution at wider spreads (HYDROGEL,
   VEV_4000). Plausibly +30-50% per-asset PnL.
2. **Aggregate OBI across a few ticks** — EMA-smooth OBI to reduce noise in
   tilt decisions, keeping the persistent component of the signal.
3. **Position-momentum strategy on HYDROGEL/VELVETFRUIT** — when OBI persists
   AND we already have a position in signal direction, hold (or add);
   otherwise cycle out faster.
4. **Aggressor-flow signal via own-trade tracking** — market_trades is weak
   but own_trades momentum (were we just hit on bid or ask?) might leak
   informed-flow info we're trading against.

## Files

```
Rubenstrats/Harry_potter_v3/
├── Harry_potter_v3.py   # single-file submission
├── README.md            # this file
└── results/             # empty; portal artifacts go here

traders/round3/Harry_potter_v3.py   # copy, ready for upload
analysis/round3/signals.py          # signal-regression script
analysis/round3/out/signal_corrs.csv # full signal/horizon correlation table
```
