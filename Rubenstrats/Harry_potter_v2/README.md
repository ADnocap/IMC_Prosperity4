# Harry_potter_v2 — R3 "Gloves Off"

Second-draft submission for R3. Replaces v1's BS-informed vol-arb with a
plain penny-jump MM after the portal showed v1 losing on vouchers.

## v1 post-mortem (portal sub 367534, total PnL −138.5)

| Asset | PnL | Final pos | Diagnosis |
|---|---|---|---|
| HYDROGEL_PACK | **+609.8** | −19 | MM worked as designed |
| VELVETFRUIT_EXTRACT | **+249.4** | +31 | MM worked as designed |
| VEV_5000 | −337.6 | +71 | Vol-arb failed |
| VEV_5100 | −296.4 | +65 | Vol-arb failed |
| VEV_5200 | −128.0 | +47 | Vol-arb failed |
| VEV_5300 | −132.3 | +57 | Vol-arb failed |
| VEV_5400 | −83.2 | +48 | Vol-arb failed |
| VEV_5500 | −20.4 | +53 | Vol-arb failed |
| **Voucher sum** | **−998** | **+341** contracts | |

The voucher loss matches `(ask − mid) × 341 ≈ 1 tick × 341 = 340–1020` — i.e.,
**pure spread-crossing cost**. Why it didn't recover:

- Vouchers MTM at the book **mid**, which equals the bot's BS price at
  σ=0.0125. Our conjectured "true fair" at σ=0.018 never shows up in PnL
  unless we can sell back at that higher fair (market doesn't come up to
  us) or hold to expiry with delta-hedging.
- Full voucher positions would need ~1100 shares of short UL to hedge,
  but VELVETFRUIT limit is 200. Structural impossibility.
- Historical σ=0.018 was likely inflated by microstructure noise in the
  voucher mids or was a measurement artifact. It was not a true
  divergence from bot pricing.

## v2 strategy

**Pure penny-jump MM on all 10 active products.** No BS. No take-on-cheap.
No delta-hedge skew. Dead VEV_6000 / VEV_6500 are skipped.

### Mechanics
- For each product in `state.order_depths`:
  - If spread < 2 → skip (no room for penny-jump).
  - Quote one tick inside: `our_bid = best_bid + 1`, `our_ask = best_ask − 1`.
  - Size 15 per side (saturates the bot-depth cap on fills; bigger wastes
    nothing but costs position-limit tail headroom).
  - Hard inventory cutoff past 60% of position limit on the heavy side.
    MC showed "soft skew" (step quote back to best price) underperforms
    because it drops priority inside the bot.
- Position-limit check uses STARTING position (`state.position`), not
  locally-tracked post-take. The exchange cancels ALL orders on a side
  if sum of outstanding > limit − starting_position.

### MC backtest (friend's calibrated sim, 100 sessions, 10k ticks)

| Trader | Mean | Median | Std | 5% | 95% |
|---|---|---|---|---|---|
| v1 (BS + vol-arb) | 8,578 | 7,990 | 7,435 | −2,960 | 21,925 |
| a.py (size=5) | 11,666 | 12,547 | 9,891 | −3,568 | 26,960 |
| b.py (size=10) | 13,238 | 12,395 | 10,538 | −3,004 | 31,237 |
| **v2 (size=15)** | **13,312** | **12,483** | 10,610 | −3,505 | 30,973 |

Size sweep (v2 logic, uniform):

| size | Mean | 5% tail | Note |
|---|---|---|---|
| 10 | 13,238 | −3,004 | same as b.py |
| 12 | 13,276 | −2,954 | |
| **15** | **13,312** | −3,505 | sweet spot |
| 20 | 13,312 | −3,505 | saturated (bot depth cap) |
| 30 | 13,312 | −3,505 | saturated |

### Pre-submission sanity
- Per-side sizes ≤ position limit headroom in all cases (size 15 ≤ 200,
  300 trivially).
- No state needed in traderData; we preserve whatever was stashed for
  safety.
- `Trader.bid()` not defined — R3 has no MAF auction.
- No conversions — no Bio-Pods product in the algorithmic data.

### Known limits / next steps
- Size saturates at 15 because the sim caps fills at bot depth. In the
  real portal other teams are also penny-jumping — our fill rate may be
  lower, in which case size 10 might be as good or better than 15.
- No per-product tuning yet. HYDROGEL has 15-wide spreads vs VEV_5200's
  3–4-wide; uniform size is almost certainly suboptimal. Testing
  per-product sizes is the obvious v3.
- No signal-based tilt on UL. VELVETFRUIT has order-book imbalance and
  trade-flow signals that could be wired in for a directional tilt.
- Multi-level quoting (post at best_bid+1 AND best_bid+2 simultaneously)
  would increase fill coverage on wide spreads — deferred to v3.

## File layout

```
Rubenstrats/Harry_potter_v2/
├── Harry_potter_v2.py   # single-file submission
├── README.md            # this file
└── results/             # empty; post-submission portal artifacts go here
```

## Relevant commits / related files

- `traders/round3/a.py`, `b.py` — friend's penny-jump baselines
- `tmp/portal_367534/*` — v1 submission log, used for post-mortem
- `tmp/portal_366383/*`, `tmp/portal_367301/*` — friend's portal subs that
  pinned down the calibrated elastic trade rate
- `calibration/<asset>/params.json` — per-asset bot formulas (informs why
  penny-jump works: bots have fixed 2-4 tick spreads we can fit inside)
