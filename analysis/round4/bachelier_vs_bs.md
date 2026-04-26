# Bachelier vs Black-Scholes smile fit on R3 voucher data

**Source data:** `data/prosperity4/round3/prices_round_3_day_{0,1,2}.csv` (30,000 ticks, 10 strikes, 1 underlying).
**Script:** `analysis/round4/bachelier_vs_bs.py` -> `analysis/round4/bachelier_vs_bs.json`
**TTE convention (defensible choice):** `T_ticks = 30_000 - (day*10_000 + ts//100)`; for BS we anchor to a calendar year so `T_years = T_ticks / (365*10_000)` (Timo / Chris convention -- vol comes out at conventional annualised scale). Bachelier uses `T_ticks` directly so `sigma` is "price units per sqrt(tick)". Smile is fit per tick on 6 core strikes (5000-5500); residuals are then evaluated on **all** 10 strikes including the wings.

---

## 1. Headline -- Black-Scholes wins by ~2.5x in price space

Pooled IV-RMSE and price-RMSE on the **core 6 strikes** (5000, 5100, 5200, 5300, 5400, 5500), per-tick parabolic fit:

| Metric (core fit) | Black-Scholes | Bachelier | BS / Bach |
|---|---:|---:|---:|
| In-fit IV RMSE (model units) | 0.02490 | 0.21200 | -- |
| In-fit price RMSE (XIRECs) | **1.479** | **3.635** | 0.41x |
| In-fit mean abs price residual (XIRECs) | 0.961 | 1.014 | 0.95x |

The IV-space numbers are not directly comparable (different units), but **price-space residuals are**. BS leaves ~2.16 XIRECs less RMSE per voucher tick. Mean-abs is essentially tied because the median tick is well-fit by both -- the gap is in the tail (BS better localizes mispricings). Either way, the price RMSE gap of >2 XIRECs is comfortably above the 0.5 XIRECs trading-significance threshold.

## 2. Per-strike residual table (core-6 fit, residual measured on ALL 10)

**Black-Scholes** (price residual = iv_resid * BS vega):

| K | n | mean iv_res | std iv_res | mean price_res | std price_res | mean abs price_res |
|---:|---:|---:|---:|---:|---:|---:|
| 4000 | 26,736 | +3.62 | 1.42 | **+288.3** | 198.4 | 288.3 |
| 4500 | 20,982 | +2.62 | 1.96 | **+253.7** | 267.3 | 253.7 |
| 5000 | 29,878 | -0.001 | 0.016 | -0.07 | 1.13 | 0.18 |
| 5100 | 29,883 | -0.005 | 0.031 | -0.10 | 1.31 | 0.67 |
| 5200 | 29,882 | +0.008 | 0.006 | +0.75 | 0.56 | 0.82 |
| 5300 | 29,880 | +0.016 | 0.020 | **+1.38** | 1.26 | 1.39 |
| 5400 | 29,883 | -0.031 | 0.021 | **-2.11** | 0.89 | 2.14 |
| 5500 | 29,878 | +0.013 | 0.012 | +0.56 | 0.41 | 0.57 |
| 6000 | 29,618 | +0.324 | 0.390 | +1.36 | 1.07 | 1.40 |
| 6500 | 29,130 | +0.675 | 0.888 | +2.21 | 2.15 | 2.28 |

**Bachelier** (price residual = iv_resid * Bachelier vega):

| K | n | mean iv_res | std iv_res | mean price_res | std price_res | mean abs price_res |
|---:|---:|---:|---:|---:|---:|---:|
| 4000 | 26,988 | +42.67 | 14.38 | **+1932** | 1032 | 1932 |
| 4500 | 21,177 | +28.39 | 23.13 | **+1253** | 1243 | 1253 |
| 5000 | 29,989 | +0.001 | 0.211 | +0.00 | 5.14 | 0.28 |
| 5100 | 29,992 | -0.022 | 0.382 | -0.17 | 4.57 | 0.74 |
| 5200 | 29,992 | +0.022 | 0.025 | +0.78 | 0.56 | 0.85 |
| 5300 | 29,991 | +0.050 | 0.176 | +1.48 | 4.15 | 1.48 |
| 5400 | 29,992 | -0.086 | 0.140 | **-2.07** | 2.31 | 2.16 |
| 5500 | 29,991 | +0.034 | 0.128 | +0.52 | 1.31 | 0.57 |
| 6000 | 29,970 | +0.916 | 4.578 | +1.25 | 4.41 | 1.43 |
| 6500 | 29,919 | +1.918 | 14.008 | +1.93 | 9.40 | 2.33 |

## 3. Wings handling -- exclude both deep ITM and deep OTM from the fit

- **VEV_4000 / VEV_4500 (deep ITM)**: under both models, IV is huge and unstable -- BS hits the 5.0 cap on >40% of ticks (mean IV 4.62 / 3.39 vs ~0.6 for the core), Bachelier hits 50.0 (mean 45 / 30 vs ~1.8). Their bid sits ~10/8 *below* intrinsic (`options_analysis.md` Section 4) so the IV inversion is meaningless -- they are essentially MM'd as "intrinsic + spread" futures, not options. **Exclude from the smile fit.** A trader can still post tight inside-spread quotes against them, but never use the smile fair value for those strikes.
- **VEV_6000 / VEV_6500 (deep OTM)**: pinned at bid=0 / ask=1, mid stuck at 0.5. IV residual is dominated by the floor, not by the smile. **Exclude.**
- **Core 5000-5500**: well-behaved IV in [0.38, 5.0]; this is the only band where the parabola is meaningful.

## 4. Pooled BS smile coefficients (recommended for hard-coding, Timo-style)

`iv = a + b * m + c * m^2`, with `m = log(K/S) / sqrt(T_years)` (T_years = ticks_remaining / 3,650,000).

**Pooled across all 30K ticks, core 6 strikes (n=179,299):**
```python
COEFS_BS = (0.580261, 0.033704, 0.089775)   # (a, b, c)
```

**Per-day stability check (BS, core 6):**

| Day | a | b | c | n |
|---:|---:|---:|---:|---:|
| 0 | 0.41095 | -0.00511 | 0.04339 | 60,000 |
| 1 | 0.49843 | +0.00381 | 0.03926 | 60,000 |
| 2 | 0.88497 | +0.03482 | 0.07328 | 59,299 |

The level (`a`) drifts up day-by-day -- effective ATM IV climbs from ~0.41 -> 0.50 -> 0.88 as TTE shrinks (this is partly the `1/sqrt(T)` rescaling of `m` distorting). The curvature (`c`) is stable around 0.04-0.07. **For a live trader, refit `a` per tick (EMA on the residuals) and treat `b, c` as static.** This matches what Timo does in `tmp/p3_research/timo_trader.py` lines 583-587 (he hard-codes `[0.27362531, 0.01007566, 0.14876677]` and rebases the level).

## 5. Recheck: is "VEV_5400 cheap vs smile" finding still valid?

`FINDINGS_v2.md` claimed VEV_5400 is structurally cheap with z = -0.73 (under their BS smile clean fit on 6 strikes). Recomputing here with both models, restricted to the same 6-strike fit:

| Strike | BS price_resid mean | BS std | **BS z** | Bach price_resid mean | Bach std | **Bach z** |
|---:|---:|---:|---:|---:|---:|---:|
| 5300 | +1.38 | 1.26 | **+1.09** | +1.48 | 4.15 | +0.36 |
| 5400 | -2.11 | 0.89 | **-2.38** | -2.07 | 2.31 | -0.89 |
| 5500 | +0.56 | 0.41 | **+1.36** | +0.52 | 1.31 | +0.39 |

The sign and rank are identical under both models -- **5400 is cheap, 5300 and 5500 are rich, in absolute price-residual terms (~2 XIRECs in either model)**. What flips is the *statistical confidence*: under BS the 5400 cheapness is z=-2.38 (very robust), under Bachelier it's z=-0.89 (borderline noise). The Bachelier residual std is 2.5-3x larger because Bachelier fits the smile worse, so the same +/-2 XIRECs of mispricing looks like noise. The BS z-scores are also higher than `FINDINGS_v2`'s -0.73 (which used a different per-tick anchoring) -- in the pooled fit here it is -2.38, even more decisive.

**Conclusion: FINDINGS_v2's "5400 cheap, 5300/5500 rich" trading thesis is robust to model choice and is in fact STRONGER under BS than the prior numbers suggested.** The per-tick smile-fit-then-trade-residual signal is therefore safe to use; switching from Bachelier to BS makes the residual std smaller, so trade thresholds (e.g. `|z|>1`) trigger more often and earlier.

## 6. Recommendation for R4 trader

1. Use **Black-Scholes** (`r=0`) for IV inversion and smile fits. Hardcode the pooled `(a, b, c) = (0.580, 0.034, 0.090)` for `m = log(K/S)/sqrt(T_years)`, then update `a` online with an EMA over the rolling residuals.
2. **Fit only on the 6 core strikes** (5000-5500). Exclude 4000/4500 (deep ITM, IV undefined) and 6000/6500 (pinned at floor).
3. Trade the residual per `FINDINGS_v2`'s vertical-spread plan -- the `5300/5400` and `5200/5400` pairs remain the highest-Sharpe signals, and their direction (5400 cheap vs 5300/5500 rich) is unchanged.
4. For 4000/4500 keep the existing penny-jump MM (don't try to value via smile).

## 7. Files

- Script: `analysis/round4/bachelier_vs_bs.py`
- Numerical output: `analysis/round4/bachelier_vs_bs.json`
- This report: `analysis/round4/bachelier_vs_bs.md`
