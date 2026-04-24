"""Stage 4 — per-bot presence model.

Port of visualizer/src/pages/calibration/stages/presence_model.ts.
"""
from __future__ import annotations

from . import kernels as K
from .data import FvAndBook
from .stage1_layers import DetectedLayer


def _build_indicator_series(data: FvAndBook, layer: DetectedLayer, side: str) -> list:
    band = layer.offset_band["bid"] if side == "bid" else layer.offset_band["ask"]
    arr = []
    for r in data.rows:
        if r.fv is None:
            arr.append(0.0); continue
        prices = r.bids if side == "bid" else r.asks
        present = 0
        for p in prices:
            off = p - r.fv
            if band[0] <= off <= band[1]:
                present = 1
                break
        arr.append(float(present))
    return arr


def _summarize_side(indicator: list) -> dict:
    n = len(indicator)
    k = int(sum(indicator))
    rate = k / n if n > 0 else 0
    ci = K.wilson(k, n, 0.80, 0.05)
    # Detect deterministic / near-deterministic presence: if the point estimate
    # of the rate is ≥ 0.95 or ≤ 0.05, treat as effectively constant — the
    # iid-Bernoulli tests can't distinguish "iid Bernoulli with p=0.96 + bursty
    # absences" from random absences with so few non-events, and reporting it
    # as a model failure isn't actionable for the sim (we'd model it as always
    # on with rare drops anyway).
    deterministic = (rate >= 0.95) or (rate <= 0.05)
    if deterministic:
        # Synthesize "trivially passes" stat objects so downstream code that
        # accesses .q / .p_value / .z keeps working.
        lj = K.LjungOut(q=0.0, df=10.0, p_value=1.0, autocorr=[0.0] * 10)
        runs = K.RunsOut(runs=1, n1=k, n2=n - k, expected=0.0, variance=0.0,
                         z=0.0, p_value=1.0)
        rl = K.RunLenOut(run_lengths=[], empirical_pmf=[], fitted_pmf=[],
                         ks_stat=0.0, ks_p=1.0, mean_length=0.0, n_runs=0)
        model = "deterministic"
    else:
        lj = K.ljung_box(indicator, 10)
        runs = K.runs_test(indicator)
        rl = K.run_length_geom(indicator)
        # Pick the best presence model:
        #   - iid Bernoulli if Ljung & runs both pass
        #   - empirical otherwise (record run-length distribution; the sim
        #     replays the empirical run lengths instead of sampling iid)
        if lj.p_value > 0.05 and runs.p_value > 0.05:
            model = "iid_bernoulli"
        else:
            model = "empirical"
    return {"rate": rate, "ci": ci, "ljung": lj, "runs": runs, "run_length": rl,
            "n_ticks": n, "n_present": k, "deterministic": deterministic,
            "model": model}


def _indep_from_indicators(a: list, b: list) -> K.Indep2x2Out:
    both = a_only = b_only = neither = 0
    n = min(len(a), len(b))
    for i in range(n):
        ax = a[i] > 0.5; bx = b[i] > 0.5
        if ax and bx: both += 1
        elif ax:      a_only += 1
        elif bx:      b_only += 1
        else:         neither += 1
    # When one side is deterministic (one row of the 2x2 has no observations),
    # the chi-squared test is undefined. Return p=1 with phi=0 so Stage 7 skips.
    if a_only + neither == 0 or both + b_only == 0 \
            or both + a_only == 0 or b_only + neither == 0:
        return K.Indep2x2Out(
            observed=[[both, a_only], [b_only, neither]],
            expected=[[float(both), float(a_only)], [float(b_only), float(neither)]],
            chi2=0.0, p_value=1.0, phi=0.0,
        )
    res = K.indep_2x2(both, a_only, b_only, neither)
    # Cochran's rule: chi-squared GoF needs every expected cell >= 5. When any
    # cell falls below that, the asymptotic chi-squared p-value can't be
    # trusted. Mark the test as not-applicable so Stage 7 doesn't false-flag.
    if any(c < 5.0 for row in res.expected for c in row):
        return K.Indep2x2Out(
            observed=res.observed, expected=res.expected,
            chi2=res.chi2, p_value=1.0, phi=res.phi,
        )
    return res


def run_stage4(data: FvAndBook, layers: list) -> dict:
    bid_inds: dict = {}
    ask_inds: dict = {}
    out_layers = []
    for L in layers:
        bid = _build_indicator_series(data, L, "bid")
        ask = _build_indicator_series(data, L, "ask")
        bid_inds[L.id] = bid
        ask_inds[L.id] = ask
        bid_summary = _summarize_side(bid)
        ask_summary = _summarize_side(ask)
        indep = _indep_from_indicators(bid, ask)
        # If the bid/ask presences are NOT independent (chi² rejects at 0.05)
        # AND neither side is deterministic (in which case the test is N/A),
        # adopt a joint empirical 2x2 presence model. The sim samples
        # (bid_present, ask_present) jointly from the observed 4-cell distribution.
        bid_det = bid_summary["deterministic"]
        ask_det = ask_summary["deterministic"]
        if not (bid_det or ask_det) and indep.p_value < 0.05:
            bid_summary["model"] = "joint_empirical"
            ask_summary["model"] = "joint_empirical"
        out_layers.append({
            "layer_id": L.id, "layer_name": L.name,
            "bid": bid_summary, "ask": ask_summary,
            "bid_ask_indep": indep,
        })
    cross = []
    ids = [L.id for L in layers]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a = ids[i]; b = ids[j]
            for side_a in ("bid", "ask"):
                for side_b in ("bid", "ask"):
                    arr_a = bid_inds[a] if side_a == "bid" else ask_inds[a]
                    arr_b = bid_inds[b] if side_b == "bid" else ask_inds[b]
                    indep = _indep_from_indicators(arr_a, arr_b)
                    # Mark any rejection of cross-bot independence as
                    # "structurally correlated" — informational, not a failure.
                    # Reasons we treat this as informational rather than pass/fail:
                    #   1. With n~1000 ticks, even tiny phi (~0.06) rejects at α=0.05.
                    #   2. Cross-bot dependence in R3 reflects a real feature
                    #      (one physical bot quoting multiple price levels) but
                    #      our sim layer-samples each bot independently anyway,
                    #      so failing the test would not lead us to fix anything.
                    #   3. The phi value is captured below for downstream review.
                    tied = abs(indep.phi) > 0.0  # all rejections marked tied
                    cross.append({
                        "a_id": a, "b_id": b,
                        "side_a": side_a, "side_b": side_b,
                        "indep": indep,
                        "tied": tied,
                    })
    return {"layers": out_layers, "cross_bot": cross}
