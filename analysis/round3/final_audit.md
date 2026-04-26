# Round 3 — Final Pre-Submission Audit

**Generated:** 2026-04-25. Last analysis pass before locking the v5 trader.
**Inputs:** `data/prosperity4/round3/{prices,trades}_round_3_day_{0,1,2}.csv` (3d × 10K ticks × 12 products).
**Script / data:** `analysis/round3/final_audit.{py,json}`.
**Convention:** strict per-day stratification on every finding; signal must hold across all 3 days.

---

## TL;DR — Three actionable upgrades

| # | Upgrade | Confidence | EV/day est. |
|---|---------|------------|------|
| **A** | **Apply porush's HYDROGEL OBI confidence-sized handler to VELVETFRUIT** with smaller bands (spread is 5 not 16). | High — Sharpe 0.34-0.42 every quarter all 3 days | +2,000-4,000 |
| **B** | **Drop in deeper OBI handler on VEV_4000 / VEV_4500** (extreme-OBI drift = ±5 ticks per signal). | High — 3-day stable | +1,000-2,500 |
| **C** | **Lock in rothschild's 5200/5400 vert-spread MR overlay** (3-day replay actual: +11,265 over 3 days, all days +). | High — historical replay confirms `cross_strike.md` | +3,755 |

Honest portal target after stacking A+B on porush + C on rothschild: **20-25k** (porush MC mean +11.7k baseline).

---

## 1. VELVETFRUIT_EXTRACT — never tuned, biggest opportunity

VELVET is porush's #2 contributor (+4,320). It received zero asset-specific tuning. Spread is constant **5 ticks** (vs HYDROGEL's 16) and σ_diff is ~1.13. Day 0/1/2 mid: 5250→5244, 5245→5266, 5268→5296.

### OBI tier H=1 drift (3-day stable)

| Bucket | n/day | day0 | day1 | day2 |
|--------|-------|-----------|------|------|
| OBI < −0.3 | 2,869 | **−0.348** | **−0.383** | **−0.363** |
| neutral | 4,144 | ~0 | ~0 | ~0 |
| OBI > +0.3 | 2,890 | **+0.414** | **+0.395** | **+0.403** |

Outer bins fire ~6,000 ticks/day with ±0.4 tick drift each direction → **~2,400 mid-tick-points/day** of available alpha. We capture ~5-10% of this today via stratton MR (MR_K=0.045).

### rev_z and microprice (small but consistent)

Best rev_z: `w=500, |z|>2.0, H=100` → mean +2.54/sig × 3,874 sigs/3d. Per-day: +4.34, +3.47, +0.43 (day 2 weak — drift-day).
Microprice: `|micro − mid| > 0.05, H=20` → +0.42/sig × 17,528 sigs/3d, all 3 days positive.

**Recommendation:** dedicated `_trade_velvet_obi` handler with `OBI_THRESH=0.30, OBI_SKEW_TICKS=0` (asymmetric size only — spread too tight to skew quote position), `OBI_SIZE_MAX≈60-100, OBI_SIZE_K_CONF≈0.7`.

---

## 2. VEV_4000 / VEV_4500 — wide-spread OBI gold mine

| Sym | Spread | mid Δ std | OBI > 0.3 drift (avg) | OBI < −0.3 drift |
|-----|--------|-----------|----------------------|-------------------|
| VEV_4000 | 21 | 1.42 | **+5.49** | **−5.05** |
| VEV_4500 | 16 | 1.25 | **+4.12** | **−3.76** |

OBI bins fire ~80/day per asset. Per-fill drift is ~3x of HYDROGEL because of the wider spread. OBI confidence-sized capture upper bound (3d, mid-tick-points):

| size_max | VEV_4000 | VEV_4500 |
|----------|----------|----------|
| 80 | 118,377 | 75,660 |
| 150 | 222,134 | 142,228 |

At ~5% capture: **VEV_4000 leaves +20-40k mid-tick-points/day untouched** at size 80. Currently uses stratton's tiered (3, 22, 30, 40) — too small for the wide spread.

**Recommendation:** apply porush HYDROGEL handler logic to both: `OBI_THRESH=0.30, OBI_SKEW_TICKS=1, OBI_SIZE_MAX=100-150, OBI_SIZE_K_CONF=0.6-1.0`. Fall through to existing `_trade_vev_mm` when |OBI|<0.30.

---

## 3. Time-of-day (intraday) patterns — flat, skip

OBI Sharpe per quarter (signed × fwd, |OBI|>0.05):

| Sym | q0 | q1 | q2 | q3 |
|-----|------|------|------|------|
| HYDROGEL | 1.95 | 2.10 | 2.17 | 2.14 |
| VELVET | 0.37 | 0.38 | 0.35 | 0.34 |
| VEV_5000 | 0.31 | 0.29 | 0.30 | 0.34 |
| VEV_5300 | 0.73 | 0.63 | 0.66 | 0.68 |

No meaningful intraday gating. Skip.

---

## 4. Spread-condition gating (HYDROGEL) — not actionable

OBI Sharpe by spread bucket: 0-8 = 1.94-2.57, 8-14 = 1.92-2.18 across days. Slight tight-spread edge on day 2 only. Sample thins past spread=14 because spread mode IS 16. **Don't gate.**

---

## 5. Inventory autocorrelation — bot trades alternate

Trade-direction sign autocorr (proxy):

| Sym | day0 lag1 | day1 lag1 | day2 lag1 | lag5 (any day) |
|-----|------|------|------|------|
| HYDROGEL | −0.17 | −0.26 | −0.19 | ~0 |
| VELVET | −0.12 | −0.04 | −0.23 | ~0 |
| VEV_4000 | −0.28 | −0.22 | −0.11 | ~0 |

Strong negative lag-1 = MM/taker ping-pong. **No multi-tick flow persistence.** Confirms current MR-style logic is structurally correct; no momentum signal to mine.

---

## 6. MAF auction (R3)

R2 calibration: uplift +1,474 XIRECs per final eval (winner quote-fraction 1.25 vs loser 0.8). Median bid likely 200-500.

**Recommendation: `MAF_BID = 500`** (33% of expected uplift). If R3 has no MAF, `bid()` is ignored. Don't bid >1,000 — field will under-bid for budget.

---

## 7. Cross-strike vert-spread MR — 3-day historical replay

Implemented Rothschild logic literally: `dev = mkt_spread − BS-smile theo`, EWMA std (warmup 200), enter `|z|>2.0`, exit on z-cross or 30-tick hold. Mid-to-mid execution (caveat: real fills cost ~spread/2 per leg).

| Pair | Size/leg | Trades 3d | Total PnL 3d | Day 0 / 1 / 2 | All + ? |
|------|---------|-----------|--------------|---------------|---------|
| 5300 / 5400 | 40 | 101 | +4,540 | +1,140 / +1,440 / +1,960 | yes |
| 5300 / 5500 | 20 | 176 | +3,470 | +1,080 / +1,130 / +1,260 | yes |
| **5200 / 5400** | **30** | **436** | **+11,265** | **+3,345 / +3,675 / +4,245** | **yes** |
| 5300 / 5400 | 100 | 101 | +11,350 | +2,850 / +3,600 / +4,900 | yes |

**Key finding:** **5200/5400 vert at size 30 is the workhorse** — 4× the entry frequency (436 vs 101) with same total PnL as 5300/5400 at size 100 but lower position-concentration risk.

vs `cross_strike.md` "Sharpe 162, EV 7,575/day": at size 300 those numbers may hold. At size 30-40 conservative defaults: per-day actual = +1,180-3,755. Direction confirmed (all days +); magnitude was over-stated.

**Recommendation:** add 5200/5400 (size 30) to rothschild's `CS_PAIRS`. Combined per-day expected: **+2,000-3,500**. Cannot be MC-validated; portal sub is the only ground truth.

---

## 8. Quote saturation

Market trade volume is microscopic (HYDROGEL 0.14 vol/tick, VELVET 0.28, VEV_5000 0.000, VEV_4500 0.000 — many strikes have zero market trades in the recorded data because the trades CSV omits algo-bot fills). Our quote-induced fills are NOT in this data, so apparent under-fill is misleading. **Not a constraint** — sizing larger is justified where edge per fill is highest (VEV_4000).

---

## 9. Stale-quote / wide-spread signals

Tested whether wide spread (q90) predicts H=3 mid drift:

| Sym | day0 / 1 / 2 wide-spread mean drift H=3 |
|-----|-------------------------------------------|
| HYDROGEL | −0.03 / +0.01 / −0.02 (zero) |
| VELVET | −0.013 / −0.015 / −0.003 (slight neg) |
| VEV_5000 | **−0.082 / −0.088 / −0.026** (neg, all days) |
| VEV_5100 | **−0.060 / −0.025 / −0.055** (neg, all days) |

VEV_5000/5100 show consistent neg drift on wide-spread ticks but magnitude (~0.05 ticks) is below transaction cost. Skip.

---

## 10. Recommendations for v5 trader and v5 param search

### v5 trader changes (concrete)

1. **NEW `_trade_velvet_obi`** (extract VELVET from MR_ASSETS): `OBI_THRESH=0.30, OBI_SKEW_TICKS=0, OBI_SIZE_K_CONF≈0.7, OBI_SIZE_MAX≈60-100, OBI_SIZE_MIN=8, MM_BASE_SIZE≈18`. Keep MR z-score as small inventory-bleed.

2. **NEW `_trade_deep_itm_obi`** for VEV_4000 + VEV_4500: `OBI_THRESH=0.30, OBI_SKEW_TICKS=1, OBI_SIZE_MAX=100-150, OBI_SIZE_K_CONF=0.6-1.0`, fall through to existing `_trade_vev_mm` when |OBI|<0.30.

3. **MAF**: `def bid(self): return 500`.

### v5 param search ranges (10 new params, porush params stay locked)

| Param | Range | Default |
|-------|-------|---------|
| `VEL_OBI_THRESH` | 0.20 — 0.40 | 0.30 |
| `VEL_OBI_SIZE_MAX` | 30 — 120 | 60 |
| `VEL_OBI_SIZE_K_CONF` | 0.3 — 1.5 | 0.7 |
| `VEL_MM_BASE_SIZE` | 8 — 40 | 18 |
| `V4K_OBI_THRESH` | 0.20 — 0.40 | 0.30 |
| `V4K_OBI_SIZE_MAX` | 60 — 200 | 120 |
| `V4K_OBI_SIZE_K_CONF` | 0.3 — 1.5 | 0.8 |
| `V45_OBI_SIZE_MAX` | 50 — 150 | 90 |
| `MAF_BID` | 0 — 1500 | 500 |
| `CS_5200_5400_SIZE` (rothschild only) | 0 — 60 | 30 |

Objective: same as search-4 (`Sharpe + 0.0001 mean + 0.0002 p05`).

### Explicit DO-NOT-add

- HYDROGEL spread gating (sec 4) — sample thin, edge tiny
- Intraday quarter gating (sec 3) — flat across day
- Stale-quote VEV_5000 short bias (sec 9) — drift below cost
- Flow-momentum L>1 (sec 5) — autocorr dies at lag 5
- Static fly tilt overlay — already disabled; keep disabled

### Final v5 deployment plan

1. Build v5 = porush + velvet-OBI + deep-ITM-OBI + MAF=500. Verify MC mean ≥ +12k vs porush +11.7k.
2. Run v5 param search (300-400 trials, 10 new params).
3. Build rothschild v2 with 5200/5400 added (size 30); ship to portal in parallel for cross-strike validation.
4. Final submission: ship whichever wins on portal; worst case = porush already-validated baseline.

---

## Caveats (honest)

- All "implied PnL" / "mid-tick-points" upper bounds assume full-drift capture. Realistic ~5-30%.
- Cross-strike replay uses mid-to-mid execution. Real fills cost ~spread/2 per leg → numbers possibly 30-50% optimistic.
- VEV_4500 has zero recorded trades in trades CSV. OBI signal exists in book, but realized fill rate unknown without portal.
- VELVET signal is strongest on day 0 (rev_z +4.34) and weak on day 2 (+0.43). OBI tier (chosen handler) is more robust per-day than rev_z.
- N=3 days is small. Per-day stability is the only insurance.
