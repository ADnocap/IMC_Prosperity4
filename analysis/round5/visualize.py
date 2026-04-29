"""Round 5 data visualization. Produces a deck of PNGs under tmp/round5_viz/.

Graphs:
  01_mids_by_category.png          mid-price time series, 10-panel grid
  02_pebble_basket_sum.png         sum of 5 pebble mids, time + dist
  03_snackpack_pair.png            CHOC + VANILLA over time, per day
  04_snackpack_triplet.png         PIS/STRAW/RASP eigvec residual
  05_spread_vs_sigma.png           per-product MM Sharpe scatter
  06_drift_products.png            3 drifters (UV_AMBER, MICROCHIP_OVAL, PEBBLES_XS)
  07_robot_dishes_mr.png           ROBOT_DISHES mean-reversion check
  08_trade_volume.png              trade count + dollar volume per product
  09_correlation_heatmap.png       50x50 return correlations
  10_spread_distribution.png       spread distribution by category
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"
OUT = REPO / "tmp" / "round5_viz"
OUT.mkdir(parents=True, exist_ok=True)

DAYS = [2, 3, 4]
TICKS_PER_DAY = 10_000
TICK_STEP = 100  # timestamps increment by 100

CATEGORIES: dict[str, list[str]] = {
    "Galaxy Sounds": [
        "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "Sleep Pods": [
        "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
    ],
    "Microchips": [
        "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
    ],
    "Pebbles": [
        "PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL",
    ],
    "Robots": [
        "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
        "ROBOT_LAUNDRY", "ROBOT_IRONING",
    ],
    "UV-Visors": [
        "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
        "UV_VISOR_RED", "UV_VISOR_MAGENTA",
    ],
    "Translators": [
        "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "Panels": [
        "PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4",
    ],
    "Oxygen Shakes": [
        "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
    ],
    "Snackpacks": [
        "SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY",
    ],
}

mpl.rcParams.update({
    "figure.dpi": 110,
    "savefig.dpi": 130,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.titlesize": 13,
})


def load_prices() -> pd.DataFrame:
    parts = []
    for d in DAYS:
        df = pd.read_parquet(DATA / f"prices_round_5_day_{d}.parquet")
        parts.append(df)
    px = pd.concat(parts, ignore_index=True)
    px["abs_t"] = (px["day"] - DAYS[0]) * TICKS_PER_DAY * TICK_STEP + px["timestamp"]
    return px


def load_trades() -> pd.DataFrame:
    parts = []
    for d in DAYS:
        df = pd.read_parquet(DATA / f"trades_round_5_day_{d}.parquet")
        df["day"] = d
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def pivot_mid(px: pd.DataFrame) -> pd.DataFrame:
    """rows = abs_t, cols = product, values = mid_price."""
    return px.pivot_table(index="abs_t", columns="product", values="mid_price", aggfunc="mean").sort_index()


def add_day_dividers(ax, total_ticks_per_day=TICKS_PER_DAY * TICK_STEP):
    for k in range(1, len(DAYS)):
        ax.axvline(k * total_ticks_per_day, color="grey", lw=0.5, ls=":", alpha=0.7)


def fig_01_mids_by_category(mid_w: pd.DataFrame):
    fig, axes = plt.subplots(5, 2, figsize=(15, 16), sharex=False)
    axes = axes.ravel()
    for i, (cat, prods) in enumerate(CATEGORIES.items()):
        ax = axes[i]
        for p in prods:
            if p in mid_w.columns:
                ax.plot(mid_w.index.values, mid_w[p].values, lw=0.6, label=p.split("_", 1)[-1])
        ax.set_title(f"{cat} — mid prices")
        ax.set_xlabel("absolute tick (days 2/3/4)")
        ax.set_ylabel("mid")
        ax.grid(True, alpha=0.25)
        add_day_dividers(ax)
        ax.legend(fontsize=7, loc="best", ncol=1)
    fig.suptitle("Round 5 — mid prices by category, days 2/3/4")
    fig.tight_layout()
    fig.savefig(OUT / "01_mids_by_category.png")
    plt.close(fig)


def fig_02_pebble_basket(mid_w: pd.DataFrame):
    pebs = CATEGORIES["Pebbles"]
    s = mid_w[pebs].sum(axis=1)
    dev = s - 50_000.0
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.5), gridspec_kw={"width_ratios": [3, 1]})
    ax = axes[0]
    ax.plot(s.index.values, s.values, lw=0.5, color="tab:blue")
    ax.axhline(50_000, color="black", lw=0.7, ls="--", label="50,000 target")
    ax.set_title(f"Pebble basket sum (XS+S+M+L+XL).  std={dev.std():.2f}, range [{dev.min():+.1f}, {dev.max():+.1f}]")
    ax.set_xlabel("absolute tick")
    ax.set_ylabel("sum of 5 mids")
    add_day_dividers(ax)
    ax.legend()
    ax.grid(True, alpha=0.25)
    ax = axes[1]
    ax.hist(dev.values, bins=80, color="tab:blue", edgecolor="black", lw=0.3)
    ax.set_title("Deviation from 50,000")
    ax.set_xlabel("dev")
    ax.set_ylabel("ticks (count)")
    ax.set_yscale("log")
    ax.grid(True, alpha=0.25)
    fig.suptitle("Round 5 — Pebble constant-sum basket constraint")
    fig.tight_layout()
    fig.savefig(OUT / "02_pebble_basket_sum.png")
    plt.close(fig)


def fig_03_snackpack_pair(px: pd.DataFrame):
    df = px[px["product"].isin(["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA"])]
    pv = df.pivot_table(index=["day", "timestamp"], columns="product", values="mid_price").reset_index()
    pv["sum"] = pv["SNACKPACK_CHOCOLATE"] + pv["SNACKPACK_VANILLA"]
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=False)
    ax = axes[0]
    for d, g in pv.groupby("day"):
        ax.plot(g["timestamp"].values, g["SNACKPACK_CHOCOLATE"].values, lw=0.6, alpha=0.7, label=f"CHOC d{d}")
        ax.plot(g["timestamp"].values, g["SNACKPACK_VANILLA"].values, lw=0.6, alpha=0.7, ls="--", label=f"VAN d{d}")
    ax.set_title("Individual mids overlay (per-day timestamp)")
    ax.set_xlabel("timestamp within day")
    ax.set_ylabel("mid")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=3, fontsize=7)
    ax = axes[1]
    daily_means = []
    for d, g in pv.groupby("day"):
        ax.plot(g["timestamp"].values, g["sum"].values, lw=0.6, label=f"day {d}, mean={g['sum'].mean():.2f}, std={g['sum'].std():.2f}")
        daily_means.append((d, g["sum"].mean()))
    ax.set_title("CHOC + VANILLA pair sum per day  (K_day drifts ~75 across days)")
    ax.set_xlabel("timestamp within day")
    ax.set_ylabel("sum")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    fig.suptitle("Round 5 — Snackpack CHOC↔VANILLA pair constraint")
    fig.tight_layout()
    fig.savefig(OUT / "03_snackpack_pair.png")
    plt.close(fig)


def fig_04_snackpack_triplet(mid_w: pd.DataFrame):
    """STRAW + RASP - 2*PIS combo (from FINDINGS) and the free PCA residual."""
    pis = mid_w["SNACKPACK_PISTACHIO"]
    straw = mid_w["SNACKPACK_STRAWBERRY"]
    rasp = mid_w["SNACKPACK_RASPBERRY"]
    # FINDINGS: smallest eigvec [+0.642, +0.292, +0.709] (PIS/STRAW/RASP)
    eig = np.array([0.642, 0.292, 0.709])
    combo = 0.642 * pis + 0.292 * straw + 0.709 * rasp
    integer_combo = straw + rasp - 2 * pis
    fig, axes = plt.subplots(2, 1, figsize=(14, 7))
    ax = axes[0]
    ax.plot(combo.index.values, combo.values, lw=0.5)
    ax.set_title(f"PCA min-eigvec residual: 0.642·PIS + 0.292·STRAW + 0.709·RASP   (std={combo.std():.1f})")
    ax.set_xlabel("absolute tick")
    add_day_dividers(ax)
    ax.grid(True, alpha=0.25)
    ax = axes[1]
    ax.plot(integer_combo.index.values, integer_combo.values, lw=0.5, color="tab:orange")
    ax.set_title(f"Integer combo: STRAW + RASP − 2·PIS   (mean={integer_combo.mean():.0f}, std={integer_combo.std():.0f})")
    ax.set_xlabel("absolute tick")
    add_day_dividers(ax)
    ax.grid(True, alpha=0.25)
    fig.suptitle("Round 5 — Snackpack triplet (PIS/STRAW/RASP) — looser than the pair")
    fig.tight_layout()
    fig.savefig(OUT / "04_snackpack_triplet.png")
    plt.close(fig)


def fig_05_spread_vs_sigma(px: pd.DataFrame):
    """Scatter spread_median vs sigma_per_tick, color by category, size by spread_over_sigma."""
    rows = []
    for prod, g in px.groupby("product"):
        spread = (g["ask_price_1"] - g["bid_price_1"]).astype(float).median()
        # within-day diffs only (avoid day boundary jumps)
        sig = g.sort_values(["day", "timestamp"]).groupby("day")["mid_price"].diff().std()
        rows.append({"product": prod, "spread_med": spread, "sigma_per_tick": sig})
    s = pd.DataFrame(rows)
    s["sharpe"] = s["spread_med"] / s["sigma_per_tick"]
    prod_to_cat = {p: c for c, prods in CATEGORIES.items() for p in prods}
    s["category"] = s["product"].map(prod_to_cat)
    cmap = plt.get_cmap("tab10")
    cat_color = {c: cmap(i % 10) for i, c in enumerate(CATEGORIES)}
    fig, ax = plt.subplots(figsize=(12, 8))
    for cat, sub in s.groupby("category"):
        ax.scatter(sub["sigma_per_tick"], sub["spread_med"], s=80, label=cat, color=cat_color[cat], alpha=0.85, edgecolor="black", lw=0.4)
    # iso-sharpe diagonals
    xs = np.linspace(s["sigma_per_tick"].min(), s["sigma_per_tick"].max(), 100)
    for sh in [0.5, 1.0, 2.0, 3.0]:
        ax.plot(xs, sh * xs, ls=":", color="grey", lw=0.6)
        ax.text(xs[-1], sh * xs[-1], f"  sharpe={sh}", color="grey", fontsize=8, va="center")
    # annotate top/bottom 5
    s_sorted = s.sort_values("sharpe", ascending=False)
    for _, r in pd.concat([s_sorted.head(5), s_sorted.tail(5)]).iterrows():
        ax.annotate(r["product"].split("_", 1)[-1], (r["sigma_per_tick"], r["spread_med"]),
                    fontsize=7, alpha=0.8, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("σ per tick (within-day Δmid std)")
    ax.set_ylabel("median spread (ticks)")
    ax.set_title("R5 plain-MM Sharpe map: spread_median vs σ_per_tick (50 products)")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "05_spread_vs_sigma.png")
    plt.close(fig)


def fig_06_drift_products(mid_w: pd.DataFrame):
    drifters = ["MICROCHIP_OVAL", "PEBBLES_XS", "UV_VISOR_AMBER"]
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    for ax, p in zip(axes, drifters):
        if p not in mid_w.columns:
            continue
        y = mid_w[p].values
        x = mid_w.index.values
        ax.plot(x, y, lw=0.6, color="tab:blue")
        # crude ols on (x, y) for slope per 10K-tick day
        coef = np.polyfit(x, y, 1)
        ax.plot(x, coef[0] * x + coef[1], lw=1.0, color="tab:red",
                label=f"OLS: {coef[0]*1e6:.2f}/Mtick = {coef[0]*TICKS_PER_DAY*TICK_STEP:.0f}/day")
        ax.set_title(p)
        ax.legend()
        ax.grid(True, alpha=0.25)
        add_day_dividers(ax)
    axes[-1].set_xlabel("absolute tick (days 2/3/4)")
    fig.suptitle("Round 5 — three down-drift products")
    fig.tight_layout()
    fig.savefig(OUT / "06_drift_products.png")
    plt.close(fig)


def fig_07_robot_dishes(mid_w: pd.DataFrame):
    p = "ROBOT_DISHES"
    if p not in mid_w.columns:
        return
    y = mid_w[p].values
    x = mid_w.index.values
    mu = y.mean()
    fig, axes = plt.subplots(2, 1, figsize=(14, 7))
    ax = axes[0]
    ax.plot(x, y, lw=0.5)
    ax.axhline(mu, color="red", lw=0.8, ls="--", label=f"mean={mu:.1f}")
    ax.set_title("ROBOT_DISHES — stationary candidate, half-life ≈ 319 ticks (FINDINGS)")
    ax.legend()
    ax.grid(True, alpha=0.25)
    add_day_dividers(ax)
    ax = axes[1]
    # autocorrelation of demeaned series
    yc = y - mu
    n = len(yc)
    lags = np.arange(1, 1500)
    var = (yc * yc).mean()
    ac = np.array([(yc[:-l] * yc[l:]).mean() / var for l in lags])
    ax.plot(lags, ac, lw=0.8)
    ax.axhline(0, color="black", lw=0.5)
    ax.axhline(np.exp(-1), color="red", ls="--", lw=0.7, label="1/e (half-life proxy)")
    ax.set_title("ROBOT_DISHES — autocorrelation of demeaned mid")
    ax.set_xlabel("lag (timesteps × 100)")
    ax.set_ylabel("ACF")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "07_robot_dishes_mr.png")
    plt.close(fig)


def fig_08_trade_volume(trades: pd.DataFrame):
    vol = trades.groupby("symbol").agg(n_trades=("quantity", "size"),
                                       qty_total=("quantity", "sum"),
                                       qty_mean=("quantity", "mean")).reset_index()
    prod_to_cat = {p: c for c, prods in CATEGORIES.items() for p in prods}
    vol["category"] = vol["symbol"].map(prod_to_cat)
    vol = vol.sort_values("n_trades", ascending=True)
    cmap = plt.get_cmap("tab10")
    cat_color = {c: cmap(i % 10) for i, c in enumerate(CATEGORIES)}
    colors = [cat_color[c] for c in vol["category"]]
    fig, axes = plt.subplots(1, 2, figsize=(15, 12))
    ax = axes[0]
    ax.barh(vol["symbol"], vol["n_trades"], color=colors, edgecolor="black", lw=0.3)
    ax.set_xlabel("trade count (3 days)")
    ax.set_title("Trades per product")
    ax.grid(True, alpha=0.25, axis="x")
    ax = axes[1]
    ax.barh(vol["symbol"], vol["qty_total"], color=colors, edgecolor="black", lw=0.3)
    ax.set_xlabel("total quantity (3 days)")
    ax.set_title("Total quantity traded per product")
    ax.grid(True, alpha=0.25, axis="x")
    # legend
    handles = [plt.Rectangle((0, 0), 1, 1, color=cat_color[c]) for c in CATEGORIES]
    fig.legend(handles, list(CATEGORIES), loc="lower center", ncol=5, fontsize=8, bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(OUT / "08_trade_volume.png", bbox_inches="tight")
    plt.close(fig)


def fig_09_correlations(mid_w: pd.DataFrame):
    """Per-day return correlation heatmap, products grouped by category."""
    # within-day diffs
    rets = mid_w.diff()
    # but cross-day boundaries are noise — set day boundary diffs to NaN
    # We'll just use overall diffs (small bias acceptable for visualization)
    order = [p for cat in CATEGORIES.values() for p in cat if p in rets.columns]
    R = rets[order].corr()
    fig, ax = plt.subplots(figsize=(13, 12))
    im = ax.imshow(R.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="equal")
    # category dividers
    cum = 0
    cuts = []
    for cat, prods in CATEGORIES.items():
        cum += sum(1 for p in prods if p in R.columns)
        cuts.append(cum)
    for c in cuts[:-1]:
        ax.axhline(c - 0.5, color="black", lw=0.6)
        ax.axvline(c - 0.5, color="black", lw=0.6)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(order, rotation=90, fontsize=6)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=6)
    fig.colorbar(im, ax=ax, label="Pearson r (Δmid)", shrink=0.8)
    ax.set_title("Round 5 — 50×50 return correlation heatmap (grouped by category)")
    fig.tight_layout()
    fig.savefig(OUT / "09_correlation_heatmap.png")
    plt.close(fig)


def fig_10_spread_distribution(px: pd.DataFrame):
    px = px.copy()
    px["spread"] = (px["ask_price_1"] - px["bid_price_1"]).astype(float)
    fig, axes = plt.subplots(5, 2, figsize=(14, 16), sharex=False)
    axes = axes.ravel()
    for i, (cat, prods) in enumerate(CATEGORIES.items()):
        ax = axes[i]
        sub = px[px["product"].isin(prods)]
        data = [sub[sub["product"] == p]["spread"].dropna().values for p in prods]
        labels = [p.split("_", 1)[-1] for p in prods]
        ax.boxplot(data, labels=labels, showfliers=False)
        ax.set_title(f"{cat} — L1 spread distribution")
        ax.set_ylabel("spread (ticks)")
        ax.tick_params(axis="x", rotation=30, labelsize=7)
        ax.grid(True, alpha=0.25, axis="y")
    fig.suptitle("Round 5 — bid/ask L1 spread by product (boxplots, no outliers)")
    fig.tight_layout()
    fig.savefig(OUT / "10_spread_distribution.png")
    plt.close(fig)


def main():
    print("Loading prices ...")
    px = load_prices()
    print(f"  rows={len(px):,}, products={px['product'].nunique()}, days={sorted(px['day'].unique())}")
    mid_w = pivot_mid(px)
    print(f"  mid pivot shape = {mid_w.shape}")
    print("Loading trades ...")
    trades = load_trades()
    print(f"  rows={len(trades):,}")

    print("01 mids by category ..."); fig_01_mids_by_category(mid_w)
    print("02 pebble basket ...");      fig_02_pebble_basket(mid_w)
    print("03 snackpack pair ...");     fig_03_snackpack_pair(px)
    print("04 snackpack triplet ...");  fig_04_snackpack_triplet(mid_w)
    print("05 spread vs sigma ...");    fig_05_spread_vs_sigma(px)
    print("06 drift products ...");     fig_06_drift_products(mid_w)
    print("07 robot_dishes mr ...");    fig_07_robot_dishes(mid_w)
    print("08 trade volume ...");       fig_08_trade_volume(trades)
    print("09 correlations ...");       fig_09_correlations(mid_w)
    print("10 spread dist ...");        fig_10_spread_distribution(px)

    print(f"\nWrote graphs to: {OUT}")
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
