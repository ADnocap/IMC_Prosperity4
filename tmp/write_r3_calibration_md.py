"""Generate calibration.md per R3 asset from the params.json the pipeline wrote."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
R3 = ["hydrogel_pack", "velvetfruit_extract", "vev_4000", "vev_4500",
      "vev_5000", "vev_5100", "vev_5200", "vev_5300", "vev_5400",
      "vev_5500", "vev_6000", "vev_6500"]


def fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


for asset in R3:
    pj = REPO / "calibration" / asset / "params.json"
    if not pj.exists():
        continue
    p = json.loads(pj.read_text())
    fvp = p["fv_process"]
    lines = [f"# {p['asset']} Calibration", ""]
    lines.append("Round 3 product. Calibrated by `calibration/run_pipeline.py`")
    lines.append("(Python port of the visualizer 9-stage pipeline).")
    lines.append("")
    lines.append("## Fair Value process")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|---|---|")
    lines.append(f"| Type | {fvp['type']} |")
    for k, v in fvp["params"].items():
        lines.append(f"| {k} | {fmt(v)} |")
    diag = fvp["diagnostics"]
    lines.append(f"| n_ticks | {diag['n_ticks']} |")
    lines.append(f"| residual Ljung p | {diag['residual_ljung_p']:.4f} |")
    lines.append(f"| residual skew z | {diag['residual_skew_z']:.3f} |")
    lines.append(f"| residual kurt z | {diag['residual_kurt_z']:.3f} |")
    lines.append("")

    for b in p["bots"]:
        lines.append(f"## Bot `{b['id']}` — {b['name']}")
        lines.append("")
        lines.append("| Property | Value |")
        lines.append("|---|---|")
        lines.append(f"| Bid formula | `{b['bid_formula_str']}` |")
        lines.append(f"| Ask formula | `{b['ask_formula_str']}` |")
        lines.append(f"| Offset type | {b['offset_type']} |")
        bid_band = b["offset_band"]["bid"]
        ask_band = b["offset_band"]["ask"]
        lines.append(f"| Offset band (bid) | [{bid_band[0]:.2f}, {bid_band[1]:.2f}] |")
        lines.append(f"| Offset band (ask) | [{ask_band[0]:.2f}, {ask_band[1]:.2f}] |")
        vol = b["volume"]
        if vol["distribution"] == "uniform":
            vol_str = f"uniform U({vol['low']}, {vol['high']})"
        else:
            vol_str = f"empirical, range [{vol['low']}, {vol['high']}]"
        lines.append(f"| Volume | {vol_str} |")
        lines.append(f"| Sides tied | {vol['sides_tied']} |")
        pr = b["presence"]
        lines.append(f"| Presence (bid rate) | {pr['bid_rate']:.3f} |")
        lines.append(f"| Presence (ask rate) | {pr['ask_rate']:.3f} |")
        lines.append(f"| Presence model (bid) | {pr['bid_model']} |")
        lines.append(f"| Presence model (ask) | {pr['ask_model']} |")
        # Diagnostics
        d = b.get("diagnostics", {})
        if d:
            lines.append("")
            lines.append("Diagnostics:")
            lines.append("")
            for k in ("bid_vol_uniform_p", "ask_vol_uniform_p", "sides_tied_rate",
                      "bid_presence_rate", "ask_presence_rate", "bid_ask_indep_p"):
                if k in d:
                    lines.append(f"- `{k}` = {fmt(d[k])}")
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append("- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs")
    lines.append("- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)")
    lines.append(f"- **Generated**: {p['metadata'].get('timestamp', '')}")
    lines.append("")

    out = REPO / "calibration" / asset / "calibration.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  + {out.relative_to(REPO)}")
print("done")
