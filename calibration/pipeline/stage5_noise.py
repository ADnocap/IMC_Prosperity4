"""Stage 5 — noise-layer model.

Port of visualizer/src/pages/calibration/stages/noise_layer.ts.
"""
from __future__ import annotations

from collections import defaultdict

from . import kernels as K
from .data import FvAndBook
from .stage1_layers import Stage1Result


def _presence_series(data: FvAndBook, noise_times: set) -> list:
    return [1.0 if r.ts in noise_times else 0.0 for r in data.rows]


def _cv_stats(vs: list) -> K.Chi2Out | None:
    if len(vs) < 10:
        return None
    lo = min(vs); hi = max(vs)
    if hi == lo:
        return None
    return K.chi2_uniform(vs, lo, hi)


def run_stage5(data: FvAndBook, stage1: Stage1Result) -> dict:
    quotes = stage1.noise_quotes
    n_data = sum(1 for r in data.rows if r.fv is not None)

    by_tick: dict = defaultdict(list)
    for q in quotes:
        by_tick[q.ts].append(q)
    n_events = len(by_tick)
    single_sided = 0
    for arr in by_tick.values():
        has_bid = any(q.side == "bid" for q in arr)
        has_ask = any(q.side == "ask" for q in arr)
        if has_bid != has_ask:
            single_sided += 1
    single_sided_rate = single_sided / n_events if n_events > 0 else 0.0

    off_count: dict = defaultdict(int)
    for q in quotes:
        off_count[round(q.price - round(q.fv))] += 1
    offset_hist = [{"offset": o, "count": off_count[o]} for o in sorted(off_count)]

    crossing = []; passive = []
    for q in quotes:
        is_cross = (q.side == "bid" and q.price > q.fv) or (q.side == "ask" and q.price < q.fv)
        (crossing if is_cross else passive).append(q.volume)
    crossing_vol = _cv_stats(crossing)
    passive_vol = _cv_stats(passive)

    run_len = K.run_length_geom(_presence_series(data, set(by_tick.keys())))

    return {
        "stats": {
            "n_events": n_events,
            "presence_rate": n_events / n_data if n_data > 0 else 0,
            "single_sided_rate": single_sided_rate,
            "offset_hist": offset_hist,
            "crossing_frac": (len(crossing) / len(quotes)) if quotes else 0,
            "crossing_n": len(crossing), "passive_n": len(passive),
            "crossing_vol": crossing_vol, "passive_vol": passive_vol,
            "crossing_vol_mean": sum(crossing) / len(crossing) if crossing else 0,
            "passive_vol_mean": sum(passive) / len(passive) if passive else 0,
            "run_length": run_len,
        },
        "quotes": quotes,
    }
