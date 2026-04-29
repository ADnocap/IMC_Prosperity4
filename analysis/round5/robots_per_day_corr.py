"""Per-day correlation analysis for the Robots basket.

Computes 5x5 correlation matrices for the 5 Robot products on each of days
2/3/4 separately, in two flavors:
  - return correlations (Δmid per tick)  — what drives pair MR
  - level correlations (raw mids)        — what drives cointegration
Outputs:
  14_robots_corr_per_day.png   side-by-side return-corr heatmaps for d2/d3/d4
  15_robots_levels_per_day.png mid trajectories per day, all 5 robots overlaid
  robots_corr_per_day.csv      machine-readable corrs (long form)
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

ROBOTS = ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
          "ROBOT_LAUNDRY",   "ROBOT_IRONING"]
SHORT = {p: p.replace("ROBOT_", "") for p in ROBOTS}
DAYS = [2, 3, 4]

mpl.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130,
                     "axes.titlesize": 11, "figure.titlesize": 13})


def load_day(day: int) -> pd.DataFrame:
    """Wide-format mids for the 5 robots, indexed by timestamp, for one day."""
    px = pd.read_parquet(DATA / f"prices_round_5_day_{day}.parquet")
    px = px[px["product"].isin(ROBOTS)]
    return px.pivot_table(index="timestamp", columns="product",
                          values="mid_price").sort_index()[ROBOTS]


def fig_returns_corr(corrs: dict[int, pd.DataFrame]):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    for ax, day in zip(axes, DAYS):
        C = corrs[day]
        im = ax.imshow(C.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(5)); ax.set_yticks(range(5))
        labels = [SHORT[p] for p in ROBOTS]
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
        ax.set_yticklabels(labels, fontsize=9)
        for r in range(5):
            for c in range(5):
                v = C.values[r, c]
                color = "white" if abs(v) > 0.5 else "black"
                ax.text(c, r, f"{v:+.2f}", ha="center", va="center",
                        fontsize=9, color=color)
        ax.set_title(f"Day {day} — Δmid Pearson r")
    fig.colorbar(im, ax=axes, shrink=0.8, pad=0.02, label="Pearson r")
    fig.suptitle("Robots basket — return correlations per day")
    fig.savefig(OUT / "14_robots_corr_per_day.png", bbox_inches="tight")
    plt.close(fig)


def fig_levels_per_day(day_data: dict[int, pd.DataFrame]):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    cmap = plt.get_cmap("tab10")
    for ax, day in zip(axes, DAYS):
        df = day_data[day]
        for i, p in enumerate(ROBOTS):
            ax.plot(df.index.values, df[p].values, lw=0.6,
                    color=cmap(i), label=SHORT[p])
        ax.set_title(f"Day {day} — mids")
        ax.set_xlabel("timestamp")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("mid")
    axes[0].legend(loc="best", fontsize=8)
    fig.suptitle("Robots basket — raw mid trajectories per day")
    fig.tight_layout()
    fig.savefig(OUT / "15_robots_levels_per_day.png")
    plt.close(fig)


def main():
    day_data = {d: load_day(d) for d in DAYS}
    rets = {d: df.diff().dropna() for d, df in day_data.items()}
    corr_ret = {d: r.corr() for d, r in rets.items()}
    corr_lvl = {d: df.corr() for d, df in day_data.items()}

    # also pooled
    pooled_rets = pd.concat([rets[d] for d in DAYS], ignore_index=True)
    corr_ret["pooled"] = pooled_rets.corr()

    print("\n=== Return correlations (Δmid) ===")
    for d in DAYS + ["pooled"]:
        print(f"\nDay {d}:")
        print(corr_ret[d].round(3).to_string())

    print("\n=== Level correlations (raw mid) ===")
    for d in DAYS:
        print(f"\nDay {d}:")
        print(corr_lvl[d].round(3).to_string())

    # long-form csv
    rows = []
    for d in DAYS + ["pooled"]:
        C = corr_ret[d]
        for a in ROBOTS:
            for b in ROBOTS:
                rows.append({"day": d, "kind": "returns",
                             "a": a, "b": b, "corr": C.loc[a, b]})
    for d in DAYS:
        C = corr_lvl[d]
        for a in ROBOTS:
            for b in ROBOTS:
                rows.append({"day": d, "kind": "levels",
                             "a": a, "b": b, "corr": C.loc[a, b]})
    pd.DataFrame(rows).to_csv(OUT / "robots_corr_per_day.csv", index=False)

    fig_returns_corr({d: corr_ret[d] for d in DAYS})
    fig_levels_per_day(day_data)

    print(f"\nWrote graphs to: {OUT}")
    for f in sorted(OUT.glob("1[45]_robots_*.png")):
        print(f"  {f.name} ({f.stat().st_size/1024:.0f} KB)")
    print(f"  robots_corr_per_day.csv ({(OUT/'robots_corr_per_day.csv').stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
