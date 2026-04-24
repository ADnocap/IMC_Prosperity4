"""Calibration pipeline CLI.

Runs all 9 stages on a calibration/<asset>/data/fv_and_book.json and writes
the resulting params.json to calibration/<asset>/params.json.

Usage:
    py -3.13 -m calibration.pipeline.cli <ASSET_SYMBOL>
    py -3.13 -m calibration.pipeline.cli ASH_COATED_OSMIUM --no-write   # dry-run
    py -3.13 -m calibration.pipeline.cli --all                           # all assets with hasData
    py -3.13 -m calibration.pipeline.cli --all --report tmp/calib.md     # write summary report
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .data import load_fv_and_book
from .stage0_fv import run_stage0
from .stage1_layers import run_stage1
from .stage2_formulas import run_stage2
from .stage3_volume import run_stage3
from .stage4_presence import run_stage4
from .stage5_noise import run_stage5
from .stage6_trades import run_stage6
from .stage7_validation import run_stage7
from .stage8_export import assemble_params


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CALIB_DIR = REPO_ROOT / "calibration"


def _to_jsonable(obj):
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj): return None
        if math.isinf(obj): return None
        return obj
    return obj


def list_assets_with_data() -> list:
    out = []
    for d in sorted(CALIB_DIR.iterdir()):
        if not d.is_dir():
            continue
        f = d / "data" / "fv_and_book.json"
        if f.is_file():
            out.append(d.name.upper())
    return out


def run_pipeline(asset: str, write: bool = True, verbose: bool = True) -> dict:
    asset_lower = asset.lower()
    data_path = CALIB_DIR / asset_lower / "data" / "fv_and_book.json"
    if not data_path.is_file():
        raise FileNotFoundError(f"No fv_and_book.json for {asset} (expected {data_path})")
    data = load_fv_and_book(data_path)

    if verbose: print(f"\n[{asset}] loading: {len(data.rows)} rows, {len(data.trades)} trades")

    fv = run_stage0(data)
    if verbose: print(f"  Stage 0: {fv.picked_type:>13}  std_step={fv.diagnostics['std_step']:.4f}  drift={fv.diagnostics['mean_step']:.6f}  ljung_p={fv.diagnostics['residual_ljung']['p']:.3f}")

    s1 = run_stage1(data)
    if verbose: print(f"  Stage 1: {len(s1.layers)} layers detected")
    for L in s1.layers:
        if verbose: print(f"           {L.id} mag={L.offset_mag:.2f} type={L.offset_type} bid_band=({L.offset_band['bid'][0]:.2f},{L.offset_band['bid'][1]:.2f}) n_bid={L.n_bid} n_ask={L.n_ask}")

    if not s1.layers:
        if verbose: print(f"  [skip] no layers detected — cannot run Stages 2-8")
        return {"asset": asset, "params": None, "fv_type": fv.picked_type,
                "n_layers": 0, "verdict": "no-layers"}

    s2 = run_stage2(s1.layers, s1.quotes)
    if verbose:
        for b in s2["bots"]:
            wb = b["winner_bid"]; wa = b["winner_ask"]
            fb = b["winner_bid_family"]; fa = b["winner_ask_family"]
            bid_str = (f"{wb.round_fn}(fv+{wb.shift})+{wb.constant}" if fb == "fixed"
                       else f"{wb.round_fn}(fv*(1-{wb.k:.5f}))")
            ask_str = (f"{wa.round_fn}(fv+{wa.shift})+{wa.constant}" if fa == "fixed"
                       else f"{wa.round_fn}(fv*(1+{wa.k:.5f}))")
            print(f"  Stage 2: {b['layer_id']} BID {bid_str} cv={wb.cv_match_rate:.4f}  ASK {ask_str} cv={wa.cv_match_rate:.4f}")

    s3 = run_stage3(data, s1.layers)
    if verbose:
        for L in s3["layers"]:
            print(f"  Stage 3: {L['layer_id']} bid_vol_p={L['bid']['uniform'].p_value:.3f} ask_vol_p={L['ask']['uniform'].p_value:.3f} sides_tied={L['sides_tied_rate']:.2%}")

    s4 = run_stage4(data, s1.layers)
    if verbose:
        for L in s4["layers"]:
            print(f"  Stage 4: {L['layer_id']} bid_rate={L['bid']['rate']:.2%} ask_rate={L['ask']['rate']:.2%} bid_ljung_p={L['bid']['ljung'].p_value:.3f} ask_ljung_p={L['ask']['ljung'].p_value:.3f} bid_ask_indep_phi={L['bid_ask_indep'].phi:.3f}")

    s5 = run_stage5(data, s1)
    if verbose: print(f"  Stage 5: noise events={s5['stats']['n_events']} crossing_frac={s5['stats']['crossing_frac']:.2%}")

    s6 = run_stage6(data)
    if verbose:
        if s6["available"]:
            print(f"  Stage 6: trades n={s6['stats']['n_trades']} rate/tick={s6['stats']['rate_per_tick']:.4f} qty_range=[{s6['stats']['qty_min']},{s6['stats']['qty_max']}]")
        else:
            print(f"  Stage 6: skipped — {s6['reason']}")

    s7 = run_stage7(fv, s2, s3, s4)
    if verbose: print(f"  Stage 7: {s7['verdict'].upper()}  {len(s7['rows'])} tests, {s7['n_fail_raw']} raw failures, {s7['n_fail_bh']} BH-adjusted failures")

    params = assemble_params(asset, fv, s1, s2, s3, s4)
    if write:
        out_path = CALIB_DIR / asset_lower / "params.json"
        with open(out_path, "w") as f:
            json.dump(_to_jsonable(params), f, indent=2)
        if verbose: print(f"  Stage 8: wrote {out_path.relative_to(REPO_ROOT)}")
    elif verbose:
        print(f"  Stage 8: dry-run (params not written)")

    return {
        "asset": asset, "params": params,
        "fv_type": fv.picked_type,
        "n_layers": len(s1.layers),
        "n_bots": len(s2["bots"]),
        "n_trades": len(data.trades),
        "verdict": s7["verdict"],
        "fisher_p": s7["fisher"].p_value if s7["fisher"] else None,
        "n_fail_raw": s7["n_fail_raw"],
        "n_fail_bh": s7["n_fail_bh"],
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", nargs="?", help="Asset symbol (e.g. ASH_COATED_OSMIUM)")
    parser.add_argument("--all", action="store_true", help="Run on every asset with fv_and_book.json")
    parser.add_argument("--no-write", action="store_true", help="Dry-run — don't write params.json")
    parser.add_argument("--quiet", action="store_true", help="Less verbose output")
    parser.add_argument("--report", help="Write a markdown summary at this path")
    args = parser.parse_args(argv)

    if args.all:
        targets = list_assets_with_data()
        if not targets:
            print("No assets found with fv_and_book.json", file=sys.stderr)
            return 1
    elif args.asset:
        targets = [args.asset.upper()]
    else:
        parser.print_help()
        return 1

    summaries = []
    for asset in targets:
        try:
            summary = run_pipeline(asset, write=not args.no_write, verbose=not args.quiet)
            summaries.append(summary)
        except Exception as e:
            print(f"\n[{asset}] FAILED: {e}", file=sys.stderr)
            if not args.quiet:
                traceback.print_exc()
            summaries.append({"asset": asset, "verdict": "error", "error": str(e)})

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Calibration pipeline report", "",
                 "| Asset | FV type | Layers | Bots | Trades | Verdict | Fisher p | Raw fail | BH fail |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for s in summaries:
            if s.get("verdict") == "error":
                lines.append(f"| {s['asset']} | error: {s.get('error', '?')[:60]} | | | | | | | |")
                continue
            fp = f"{s['fisher_p']:.2e}" if s.get("fisher_p") is not None else "-"
            lines.append(
                f"| {s['asset']} | {s.get('fv_type','-')} | {s.get('n_layers',0)} | "
                f"{s.get('n_bots',0)} | {s.get('n_trades',0)} | {s.get('verdict','-')} | "
                f"{fp} | {s.get('n_fail_raw','-')} | {s.get('n_fail_bh','-')} |"
            )
        Path(args.report).write_text("\n".join(lines))
        print(f"\nReport written: {args.report}")

    print(f"\nSummary: {len(summaries)} asset(s)  "
          + " ".join(f"{s['asset']}={s.get('verdict','?')}" for s in summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
