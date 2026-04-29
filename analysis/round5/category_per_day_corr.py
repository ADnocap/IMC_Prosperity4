"""Per-day correlation analysis for any 5-product R5 category.

For each category specified, computes:
  - return-correlation 5x5 matrix per day (Δmid Pearson r) + pooled
  - level-correlation 5x5 matrix per day (raw mid Pearson r)
  - stability score: max abs day-to-day change in pair correlations
Outputs a heatmap deck under tmp/round5_viz/ and a CSV per category.
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

CATEGORIES = {
    "uv_visors":  ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                   "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
    "microchips": ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                   "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
}

mpl.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130,
                     "axes.titlesize": 11, "figure.titlesize": 13})


def load_day(day: int, prods: list[str]) -> pd.DataFrame:
    px = pd.read_parquet(DATA / f"prices_round_5_day_{day}.parquet")
    px = px[px["product"].isin(prods)]
    return px.pivot_table(index="timestamp", columns="product",
                          values="mid_price").sort_index()[prods]


def short(p: str) -> str:
    for prefix in ("UV_VISOR_", "MICROCHIP_", "ROBOT_", "SLEEP_POD_",
                   "GALAXY_SOUNDS_", "PEBBLES_", "TRANSLATOR_", "PANEL_",
                   "OXYGEN_SHAKE_", "SNACKPACK_"):
        if p.startswith(prefix):
            return p[len(prefix):]
    return p


def fig_corrs(corrs: dict[int, pd.DataFrame], prods: list[str], title: str, fname: str):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    labels = [short(p) for p in prods]
    for ax, day in zip(axes, DAYS):
        C = corrs[day]
        im = ax.imshow(C.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(5)); ax.set_yticks(range(5))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
        ax.set_yticklabels(labels, fontsize=9)
        for r in range(5):
            for c in range(5):
                v = C.values[r, c]
                color = "white" if abs(v) > 0.5 else "black"
                ax.text(c, r, f"{v:+.2f}", ha="center", va="center",
                        fontsize=9, color=color)
        ax.set_title(f"Day {day}")
    fig.colorbar(im, ax=axes, shrink=0.8, pad=0.02, label="Pearson r")
    fig.suptitle(title)
    fig.savefig(OUT / fname, bbox_inches="tight")
    plt.close(fig)


def fig_levels(day_data: dict[int, pd.DataFrame], prods: list[str], title: str, fname: str):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    cmap = plt.get_cmap("tab10")
    labels = [short(p) for p in prods]
    for ax, day in zip(axes, DAYS):
        df = day_data[day]
        for i, p in enumerate(prods):
            ax.plot(df.index.values, df[p].values, lw=0.6,
                    color=cmap(i), label=labels[i])
        ax.set_title(f"Day {day} — mids")
        ax.set_xlabel("timestamp")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("mid")
    axes[0].legend(loc="best", fontsize=8)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(OUT / fname)
    plt.close(fig)


def stability_report(corrs: dict[int, pd.DataFrame], prods: list[str], kind: str, name: str):
    """Print pair-by-pair correlations across days and the spread (max-min)."""
    rows = []
    for i in range(5):
        for j in range(i + 1, 5):
            vals = [corrs[d].values[i, j] for d in DAYS]
            spread = max(vals) - min(vals)
            rows.append({
                "pair": f"{short(prods[i])}-{short(prods[j])}",
                **{f"d{d}": vals[k] for k, d in enumerate(DAYS)},
                "spread": spread,
                "max_abs": max(abs(v) for v in vals),
                "sign_flip": (max(vals) > 0.05) and (min(vals) < -0.05),
            })
    df = pd.DataFrame(rows).sort_values("max_abs", ascending=False)
    print(f"\n--- {name} {kind} stability ---")
    print(df.round(3).to_string(index=False))
    return df


def run_category(name: str, prods: list[str]):
    day_data = {d: load_day(d, prods) for d in DAYS}
    rets = {d: df.diff().dropna() for d, df in day_data.items()}
    corr_ret = {d: r.corr() for d, r in rets.items()}
    corr_lvl = {d: df.corr() for d, df in day_data.items()}

    print(f"\n========== {name} ==========")
    print("\n=== Δmid (return) correlations per day ===")
    for d in DAYS:
        print(f"\nDay {d}:")
        print(corr_ret[d].round(3).to_string())
    print("\n=== Level (raw mid) correlations per day ===")
    for d in DAYS:
        print(f"\nDay {d}:")
        print(corr_lvl[d].round(3).to_string())

    df_ret = stability_report(corr_ret, prods, "returns", name)
    df_lvl = stability_report(corr_lvl, prods, "levels", name)

    rows = []
    for d in DAYS:
        for a in prods:
            for b in prods:
                rows.append({"day": d, "kind": "returns", "a": a, "b": b,
                             "corr": corr_ret[d].loc[a, b]})
                rows.append({"day": d, "kind": "levels", "a": a, "b": b,
                             "corr": corr_lvl[d].loc[a, b]})
    pd.DataFrame(rows).to_csv(OUT / f"{name}_corr_per_day.csv", index=False)

    fig_corrs(corr_ret, prods,
              f"{name.replace('_', '-').title()} — return correlations per day",
              f"16_{name}_corr_per_day_returns.png")
    fig_corrs(corr_lvl, prods,
              f"{name.replace('_', '-').title()} — level correlations per day",
              f"17_{name}_corr_per_day_levels.png")
    fig_levels(day_data, prods,
               f"{name.replace('_', '-').title()} — raw mids per day",
               f"18_{name}_levels_per_day.png")

    return df_ret, df_lvl


def main():
    for name, prods in CATEGORIES.items():
        run_category(name, prods)
    print(f"\nGraphs in {OUT}:")
    for f in sorted(OUT.glob("1[678]_*.png")):
        print(f"  {f.name} ({f.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
