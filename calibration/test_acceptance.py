"""Acceptance tests for the calibration pipeline.

Loads `calibration/<asset>/data/fv_and_book.json` and `params.json` for each
asset with a file in `rust_simulator/src/assets/`, then verifies that the
documented formulas in params.json recover their claimed match rate on the
extracted data.

This is a regression test for the calibration ground truth. If someone edits
params.json to something broken, this test fails. It also validates that the
extraction pipeline + parameter format are in sync.

Run:  py -3.13 calibration/test_acceptance.py
Or:   py -3.13 -m pytest calibration/test_acceptance.py  (if pytest installed)
"""

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ASSETS_DIR = REPO_ROOT / "rust_simulator" / "src" / "assets"
CALIB_DIR = REPO_ROOT / "calibration"

# Formula-match minimums we accept for passed calibration.
MIN_FORMULA_MATCH = 0.98
# FV process diagnostics — loose sanity bounds.
FV_PROCESS_CHECKS = {
    "random_walk":  {"sigma_max": 1.0, "drift_max_abs": 0.01},
    "linear_drift": {"drift_min_abs": 0.01},
    "constant":     {"sigma_max": 0.01},
    "ar1":          {},
}


def evaluate_formula(spec: dict, side: str, fv: float) -> int:
    """Apply a single formula_spec side to FV → predicted price (int)."""
    rnd = spec["round_fn"]
    shift = spec.get("shift", 0.0)
    const = spec.get("constant", 0)
    K = spec.get("K")
    if K is None:
        x = fv + shift
    else:
        sign = -1 if side == "bid" else 1
        x = fv * (1.0 + sign * K)
    if rnd == "floor":
        base = math.floor(x)
    elif rnd == "ceil":
        base = math.ceil(x)
    elif rnd == "round":
        # Python banker's rounding (same as the Rust kernel's "round").
        base = int(round(x))
    else:
        raise ValueError(f"unknown round_fn {rnd}")
    return base + int(const)


def list_tested_assets() -> list[str]:
    out = []
    for f in sorted(ASSETS_DIR.glob("*.rs")):
        if f.name == "mod.rs":
            continue
        out.append(f.stem)
    return out


def check_asset(asset_lower: str) -> list[str]:
    errors: list[str] = []
    data_path = CALIB_DIR / asset_lower / "data" / "fv_and_book.json"
    params_path = CALIB_DIR / asset_lower / "params.json"
    if not data_path.exists():
        return [f"[{asset_lower}] missing fv_and_book.json"]
    if not params_path.exists():
        return [f"[{asset_lower}] missing params.json"]
    with open(data_path) as f:
        data = json.load(f)
    with open(params_path) as f:
        params = json.load(f)

    rows = [r for r in data["rows"] if r.get("fv") is not None]
    if len(rows) < 100:
        errors.append(f"[{asset_lower}] only {len(rows)} FV rows — need >= 100")
        return errors

    # ── FV process sanity ──
    fp = params["fv_process"]
    checks = FV_PROCESS_CHECKS.get(fp["type"], {})
    steps = [rows[i]["fv"] - rows[i - 1]["fv"] for i in range(1, len(rows))]
    mean_step = sum(steps) / len(steps)
    std_step = math.sqrt(sum((s - mean_step) ** 2 for s in steps) / len(steps))
    if "sigma_max" in checks and std_step > checks["sigma_max"]:
        errors.append(f"[{asset_lower}] std_step={std_step:.3f} exceeds {checks['sigma_max']} for {fp['type']}")
    if "drift_max_abs" in checks and abs(mean_step) > checks["drift_max_abs"]:
        errors.append(f"[{asset_lower}] |mean_step|={abs(mean_step):.4f} exceeds {checks['drift_max_abs']} for {fp['type']}")
    if "drift_min_abs" in checks and abs(mean_step) < checks["drift_min_abs"]:
        errors.append(f"[{asset_lower}] |mean_step|={abs(mean_step):.4f} below {checks['drift_min_abs']} for {fp['type']}")

    # ── Per-bot formula match rate ──
    for bot in params["bots"]:
        bid_band = bot["offset_band"]["bid"]
        ask_band = bot["offset_band"]["ask"]
        bid_spec = bot["formula_spec"]["bid"]
        ask_spec = bot["formula_spec"]["ask"]

        bid_match = bid_total = ask_match = ask_total = 0
        for r in rows:
            fv = r["fv"]
            for bp in r["bids"]:
                off = bp - fv
                if bid_band[0] <= off <= bid_band[1]:
                    bid_total += 1
                    if evaluate_formula(bid_spec, "bid", fv) == bp:
                        bid_match += 1
            for ap in r["asks"]:
                off = ap - fv
                if ask_band[0] <= off <= ask_band[1]:
                    ask_total += 1
                    if evaluate_formula(ask_spec, "ask", fv) == ap:
                        ask_match += 1

        if bid_total > 0:
            rate = bid_match / bid_total
            if rate < MIN_FORMULA_MATCH:
                errors.append(
                    f"[{asset_lower}] bot {bot['id']} bid formula "
                    f"'{bot['bid_formula_str']}' match={rate:.3%} "
                    f"({bid_match}/{bid_total}) < {MIN_FORMULA_MATCH:.0%}"
                )
            else:
                print(f"  [{asset_lower}] {bot['id']} bid: {rate:.3%} ({bid_match}/{bid_total}) OK")
        if ask_total > 0:
            rate = ask_match / ask_total
            if rate < MIN_FORMULA_MATCH:
                errors.append(
                    f"[{asset_lower}] bot {bot['id']} ask formula "
                    f"'{bot['ask_formula_str']}' match={rate:.3%} "
                    f"({ask_match}/{ask_total}) < {MIN_FORMULA_MATCH:.0%}"
                )
            else:
                print(f"  [{asset_lower}] {bot['id']} ask: {rate:.3%} ({ask_match}/{ask_total}) OK")
    return errors


def main() -> int:
    assets = list_tested_assets()
    print(f"Testing {len(assets)} asset(s): {assets}\n")
    all_errors: list[str] = []
    for a in assets:
        errs = check_asset(a)
        all_errors.extend(errs)
    print()
    if all_errors:
        print("FAILED:")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    print(f"PASS — {len(assets)} asset(s) match their documented calibration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
