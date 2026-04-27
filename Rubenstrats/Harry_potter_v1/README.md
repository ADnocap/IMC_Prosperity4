# Harry_potter_v1 — Round 3 "Gloves Off"

First-draft trader for P4 R3 on Solvenar. Consolidates all R3 EDA findings
as of 2026-04-24. Single-file submission (`Harry_potter_v1.py`).

## Round context

- R3 "Gloves Off" kicks off the **Great Orbital Ascension Trials (GOAT)**;
  leaderboard resets, all teams start from 0 PnL.
- Rounds on Solvenar last **48 hours**.
- Prior-round products (OSMIUM, PEPPER_ROOT) are **not tradeable** — no
  handlers needed in the submission.
- Manual challenge: **Ornamental Bio-Pods** (two offers to the Celestial
  Gardeners' Guild, auto-converted to profit). Handled separately.

## Products and limits

| Product | Type | Limit |
|---|---|---|
| HYDROGEL_PACK | delta-1 | 200 |
| VELVETFRUIT_EXTRACT | delta-1 (options underlying) | 200 |
| VEV_4000 … VEV_6500 (10 strikes) | European call vouchers on VELVETFRUIT_EXTRACT | **300 each** |

**Voucher strikes**: 4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500.

**Voucher expiry**: 7 days from start of R1. TTE schedule:

| Round | TTE at start | TTE at end |
|---|---|---|
| R1 (historical day 1) | 7d | 6d |
| R2 (historical day 2) | 6d | 5d |
| **R3 (final eval)** | **5d** | **4d** |
| R4 | 4d | 3d |
| R5 | 3d | 2d |
| R6 | 2d | 1d |
| R7 | 1d | 0 (expiry) |

**Historical CSVs in `data/prosperity4/round3/` cover days 0, 1, 2**
(tutorial, R1, R2) with TTEs of 8d, 7d, 6d respectively.

## Underlying: VELVETFRUIT_EXTRACT

Quick stats across 30,000 snapshots (3 days × 10k ticks):

| Metric | Value |
|---|---|
| Mean | 5250.1 |
| Range | [5198, 5300] |
| Spread | median 5 |
| Depth | bid1 25, ask1 25 |
| Per-day σ | 2.136% → 2.162% → 2.166% (day 0→2) |
| Inter-day σ std | 0.016% (stable) |
| Log-return skew / excess kurt | −0.03 / +0.35 (~Gaussian) |

**Microstructure correction** (critical): per-tick σ is inflated by bid-ask
bounce. Variance-ratio test gives VR(k→∞) = 0.71 and lag-1 ACF = −0.16. The
de-noised realized σ plateau is **~1.8%/day** (stable across k ∈ [10, 50]).

## The edge

Black-Scholes IV inversion (correct TTE of 8d/7d/6d across the 3 days) on
each VEV strike shows a rock-stable implied vol:

| Strike | Median IV/day | Note |
|---|---|---|
| 5000 | 0.0127 | ATM |
| 5100 | 0.0125 | ATM |
| 5200 | 0.0127 | ATM |
| 5300 | 0.0129 | ATM |
| 5400 | 0.0120 | ATM |
| 5500 | 0.0130 | slightly OTM |
| 6000 | 0.0205 | pricing-floor artifact (ask = 1) |
| 6500 | 0.0312 | pricing-floor artifact (ask = 1) |
| 4000 / 4500 | ~0 | pinned at intrinsic |

ATM IV/day is **0.0125 ± 0.0003 across all days and all ATM strikes** — the
bot is using a fixed vol parameter. Realized σ (microstructure-adjusted) is
**0.018/day**. **Options are ~30% low in σ-terms, ~53% low in variance.**

Per-voucher edge at T=5d, S=5250 (vega × Δσ):

| K | Fair @ σ=0.018 | Bot fair @ σ=0.0125 | Edge | Δ (σ=0.018) |
|---|---|---|---|---|
| 5000 | 260 | 255 | 5 | 0.89 |
| 5100 | 177 | 158 | 19 | 0.77 |
| 5200 | 109 | 83 | 26 | 0.60 |
| 5300 | 64 | 34 | 30 | 0.41 |
| 5400 | 28 | 8 | 20 | 0.25 |
| 5500 | 12 | 4 | 8 | 0.13 |

Magritte's *"Ceci n'est pas une pipe"* image in the R3 data capsule fits the
theme — **implied vol is not realized vol**. That's the R3 edge.

## Hedge capacity constraint

- Position limit on VELVETFRUIT_EXTRACT is 200 — that bounds our hedge.
- Peak net voucher delta at full positions: up to ~1100 (all 6 strikes
  maxed).
- So we can only hold **~17% of max voucher position before exhausting hedge
  headroom**.

We cap net voucher delta at **NET_DELTA_BUDGET = 180** (keeps a 20-share
buffer vs the hedge limit for MM slack).

Greedy allocation by edge-per-delta at T=5d:

| K | Edge/Δ | Strategy |
|---|---|---|
| 5400 | 80.0 | Load up first |
| 5300 | 73.2 | Fill next |
| 5500 | 62.5 | Small vega but cheap delta |
| 5200 | 43.3 | Fill only if cheap |
| 5100 | 24.7 | Opportunistic |
| 5000 | 5.6 | Skip — delta burn too high |

## Bot calibration (from `calibration/<asset>/params.json`)

Pipeline successfully fit bot quoting formulas for all 12 assets. **Structural
caveat**: each asset's "FV process" was fit as an independent random walk on
its own mid price. For the VEV vouchers, that's wrong — real FV is
`BS(S_velvetfruit, K, T, σ_bot)`. The calibrated `mean` values are just
time-averaged BS fair values, and the `sigma` is the noise around that mean,
not the vega coupling. **Result: the MC sim built from these params will not
correctly couple UL and voucher moves — delta-hedging cannot be backtested in
the Rust sim** until the FV process is replaced with a BS-on-UL process.

The **bot formulas themselves are useful** — they're expressed in terms of
`fv`, which can be supplied from BS at runtime.

### Bot quoting formulas

**HYDROGEL_PACK** (2 layers, always present)

- Layer 1 (outer, presence 0.999): `bid = floor(fv · 0.999)`, `ask = ceil(fv · 1.001)` → ~20 wide
- Layer 2 (inner, presence 0.975–0.98): `bid = floor(fv − 0.5) − 7`, `ask = round(fv) + 8` → ~15 wide
- Volume: uniform [20, 30] and [10, 15]

**VELVETFRUIT_EXTRACT** (3 layers)

- Layer 1 (presence 0.11–0.14): `bid = floor(fv − 0.75) − 2`, `ask = floor(fv − 0.75) + 5`
- Layer 2 (presence 0.999, the anchor): `bid = floor(fv − 0.5) − 2`, `ask = floor(fv − 0.5) + 4` → 6 wide
- Layer 3 (presence 0.38–0.40): `bid = floor(fv − 0.75) − 1`, `ask = floor(fv − 0.5) + 3` → 4 wide

**VEV deep ITM** (proportional offsets — identical template to PEPPER R1)

- VEV_4000: `bid = floor(fv · (1 − 0.01))`, `ask = ceil(fv · (1 + 0.01))`
- VEV_4500: similar proportional + deep-fixed layer

**VEV near-money** (fixed offsets, narrow spreads)

- VEV_5200: `bid = floor(fv − 0.5) − 1`, `ask = floor(fv − 0.5) + 3` → 4 wide
- VEV_5300: `bid = floor(fv + 0.5) − 1`, `ask = floor(fv − 0.5) + 2` → 3 wide
- Others follow same pattern

**VEV deep OTM** (pinned at 0/1 by flooring)

- VEV_6000, VEV_6500: `bid = 0`, `ask = 1`. Zero taker flow in data.

## What was ruled out

- **Deep-ITM arb** (VEV_4000, 4500): only 1 snapshot in 30k shows `ask < S − K − edge`. Market quotes pinned tightly at intrinsic.
- **Deep-OTM passive short** (VEV_6000, 6500): 0 trades at price=1 across 30k snapshots. All observed trades are at price=0 (people dumping worthless contracts). No taker flow to exploit.
- **Vertical spread / convexity arb**: not formally scanned, low prior — bot uses one BS formula across strikes.
- **Signal-based directional on UL**: UL realizes σ=1.8%/day, drift ~0.3%/day (noise). Position limit caps directional edge below vol-arb edge. Deferred.
- **Basket / cross-asset hypothesis** (HYDROGEL vs UL): not formally checked but UL and HYDROGEL have very different scales (5250 vs 10000) and σs (0.018 vs 0.006). Low prior.

## Trader strategy (v1)

1. **Compute TTE** each tick: `TTE = 5.0 − (day + timestamp/1e6)`. Day counter bumps when `timestamp < prev_timestamp`.
2. **VEV take-only, no MM.** For K ∈ {5000, 5100, 5200, 5300, 5400, 5500}:
   - `our_fair = BS(UL_mid, K, TTE, 0.018)`
   - Take each ask below `our_fair − 2`, up to: position limit 300, or hedge budget.
   - Rare: sell bids above `our_fair + 2`.
3. **Delta-hedge via VELVETFRUIT MM.**
   - `target_velv = −round(net_voucher_delta)`, capped to ±200.
   - Standard MM (penny-jump inside Layer 2) with quotes skewed aggressively toward target.
4. **HYDROGEL MM** (independent).
   - Midprice FV, 15–16-wide bot spread, penny-jump inside, inventory skew past ±80, base size 30.
5. **No MAF bid** (R2-only).
6. **No conversions** (no Bio-Pods products in algorithmic data).

## Parameters

| Constant | Value | Rationale |
|---|---|---|
| `SIGMA_TRUE` | 0.018 | Microstructure-robust realized σ/day on VELVETFRUIT |
| `SIGMA_BOT` | 0.0125 | Bot pricing σ (reference only) |
| `TTE_AT_START` | 5.0 | R3 start of eval (update per round) |
| `EDGE_TAKE_VEV` | 2 | Min XIRECs below fair to take |
| `EDGE_TAKE_HYDROGEL` | 3 | Same for UL |
| `EDGE_TAKE_VELVETFRUIT` | 2 | Same |
| `NET_DELTA_BUDGET` | 180 | Hedge headroom (200 limit − 20 MM buffer) |
| `MM_BASE_SIZE_HYDROGEL` | 30 | Per-side MM size |
| `MM_BASE_SIZE_VELVETFRUIT` | 30 | Per-side MM size |
| `SKEW_THRESHOLD_HYDROGEL` | 80 | Inventory skew trigger (40% of limit) |
| `SKEW_THRESHOLD_VELVETFRUIT` | 80 | Same |

## Known limitations / next steps

1. **MC backtest is invalid** for vol-arb until the calibration FV process is
   replaced for VEVs (BS-on-UL instead of independent RW). Validate with
   `prosperity3bt` on R3 CSVs for now (UL-VEV coupling is real there).
2. **Hedge is static delta** — no gamma/vega re-hedging logic beyond per-tick
   target updates. Acceptable for 1-day eval; revisit if we hold overnight.
3. **No MM on VEVs** — bot spreads of 3–4 ticks leave little room to quote
   inside and still have edge after slippage. Could revisit at Layer 2
   offsets if fills come cleanly.
4. **Strike allocation is implicit** via the greedy take-on-cheap loop, not
   explicit linear-program allocation. Probably ~5% suboptimal.
5. **No adjustment for realized-vol uncertainty** — we assume 0.018 exactly.
   If true realized σ is lower (closer to bot's 0.0125), we overpay for VEVs
   and lose on the hedge leg. Consider a conservative σ=0.017 if results are
   marginal.
6. **Signal-based tilts not wired in** — could add top-of-book imbalance or
   trade-flow signal to bias VELVETFRUIT MM direction.

## File structure

```
Rubenstrats/Harry_potter_v1/
├── Harry_potter_v1.py   # The trader (single-file submission)
├── README.md            # This file
└── results/             # Post-submission portal logs (.png / .log / .json)
```

## Related analysis

- `analysis/round3/eda.py` — underlying path, raw IV smile, product summary
- `analysis/round3/iv_correct_tte.py` — IV smile with proper TTE + ATM IV time series
- `analysis/round3/ul_vol_check.py` — per-day σ, VR test, normality
- `analysis/round3/arb_and_hydrogel.py` — wing-arb scan + HYDROGEL AR(1) fit
- `analysis/round3/survey_calibration.py` — bot formula summary per asset
- `calibration/<asset>/params.json` + `calibration.md` — per-asset bot fits
- `tmp/calib_report_v14.md` — pipeline stat-test results (all pass)
