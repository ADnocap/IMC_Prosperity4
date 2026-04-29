"""Visualize basket-signal strength across the 10 R5 categories.

Produces:
  11_basket_eigenvalues.png  per-category 5 eigvals + a marker at the cutoff
  12_basket_constraint_strength.png  smallest eigval + total-sum-std-normalized
  13_intra_category_corrs.png  per-category 5x5 return-corr blocks (small panels)
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "prosperity4" / "round5"
OUT = REPO / "tmp" / "round5_viz"
OUT.mkdir(parents=True, exist_ok=True)
ANALYSIS = REPO / "analysis" / "round5"

CATEGORIES = {
    "Galaxy Sounds": ["GALAXY_SOUNDS_DARK_MATTER","GALAXY_SOUNDS_BLACK_HOLES","GALAXY_SOUNDS_PLANETARY_RINGS","GALAXY_SOUNDS_SOLAR_WINDS","GALAXY_SOUNDS_SOLAR_FLAMES"],
    "Sleep Pods":   ["SLEEP_POD_SUEDE","SLEEP_POD_LAMB_WOOL","SLEEP_POD_POLYESTER","SLEEP_POD_NYLON","SLEEP_POD_COTTON"],
    "Microchips":   ["MICROCHIP_CIRCLE","MICROCHIP_OVAL","MICROCHIP_SQUARE","MICROCHIP_RECTANGLE","MICROCHIP_TRIANGLE"],
    "Pebbles":      ["PEBBLES_XS","PEBBLES_S","PEBBLES_M","PEBBLES_L","PEBBLES_XL"],
    "Robots":       ["ROBOT_VACUUMING","ROBOT_MOPPING","ROBOT_DISHES","ROBOT_LAUNDRY","ROBOT_IRONING"],
    "UV-Visors":    ["UV_VISOR_YELLOW","UV_VISOR_AMBER","UV_VISOR_ORANGE","UV_VISOR_RED","UV_VISOR_MAGENTA"],
    "Translators":  ["TRANSLATOR_SPACE_GRAY","TRANSLATOR_ASTRO_BLACK","TRANSLATOR_ECLIPSE_CHARCOAL","TRANSLATOR_GRAPHITE_MIST","TRANSLATOR_VOID_BLUE"],
    "Panels":       ["PANEL_1X2","PANEL_2X2","PANEL_1X4","PANEL_2X4","PANEL_4X4"],
    "Oxygen Shakes":["OXYGEN_SHAKE_MORNING_BREATH","OXYGEN_SHAKE_EVENING_BREATH","OXYGEN_SHAKE_MINT","OXYGEN_SHAKE_CHOCOLATE","OXYGEN_SHAKE_GARLIC"],
    "Snackpacks":   ["SNACKPACK_CHOCOLATE","SNACKPACK_VANILLA","SNACKPACK_PISTACHIO","SNACKPACK_STRAWBERRY","SNACKPACK_RASPBERRY"],
}

mpl.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130, "axes.titlesize": 11, "figure.titlesize": 13})

def load_basket():
    with open(ANALYSIS / "basket_search.json") as f:
        return json.load(f)

def cat_key(name): return name.lower().replace(" ", "_").replace("-", "_")

def fig_11(b):
    fig, ax = plt.subplots(figsize=(13, 6))
    cats = list(CATEGORIES)
    cmap = plt.get_cmap("tab10")
    x = np.arange(len(cats))
    width = 0.16
    eigs = np.array([b["category_signatures"][cat_key(c)]["eigvals"] for c in cats])
    # sorted ascending so smallest is rightmost? show all 5 stacked
    for i in range(5):
        ax.bar(x + (i - 2) * width, eigs[:, i], width=width,
               color=cmap(i), label=f"eigval[{i}]", edgecolor="black", lw=0.3)
    ax.axhline(1.0, color="grey", lw=0.6, ls="--", label="random-walk baseline (1.0)")
    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=20, ha="right")
    ax.set_ylabel("PCA eigenvalue (return-correlation matrix, mean = 1)")
    ax.set_title("Per-category PCA eigenvalue spectrum — small eigvals = hidden linear constraint")
    ax.legend(ncol=3, fontsize=8)
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(OUT / "11_basket_eigenvalues.png")
    plt.close(fig)

def fig_12(b):
    cats = list(CATEGORIES)
    smallest = [b["category_signatures"][cat_key(c)]["smallest_eigval"] for c in cats]
    second = [b["category_signatures"][cat_key(c)]["second_smallest"] for c in cats]
    sum_norm = [b["category_signatures"][cat_key(c)]["total_sum_std_normalized"] for c in cats]
    order = np.argsort(smallest)
    cats_o = [cats[i] for i in order]
    smallest_o = [smallest[i] for i in order]
    second_o = [second[i] for i in order]
    sum_norm_o = [sum_norm[i] for i in order]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    ax = axes[0]
    x = np.arange(len(cats_o))
    ax.bar(x - 0.18, smallest_o, width=0.36, label="smallest eigval", color="tab:red", edgecolor="black", lw=0.3)
    ax.bar(x + 0.18, second_o, width=0.36, label="2nd smallest eigval", color="tab:orange", edgecolor="black", lw=0.3)
    ax.axhline(1.0, color="grey", lw=0.6, ls="--", label="RW baseline")
    ax.set_xticks(x)
    ax.set_xticklabels(cats_o, rotation=25, ha="right")
    ax.set_ylabel("eigenvalue")
    ax.set_title("Constraint strength: bottom-2 PCA eigvals per category\n(values near 0 = strong linear constraint)")
    ax.legend()
    ax.grid(True, alpha=0.25, axis="y")
    ax = axes[1]
    ax.barh(cats_o, sum_norm_o, color="tab:blue", edgecolor="black", lw=0.3)
    ax.set_xscale("log")
    ax.set_xlabel("normalized total-sum std (sum_std / typical solo σ)  — log scale")
    ax.set_title("Sum-of-5 std vs typical individual product σ\n(<1 = sum is more stable than its members)")
    ax.grid(True, alpha=0.25, axis="x")
    fig.suptitle("R5 — which categories have a true basket constraint?")
    fig.tight_layout()
    fig.savefig(OUT / "12_basket_constraint_strength.png")
    plt.close(fig)

def fig_13_intra_corrs():
    parts = []
    for d in [2, 3, 4]:
        parts.append(pd.read_parquet(DATA / f"prices_round_5_day_{d}.parquet"))
    px = pd.concat(parts, ignore_index=True)
    mid_w = px.pivot_table(index=["day", "timestamp"], columns="product", values="mid_price").sort_index()
    rets = mid_w.diff().dropna(how="all")
    fig, axes = plt.subplots(2, 5, figsize=(17, 7))
    axes = axes.ravel()
    for i, (cat, prods) in enumerate(CATEGORIES.items()):
        ax = axes[i]
        sub = rets[prods].corr()
        im = ax.imshow(sub.values, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_title(cat, fontsize=10)
        labels = [p.split("_", 1)[-1][:10] for p in prods]
        ax.set_xticks(range(5)); ax.set_xticklabels(labels, rotation=80, fontsize=7)
        ax.set_yticks(range(5)); ax.set_yticklabels(labels, fontsize=7)
        # annotate cells
        for r in range(5):
            for c in range(5):
                if r != c:
                    val = sub.values[r, c]
                    color = "white" if abs(val) > 0.5 else "black"
                    ax.text(c, r, f"{val:+.2f}", ha="center", va="center",
                            fontsize=6, color=color)
    fig.colorbar(im, ax=axes, label="Pearson r (Δmid)", shrink=0.8, pad=0.02)
    fig.suptitle("Intra-category 5×5 return correlations — Pebbles & Snackpacks have visible structure; the rest don't")
    fig.savefig(OUT / "13_intra_category_corrs.png", bbox_inches="tight")
    plt.close(fig)

def main():
    b = load_basket()
    print("11 eigenvalue spectrum ..."); fig_11(b)
    print("12 constraint strength ..."); fig_12(b)
    print("13 intra-cat corrs ...");      fig_13_intra_corrs()
    print(f"\nWrote to {OUT}")
    for f in sorted(OUT.glob("1[123]_*.png")):
        print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
