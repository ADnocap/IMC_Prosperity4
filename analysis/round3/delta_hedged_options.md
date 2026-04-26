# Delta-Hedged Short-Vol on R3 Vouchers — Walk-Forward

**2026-04-25** — `delta_hedged_options.py` on 3×10K ticks. Smile: `iv = 0.230 + 0.044·m
+ 1.938·m²`, `m = log(K/S)`, `T = 6/365` (matches `r3_smile_clean.py:78,94`). Strikes:
VEV_5200/5300/5400/5500.

## Headline

**Delta hedging helps but does NOT unlock 60k+ alpha on R3.** Best PnL on the 3-day
path is **+166 to +1,033 XIRECs/day**. Chris's "spread eats hedge"
(`p3_options_reference.md:213-219`) is partially confirmed: at rebal freq < 500 ticks
the spot-spread cost dominates the alpha.

## 1. Rebalance frequency sweep (always-on short, hedged)

**1a. Full book (300/strike, 1,200 contracts)** — spot cap binds:

| every | PnL/day | hedge spread/day | resid Δ std |
|---:|---:|---:|---:|
| 1     | +633 | 200 | 34.0 |
| 100   | +633 | 200 | 34.1 |
| 1000  | +633 | 200 | 32.3 |

Frequency irrelevant: book delta ≈364 vs spot cap 200 → spot pinned at −200 from tick 0;
no further rebalances. **Spot 200 limit binds when shorting all 4 strikes to limit.**

**1b. Small book (100/strike, 400 contracts)** — hedge fits in cap:

| every | PnL/day | hedge spread/day |
|---:|---:|---:|
| 1     | **−18,401** | 15,210 |
| 100   | −2,985  | 1,470 |
| 500   | −1,494  | 641   |
| 1000  | **+166**  | 352   |

Hedge cost scales linearly with rebalance count (~5 ticks spot spread × Δqty per
rebalance). **Sweet spot ≥ 1000 ticks.**

## 2. Hedged vs unhedged (best freq = 1000)

| size | fill | hedged/day | unhedged/day | benefit |
|---:|---|---:|---:|---:|
| 300 | bid-cross    | +633   | −2,200 | **+2,833** |
| 100 | bid-cross    | +166   | −733   | +900 |
| 300 | passive @ mid | **+1,033** | −1,800 | +2,833 |
| 100 | passive @ mid | +300 | −600 | +900 |

The +2,833 benefit is **directional risk removal** (S drifted +9 against a 364-Δ
short over 3 days), NOT vol-alpha capture.

## 3. Per-strike unhedged PnL (300 short, freq=1000, bid-cross)

| K | PnL/day | day-0 mid → day-2 mid |
|---:|---:|---:|
| 5200 | **−1,900** | 101.5 → 119.0 |
| 5300 | −600   | 53.0 → 58.0 |
| 5400 | +200   | 23.0 → 20.0 |
| 5500 | +100   | 8.5 → 7.0 |

**Prior `options_analysis.md:194-199` "+1,320 EV/round on VEV_5300" does not survive
walk-forward.** It used day-0/day-2 mid drops on strikes the underlying moved TOWARD.
On this realized path S rallied 9 → 5200/5300 went UP. Theta only wins on
small-delta strikes (5400, 5500).

## 4. Signal-threshold sweep (mid – BS_fair > k·σ_diff, hedge on, freq=100)

| k | short PnL/day | long PnL/day |
|---:|---:|---:|
| 0.0 | **+633** | −1,833 |
| 0.5 | −1,487   | −1,741 |
| 1.0 | −1,482   | −611  |
| 1.5 | +465     | 0     |
| 2.0 | −7,420   | 0     |

σ_diff ≈ 3.85, much tighter than P3 (~15) → flipping in/out at k≥0.5 churns the book
and spread cost dominates. Always-on short (k=0) wins. **Timo's IV-scalp does not
port to R3.** Long-vol loses at every threshold.

## 5. Symmetry, hedge cost, vega

- Mean(mid – fair) = +3.80, frac>0 = **81.5%** — one-sided rich.
- Spot bid-ask: **5 ticks** (NOT 3). Round-trip 100 lots = 500 XIRECs.
- Full-cap delta 364 vs spot cap 200 → neutralize only **55%** of book delta.
- Vega = 199,940/1.0 vol → **2,000 XIRECs per 1% IV shift** > daily alpha. Vega is
  the dominant uncovered risk.

## 6. Per-day stability (signal=0, freq=100, hedged, full)

| day | PnL | spread |
|---:|---:|---:|
| 0 | +2,850 | 600 |
| 1 | −1,000 | 600 |
| 2 | −3,300 | 500 |

Day-to-day std (~3k) >> mean (+166). N=3 too small. **No statistical edge established.**

## Recommendation

**Do not size up on a delta-hedged short-vol play.** The data shows:

1. **Rich-vouchers alpha was overstated** in `options_analysis.md`. Walk-forward:
   shorting K=5200/5300 LOSES because S drifted toward the strikes faster than theta.
2. **Hedging adds ~+900–2,800/day** but only as directional-drift removal — not vol alpha.
3. **Spot spread = 5 ticks**, hedge dominates at any rebal freq < 500.
4. **Smile-deviation signal too noisy** (σ≈3.85) — Timo's flip-scalp doesn't transfer.
5. **Vega risk** (2k/1%) > daily alpha even fully delta-hedged.

### Next steps

- Keep penny-jump MM in `traders/round3/a.py`.
- Add **small always-on short** on LOW-delta strikes only (VEV_5400/5500), ~50 each —
  only strikes where unhedged short was profitable. EV +100–300/day, negligible risk.
- **Skip delta hedge in v1.** Revisit only if MC residual-delta swings > 2k.
- **Run on MC** (`prosperity4mcbt`) — N=3 days is not enough; +166/day has ~3k std.
- The 60–150k P3 numbers needed wider smile residual and voucher-to-intrinsic expiry —
  P4 R3 has neither.

## Files

`delta_hedged_options.py`, `.json`, `smile_coefs_day2.json`, `r3_smile_clean.py:104-112`,
`options_analysis.md:194-231` (contradicted), `p3_options_reference.md:206-224`.
