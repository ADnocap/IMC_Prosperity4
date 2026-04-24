"""Stage 6 — trade bot model.

Port of visualizer/src/pages/calibration/stages/trade_bot.ts.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import kernels as K
from .data import FvAndBook


def _poisson_pmf(k: int, lam: float) -> float:
    if lam < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    log_p = -lam + k * math.log(lam)
    for i in range(2, k + 1):
        log_p -= math.log(i)
    return math.exp(log_p)


def run_stage6(data: FvAndBook) -> dict:
    if not data.trades:
        return {"available": False,
                "reason": "No trades in fv_and_book.json. Re-run extractor with --trades-csv.",
                "stats": None}

    n_ticks = sum(1 for r in data.rows if r.fv is not None)
    trades = data.trades

    per_tick: dict = defaultdict(int)
    for t in trades:
        bucket = (t.ts // 100) * 100
        per_tick[bucket] += 1
    max_k = max(per_tick.values()) if per_tick else 0
    dist = [0] * (max_k + 1)
    non_zero = len(per_tick)
    dist[0] = max(0, n_ticks - non_zero)
    for c in per_tick.values():
        dist[c] += 1

    lam = len(trades) / max(1, n_ticks)
    expected_probs = [0.0] * len(dist)
    tail = 1.0
    for k in range(len(dist) - 1):
        expected_probs[k] = _poisson_pmf(k, lam)
        tail -= expected_probs[k]
    expected_probs[-1] = max(0.0, tail)
    gof = K.chi2_gof(dist, expected_probs)

    qtys = [t.quantity for t in trades]
    q_min = min(qtys) if qtys else 0
    q_max = max(qtys) if qtys else 0
    q_mean = sum(qtys) / len(qtys) if qtys else 0
    q_map: dict = defaultdict(int)
    for q in qtys:
        q_map[q] += 1
    q_hist = [{"qty": q, "count": q_map[q]} for q in sorted(q_map)]
    q_uniform = (K.chi2_uniform(qtys, q_min, q_max)
                 if (len(qtys) >= 30 and q_max > q_min) else None)

    cp_map: dict = {}
    for t in trades:
        for label, name in (("buyer", t.buyer), ("seller", t.seller)):
            if not name:
                continue
            entry = cp_map.setdefault(name, {"buys": 0, "sells": 0, "qty_sum": 0, "qty_n": 0})
            if label == "buyer":
                entry["buys"] += 1
            else:
                entry["sells"] += 1
            entry["qty_sum"] += t.quantity
            entry["qty_n"] += 1
    counterparties = []
    for name, v in sorted(cp_map.items(), key=lambda kv: -(kv[1]["buys"] + kv[1]["sells"])):
        counterparties.append({
            "name": name, "buys": v["buys"], "sells": v["sells"],
            "mean_qty": v["qty_sum"] / v["qty_n"] if v["qty_n"] > 0 else 0,
        })

    return {
        "available": True, "reason": None,
        "stats": {
            "n_trades": len(trades), "n_ticks": n_ticks,
            "rate_per_tick": lam,
            "count_hist": [{"k": k, "observed": dist[k],
                            "expected_poisson": expected_probs[k] * n_ticks}
                           for k in range(len(dist))],
            "poisson_gof": gof,
            "qty_hist": q_hist,
            "qty_min": q_min, "qty_max": q_max, "qty_mean": q_mean,
            "qty_uniform_gof": q_uniform,
            "counterparties": counterparties,
        },
    }
