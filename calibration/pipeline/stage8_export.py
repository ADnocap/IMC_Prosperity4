"""Stage 8 — assemble params.json from upstream stage results.

Port of visualizer/src/pages/calibration/stages/export.ts.
"""
from __future__ import annotations

import datetime as _dt

from .stage2_formulas import layers_to_bot_specs


def assemble_params(asset: str, fv, s1, s2, s3=None, s4=None) -> dict:
    if not (fv and s1 and s2):
        raise ValueError("Stage 8 requires at least Stages 0-2 to have run")

    fv_params: dict = {"quantization": fv.diagnostics["quantization"]["value"]}
    fv_type = fv.picked_type
    d = fv.diagnostics
    if fv_type == "random_walk":
        fv_params["drift"] = 0.0
        fv_params["sigma"] = d["std_step"]
        fv_params["mean"] = d["mean_fv"]
    elif fv_type == "linear_drift":
        fv_params["drift"] = d["linear_fit"]["beta"]
        fv_params["mean"] = d["linear_fit"]["alpha"]
        # Use step std (innovation), not residual std of the level fit. The
        # linear regression residual is the per-tick deviation from the line;
        # the per-step innovation is what the simulator needs to match.
        fv_params["sigma"] = d["std_step"]
    elif fv_type == "ar1":
        fv_params["ar1_coef"] = d["delta_ac1"]
        fv_params["drift"] = d["mean_step"]
        fv_params["sigma"] = d["std_step"]
    else:
        # constant-type FV: use step std (innovation noise) not level std.
        # For nearly-constant series the level is approximately mean while
        # tick-to-tick noise has its own (typically much smaller) scale.
        fv_params["mean"] = d["mean_fv"]
        fv_params["sigma"] = d["std_step"]

    bots = layers_to_bot_specs(s1.layers, s2)

    if s3:
        for model in s3["layers"]:
            b = next((x for x in bots if x["id"] == model["layer_id"]), None)
            if not b:
                continue
            bid_dist = model["bid"].get("best_dist", "uniform")
            ask_dist = model["ask"].get("best_dist", "uniform")
            # When sides are tied (always equal volume per tick), we have one
            # draw; pick whichever side's chosen distribution. When mixed,
            # default to "empirical" to be safe.
            if bid_dist == ask_dist:
                dist = bid_dist
            else:
                dist = "empirical"
            b["volume"] = {
                "distribution": dist,
                "low": min(model["bid"]["min"], model["ask"]["min"]),
                "high": max(model["bid"]["max"], model["ask"]["max"]),
                "sides_tied": model["sides_tied_rate"] > 0.95,
            }
            if dist == "empirical":
                # Record the empirical PMF (use bid side; ask should be similar
                # when sides are tied, slightly different otherwise).
                b["volume"]["pmf"] = model["bid"].get("empirical_pmf", {})
            b.setdefault("diagnostics", {}).update({
                "bid_vol_uniform_p": model["bid"]["uniform"].p_value,
                "ask_vol_uniform_p": model["ask"]["uniform"].p_value,
                "bid_dist": bid_dist, "ask_dist": ask_dist,
                "sides_tied_rate": model["sides_tied_rate"],
            })

    if s4:
        for model in s4["layers"]:
            b = next((x for x in bots if x["id"] == model["layer_id"]), None)
            if not b:
                continue
            bid_det = model["bid"].get("deterministic", False)
            ask_det = model["ask"].get("deterministic", False)
            bid_model = model["bid"].get("model", "iid_bernoulli")
            ask_model = model["ask"].get("model", "iid_bernoulli")
            iid_pass = (bid_model == "iid_bernoulli" and ask_model == "iid_bernoulli")
            # Per-side presence model — when not iid, the sim should sample
            # presence from the empirical run-length distribution recorded
            # below. When deterministic, just always emit.
            b["presence"] = {
                "rate": (model["bid"]["rate"] + model["ask"]["rate"]) / 2,
                "bid_rate": model["bid"]["rate"],
                "ask_rate": model["ask"]["rate"],
                "bid_model": bid_model, "ask_model": ask_model,
                "iid": iid_pass,
                "bid_ask_independent": model["bid_ask_indep"].p_value > 0.05,
                "deterministic_bid": bid_det,
                "deterministic_ask": ask_det,
            }
            # Record run-length stats for empirical models (sim consumes these).
            if bid_model == "empirical":
                rl = model["bid"]["run_length"]
                b["presence"]["bid_run_length"] = {
                    "mean": rl.mean_length, "n_runs": rl.n_runs,
                }
            if ask_model == "empirical":
                rl = model["ask"]["run_length"]
                b["presence"]["ask_run_length"] = {
                    "mean": rl.mean_length, "n_runs": rl.n_runs,
                }
            b.setdefault("diagnostics", {}).update({
                "bid_presence_rate": model["bid"]["rate"],
                "ask_presence_rate": model["ask"]["rate"],
                "bid_ask_indep_p": model["bid_ask_indep"].p_value,
            })

    return {
        "asset": asset,
        "position_limit": 80,
        "fv_process": {
            "type": fv_type,
            "params": fv_params,
            "diagnostics": {
                "n_ticks": d["n_ticks"],
                "residual_ljung_p": d["residual_ljung"]["p"],
                "residual_skew_z": d["skew_z"],
                "residual_kurt_z": d["kurt_z"],
            },
        },
        "bots": bots,
        "metadata": {
            "calibrated_from": "discovery pipeline (calibration/run_pipeline.py, Stages 0-4)",
            "pipeline_version": "1.0.0-py",
            "timestamp": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "notes": "Auto-generated by Python CLI port of the visualizer Calibration tab.",
        },
    }
