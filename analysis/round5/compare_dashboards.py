"""Compare two MC dashboards by per-asset PnL.

Usage:
    py -3.12 analysis/round5/compare_dashboards.py <baseline_json> <candidate_json>
"""
import json
import sys
from pathlib import Path

import pandas as pd


def per_asset(d):
    rows = []
    for prod, info in d["products"].items():
        rows.append({
            "product": prod,
            "mean": info["pnl"]["mean"],
            "std":  info["pnl"]["std"],
            "p05":  info["pnl"]["p05"],
            "p95":  info["pnl"]["p95"],
        })
    return pd.DataFrame(rows).set_index("product").sort_index()


def main(base_path: str, cand_path: str):
    base = json.load(open(base_path))
    cand = json.load(open(cand_path))

    b = per_asset(base)
    c = per_asset(cand)

    df = pd.DataFrame({
        "base_mean": b["mean"],
        "cand_mean": c["mean"],
        "delta":     c["mean"] - b["mean"],
        "base_std":  b["std"],
        "cand_std":  c["std"],
    })
    df["delta_pct"] = df["delta"] / df["base_mean"].abs().clip(lower=1)

    # category prefix
    def cat(p):
        for prefix, name in [
            ("GALAXY_", "Galaxy"), ("SLEEP_", "Sleep"), ("MICROCHIP_", "Microchip"),
            ("PEBBLES_", "Pebble"), ("ROBOT_", "Robot"), ("UV_", "UVVisor"),
            ("TRANSLATOR_", "Translator"), ("PANEL_", "Panel"),
            ("OXYGEN_", "OxygenShake"), ("SNACKPACK_", "Snackpack"),
        ]:
            if p.startswith(prefix): return name
        return "?"
    df["cat"] = df.index.map(cat)

    print(f"\n=== Per-asset comparison: {Path(cand_path).parent.name} vs {Path(base_path).parent.name} ===")
    print(f"{'product':36s} {'cat':10s} {'base':>10s} {'cand':>10s} {'Δ':>10s}")
    for prod, row in df.sort_values("delta", ascending=False).iterrows():
        marker = "↑" if row["delta"] > 0 else ("↓" if row["delta"] < 0 else " ")
        print(f"{prod:36s} {row['cat']:10s} {row['base_mean']:10.0f} {row['cand_mean']:10.0f} {row['delta']:+10.0f} {marker}")

    print("\n=== Aggregated by category ===")
    agg = df.groupby("cat").agg(
        base=("base_mean", "sum"),
        cand=("cand_mean", "sum"),
        n=("base_mean", "size"),
    )
    agg["delta"] = agg["cand"] - agg["base"]
    agg["delta_pct"] = agg["delta"] / agg["base"].abs().clip(lower=1) * 100
    print(agg.sort_values("delta", ascending=False).round(0).to_string())

    print("\n=== Total ===")
    print(f"  base mean total = {df['base_mean'].sum():>10,.0f}")
    print(f"  cand mean total = {df['cand_mean'].sum():>10,.0f}")
    print(f"  delta total     = {df['delta'].sum():>+10,.0f}")
    print(f"  ratio cand/base = {df['cand_mean'].sum()/df['base_mean'].sum():.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
