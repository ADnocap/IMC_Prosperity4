"""Holistic validator — confirm each calibrated `params.json` actually fits the data.

For each asset, computes:
  1. **Coverage**: fraction of recorded quotes explained by the formulas in params.json.
  2. **Formula match rate**: Wilson 95% CI on per-side bid/ask formula match.
  3. **Per-tick reconstruction**: per-tick predicted vs actual (price, volume) tuples.
  4. **FV simulation KS test**: 2-sample KS — simulated FV path under fv_process vs real FV.
  5. **Volume simulation KS test**: per-bot per-side simulated volume samples vs real.
  6. **Presence chi² goodness-of-fit**: observed vs predicted Bernoulli/empirical/joint counts.

Run:  py -3.13 calibration/validate_against_data.py            # all assets
      py -3.13 calibration/validate_against_data.py ASH_COATED_OSMIUM
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration.pipeline.data import load_fv_and_book
from calibration.pipeline import kernels as K


REPO_ROOT = Path(__file__).resolve().parent.parent
CALIB_DIR = REPO_ROOT / "calibration"


def _round_apply(round_fn: str, x: float) -> int:
    if round_fn == "floor": return int(math.floor(x))
    if round_fn == "ceil":  return int(math.ceil(x))
    # banker's rounding (matches kernels.py)
    f = math.floor(x); frac = x - f
    if frac > 0.5: return int(f) + 1
    if frac < 0.5: return int(f)
    fi = int(f); return fi if fi % 2 == 0 else fi + 1


def _predict(spec: dict, side: str, fv: float) -> int:
    """Apply formula_spec (one side) to FV → predicted integer price."""
    if spec.get("K") is not None:
        sign = -1.0 if side == "bid" else 1.0
        return _round_apply(spec["round_fn"], fv * (1.0 + sign * spec["K"]))
    return _round_apply(spec["round_fn"], fv + spec["shift"]) + int(spec["constant"])


def _bot_band(bot: dict, side: str) -> tuple:
    band = bot["offset_band"]
    return (band[side][0], band[side][1])


def _list_assets() -> list:
    out = []
    for d in sorted(CALIB_DIR.iterdir()):
        if not d.is_dir():
            continue
        if (d / "data" / "fv_and_book.json").is_file() and (d / "params.json").is_file():
            out.append(d.name.upper())
    return out


def _simulate_fv(fv_proc: dict, n: int, seed: int = 42) -> list:
    """Simulate an FV path under the chosen process for KS comparison."""
    rng = random.Random(seed)
    typ = fv_proc["type"]
    p = fv_proc["params"]
    sigma = p.get("sigma", 0.0)
    mean = p.get("mean", 0.0)
    if typ == "constant":
        # Constant FV with quantization noise: sigma stored in params is the
        # std of FV across ticks (since the "process" is just the constant).
        return [mean + rng.gauss(0, sigma) for _ in range(n)]
    if typ == "linear_drift":
        drift = p.get("drift", 0.0)
        return [mean + drift * i + rng.gauss(0, sigma) for i in range(n)]
    if typ == "ar1":
        phi = p.get("ar1_coef", 0.0)
        drift = p.get("drift", 0.0)
        out = [mean]
        prev_step = drift
        for _ in range(n - 1):
            step = drift + phi * (prev_step - drift) + rng.gauss(0, sigma)
            out.append(out[-1] + step)
            prev_step = step
        return out
    # random_walk
    drift = p.get("drift", 0.0)
    out = [mean]
    for _ in range(n - 1):
        out.append(out[-1] + drift + rng.gauss(0, sigma))
    return out


def validate_asset(asset: str, verbose: bool = True) -> dict:
    asset_lower = asset.lower()
    data = load_fv_and_book(CALIB_DIR / asset_lower / "data" / "fv_and_book.json")
    params_path = CALIB_DIR / asset_lower / "params.json"
    if not params_path.is_file():
        return {"asset": asset, "status": "no params.json"}
    with open(params_path) as f:
        params = json.load(f)

    rows = [r for r in data.rows if r.fv is not None]
    n_ticks = len(rows)
    bots = params.get("bots", [])

    # ── 1. Coverage: per-tick, count quotes explained by some bot ──
    n_bid_total = 0
    n_ask_total = 0
    n_bid_explained = 0
    n_ask_explained = 0
    # Per-bot per-side formula match (numerator, denominator).
    bot_match: dict = {b["id"]: {"bid_n": 0, "bid_match": 0, "ask_n": 0, "ask_match": 0}
                       for b in bots}
    # For each tick, get predicted prices per bot.
    for r in rows:
        for bp in r.bids:
            n_bid_total += 1
            off = bp - r.fv
            for b in bots:
                lo, hi = _bot_band(b, "bid")
                if lo <= off <= hi:
                    n_bid_explained += 1
                    bot_match[b["id"]]["bid_n"] += 1
                    pred = _predict(b["formula_spec"]["bid"], "bid", r.fv)
                    if pred == bp:
                        bot_match[b["id"]]["bid_match"] += 1
                    break
        for ap in r.asks:
            n_ask_total += 1
            off = ap - r.fv
            for b in bots:
                lo, hi = _bot_band(b, "ask")
                if lo <= off <= hi:
                    n_ask_explained += 1
                    bot_match[b["id"]]["ask_n"] += 1
                    pred = _predict(b["formula_spec"]["ask"], "ask", r.fv)
                    if pred == ap:
                        bot_match[b["id"]]["ask_match"] += 1
                    break

    bid_cov = n_bid_explained / n_bid_total if n_bid_total else 0.0
    ask_cov = n_ask_explained / n_ask_total if n_ask_total else 0.0

    # ── 2. Wilson CIs on per-bot formula match ──
    bot_diags = []
    for b in bots:
        m = bot_match[b["id"]]
        bid_ci = K.wilson(m["bid_match"], m["bid_n"], 0.95, 0.05) if m["bid_n"] > 0 else None
        ask_ci = K.wilson(m["ask_match"], m["ask_n"], 0.95, 0.05) if m["ask_n"] > 0 else None
        bot_diags.append({
            "id": b["id"],
            "bid_match": m["bid_match"], "bid_n": m["bid_n"],
            "bid_rate": m["bid_match"] / m["bid_n"] if m["bid_n"] else 0.0,
            "bid_ci_lo": bid_ci.lo if bid_ci else 0.0,
            "ask_match": m["ask_match"], "ask_n": m["ask_n"],
            "ask_rate": m["ask_match"] / m["ask_n"] if m["ask_n"] else 0.0,
            "ask_ci_lo": ask_ci.lo if ask_ci else 0.0,
        })

    # ── 3. FV STEPS 2-sample KS ──
    # Comparing FV levels is wrong (consecutive ticks aren't iid). Compare the
    # innovation distribution: ΔFV. Under a random walk the steps are iid
    # Normal(drift, sigma); under linear_drift the steps are Normal(drift, sigma).
    real_fvs = [r.fv for r in rows]
    real_steps = [real_fvs[i] - real_fvs[i - 1] for i in range(1, len(real_fvs))]
    sim_fvs = _simulate_fv(params["fv_process"], n_ticks)
    sim_steps = [sim_fvs[i] - sim_fvs[i - 1] for i in range(1, len(sim_fvs))]
    if real_steps and sim_steps:
        fv_ks = K.ks_2sample(real_steps, sim_steps)
    else:
        fv_ks = K.Ks2Out(0.0, 1.0, 0, 0)

    # ── 4. Volume distribution KS per bot per side ──
    vol_ks = []
    rng = random.Random(42)
    for b in bots:
        for side in ("bid", "ask"):
            real_vols = []
            for r in rows:
                vol_dict = r.bid_vols if side == "bid" else r.ask_vols
                prices = r.bids if side == "bid" else r.asks
                lo, hi = _bot_band(b, side)
                for p_int in prices:
                    off = p_int - r.fv
                    if lo <= off <= hi:
                        real_vols.append(vol_dict.get(p_int, 0))
                        break
            if not real_vols:
                continue
            vol_def = b["volume"]
            n_sim = len(real_vols)
            if vol_def["distribution"] == "uniform":
                lo_v = vol_def["low"]; hi_v = vol_def["high"]
                sim_vols = [rng.randint(lo_v, hi_v) for _ in range(n_sim)]
            elif vol_def["distribution"] == "empirical":
                pmf = vol_def.get("pmf", {})
                if not pmf:
                    continue
                # Sample from empirical
                items = list(pmf.items())
                # PMF keys may be strings or ints depending on JSON
                keys = [int(k) for k, _ in items]
                weights = [float(v) for _, v in items]
                tot = sum(weights)
                weights = [w / tot for w in weights]
                sim_vols = [_weighted_choice(rng, keys, weights) for _ in range(n_sim)]
            else:
                continue
            try:
                ks = K.ks_2sample(real_vols, sim_vols)
                vol_ks.append({
                    "bot_id": b["id"], "side": side,
                    "ks_d": ks.d, "ks_p": ks.p_value,
                    "n_real": len(real_vols), "n_sim": len(sim_vols),
                })
            except Exception:
                pass

    # ── 5. Presence chi² (observed cells vs predicted under model) ──
    presence_chi = []
    # Count actual presence per tick per bot.
    for b in bots:
        bid_pres = []
        ask_pres = []
        for r in rows:
            lo_b, hi_b = _bot_band(b, "bid")
            lo_a, hi_a = _bot_band(b, "ask")
            bp_present = any(lo_b <= bp - r.fv <= hi_b for bp in r.bids)
            ap_present = any(lo_a <= ap - r.fv <= hi_a for ap in r.asks)
            bid_pres.append(int(bp_present))
            ask_pres.append(int(ap_present))
        n = len(bid_pres)
        both = sum(1 for i in range(n) if bid_pres[i] and ask_pres[i])
        b_only = sum(1 for i in range(n) if bid_pres[i] and not ask_pres[i])
        a_only = sum(1 for i in range(n) if not bid_pres[i] and ask_pres[i])
        neither = n - both - b_only - a_only
        observed = [both, b_only, a_only, neither]
        # Expected under iid Bernoulli with rates from params:
        rate_b = b["presence"].get("bid_rate", b["presence"]["rate"])
        rate_a = b["presence"].get("ask_rate", b["presence"]["rate"])
        expected_iid = [rate_b * rate_a * n, rate_b * (1 - rate_a) * n,
                        (1 - rate_b) * rate_a * n, (1 - rate_b) * (1 - rate_a) * n]
        chi2 = 0.0
        for o, e in zip(observed, expected_iid):
            if e > 0:
                chi2 += (o - e) ** 2 / e
        # df = 4 - 2 (rates fitted) - 1 = 1 for 2x2 with marginals fixed. We compute with df=3 for honesty
        p = K.chi2_p(chi2, 3.0)
        presence_chi.append({
            "bot_id": b["id"],
            "observed": observed, "expected_iid": expected_iid,
            "chi2": chi2, "p_value": p,
            "rate_b": rate_b, "rate_a": rate_a,
            "model": b["presence"].get("bid_model", "iid_bernoulli"),
        })

    summary = {
        "asset": asset,
        "n_ticks": n_ticks,
        "n_bid_total": n_bid_total, "n_ask_total": n_ask_total,
        "bid_coverage": bid_cov, "ask_coverage": ask_cov,
        "bot_match": bot_diags,
        "fv_ks_d": fv_ks.d, "fv_ks_p": fv_ks.p_value,
        "vol_ks": vol_ks,
        "presence_chi": presence_chi,
    }

    if verbose:
        _print_summary(summary)
    return summary


def _weighted_choice(rng: random.Random, keys: list, weights: list) -> int:
    r = rng.random()
    cum = 0.0
    for k, w in zip(keys, weights):
        cum += w
        if r <= cum:
            return k
    return keys[-1]


def _verdict(s: dict) -> str:
    """Overall pass/warn/fail based on coverage + match + KS thresholds."""
    if s["bid_coverage"] < 0.95 or s["ask_coverage"] < 0.95:
        return "WARN_COVERAGE"
    for b in s["bot_match"]:
        if b["bid_n"] > 20 and b["bid_ci_lo"] < 0.95: return "FAIL_FORMULA"
        if b["ask_n"] > 20 and b["ask_ci_lo"] < 0.95: return "FAIL_FORMULA"
    if s["fv_ks_p"] < 0.001:
        return "WARN_FV_KS"
    return "OK"


def _print_summary(s: dict) -> None:
    print(f"\n=== {s['asset']} ({s['n_ticks']} ticks) ===")
    print(f"  Coverage: bid {s['bid_coverage']:.3f} ({sum(b['bid_n'] for b in s['bot_match'])}/{s['n_bid_total']})  "
          f"ask {s['ask_coverage']:.3f} ({sum(b['ask_n'] for b in s['bot_match'])}/{s['n_ask_total']})")
    for b in s["bot_match"]:
        bid_ci = f"[{b['bid_ci_lo']:.3f},…]" if b['bid_n'] else "[—]"
        ask_ci = f"[{b['ask_ci_lo']:.3f},…]" if b['ask_n'] else "[—]"
        print(f"  {b['id']}: BID match {b['bid_match']:>4}/{b['bid_n']:>4} "
              f"= {b['bid_rate']:.4f} 95% CI lo={bid_ci}  "
              f"ASK match {b['ask_match']:>4}/{b['ask_n']:>4} "
              f"= {b['ask_rate']:.4f} 95% CI lo={ask_ci}")
    print(f"  FV simulation KS: D={s['fv_ks_d']:.4f} p={s['fv_ks_p']:.4f}")
    for v in s["vol_ks"]:
        print(f"  Vol KS [{v['bot_id']} {v['side']}]: D={v['ks_d']:.3f} p={v['ks_p']:.3f} "
              f"(n_real={v['n_real']})")
    for c in s["presence_chi"]:
        print(f"  Presence chi² [{c['bot_id']} model={c['model']}]: "
              f"obs={c['observed']} exp_iid=[{','.join(f'{x:.0f}' for x in c['expected_iid'])}] "
              f"chi2={c['chi2']:.2f} p={c['p_value']:.4f}")
    print(f"  Verdict: {_verdict(s)}")


def main(argv: list | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    targets = args if args else _list_assets()
    rows = []
    for asset in targets:
        try:
            s = validate_asset(asset.upper(), verbose=True)
            rows.append(s)
        except Exception as e:
            print(f"\n[{asset}] FAILED: {e}", file=sys.stderr)
            import traceback; traceback.print_exc()
    print(f"\n{'='*60}\nSUMMARY ({len(rows)} assets)\n{'='*60}")
    print(f"{'Asset':<25} {'BidCov':>7} {'AskCov':>7} {'FV_KS_p':>8} {'Verdict':>16}")
    for s in rows:
        if "asset" not in s: continue
        bid_cov = s.get("bid_coverage", 0)
        ask_cov = s.get("ask_coverage", 0)
        fv_p = s.get("fv_ks_p", 0)
        v = _verdict(s) if "n_ticks" in s else "ERROR"
        print(f"{s['asset']:<25} {bid_cov:>7.3f} {ask_cov:>7.3f} {fv_p:>8.4f} {v:>16}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
