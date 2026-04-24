"""Stage 2 — formula discovery.

Port of visualizer/src/pages/calibration/stages/formula_discovery.ts.
"""
from __future__ import annotations

from . import kernels as K
from .stage1_layers import DetectedLayer, Quote


def _quotes_for_layer(quotes: list, layer: DetectedLayer, side: str) -> list:
    band = layer.offset_band["bid"] if side == "bid" else layer.offset_band["ask"]
    return [q for q in quotes if q.side == side and band[0] <= q.offset <= band[1]]


def _search_side(qs: list, side_sign: int, k_guess: float, use_wide: bool) -> K.FormulaSearchOut:
    fvs = [q.fv for q in qs]
    prices = [q.price for q in qs]
    const_lo = -15 if side_sign < 0 else 1
    const_hi = -1 if side_sign < 0 else 15
    # Always sweep [0, 2e-2] wide. The original visualizer narrowed around
    # Stage 1's OLS k_guess, but that's unreliable on integer-quantized
    # offsets — Stage 1 underestimated K=0.01 on VEV_4000, narrow search
    # then missed the true value. Wide sweep at 600 steps gives Δk = 3.3e-5,
    # enough resolution to land on K=0.001 and K=0.01 alike.
    res = K.formula_search(fvs, prices, side_sign, const_lo, const_hi,
                           0.0, 2e-2, 600, top_n=10)
    # If a k_guess was provided, also do a refined search around it and
    # merge results — important when K sits near a round value the wide
    # grid happens to skip.
    if k_guess > 0 and not use_wide:
        spread = max(k_guess * 0.25, 1e-4)
        refined = K.formula_search(
            fvs, prices, side_sign, const_lo, const_hi,
            max(0.0, k_guess - spread), k_guess + spread, 400, top_n=10,
        )
        # Merge top-N proportional candidates by CV (keeping wide's fixed_top).
        merged = (res.proportional_top + refined.proportional_top)
        merged.sort(key=lambda c: -c.cv_match_rate)
        res.proportional_top = merged[:10]
    return res


def _pick_winner(result: K.FormulaSearchOut) -> tuple:
    fixed_best = result.fixed_top[0] if result.fixed_top else None
    prop_best = result.proportional_top[0] if result.proportional_top else None
    if not fixed_best and not prop_best:
        raise ValueError("formula search returned no candidates")
    if not fixed_best:
        return (prop_best, "proportional")
    if not prop_best:
        return (fixed_best, "fixed")
    fixed_spread = max(fixed_best.fv_decile_match) - min(fixed_best.fv_decile_match)
    prop_spread = max(prop_best.fv_decile_match) - min(prop_best.fv_decile_match)
    cv_gap = prop_best.cv_match_rate - fixed_best.cv_match_rate
    # If proportional clearly dominates on CV (>= 1% margin), pick it regardless
    # of decile-spread shape — the original "spread must be flatter" guard was
    # designed to prevent fixed→prop overfitting on narrow-FV-range data, but
    # it backfires when proportional really is the right family and integer
    # quantization noise gives a less-flat decile profile (observed on VEV_4000).
    if cv_gap >= 0.01:
        return (prop_best, "proportional")
    # If only marginally better on CV (0.5-1%), require flatter spread.
    if cv_gap > 0.005 and prop_spread < fixed_spread:
        return (prop_best, "proportional")
    return (fixed_best, "fixed")


def _refit_symmetric_proportional(
    bid_res: K.FormulaSearchOut, ask_res: K.FormulaSearchOut,
    bid_qs: list, ask_qs: list,
    bid_fam: str, ask_fam: str,
) -> tuple:
    """When BOTH sides land on a proportional family, prefer the canonical
    symmetric pair: floor(fv*(1-K)) for bid + ceil(fv*(1+K)) for ask, same K.

    Searches the top-N of both sides for the highest-CV (K_bid, K_ask) pair
    that satisfies (round_bid='floor', round_ask='ceil', |K_bid - K_ask| <= eps).
    If the symmetric pair is within 0.5% CV of the asymmetric winner, swap.

    HYDROGEL_PACK is the motivating case: pipeline picks floor/floor with
    K=0.001/K=0.0011 (CV 1.000/0.998); the canonical floor/ceil with K=0.001
    fits both sides at 100%.
    """
    if bid_fam != "proportional" or ask_fam != "proportional":
        return None
    asym_bid_cv = bid_res.proportional_top[0].cv_match_rate
    asym_ask_cv = ask_res.proportional_top[0].cv_match_rate
    asym_avg = (asym_bid_cv + asym_ask_cv) / 2

    best = None
    for cb in bid_res.proportional_top:
        if cb.round_fn != "floor":
            continue
        for ca in ask_res.proportional_top:
            if ca.round_fn != "ceil":
                continue
            # Same K within reasonable tolerance (the search grid is finite).
            if abs(cb.k - ca.k) > max(cb.k, ca.k, 1e-6) * 0.05:
                continue
            avg = (cb.cv_match_rate + ca.cv_match_rate) / 2
            if best is None or avg > best[2]:
                best = (cb, ca, avg)
    if best is None:
        return None
    sym_bid, sym_ask, sym_avg = best
    if sym_avg >= asym_avg - 0.005:
        return (sym_bid, sym_ask)
    return None


def run_stage2(layers: list, quotes: list) -> dict:
    bots = []
    for L in layers:
        bid_qs = _quotes_for_layer(quotes, L, "bid")
        ask_qs = _quotes_for_layer(quotes, L, "ask")
        if len(bid_qs) < 20 or len(ask_qs) < 20:
            continue
        k_guess = L.k_estimate if L.offset_type == "proportional" else 0.0
        bid_res = _search_side(bid_qs, -1, k_guess, L.offset_type == "fixed")
        ask_res = _search_side(ask_qs, 1, k_guess, L.offset_type == "fixed")
        w_bid, fam_bid = _pick_winner(bid_res)
        w_ask, fam_ask = _pick_winner(ask_res)
        sym = _refit_symmetric_proportional(bid_res, ask_res, bid_qs, ask_qs, fam_bid, fam_ask)
        if sym is not None:
            w_bid, w_ask = sym
        bots.append({
            "layer_id": L.id, "layer_name": L.name,
            "bid": bid_res, "ask": ask_res,
            "winner_bid": w_bid, "winner_ask": w_ask,
            "winner_bid_family": fam_bid,
            "winner_ask_family": fam_ask,
        })
    return {"bots": bots}


def winner_to_formula_spec(cand, family: str) -> dict:
    if family == "fixed":
        return {"round_fn": cand.round_fn, "shift": cand.shift,
                "constant": cand.constant, "K": None}
    return {"round_fn": cand.round_fn, "shift": 0.0, "constant": 0, "K": cand.k}


def formula_string(spec: dict, side: str) -> str:
    if spec["K"] is None:
        sh = spec["shift"]
        if sh == 0:
            shift_s = "fv"
        else:
            sign = "+" if sh >= 0 else "-"
            shift_s = f"fv {sign} {abs(sh)}"
        c = spec["constant"]
        c_s = "" if c == 0 else f" {'+' if c >= 0 else '-'} {abs(c)}"
        return f"{spec['round_fn']}({shift_s}){c_s}"
    sign = "-" if side == "bid" else "+"
    k = spec["K"]
    return f"{spec['round_fn']}(fv * (1 {sign} {k:.4e}))"


def layers_to_bot_specs(layers: list, stage2: dict) -> list:
    bots = []
    layer_by_id = {L.id: L for L in layers}
    for b in stage2["bots"]:
        L = layer_by_id[b["layer_id"]]
        bid_spec = winner_to_formula_spec(b["winner_bid"], b["winner_bid_family"])
        ask_spec = winner_to_formula_spec(b["winner_ask"], b["winner_ask_family"])
        offset_type = ("proportional"
                       if b["winner_bid_family"] == "proportional" or b["winner_ask_family"] == "proportional"
                       else "fixed")
        bots.append({
            "id": b["layer_id"],
            "name": L.name,
            "offset_type": offset_type,
            "bid_formula_str": formula_string(bid_spec, "bid"),
            "ask_formula_str": formula_string(ask_spec, "ask"),
            "formula_spec": {"bid": bid_spec, "ask": ask_spec},
            "volume": {"distribution": "uniform", "low": 0, "high": 0, "sides_tied": True},
            "presence": {"rate": 0.8, "iid": True, "bid_ask_independent": True},
            "offset_band": {
                "bid": [float(L.offset_band["bid"][0]), float(L.offset_band["bid"][1])],
                "ask": [float(L.offset_band["ask"][0]), float(L.offset_band["ask"][1])],
            },
        })
    return bots
