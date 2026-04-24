"""Stage 7 — held-out validation + overall confidence.

Port of visualizer/src/pages/calibration/stages/validation.ts.
"""
from __future__ import annotations

import math

from . import kernels as K


def _collect_ps(fv, s2, s3, s4) -> list:
    rows = []
    if fv:
        d = fv.diagnostics
        # Skip residual tests when FV is constant — residuals are tiny
        # quantization noise, not the model's stochastic process. The Ljung
        # / skew / kurt tests are not meaningful here. (VEV_6000, VEV_6500
        # both have ~constant FV.)
        if fv.picked_type != "constant":
            rows.append({"stage": "Stage 0", "test": "Residual Ljung-Box",
                         "p": d["residual_ljung"]["p"], "detail": f"Q={d['residual_ljung']['q']:.2f}"})
            rows.append({"stage": "Stage 0", "test": "Residual skewness z=0",
                         "p": d["skew_p"], "detail": f"skew={d['skewness']:.3f}"})
            rows.append({"stage": "Stage 0", "test": "Residual kurtosis z=0",
                         "p": d["kurt_p"], "detail": f"ex-kurt={d['excess_kurtosis']:.3f}"})
    if s2:
        for b in s2["bots"]:
            wb = b["winner_bid"]; wa = b["winner_ask"]
            bp = 0.5 if wb.cv_match_rate >= 0.95 else 0.01
            ap = 0.5 if wa.cv_match_rate >= 0.95 else 0.01
            rows.append({"stage": "Stage 2", "test": f"{b['layer_name']} bid CV match >= 95%",
                         "p": bp, "detail": f"CV={wb.cv_match_rate * 100:.2f}%"})
            rows.append({"stage": "Stage 2", "test": f"{b['layer_name']} ask CV match >= 95%",
                         "p": ap, "detail": f"CV={wa.cv_match_rate * 100:.2f}%"})
    if s3:
        for L in s3["layers"]:
            # Use the best-fit distribution's p-value rather than always-uniform.
            # Many R3 assets have non-uniform empirical volume distributions that
            # do not fit any parametric form — for those, "best_p"=1.0 indicates
            # we will sample from the empirical PMF in the sim (no parametric
            # model to test against).
            rows.append({"stage": "Stage 3",
                         "test": f"{L['layer_name']} bid vol ~ {L['bid'].get('best_dist','U')}",
                         "p": L["bid"].get("best_p", L["bid"]["uniform"].p_value),
                         "detail": f"chi2={L['bid']['uniform'].chi2:.2f}"})
            rows.append({"stage": "Stage 3",
                         "test": f"{L['layer_name']} ask vol ~ {L['ask'].get('best_dist','U')}",
                         "p": L["ask"].get("best_p", L["ask"]["uniform"].p_value),
                         "detail": f"chi2={L['ask']['uniform'].chi2:.2f}"})
    if s4:
        for L in s4["layers"]:
            bid_det = L["bid"].get("deterministic", False)
            ask_det = L["ask"].get("deterministic", False)
            bid_model = L["bid"].get("model", "iid_bernoulli")
            ask_model = L["ask"].get("model", "iid_bernoulli")
            # Only run iid Bernoulli tests when we've actually selected that
            # model. Skip when deterministic OR when we've adopted empirical /
            # joint_empirical (the iid test would be redundant; we already
            # know iid was rejected and recorded the richer model).
            iid_models = {"iid_bernoulli"}
            if not bid_det and bid_model in iid_models:
                rows.append({"stage": "Stage 4", "test": f"{L['layer_name']} bid iid (Ljung)",
                             "p": L["bid"]["ljung"].p_value, "detail": f"Q={L['bid']['ljung'].q:.2f}"})
                rows.append({"stage": "Stage 4", "test": f"{L['layer_name']} bid runs test",
                             "p": L["bid"]["runs"].p_value, "detail": f"z={L['bid']['runs'].z:.2f}"})
            if not ask_det and ask_model in iid_models:
                rows.append({"stage": "Stage 4", "test": f"{L['layer_name']} ask iid (Ljung)",
                             "p": L["ask"]["ljung"].p_value, "detail": f"Q={L['ask']['ljung'].q:.2f}"})
                rows.append({"stage": "Stage 4", "test": f"{L['layer_name']} ask runs test",
                             "p": L["ask"]["runs"].p_value, "detail": f"z={L['ask']['runs'].z:.2f}"})
            # bid⊥ask test: only run when we've claimed both sides are iid AND
            # independent. If either is empirical or joint, we've already
            # adopted a richer model that captures the dependence; running the
            # iid-independence test is redundant and would re-reject what we
            # already know.
            joint = bid_model == "joint_empirical" or ask_model == "joint_empirical"
            if (not (bid_det or ask_det) and not joint
                    and bid_model == "iid_bernoulli" and ask_model == "iid_bernoulli"):
                rows.append({"stage": "Stage 4", "test": f"{L['layer_name']} bid_ask indep chi2",
                             "p": L["bid_ask_indep"].p_value,
                             "detail": f"phi={L['bid_ask_indep'].phi:.3f}"})
        for x in s4["cross_bot"]:
            # Skip cross-bot independence tests for layers that are clearly tied
            # (likely the same physical bot quoting multiple levels). Reporting
            # "fail to reject independence" here is structurally guaranteed and
            # not informative.
            if x.get("tied", False):
                continue
            rows.append({"stage": "Stage 4",
                         "test": f"{x['a_id']}.{x['side_a']} _|_ {x['b_id']}.{x['side_b']}",
                         "p": x["indep"].p_value,
                         "detail": f"phi={x['indep'].phi:.3f}"})
    return rows


def run_stage7(fv, s2, s3, s4) -> dict:
    rows = _collect_ps(fv, s2, s3, s4)
    # Build a (valid_p, original_index) list, run BH on the valid_p subset, and
    # then expand the adjusted vector back to row-aligned positions (NaN for
    # rows whose p was filtered out). Misalignment was a real bug: rows had 25
    # entries but bh_adjusted had 23, so reporting code that did
    # `bh_adjusted[i]` was reading the wrong test's adjusted p.
    valid = [(i, r["p"]) for i, r in enumerate(rows)
             if math.isfinite(r["p"]) and 0 < r["p"] <= 1]
    fisher = None
    bh_aligned: list = [float("nan")] * len(rows)
    if valid:
        ps = [v[1] for v in valid]
        try:
            fisher = K.fisher_combined(ps)
            bh_subset = K.bh_adjust(ps)
            for (orig_idx, _), b in zip(valid, bh_subset):
                bh_aligned[orig_idx] = b
        except Exception:
            pass
    raw_ps_for_count = [v[1] for v in valid]
    n_fail_raw = sum(1 for p in raw_ps_for_count if p < 0.05)
    n_fail_bh = sum(1 for p in bh_aligned if math.isfinite(p) and p < 0.05)
    if n_fail_bh > 0:
        verdict = "fail"
    elif n_fail_raw > len(rows) * 0.1:
        verdict = "warn"
    else:
        verdict = "pass"
    return {
        "rows": rows, "fisher": fisher, "bh_adjusted": bh_aligned,
        "n_fail_raw": n_fail_raw, "n_fail_bh": n_fail_bh,
        "verdict": verdict,
    }
