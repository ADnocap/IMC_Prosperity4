"""Round 5 — deeper-dive analysis on the 8 'no structure' categories.

FINDINGS_v2.md said only Pebbles + Snackpacks have hidden structure, based on:
  - 5-asset PCA per category (eigvals flat -> independent)
  - Pearson |r| >= 0.7 across all 50 (only intra-snackpack pairs survived)

That analysis can miss:
  1. Sub-basket (pair/triplet) constraints inside a category where the other 2-3 assets are independent
  2. Lagged cross-correlations (A leads B at lag k)
  3. Cointegration: random walks with a stationary linear combo
  4. Order-book imbalance signals (mid-only blind)
  5. Cross-category common factors at threshold < 0.7
  6. Pulse-conditional drift

This script runs all six and reports any anomaly worth chasing.
"""
from __future__ import annotations

import itertools
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from numpy.linalg import lstsq

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"

CATEGORIES = {
    "galaxy_sounds": ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                      "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                      "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "sleep_pods": ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                   "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "microchips": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                   "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "robots": ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
               "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "uv_visors": ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                  "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "translators": ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                    "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                    "TRANSLATOR_VOID_BLUE"],
    "panels": ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "oxygen_shakes": ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                      "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE",
                      "OXYGEN_SHAKE_GARLIC"],
}
ALL_PRODUCTS = [p for ps in CATEGORIES.values() for p in ps]
N = len(ALL_PRODUCTS)


def load_prices() -> pd.DataFrame:
    """Wide df: rows = global tick, cols = product mid_price."""
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        frames.append(df.pivot(index="tick", columns="product", values="mid_price"))
    return pd.concat(frames).sort_index()


def load_book() -> pd.DataFrame:
    """Long df with bid_vol_1, ask_vol_1, mid_price for OBI signal."""
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA / f"prices_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        df["day"] = d
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_trades() -> pd.DataFrame:
    frames = []
    for d in (2, 3, 4):
        df = pd.read_csv(DATA / f"trades_round_5_day_{d}.csv", sep=";")
        df["tick"] = (d - 2) * 10_000 + df["timestamp"] // 100
        df["day"] = d
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 1. Sub-basket scan: all pairs + all triplets within each category
# ---------------------------------------------------------------------------
def scan_subbaskets(prices: pd.DataFrame):
    print("=" * 78)
    print("1. SUB-BASKET SCAN — pairs & triplets inside each non-structured category")
    print("=" * 78)
    print("Best per category, ranked by std(combo) / median(|combo|).")
    print("A 'real' constraint shows std/median < 0.005 (Pebbles-like) or stationary residual.\n")

    findings = []
    for cat, syms in CATEGORIES.items():
        if cat in ("pebbles", "snackpacks"):
            continue
        cat_results = []

        # Pairs: A + B, A - B
        for a, b in itertools.combinations(syms, 2):
            for sign, name in [(+1, "+"), (-1, "-")]:
                combo = prices[a] + sign * prices[b]
                m, s = combo.mean(), combo.std()
                cat_results.append({
                    "kind": "pair",
                    "expr": f"{a} {name} {b}",
                    "mean": m,
                    "std": s,
                    "rel_std": s / max(abs(m), 1e-6),
                })

        # Triplets: A + B + C, A + B - C, A - B + C, etc. — all sign patterns
        for a, b, c in itertools.combinations(syms, 3):
            for s_b in (+1, -1):
                for s_c in (+1, -1):
                    combo = prices[a] + s_b * prices[b] + s_c * prices[c]
                    m, s = combo.mean(), combo.std()
                    expr = f"{a} {'+' if s_b > 0 else '-'} {b} {'+' if s_c > 0 else '-'} {c}"
                    cat_results.append({
                        "kind": "triplet",
                        "expr": expr,
                        "mean": m,
                        "std": s,
                        "rel_std": s / max(abs(m), 1e-6),
                    })

        # Best fit by smallest std (after stripping the obvious A+B+C+D+E sum which
        # we can't claim is a constraint without the eigval gap).
        cat_results.sort(key=lambda r: r["std"])
        print(f"--- {cat} (top 5 by smallest std) ---")
        for r in cat_results[:5]:
            print(f"  std={r['std']:8.2f}  rel_std={r['rel_std']:.5f}  mean={r['mean']:10.2f}  {r['expr']}")
            if r["std"] < 50:  # potentially interesting
                findings.append((cat, r))
        print()

    return findings


# ---------------------------------------------------------------------------
# 2. Optimal-weight basket: solve for weights w that minimize std(A + w*B)
# ---------------------------------------------------------------------------
def optimal_basket_search(prices: pd.DataFrame):
    print("=" * 78)
    print("2. OPTIMAL-WEIGHT 2-ASSET BASKET — find best hedge ratio per pair")
    print("=" * 78)
    print("For each within-category pair, find w minimizing std(A - w*B).")
    print("If the residual std is much smaller than std(A), it's a tight relationship.\n")

    findings = []
    for cat, syms in CATEGORIES.items():
        if cat in ("pebbles", "snackpacks"):
            continue
        cat_rows = []
        for a, b in itertools.combinations(syms, 2):
            x = prices[b].values
            y = prices[a].values
            # OLS: y = w*x + c
            A = np.vstack([x, np.ones_like(x)]).T
            (w, c), *_ = lstsq(A, y, rcond=None)
            resid = y - (w * x + c)
            std_a = prices[a].std()
            shrink = resid.std() / std_a
            cat_rows.append({
                "a": a, "b": b, "w": w, "c": c,
                "resid_std": resid.std(),
                "std_a": std_a,
                "shrink": shrink,
            })
        cat_rows.sort(key=lambda r: r["shrink"])
        print(f"--- {cat} (top 3 tightest pairs by std-shrinkage) ---")
        for r in cat_rows[:3]:
            print(f"  {r['a']} = {r['w']:7.4f} * {r['b']} + {r['c']:8.2f}  "
                  f"resid_std={r['resid_std']:7.2f}  shrink={r['shrink']:.3f}")
            if r["shrink"] < 0.5:
                findings.append((cat, r))
        print()
    return findings


# ---------------------------------------------------------------------------
# 3. Lagged cross-correlations within categories
# ---------------------------------------------------------------------------
def lagged_cross_corr(prices: pd.DataFrame):
    print("=" * 78)
    print("3. LAGGED CROSS-CORRELATIONS (A leads B at lag k?)")
    print("=" * 78)
    print("For each within-cat pair, corr(diff_A[t-k], diff_B[t]) at k in [1,5,10,50].")
    print("Strong (|r|>0.05) lagged corr is a tradeable lead-lag signal.\n")

    findings = []
    diffs = prices.diff().dropna()

    for cat, syms in CATEGORIES.items():
        if cat in ("pebbles", "snackpacks"):
            continue
        best_per_cat = []
        for a, b in itertools.combinations(syms, 2):
            for lag in (1, 5, 10, 50):
                # A leads B at +lag
                r_lead = diffs[a].shift(lag).corr(diffs[b])
                # B leads A at +lag
                r_lag = diffs[b].shift(lag).corr(diffs[a])
                for direction, r in (("A->B", r_lead), ("B->A", r_lag)):
                    if abs(r) > 0.04:
                        best_per_cat.append({
                            "pair": f"{a} {direction} {b}",
                            "lag": lag, "r": r,
                        })
        best_per_cat.sort(key=lambda x: -abs(x["r"]))
        if best_per_cat:
            print(f"--- {cat} (signals with |r|>0.04) ---")
            for x in best_per_cat[:5]:
                print(f"  lag={x['lag']:3d}  r={x['r']:+.4f}  {x['pair']}")
                findings.append((cat, x))
        else:
            print(f"--- {cat}: no |r|>0.04 lagged signal ---")
        print()
    return findings


# ---------------------------------------------------------------------------
# 4. Engle-Granger cointegration
# ---------------------------------------------------------------------------
def engle_granger_test(prices: pd.DataFrame):
    print("=" * 78)
    print("4. ENGLE-GRANGER COINTEGRATION (within-category pairs)")
    print("=" * 78)
    print("Levels regression A ~ B + c, ADF-test the residual. If p < 0.05, A & B are")
    print("cointegrated even though both are I(1) — strong basis for pair-trading.\n")

    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        print("  [statsmodels not installed — skipping]\n")
        return []

    findings = []
    for cat, syms in CATEGORIES.items():
        if cat in ("pebbles", "snackpacks"):
            continue
        cat_results = []
        for a, b in itertools.combinations(syms, 2):
            x = prices[b].values
            y = prices[a].values
            A = np.vstack([x, np.ones_like(x)]).T
            (w, c), *_ = lstsq(A, y, rcond=None)
            resid = y - (w * x + c)
            try:
                adf_stat, pval, *_ = adfuller(resid, regression="c", autolag="AIC")
            except Exception as e:
                print(f"    adfuller failed for {a},{b}: {e}")
                continue
            cat_results.append({
                "a": a, "b": b, "w": w, "p": pval, "adf": adf_stat,
                "resid_std": resid.std(),
            })
        if not cat_results:
            print(f"--- {cat}: no usable pairs ---")
            print()
            continue
        cat_results.sort(key=lambda r: r["p"])
        sig = [r for r in cat_results if r["p"] < 0.05]
        if sig:
            print(f"--- {cat} (cointegrated pairs, p<0.05) ---")
            for r in sig[:3]:
                print(f"  p={r['p']:.4f}  adf={r['adf']:.2f}  "
                      f"{r['a']} = {r['w']:.3f}*{r['b']} + c  resid_std={r['resid_std']:.2f}")
                findings.append((cat, r))
        else:
            print(f"--- {cat}: no cointegrated pair (best p={cat_results[0]['p']:.3f}) ---")
        print()
    return findings


# ---------------------------------------------------------------------------
# 5. Order-book imbalance signal
# ---------------------------------------------------------------------------
def obi_signal(book: pd.DataFrame):
    print("=" * 78)
    print("5. ORDER-BOOK IMBALANCE -> FUTURE RETURN")
    print("=" * 78)
    print("OBI = (bid_vol_1 - ask_vol_1) / (bid_vol_1 + ask_vol_1)")
    print("If OBI predicts future mid-return at +1/+5/+50 ticks, it's a free signal.\n")

    rows = []
    for prod in ALL_PRODUCTS:
        sub = book[book["product"] == prod].sort_values(["day", "timestamp"])
        if sub.empty:
            continue
        for d in sub["day"].unique():
            day_sub = sub[sub["day"] == d].copy()
            bv1 = day_sub["bid_volume_1"].fillna(0).astype(float)
            av1 = day_sub["ask_volume_1"].fillna(0).astype(float)
            tot = bv1 + av1
            obi = (bv1 - av1) / tot.replace(0, np.nan)
            mid = day_sub["mid_price"].astype(float)
            results = {}
            for h in (1, 5, 50):
                fwd_ret = mid.shift(-h) - mid
                r = obi.corr(fwd_ret)
                results[f"r_{h}"] = r
            rows.append({"product": prod, "day": d, **results})

    df = pd.DataFrame(rows)
    if df.empty:
        print("  [no book rows]\n")
        return []
    # Aggregate per product (mean across days)
    agg = df.groupby("product").agg({"r_1": "mean", "r_5": "mean", "r_50": "mean"}).reset_index()
    agg["max_abs"] = agg[["r_1", "r_5", "r_50"]].abs().max(axis=1)
    agg = agg.sort_values("max_abs", ascending=False)
    print("Top 15 products by max |OBI->future_return correlation|:")
    print(f"{'product':<35} {'r_1':>7} {'r_5':>7} {'r_50':>7} {'max':>7}")
    findings = []
    for _, row in agg.head(15).iterrows():
        print(f"{row['product']:<35} {row['r_1']:+.4f} {row['r_5']:+.4f} "
              f"{row['r_50']:+.4f} {row['max_abs']:.4f}")
        if row["max_abs"] > 0.05:
            findings.append(row.to_dict())
    print()
    return findings


# ---------------------------------------------------------------------------
# 6. Cross-category factor (PC4-PC10 stability)
# ---------------------------------------------------------------------------
def cross_cat_factors(prices: pd.DataFrame):
    print("=" * 78)
    print("6. CROSS-CATEGORY PC STABILITY (PC4-PC10)")
    print("=" * 78)
    print("FACTOR_MODEL.md confirmed PC1-3 (snackpack & pebble structure).")
    print("Re-checking PC4-PC10 with finer cosine threshold (0.7 instead of 0.85).\n")

    diffs = prices.diff().dropna()
    # Z-score (CORR-PCA mode)
    diffs_z = (diffs - diffs.mean()) / diffs.std()
    diffs_z = diffs_z.dropna()

    full_cov = diffs_z.cov().values
    eigvals_full, eigvecs_full = np.linalg.eigh(full_cov)
    # Sort descending
    idx = np.argsort(-eigvals_full)
    eigvals_full = eigvals_full[idx]
    eigvecs_full = eigvecs_full[:, idx]
    total_var = eigvals_full.sum()

    # Day-by-day PCA
    day_eigvecs = []
    for d in (0, 1, 2):  # day 2/3/4 = ticks 0-10K / 10-20K / 20-30K
        sub = diffs_z.iloc[d * 10_000:(d + 1) * 10_000].dropna()
        if len(sub) < 1000:
            continue
        c = sub.cov().values
        ev, vec = np.linalg.eigh(c)
        idx_d = np.argsort(-ev)
        day_eigvecs.append(vec[:, idx_d])

    print(f"{'PC':>3} {'var%':>6} {'day2_cos':>8} {'day3_cos':>8} {'day4_cos':>8} {'verdict':<10}")
    for k in range(min(12, len(eigvals_full))):
        var_pct = eigvals_full[k] / total_var * 100
        cosines = []
        for vec in day_eigvecs:
            c = abs(np.dot(eigvecs_full[:, k], vec[:, k]))
            cosines.append(c)
        verdict = "STABLE" if all(c > 0.7 for c in cosines) else "unstable"
        cs = "  ".join(f"{c:.3f}" for c in cosines)
        print(f"PC{k+1:>2} {var_pct:5.2f}% {cs}  {verdict}")

    # For stable PCs beyond PC4, look at top loadings cross-category
    print("\nLoadings of PC5-PC8 (top 8 by |loading|):")
    for k in range(4, 8):
        if k >= len(eigvals_full):
            break
        loadings = pd.Series(eigvecs_full[:, k], index=diffs_z.columns)
        top = loadings.reindex(loadings.abs().sort_values(ascending=False).index).head(8)
        print(f"\n  PC{k+1} ({eigvals_full[k]/total_var*100:.2f}% var):")
        for sym, val in top.items():
            print(f"    {sym:<35} {val:+.4f}")
    print()
    return []


# ---------------------------------------------------------------------------
# 7. Pulse-conditional drift
# ---------------------------------------------------------------------------
def pulse_conditional_drift(prices: pd.DataFrame, trades: pd.DataFrame):
    print("=" * 78)
    print("7. PULSE-CONDITIONAL DRIFT")
    print("=" * 78)
    print("V-pulse fires 40 products together (not snackpacks/pebbles/microchips).")
    print("Test: when a V-pulse fires direction X, does next-100-tick mean return")
    print("of any non-pulsed category respond?\n")

    # Build pulse log: per tick, count of trades and net direction
    # In R5, trades[buyer]/trades[seller] are empty — we infer direction from price
    # vs the previous mid (sell trade at bid_price_1, buy at ask_price_1)
    # But for this we just want bulk-trade ticks
    n_trades_per_tick = trades.groupby("tick").size()

    # Find ticks with >= 5 simultaneous trades (likely a pulse fired)
    pulse_ticks = n_trades_per_tick[n_trades_per_tick >= 5].index.tolist()
    print(f"  Found {len(pulse_ticks)} ticks with >=5 simultaneous trades (likely pulses)")

    # For each pulse tick, compute net side (buys - sells) per V-group product
    # In R5, sell trades match against bid_price_1 — we can detect by comparing
    # trade price vs prior mid. Use a heuristic: trade price > prior mid -> buy.
    # Skip for now since we don't have clean direction labels from R5 trades file.
    # Instead, simpler test: split ticks by total trade volume, look at next-100 mean

    # Simple test: tick volume -> next-100 cumulative return per product
    H = 100
    print(f"\nFor each product, corr(tick_volume, next {H}-tick mid-return):")
    rows = []
    for prod in ALL_PRODUCTS:
        mid = prices[prod].dropna()
        fwd_ret = mid.shift(-H) - mid
        # Volume per tick (this product)
        vol_per_tick = trades[trades["symbol"] == prod].groupby("tick")["quantity"].sum()
        vol_aligned = vol_per_tick.reindex(mid.index, fill_value=0)
        if vol_aligned.std() > 0:
            r = vol_aligned.corr(fwd_ret)
            rows.append({"product": prod, "corr": r})
    df = pd.DataFrame(rows).sort_values("corr", key=lambda s: s.abs(), ascending=False)
    print(f"{'product':<35} {'corr_vol_to_fwdret':>12}")
    findings = []
    for _, row in df.head(15).iterrows():
        print(f"{row['product']:<35} {row['corr']:+.4f}")
        if abs(row["corr"]) > 0.05:
            findings.append(row.to_dict())
    print()
    return findings


# ---------------------------------------------------------------------------
def distributional_anomalies(prices: pd.DataFrame, book: pd.DataFrame):
    """Look for exploitable distribution shapes — heavy tails, bimodality,
    snap-to-grid quanta, calendar effects."""
    print("=" * 78)
    print("8. DISTRIBUTIONAL ANOMALIES")
    print("=" * 78)
    print("  (a) Tick-diff kurtosis & skew vs Gaussian (extreme = jumpy = MR-friendly)")
    print("  (b) Bimodality on mid level (Hartigan-style dip approximation)")
    print("  (c) Mid-fractional quantum (does mid prefer integers, halves?)")
    print("  (d) Calendar/intraday seasonality (tick-of-day mean return)\n")

    diffs = prices.diff().dropna()

    # (a) Per-product diff distribution stats
    print("--- (a) Tick-diff kurtosis (>3 = heavier tails than Gaussian) ---")
    rows = []
    for p in ALL_PRODUCTS:
        d = diffs[p].dropna().values
        if len(d) < 100:
            continue
        kurt = stats.kurtosis(d, fisher=False)  # Gaussian = 3
        skew = stats.skew(d)
        rows.append({"product": p, "kurtosis": kurt, "skew": skew, "std": d.std()})
    df = pd.DataFrame(rows).sort_values("kurtosis", ascending=False)
    print("Top 10 by kurtosis (jumpy = bigger MR opportunities):")
    for _, r in df.head(10).iterrows():
        flag = "  <-- HEAVY TAIL" if r["kurtosis"] > 6 else ""
        print(f"  {r['product']:<35} kurt={r['kurtosis']:6.1f} skew={r['skew']:+.3f}{flag}")
    print()

    # (b) Bimodality test: ratio of stdev to MAD-based estimate.
    # For unimodal Gaussian, std/IQR ~ 1/1.349 = 0.741
    # Bimodal distributions have std/IQR > 0.741 (variance inflated by mode separation)
    print("--- (b) Bimodality screen (std/IQR > 0.95 = candidate bimodal) ---")
    rows = []
    for p in ALL_PRODUCTS:
        m = prices[p].dropna()
        iqr = m.quantile(0.75) - m.quantile(0.25)
        if iqr > 0:
            ratio = m.std() / iqr
            rows.append({"product": p, "std_iqr": ratio,
                         "range": m.max() - m.min(), "iqr": iqr})
    df = pd.DataFrame(rows).sort_values("std_iqr", ascending=False)
    print("Top 10 by std/IQR ratio:")
    for _, r in df.head(10).iterrows():
        flag = "  <-- BIMODAL?" if r["std_iqr"] > 0.95 else ""
        print(f"  {r['product']:<35} std/IQR={r['std_iqr']:.3f} range={r['range']:.0f}{flag}")
    print()

    # (c) Mid quantum
    print("--- (c) Mid-fractional quantum ({0.0, 0.5} expected per FINDINGS_v2) ---")
    print("Products where >5% of mids land on a fraction OUTSIDE {0.0, 0.5}:")
    flagged = []
    for p in ALL_PRODUCTS:
        m = prices[p].dropna()
        frac = (m * 2) % 1  # 0 if mid is integer or half-integer
        bad = (frac > 0.001) & (frac < 0.999)
        if bad.mean() > 0.05:
            flagged.append((p, bad.mean()))
    if flagged:
        for p, pct in flagged:
            print(f"  {p:<35}  {pct*100:.1f}% off-grid")
    else:
        print("  (none — confirms FINDINGS_v2 half-integer quantum)")
    print()

    # (d) Calendar / intraday seasonality: tick-of-day mean return
    print("--- (d) Intraday seasonality: mean return by 1000-tick bucket ---")
    print("Looking for monotone drift or sharp open/close patterns.\n")
    rows = []
    for p in ALL_PRODUCTS:
        d = diffs[p].dropna().reset_index(drop=False)
        d.columns = ["tick", "ret"]
        d["bucket"] = (d["tick"] % 10000) // 1000  # 0..9 within each day
        means = d.groupby("bucket")["ret"].mean()
        # Variation across buckets indicates seasonality
        coef_var = means.std() / max(d["ret"].std(), 1e-9) * np.sqrt(1000)
        rows.append({"product": p, "bucket_var": coef_var,
                     "max_bucket_mean": means.abs().max()})
    df = pd.DataFrame(rows).sort_values("bucket_var", ascending=False)
    print("Top 10 by tick-of-day variation (>2.0 = significant seasonality):")
    for _, r in df.head(10).iterrows():
        flag = "  <-- SEASONAL" if r["bucket_var"] > 2.0 else ""
        print(f"  {r['product']:<35} bucket_var={r['bucket_var']:.2f} "
              f"max_mean={r['max_bucket_mean']:+.3f}{flag}")
    print()

    return df


def basket_residual_distributions(prices: pd.DataFrame):
    """For pairs found in the optimal-weight search (top shrinkage), check the
    residual distribution. Heavy-tailed or bimodal residuals are MORE exploitable
    than Gaussian ones — extremes are larger and more frequent."""
    print("=" * 78)
    print("9. BASKET-RESIDUAL DISTRIBUTIONS — exploit non-Gaussian residuals")
    print("=" * 78)
    print("For top-shrinkage pairs, fit residuals and check kurtosis / autocorr.")
    print("Heavy-tailed + autocorr-positive residuals = best MR setup.\n")

    candidates = [
        ("sleep_pods", "SLEEP_POD_POLYESTER", "SLEEP_POD_COTTON"),
        ("sleep_pods", "SLEEP_POD_SUEDE", "SLEEP_POD_POLYESTER"),
        ("microchips", "MICROCHIP_SQUARE", "MICROCHIP_RECTANGLE"),
        ("microchips", "MICROCHIP_OVAL", "MICROCHIP_TRIANGLE"),
        ("uv_visors", "UV_VISOR_AMBER", "UV_VISOR_MAGENTA"),
        ("uv_visors", "UV_VISOR_AMBER", "UV_VISOR_ORANGE"),
        ("translators", "TRANSLATOR_ASTRO_BLACK", "TRANSLATOR_VOID_BLUE"),
        ("translators", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_VOID_BLUE"),
        ("robots", "ROBOT_VACUUMING", "ROBOT_LAUNDRY"),
        ("robots", "ROBOT_VACUUMING", "ROBOT_MOPPING"),
    ]
    print(f"{'cat':<14} {'pair':<55} {'w':>7} {'std':>7} {'kurt':>6} {'rho1':>6} {'half_life':>9}")
    findings = []
    for cat, a, b in candidates:
        if a not in prices.columns or b not in prices.columns:
            continue
        x = prices[b].values
        y = prices[a].values
        A = np.vstack([x, np.ones_like(x)]).T
        (w, c), *_ = lstsq(A, y, rcond=None)
        resid = y - (w * x + c)
        # AR(1) on residual
        rho1 = pd.Series(resid).autocorr(lag=1)
        # Half-life from AR(1): -ln(2) / ln(|rho1|) if 0 < rho1 < 1
        if 0 < rho1 < 1:
            half_life = -np.log(2) / np.log(rho1)
        else:
            half_life = float("inf")
        kurt = stats.kurtosis(resid, fisher=False)
        line = (f"{cat:<14} {a}-w*{b:<32} {w:>+7.3f} {resid.std():>7.1f} "
                f"{kurt:>6.1f} {rho1:>+.3f} {half_life:>9.0f}")
        print(line)
        # Flag tradeable: half-life within a few hundred ticks AND kurt > 4
        if half_life < 2000 and kurt > 4:
            findings.append((cat, a, b, w, half_life, kurt))
    print()
    if findings:
        print("FLAGGED PAIRS (half_life<2000 AND kurt>4):")
        for f in findings:
            print(f"  {f[0]} | {f[1]} - {f[3]:.3f}*{f[2]} | half_life={f[4]:.0f} | kurt={f[5]:.1f}")
    print()
    return findings


def main():
    print("Loading R5 historical data...")
    prices = load_prices()
    book = load_book()
    trades = load_trades()
    print(f"  prices: {prices.shape}  book: {book.shape}  trades: {trades.shape}\n")

    f1 = scan_subbaskets(prices)
    f2 = optimal_basket_search(prices)
    f3 = lagged_cross_corr(prices)
    f4 = engle_granger_test(prices)
    f5 = obi_signal(book)
    f6 = cross_cat_factors(prices)
    f7 = pulse_conditional_drift(prices, trades)
    f8 = distributional_anomalies(prices, book)
    f9 = basket_residual_distributions(prices)

    print("=" * 78)
    print("SUMMARY OF ANOMALIES WORTH INVESTIGATING")
    print("=" * 78)
    print(f"  Sub-basket constraints (std<50):       {len(f1)}")
    print(f"  Optimal-weight pairs (shrink<0.5):     {len(f2)}")
    print(f"  Lagged xcorr signals (|r|>0.04):       {len(f3)}")
    print(f"  Cointegrated pairs (p<0.05):           {len(f4)}")
    print(f"  OBI -> future-return (|r|>0.05):       {len(f5)}")
    print(f"  Pulse/volume -> drift (|r|>0.05):      {len(f7)}")
    print(f"  Heavy-tailed + MR pair-residuals:      {len(f9)}")


if __name__ == "__main__":
    main()
