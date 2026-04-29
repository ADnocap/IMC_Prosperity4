"""Feature discovery for plain-MM on the 40 non-basket R5 assets.

We've shown: tick-level Δmid correlations across these 40 are ~0 (no cross-product signal).
What MIGHT still be exploitable is *within-asset* short-horizon microstructure:

  1. L1 order-book imbalance (OBI) -> next-tick Δmid
       OBI_t = bid_vol1 / (bid_vol1 + ask_vol1) - 0.5
       If r(OBI_t, Δmid_{t+1}) > 0, leaning the quote pair toward the heavier side
       is a free skew on top of mm_v2's inventory skew.
  2. Microprice = vol-weighted L1 mid; microprice - mid as an FV correction.
  3. Post-trade Δmid: when a market trade prints, what does mid do over the next
     1, 5, 10 ticks? Continuation = adverse selection cost; reversion = MM edge.
  4. Spread regime: median, p90, fraction of ticks with wide spread.
  5. L1 size: typical posted volume — informs how often penny-jumping wins
     queue position vs joining at L1.

Outputs:
  mm_features.csv          per-asset, per-day feature table
  19_obi_signal.png        per-asset OBI->next-Δmid r (bar, sorted)
  20_microprice_bias.png   microprice - mid bias distribution per category
  21_post_trade_flow.png   buy-flow vs sell-flow next-tick Δmid (per category)
  22_spread_regime.png     median spread + p90 spread + frac>=h+2 per category
  23_feature_summary.png   one card per asset: spread, σ, OBI-r, post-trade
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"
OUT  = REPO / "tmp" / "round5_viz"
OUT.mkdir(parents=True, exist_ok=True)
ANL  = REPO / "analysis" / "round5"

DAYS = [2, 3, 4]

# 40 non-basket assets (excluding Pebbles + Snackpacks per user instruction)
EXCLUDE_PREFIXES = ("PEBBLES_", "SNACKPACK_")

CATEGORIES = {
    "Galaxy Sounds": ["GALAXY_SOUNDS_DARK_MATTER","GALAXY_SOUNDS_BLACK_HOLES","GALAXY_SOUNDS_PLANETARY_RINGS","GALAXY_SOUNDS_SOLAR_WINDS","GALAXY_SOUNDS_SOLAR_FLAMES"],
    "Sleep Pods":   ["SLEEP_POD_SUEDE","SLEEP_POD_LAMB_WOOL","SLEEP_POD_POLYESTER","SLEEP_POD_NYLON","SLEEP_POD_COTTON"],
    "Microchips":   ["MICROCHIP_CIRCLE","MICROCHIP_OVAL","MICROCHIP_SQUARE","MICROCHIP_RECTANGLE","MICROCHIP_TRIANGLE"],
    "Robots":       ["ROBOT_VACUUMING","ROBOT_MOPPING","ROBOT_DISHES","ROBOT_LAUNDRY","ROBOT_IRONING"],
    "UV-Visors":    ["UV_VISOR_YELLOW","UV_VISOR_AMBER","UV_VISOR_ORANGE","UV_VISOR_RED","UV_VISOR_MAGENTA"],
    "Translators":  ["TRANSLATOR_SPACE_GRAY","TRANSLATOR_ASTRO_BLACK","TRANSLATOR_ECLIPSE_CHARCOAL","TRANSLATOR_GRAPHITE_MIST","TRANSLATOR_VOID_BLUE"],
    "Panels":       ["PANEL_1X2","PANEL_2X2","PANEL_1X4","PANEL_2X4","PANEL_4X4"],
    "Oxygen Shakes":["OXYGEN_SHAKE_MORNING_BREATH","OXYGEN_SHAKE_EVENING_BREATH","OXYGEN_SHAKE_MINT","OXYGEN_SHAKE_CHOCOLATE","OXYGEN_SHAKE_GARLIC"],
}
ALL40 = [p for prods in CATEGORIES.values() for p in prods]

mpl.rcParams.update({"figure.dpi":110,"savefig.dpi":130,"axes.titlesize":10,
                     "figure.titlesize":13})


def _short(p: str) -> str:
    for pre in ("UV_VISOR_","MICROCHIP_","ROBOT_","SLEEP_POD_",
                "GALAXY_SOUNDS_","TRANSLATOR_","PANEL_","OXYGEN_SHAKE_"):
        if p.startswith(pre): return p[len(pre):]
    return p


def load_prices_one_day(day: int) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"prices_round_5_day_{day}.parquet")

def load_trades_one_day(day: int) -> pd.DataFrame:
    return pd.read_parquet(DATA / f"trades_round_5_day_{day}.parquet")


def per_asset_features_one_day(day: int) -> pd.DataFrame:
    """For each of the 40 assets, compute per-day microstructure features."""
    px = load_prices_one_day(day)
    px = px[px["product"].isin(ALL40)].sort_values(["product","timestamp"]).copy()

    # bid/ask vols at L1
    bid_v1 = px["bid_volume_1"].astype(float).fillna(0.0)
    ask_v1 = px["ask_volume_1"].astype(float).fillna(0.0)
    px["spread"]       = px["ask_price_1"] - px["bid_price_1"]
    px["mid"]          = (px["ask_price_1"] + px["bid_price_1"]) / 2.0
    den                = bid_v1 + ask_v1
    px["obi"]          = np.where(den > 0, bid_v1 / den - 0.5, 0.0)
    px["microprice"]   = np.where(den > 0,
                                  (px["ask_price_1"]*bid_v1 + px["bid_price_1"]*ask_v1) / den,
                                  px["mid"])
    px["mp_bias"]      = px["microprice"] - px["mid"]

    # next-tick mid change (within product)
    px["dmid_next"] = px.groupby("product")["mid"].shift(-1) - px["mid"]

    rows = []
    for prod, g in px.groupby("product"):
        g = g.dropna(subset=["dmid_next","obi","spread","mid"])
        if len(g) < 100: continue
        # within-day Δmid std (excluding NA)
        dmid = g["dmid_next"].values
        sigma_per_tick = float(np.std(dmid, ddof=1))
        # OBI predictive r
        obi = g["obi"].values
        if obi.std() > 0 and sigma_per_tick > 0:
            r_obi = float(np.corrcoef(obi, dmid)[0,1])
        else:
            r_obi = float("nan")
        # microprice bias predictive r
        mpb = g["mp_bias"].values
        if mpb.std() > 0 and sigma_per_tick > 0:
            r_mp = float(np.corrcoef(mpb, dmid)[0,1])
        else:
            r_mp = float("nan")
        # OBI / mp slope (β) on dmid_next
        beta_obi = float(np.cov(obi, dmid, ddof=1)[0,1] / (obi.var(ddof=1)+1e-12))
        beta_mp  = float(np.cov(mpb, dmid, ddof=1)[0,1] / (mpb.var(ddof=1)+1e-12))
        rows.append({
            "day": day, "product": prod,
            "spread_med":   float(g["spread"].median()),
            "spread_p90":   float(g["spread"].quantile(0.90)),
            "frac_spread_ge_4": float((g["spread"] >= 4).mean()),
            "frac_spread_eq_1": float((g["spread"] == 1).mean()),
            "bid_vol1_med": float(g["bid_volume_1"].median()),
            "ask_vol1_med": float(g["ask_volume_1"].median()),
            "sigma_per_tick": sigma_per_tick,
            "obi_std":      float(obi.std()),
            "mp_bias_std":  float(mpb.std()),
            "r_obi_dmid_next": r_obi,
            "r_mp_dmid_next":  r_mp,
            "beta_obi": beta_obi,
            "beta_mp":  beta_mp,
        })
    return pd.DataFrame(rows)


def post_trade_flow_one_day(day: int) -> pd.DataFrame:
    """For each asset, classify trades as buy-flow (price=ask) or sell-flow
    (price=bid) by matching the trade timestamp to the prices snapshot, then
    measure mid drift over windows {+1,+5,+10} ticks (mid steps of 100)."""
    px = load_prices_one_day(day)
    px = px[px["product"].isin(ALL40)].sort_values(["product","timestamp"])
    trades = load_trades_one_day(day)
    trades = trades[trades["symbol"].isin(ALL40)].sort_values(["symbol","timestamp"])

    # join on (product, timestamp)
    merged = trades.merge(
        px[["product","timestamp","bid_price_1","ask_price_1"]].rename(columns={"product":"symbol"}),
        on=["symbol","timestamp"], how="left",
    )
    # flow side: +1 if hits ask (buy flow), -1 if hits bid (sell flow)
    px_at_ask = merged["price"] >= merged["ask_price_1"]
    px_at_bid = merged["price"] <= merged["bid_price_1"]
    side = np.where(px_at_ask, 1, np.where(px_at_bid, -1, 0))
    merged["side"] = side

    # mid lookups for {+1,+5,+10}*100 timestamp offsets
    px_idx = px.set_index(["product","timestamp"])
    px_idx["mid_now"] = (px_idx["ask_price_1"] + px_idx["bid_price_1"]) / 2.0

    rows = []
    for sym, g in merged.groupby("symbol"):
        if len(g) < 30: continue
        ts = g["timestamp"].values
        sd = g["side"].values
        try:
            mid_now = px_idx.loc[sym].reindex(ts)["mid_now"].values
            mid_p1  = px_idx.loc[sym].reindex(ts + 100)["mid_now"].values
            mid_p5  = px_idx.loc[sym].reindex(ts + 500)["mid_now"].values
            mid_p10 = px_idx.loc[sym].reindex(ts + 1000)["mid_now"].values
        except KeyError:
            continue
        for label, mid_after in [("p1", mid_p1), ("p5", mid_p5), ("p10", mid_p10)]:
            dm = (mid_after - mid_now) * sd  # signed flow direction
            valid = ~np.isnan(dm) & (sd != 0)
            if valid.sum() < 30: continue
            mean_dm = float(np.nanmean(dm[valid]))
            frac_continue = float(np.nanmean(dm[valid] > 0))
            n = int(valid.sum())
            rows.append({"day": day, "product": sym, "horizon": label,
                         "n_trades": n, "mean_signed_dmid": mean_dm,
                         "frac_continue": frac_continue})
    return pd.DataFrame(rows)


def fig_19_obi_signal(feat: pd.DataFrame):
    """Per-asset OBI predictive r (averaged across days), sorted; color = category."""
    avg = feat.groupby("product")["r_obi_dmid_next"].mean().reset_index()
    avg["category"] = avg["product"].map({p: c for c, ps in CATEGORIES.items() for p in ps})
    avg["short"] = avg["product"].apply(_short)
    avg = avg.sort_values("r_obi_dmid_next")
    cmap = plt.get_cmap("tab10")
    cat_color = {c: cmap(i % 10) for i, c in enumerate(CATEGORIES)}

    fig, ax = plt.subplots(figsize=(13, 11))
    colors = [cat_color[c] for c in avg["category"]]
    ax.barh(range(len(avg)), avg["r_obi_dmid_next"].values,
            color=colors, edgecolor="black", lw=0.3)
    ax.set_yticks(range(len(avg)))
    ax.set_yticklabels([f"{r['category'][:3]}-{r['short']}" for _, r in avg.iterrows()],
                       fontsize=7)
    ax.axvline(0, color="black", lw=0.6)
    # noise floor: 1/√(N_obs / 3 days * 10K) ~ 1/√10K ≈ 0.01 per day; pooled ~0.0058
    nf = 1 / np.sqrt(30000)
    ax.axvline( nf, color="red", lw=0.5, ls="--", alpha=0.6, label=f"noise floor ±{nf:.3f}")
    ax.axvline(-nf, color="red", lw=0.5, ls="--", alpha=0.6)
    ax.set_xlabel("Pearson r(OBI_t, Δmid_{t+1})  averaged over 3 days")
    ax.set_title("OBI → next-tick Δmid predictive correlation, per asset (40 plain-MM assets)")
    handles = [plt.Rectangle((0,0),1,1,color=cat_color[c]) for c in CATEGORIES]
    ax.legend(handles + ax.get_legend_handles_labels()[0],
              list(CATEGORIES) + ax.get_legend_handles_labels()[1],
              fontsize=8, loc="lower right")
    ax.grid(True, alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(OUT / "19_obi_signal.png")
    plt.close(fig)


def fig_20_microprice_bias(feat: pd.DataFrame):
    """Microprice-bias predictive r vs Pearson r(OBI). They're correlated — but
    microprice can pick up half-tick volume asymmetries OBI misses."""
    avg = feat.groupby("product")[["r_obi_dmid_next","r_mp_dmid_next"]].mean().reset_index()
    avg["category"] = avg["product"].map({p: c for c, ps in CATEGORIES.items() for p in ps})
    cmap = plt.get_cmap("tab10")
    cat_color = {c: cmap(i % 10) for i, c in enumerate(CATEGORIES)}

    fig, ax = plt.subplots(figsize=(9, 8))
    for cat, sub in avg.groupby("category"):
        ax.scatter(sub["r_obi_dmid_next"], sub["r_mp_dmid_next"],
                   color=cat_color[cat], s=80, label=cat,
                   edgecolor="black", lw=0.4)
    lo = min(avg["r_obi_dmid_next"].min(), avg["r_mp_dmid_next"].min())
    hi = max(avg["r_obi_dmid_next"].max(), avg["r_mp_dmid_next"].max())
    ax.plot([lo, hi], [lo, hi], "k--", lw=0.6, alpha=0.6, label="y=x")
    ax.axhline(0, color="grey", lw=0.4); ax.axvline(0, color="grey", lw=0.4)
    ax.set_xlabel("r(OBI, Δmid_{t+1})")
    ax.set_ylabel("r(microprice−mid, Δmid_{t+1})")
    ax.set_title("OBI vs microprice bias as predictors — per asset, 3-day avg")
    for _, r in avg.iterrows():
        ax.annotate(_short(r["product"]),
                    (r["r_obi_dmid_next"], r["r_mp_dmid_next"]),
                    fontsize=6, alpha=0.7, xytext=(2, 2), textcoords="offset points")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "20_microprice_bias.png")
    plt.close(fig)


def fig_21_post_trade_flow(pt: pd.DataFrame):
    """Post-trade signed Δmid by horizon, per category boxplot.
    Positive value = continuation (adverse for MM); negative = reversion (good)."""
    pt2 = pt.copy()
    pt2["category"] = pt2["product"].map({p: c for c, ps in CATEGORIES.items() for p in ps})
    pt2 = pt2.dropna(subset=["category"])
    horizons = ["p1", "p5", "p10"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), sharey=True)
    cats = list(CATEGORIES)
    for ax, h in zip(axes, horizons):
        sub = pt2[pt2["horizon"] == h]
        data = [sub[sub["category"] == c]["mean_signed_dmid"].dropna().values for c in cats]
        bp = ax.boxplot(data, tick_labels=cats, showfliers=True, patch_artist=True)
        cmap = plt.get_cmap("tab10")
        for i, b in enumerate(bp["boxes"]):
            b.set_facecolor(cmap(i % 10)); b.set_alpha(0.6)
        ax.axhline(0, color="black", lw=0.6, ls="--")
        ax.set_title(f"horizon = {h}")
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        ax.grid(True, alpha=0.25, axis="y")
    axes[0].set_ylabel("mean signed Δmid after trade  (>0 = continuation/adverse)")
    fig.suptitle("Post-trade flow: does mid follow the trade direction or revert?")
    fig.tight_layout()
    fig.savefig(OUT / "21_post_trade_flow.png")
    plt.close(fig)


def fig_22_spread_regime(feat: pd.DataFrame):
    """Per-asset median spread + p90 + frac(spread>=4) bar grid by category."""
    avg = feat.groupby("product")[["spread_med","spread_p90","frac_spread_ge_4",
                                    "frac_spread_eq_1","sigma_per_tick"]].mean().reset_index()
    avg["category"] = avg["product"].map({p: c for c, ps in CATEGORIES.items() for p in ps})
    avg["short"] = avg["product"].apply(_short)

    fig, axes = plt.subplots(2, 4, figsize=(16, 9), sharey=False)
    axes = axes.ravel()
    cats = list(CATEGORIES)
    cmap = plt.get_cmap("tab10")
    for i, cat in enumerate(cats):
        sub = avg[avg["category"] == cat].sort_values("spread_med", ascending=False)
        ax = axes[i]
        x = np.arange(len(sub))
        ax.bar(x - 0.25, sub["spread_med"], width=0.25, label="median", color=cmap(0))
        ax.bar(x + 0.00, sub["spread_p90"], width=0.25, label="p90", color=cmap(1))
        ax.bar(x + 0.25, sub["sigma_per_tick"], width=0.25, label="σ/tick", color=cmap(3))
        ax.set_xticks(x); ax.set_xticklabels(sub["short"], rotation=30, fontsize=7, ha="right")
        ax.set_title(f"{cat}")
        ax.grid(True, alpha=0.25, axis="y")
        if i == 0:
            ax.legend(fontsize=7, loc="best")
    fig.suptitle("Spread regime + σ per tick, per asset (3-day average)")
    fig.tight_layout()
    fig.savefig(OUT / "22_spread_regime.png")
    plt.close(fig)


def fig_23_feature_summary(feat: pd.DataFrame, pt: pd.DataFrame):
    """Two-axis chart: each asset = 1 dot. x = spread/σ Sharpe, y = OBI predictive r.
    Color = post-trade flow at h=5 (red = adverse, green = revert).
    Top-right = best plain-MM candidates that ALSO have an OBI skew available."""
    feat_avg = feat.groupby("product")[["spread_med","sigma_per_tick","r_obi_dmid_next"]].mean().reset_index()
    feat_avg["sharpe"] = feat_avg["spread_med"] / feat_avg["sigma_per_tick"]
    pt_avg = pt[pt["horizon"]=="p5"].groupby("product")["mean_signed_dmid"].mean().reset_index()
    df = feat_avg.merge(pt_avg, on="product", how="left")
    df["category"] = df["product"].map({p: c for c, ps in CATEGORIES.items() for p in ps})
    df["short"] = df["product"].apply(_short)
    cmap_pt = plt.get_cmap("RdYlGn_r")  # negative=green=revert, positive=red=adverse
    vmax = float(np.nanmax(np.abs(df["mean_signed_dmid"]).values))
    if not np.isfinite(vmax) or vmax == 0: vmax = 1.0

    fig, ax = plt.subplots(figsize=(13, 9))
    sc = ax.scatter(df["sharpe"], df["r_obi_dmid_next"],
                    c=df["mean_signed_dmid"], cmap=cmap_pt, vmin=-vmax, vmax=vmax,
                    s=140, edgecolor="black", lw=0.5)
    nf = 1/np.sqrt(30000)
    ax.axhline( nf, color="red", lw=0.5, ls="--", alpha=0.5)
    ax.axhline(-nf, color="red", lw=0.5, ls="--", alpha=0.5)
    ax.axhline(0, color="black", lw=0.6)
    ax.axvline(1.0, color="grey", lw=0.5, ls=":", alpha=0.6)
    for _, r in df.iterrows():
        ax.annotate(f"{r['short']}", (r["sharpe"], r["r_obi_dmid_next"]),
                    fontsize=7, alpha=0.85, xytext=(3, 3), textcoords="offset points")
    cb = plt.colorbar(sc, ax=ax)
    cb.set_label("post-trade signed Δmid @ h=5  (red = adverse, green = MM-favorable)")
    ax.set_xlabel("plain-MM Sharpe = spread_median / σ_per_tick")
    ax.set_ylabel("r(OBI_t, Δmid_{t+1})")
    ax.set_title("MM feature summary — top right = wide spread × strong OBI signal × MM-favorable post-trade")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "23_feature_summary.png")
    plt.close(fig)


def main():
    print("Computing per-asset features ...")
    feats = pd.concat([per_asset_features_one_day(d) for d in DAYS], ignore_index=True)
    feats.to_csv(OUT / "mm_features.csv", index=False)
    print(f"  {len(feats)} rows -> mm_features.csv")

    print("Computing post-trade flow ...")
    pts = pd.concat([post_trade_flow_one_day(d) for d in DAYS], ignore_index=True)
    pts.to_csv(OUT / "mm_post_trade.csv", index=False)
    print(f"  {len(pts)} rows -> mm_post_trade.csv")

    print("Charts:")
    fig_19_obi_signal(feats);       print("  19 OBI per asset")
    fig_20_microprice_bias(feats);  print("  20 microprice vs OBI")
    fig_21_post_trade_flow(pts);    print("  21 post-trade flow")
    fig_22_spread_regime(feats);    print("  22 spread regime")
    fig_23_feature_summary(feats, pts); print("  23 feature summary card")

    # quick text summary of best signals
    print("\n=== TOP 10 OBI signals (3-day mean |r|) ===")
    by_obi = feats.groupby("product")["r_obi_dmid_next"].mean().reset_index()
    by_obi["abs_r"] = by_obi["r_obi_dmid_next"].abs()
    print(by_obi.sort_values("abs_r", ascending=False).head(10).to_string(index=False))

    print("\n=== TOP 10 post-trade reversion candidates (h=5, most negative) ===")
    by_pt5 = pts[pts["horizon"]=="p5"].groupby("product")["mean_signed_dmid"].mean().reset_index()
    print(by_pt5.sort_values("mean_signed_dmid").head(10).to_string(index=False))

    print("\n=== TOP 10 post-trade ADVERSE (h=5, most positive — avoid penny-jumping these) ===")
    print(by_pt5.sort_values("mean_signed_dmid", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
