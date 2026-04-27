# pete_hegseth_v1

Counterparty-flow follower on **VELVETFRUIT_EXTRACT**. Built off the Round-4 trades CSV which now reveals the buyer/seller of each fill (anonymised "Mark 01..67").

## Signals (lead-lag test, day-3 holdout validated)

| Trader | Side | h=1 hit% / t | h=20 hit% / t |
|---|---|---|---|
| Mark 67 | BUY VELVETFRUIT | 95.7% / +13.1 | 65.2% / +3.34 |
| Mark 49 | SELL VELVETFRUIT | 5.1% / −11.7 | 25.6% / −3.69 |

Mean signed move ~ ±2 mid units, sustained through h≈20 (2000 timestamps), decays past that. Per-day t-stats scale ~1/√N — signal is intra-day stable, not an artifact of the two re-released days (R4 d1=R3 d1, R4 d2=R3 d2; d3 is fresh).

Mark 22's VEV-ladder fade signals from the pooled 3-day run failed day-3 holdout, so they're **not** included here.

## Logic

1. Each tick, scan `state.market_trades[VELVETFRUIT_EXTRACT]` for fills strictly newer than `last_seen_ts`.
2. New `Mark 67` BUY → push bias `(timestamp, +qty)` onto the active list.
3. New `Mark 49` SELL → push bias `(timestamp, −qty)`.
4. Sum active biases with linear decay `max(0, 1 − age/HOLD_TICKS)`; expire at `HOLD_TICKS=2000`.
5. `target = clamp(SIGNAL_GAIN × signed_weight, ±LIMIT)`. `SIGNAL_GAIN=4.0` per traded share at peak.
6. Reach target by **aggressive cross-spread takes** capped at `TAKE_MAX=40`/tick (passive sits too long for an alpha that decays in 2000 ticks).
7. All other products quoted flat — v1 isolates the follower edge.

## Tunables

```python
HOLD_TICKS = 2000      # decay window (matches h≈20 signal horizon)
SIGNAL_GAIN = 4.0      # position units per traded share at peak
TAKE_MAX = 40          # max takes per tick
```

## Notes

- Mark 67's h=1 hit-rate (96%) is partly mechanical (his lift IS the print). But the signal still has t=+5.97 at h=20 OOS, so it's real predictive content past the same-bar effect.
- This is the v1 minimum viable test. Future:
  - v2: layer onto Harry_potter_v8's MR-on-everything baseline so VELVETFRUIT trades both signals (counterparty + z-score).
  - v3: confirm whether pickling fewer/more trades into one bias bucket vs decaying continuously matters.
  - v4: revisit Mark 22 VEV ladder fade with more data once R5 lands.
