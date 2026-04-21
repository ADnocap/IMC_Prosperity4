# ASH_COATED_OSMIUM Calibration

Round 1/2 product. Gaussian random walk around ~10,000.

**Source data**: portal hold-1 submission 103017 (FV extracted via `PnL(t) + buy_price = server_FV(t)`) + 30,000-tick CSV dataset (days -2, -1, 0). Raw extract at `data/fv_and_book.json`.

## Fair Value process

| Property | Value |
|---|---|
| Type | Pure Gaussian random walk |
| σ per step | 0.3117 |
| Drift | 0.0 (mean step = 0.000016, n.s.) |
| Quantization | 1/1024 (~0.001) |
| Starting value | ~10,002 |
| Autocorrelation | none (all lags p > 0.05 after Bonferroni) |
| Normality | skewness z=0.64, kurtosis z=−0.14 |
| Position limit | 80 |

## Bot 1 — Outer Wall

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `floor(FV) - 10` | 99.7% (791/793); misses at frac ≈ 1.0 boundary |
| Ask formula | `ceil(FV) + 10` | 100.0% (778/778) |
| Volume | `U(20, 30)`, same both sides per tick | χ² uniform p=0.22 |
| Presence | 80% per side, iid Bernoulli | |
| Spread | 21 (non-integer FV), 20 (integer FV) | |

## Bot 2 — Inner Wall

| Property | Value | Confidence |
|---|---|---|
| Bid formula | `round(FV) - 8` (equiv. `floor(FV - 0.5) - 7`) | 100.0% (758/758) |
| Ask formula | `round(FV) + 8` (equiv. `floor(FV - 0.5) + 9`) | 100.0% (806/806) |
| Volume | `U(10, 15)`, same both sides per tick | χ² uniform p=0.89 |
| Presence | 80% per side, iid Bernoulli | |
| Spread | 16 always |  |

The `floor(FV - 0.5)` notation is preferred for the Rust simulator — it makes the constant 16-wide spread explicit and unambiguously breaks ties downward.

## Bot 3 — Noise

| Property | Value |
|---|---|
| Presence | 7.6% of ticks |
| Single-sided | 100% |
| Offsets from round(FV) | {−3, −2, +1, +2}, roughly uniform |
| Crossing volume | `U(4, 10)`, mean 7.4 |
| Passive volume | `U(1, 5)`, mean 3.4 |
| Duration | 87% single-tick, 7% two-tick |

Low impact on strategy — can be approximated or ignored.

## Trade bots

- Trades on ~4.0% of ticks, mostly 1 trade per tick
- Quantity bimodal: {2–6} and {7–10}

## Open question — proportional K values

OSMIUM's FV range is too narrow (~±30) in portal data to distinguish proportional offsets from fixed integers. If OSMIUM uses the same proportional scheme as PEPPER, the effective K values around FV=10,000 would be:
- K_bot1 ≈ 0.00105 (gives offset ≈ 10.5 at FV=10,000)
- K_bot2 ≈ 0.0008 (gives offset ≈ 8 at FV=10,000)

Since OSMIUM is stationary, it doesn't matter in practice — fixed offsets match at 99.7–100%.

## Presence model (shared with PEPPER)

Each bot quotes on each side independently with ~80% probability per tick. All four channels (B1_bid, B1_ask, B2_bid, B2_ask) pass χ² independence tests (p > 0.05). No autocorrelation (|r| < 0.025, p > 0.49). Geometric run-lengths consistent with iid Bernoulli.

## Scripts

- `scripts/calibrate.py` — brute-force formula search + statistical validation. The template to clone for a new random-walk asset.
