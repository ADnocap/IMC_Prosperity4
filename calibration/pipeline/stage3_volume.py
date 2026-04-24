"""Stage 3 — per-bot volume model.

Port of visualizer/src/pages/calibration/stages/volume_model.ts.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import kernels as K
from .data import FvAndBook
from .stage1_layers import DetectedLayer, Quote


def _quotes_by_tick(quotes: list) -> dict:
    m: dict = defaultdict(list)
    for q in quotes:
        m[q.ts].append(q)
    return m


def _side_quotes(quotes: list, layer: DetectedLayer, side: str) -> list:
    band = layer.offset_band["bid"] if side == "bid" else layer.offset_band["ask"]
    return [q for q in quotes if q.side == side and band[0] <= q.offset <= band[1]]


def _fit_side_uniform(qs: list) -> dict:
    vols = [q.volume for q in qs if math.isfinite(q.volume)]
    if not vols:
        return {
            "min": 0, "max": 0, "mean": 0, "n": 0,
            "uniform": K.Chi2Out(0, 0, 1, 0, [], []),
            "by_offset": [], "best_dist": "empirical", "best_p": 1.0,
            "empirical_pmf": {},
        }
    lo = min(vols); hi = max(vols)
    uni = K.chi2_uniform(vols, lo, hi)

    by_round: dict = defaultdict(list)
    for q in qs:
        by_round[round(q.offset)].append(q.volume)
    by_offset = []
    for off in sorted(by_round):
        vs = by_round[off]
        p = float("nan")
        if len(vs) >= 20 and lo < hi:
            p = K.chi2_uniform(vs, lo, hi).p_value
        by_offset.append({"offset": off, "n": len(vs),
                          "mean": sum(vs) / len(vs), "p_uniform": p})

    # Empirical PMF — always recoverable; we use it as the "model" when the
    # uniform fit fails. Many R3 assets show clearly non-uniform volume
    # distributions (peak in upper end, thin tails) — calling them "uniform"
    # would be wrong; reporting them as empirical is honest.
    from collections import Counter as _C
    counts = _C(vols)
    pmf = {int(v): c / len(vols) for v, c in counts.items()}
    best_dist = "uniform" if uni.p_value > 0.05 else "empirical"
    best_p = uni.p_value if best_dist == "uniform" else 1.0  # empirical fits by construction
    return {
        "min": lo, "max": hi, "n": len(vols),
        "mean": sum(vols) / len(vols),
        "uniform": uni, "by_offset": by_offset,
        "best_dist": best_dist, "best_p": best_p,
        "empirical_pmf": pmf,
    }


def _extract_quotes(data: FvAndBook) -> list:
    out = []
    for r in data.rows:
        if r.fv is None:
            continue
        for bp in r.bids:
            v = r.bid_vols.get(bp, 0)
            out.append(Quote("bid", bp, v, r.fv, bp - r.fv, r.ts))
        for ap in r.asks:
            v = r.ask_vols.get(ap, 0)
            out.append(Quote("ask", ap, v, r.fv, ap - r.fv, r.ts))
    return out


def run_stage3(data: FvAndBook, layers: list) -> dict:
    quotes = _extract_quotes(data)
    tick_map = _quotes_by_tick(quotes)

    out = []
    for L in layers:
        bid_q = _side_quotes(quotes, L, "bid")
        ask_q = _side_quotes(quotes, L, "ask")
        bid = _fit_side_uniform(bid_q)
        ask = _fit_side_uniform(ask_q)

        both_n = same_n = 0
        for ts, arr in tick_map.items():
            b_side = next((q for q in arr if q.side == "bid"
                           and L.offset_band["bid"][0] <= q.offset <= L.offset_band["bid"][1]), None)
            a_side = next((q for q in arr if q.side == "ask"
                           and L.offset_band["ask"][0] <= q.offset <= L.offset_band["ask"][1]), None)
            if b_side and a_side:
                both_n += 1
                if b_side.volume == a_side.volume:
                    same_n += 1
        rate = same_n / both_n if both_n > 0 else 0.0
        lo = min(bid["min"], ask["min"])
        hi = max(bid["max"], ask["max"])
        p_null = 1.0 / (hi - lo + 1) if hi >= lo else 1.0 / 10
        se = math.sqrt(p_null * (1 - p_null) / both_n) if both_n > 0 else 1.0
        z = (rate - p_null) / se if se > 0 else 0.0
        p = K.two_sided_p(z)
        out.append({
            "layer_id": L.id, "layer_name": L.name,
            "bid": bid, "ask": ask,
            "sides_tied_rate": rate, "sides_tied_n": both_n, "sides_tied_p": p,
        })
    return {"layers": out}
