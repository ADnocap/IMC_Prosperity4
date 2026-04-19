"""OSMIUM ML experiment.

Target: sign(FV_{t+50} - FV_t) ∈ {-1, 0, +1}. Drop 0 for binary logistic.
Features: book state + short-horizon FV lags + position-agnostic state.
CV: 6-fold leave-one-day-out. If median AUC < 0.55, report and stop.

Usage:
    py -3.13 analysis/round1/osmium_ml.py
"""
from __future__ import annotations
import csv
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
R1 = ROOT / "data" / "prosperity4" / "round1"
R2 = ROOT / "data" / "prosperity4" / "round2"

# (directory, round, day) — 6 days total
DAYS = [
    (R1, 1, -2), (R1, 1, -1), (R1, 1, 0),
    (R2, 2, -1), (R2, 2, 0), (R2, 2, 1),
]

SYMBOL = "ASH_COATED_OSMIUM"
HORIZON = 50  # ticks; 1 tick = 100 timestamp units


# --------------------------------------------------------------------- loaders

def load_books(dir_, rnd, day):
    path = dir_ / f"prices_round_{rnd}_day_{day}.csv"
    out = []
    with path.open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["product"] != SYMBOL:
                continue
            def i(k):
                v = r[k]
                return int(v) if v not in (None, "") else None
            def iv(k):
                v = r[k]
                return int(v) if v not in (None, "") else 0
            out.append({
                "ts": int(r["timestamp"]),
                "bp1": i("bid_price_1"), "bv1": iv("bid_volume_1"),
                "bp2": i("bid_price_2"), "bv2": iv("bid_volume_2"),
                "bp3": i("bid_price_3"), "bv3": iv("bid_volume_3"),
                "ap1": i("ask_price_1"), "av1": iv("ask_volume_1"),
                "ap2": i("ask_price_2"), "av2": iv("ask_volume_2"),
                "ap3": i("ask_price_3"), "av3": iv("ask_volume_3"),
            })
    return out


# ----------------------------------------------------------- FV reconstruction
# Mirrors v20._fv. Must be deterministic and order-preserving so features match
# what the live trader sees.

def fv_from_book(b, prev_fv):
    bids = [(b["bp1"], b["bv1"]), (b["bp2"], b["bv2"]), (b["bp3"], b["bv3"])]
    asks = [(b["ap1"], b["av1"]), (b["ap2"], b["av2"]), (b["ap3"], b["av3"])]
    bids = [(p, v) for p, v in bids if p is not None]
    asks = [(p, v) for p, v in asks if p is not None]

    if not bids and not asks:
        return prev_fv

    # Symmetric book with Bot2-sized L1
    if bids and asks and (asks[0][0] - bids[0][0]) == 16:
        bv1 = bids[0][1]
        av1 = asks[0][1]
        if 10 <= bv1 <= 15 and 10 <= av1 <= 15:
            return (bids[0][0] + asks[0][0]) / 2

    # Bot1 anchors (vol 20-30)
    bot1_bid = next((p for p, v in bids if 20 <= v <= 30), None)
    bot1_ask = next((p for p, v in asks if 20 <= v <= 30), None)

    if bot1_bid is not None and bot1_ask is not None:
        return (bot1_bid + bot1_ask) / 2

    if bot1_bid is not None and prev_fv is not None:
        return 0.3 * (bot1_bid + 10.5) + 0.7 * prev_fv
    if bot1_ask is not None and prev_fv is not None:
        return 0.3 * (bot1_ask - 10.5) + 0.7 * prev_fv

    if prev_fv is not None:
        return prev_fv

    if bids and asks:
        return (bids[0][0] + asks[0][0]) / 2
    if bids:
        return bids[0][0] + 10.5
    return asks[0][0] - 10.5


# -------------------------------------------------------------------- features

FEATURE_NAMES = [
    # center_dist dropped on purpose — the OU pull in the live trader already
    # exploits that signal. We want the ML model to learn the RESIDUAL alpha.
    "ret1",              # fv_r(t) - fv_r(t-1)
    "ret5",              # fv_r(t) - fv_r(t-5)
    "ret20",             # fv_r(t) - fv_r(t-20)
    "bid_gap",           # bp1 - bp2 (0 if missing)
    "ask_gap",           # ap2 - ap1 (0 if missing)
    "l2_gap_sign",       # +1 if (2,3), -1 if (3,2), 0 otherwise
    "spread",            # ap1 - bp1
    "obi",               # (bv1 - av1) / (bv1 + av1)
    "log_l1_vol",        # log(1 + bv1 + av1)
]


def build_features_labels(books):
    n = len(books)

    # Precompute FV sequence with previous-FV fallback
    fvs = []
    prev = None
    for b in books:
        fv = fv_from_book(b, prev)
        fvs.append(fv)
        if fv is not None:
            prev = fv

    fv_r = np.array([int(round(x)) if x is not None else 0 for x in fvs], dtype=np.float64)

    # Skip rows where we don't have valid history or lookahead
    start = 20
    end = n - HORIZON

    X = []
    y = []
    meta_ts = []

    for t in range(start, end):
        if fvs[t] is None or fvs[t-1] is None or fvs[t-5] is None or fvs[t-20] is None:
            continue
        if fvs[t + HORIZON] is None:
            continue

        b = books[t]
        fr = fv_r[t]

        ret1 = fr - fv_r[t-1]
        ret5 = fr - fv_r[t-5]
        ret20 = fr - fv_r[t-20]

        bp1 = b["bp1"] or 0
        bp2 = b["bp2"] or 0
        ap1 = b["ap1"] or 0
        ap2 = b["ap2"] or 0
        bv1 = b["bv1"]
        av1 = b["av1"]

        bid_gap = (bp1 - bp2) if (bp1 and bp2) else 0
        ask_gap = (ap2 - ap1) if (ap1 and ap2) else 0

        if bid_gap == 2 and ask_gap == 3:
            l2_sign = 1
        elif bid_gap == 3 and ask_gap == 2:
            l2_sign = -1
        else:
            l2_sign = 0

        spread = (ap1 - bp1) if (ap1 and bp1) else 16
        total = bv1 + av1
        obi = (bv1 - av1) / total if total > 0 else 0.0
        log_l1 = math.log1p(total)

        # Label: sign of FV_{t+H} - FV_t (using rounded FV to match live rounding)
        future = fv_r[t + HORIZON]
        diff = future - fr
        if diff > 0:
            lbl = 1
        elif diff < 0:
            lbl = -1
        else:
            lbl = 0

        X.append([ret1, ret5, ret20, bid_gap, ask_gap,
                  l2_sign, spread, obi, log_l1])
        y.append(lbl)
        meta_ts.append(b["ts"])

    return np.array(X, dtype=np.float64), np.array(y, dtype=np.int8), np.array(meta_ts, dtype=np.int64)


# ------------------------------------------------------------------- LR (numpy)

def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(X, y, reg=1.0, iters=400, lr_init=0.3):
    # y ∈ {0, 1}
    n, d = X.shape
    # Standardize features
    mu = X.mean(0)
    sd = X.std(0) + 1e-9
    Xn = (X - mu) / sd
    w = np.zeros(d)
    b = 0.0
    for it in range(iters):
        z = Xn @ w + b
        p = sigmoid(z)
        grad_w = Xn.T @ (p - y) / n + reg * w / n
        grad_b = (p - y).mean()
        step = lr_init / (1 + it * 0.01)
        w -= step * grad_w
        b -= step * grad_b
    return w, b, mu, sd


def predict_proba(X, w, b, mu, sd):
    Xn = (X - mu) / sd
    return sigmoid(Xn @ w + b)


def auc(y_true, scores):
    # y_true ∈ {0,1}. Simple Mann-Whitney U.
    pos_idx = np.where(y_true == 1)[0]
    neg_idx = np.where(y_true == 0)[0]
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return float("nan")
    pos_scores = scores[pos_idx]
    neg_scores = scores[neg_idx]
    # rank-based AUC
    combined = np.concatenate([pos_scores, neg_scores])
    order = np.argsort(combined)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(combined) + 1)
    rank_sum_pos = ranks[:len(pos_scores)].sum()
    return (rank_sum_pos - len(pos_scores) * (len(pos_scores) + 1) / 2) / (len(pos_scores) * len(neg_scores))


# ------------------------------------------------------------------- main loop

def main():
    print(f"OSMIUM ML — target=sign(FV_t+{HORIZON} - FV_t), {len(DAYS)} days")
    day_data = []
    for dir_, rnd, day in DAYS:
        books = load_books(dir_, rnd, day)
        X, y, ts = build_features_labels(books)
        mask = y != 0
        day_data.append((f"r{rnd}d{day}", X[mask], y[mask], ts[mask]))
        print(f"  r{rnd} day {day:>2}: {len(books)} ticks -> {len(X)} rows, "
              f"{int(mask.sum())} non-flat (up={int((y[mask]==1).sum())}, "
              f"dn={int((y[mask]==-1).sum())})")

    print("\n--- Leave-one-day-out CV ---")
    aucs = []
    accs = []
    all_w, all_b, all_mu, all_sd = [], [], [], []
    for i, (name, Xte, yte, _) in enumerate(day_data):
        Xtr = np.vstack([d[1] for j, d in enumerate(day_data) if j != i])
        ytr = np.concatenate([d[2] for j, d in enumerate(day_data) if j != i])
        # map to {0,1}
        ytr_b = (ytr == 1).astype(np.float64)
        yte_b = (yte == 1).astype(np.float64)

        w, b, mu, sd = fit_logistic(Xtr, ytr_b, reg=1.0, iters=600, lr_init=0.2)
        p = predict_proba(Xte, w, b, mu, sd)
        a = auc(yte_b, p)
        pred = (p >= 0.5).astype(np.float64)
        acc = (pred == yte_b).mean()
        aucs.append(a)
        accs.append(acc)
        all_w.append(w); all_b.append(b); all_mu.append(mu); all_sd.append(sd)
        print(f"  fold {i} test={name}: auc={a:.4f} acc={acc:.4f} n_test={len(yte)}")

    print(f"\n  mean auc={np.mean(aucs):.4f} median={np.median(aucs):.4f}")
    print(f"  mean acc={np.mean(accs):.4f} median={np.median(accs):.4f}")

    # Refit on ALL days for deployment
    Xall = np.vstack([d[1] for d in day_data])
    yall = np.concatenate([d[2] for d in day_data])
    yall_b = (yall == 1).astype(np.float64)
    w, b, mu, sd = fit_logistic(Xall, yall_b, reg=1.0, iters=800, lr_init=0.2)

    print("\n--- Final model (trained on all days) ---")
    print(f"  intercept: {b:.6f}")
    for name, wi, mi, si in zip(FEATURE_NAMES, w, mu, sd):
        print(f"  {name:<14} w={wi:+.4f}  mu={mi:+.3f}  sd={si:.3f}")

    # Compute deployable "raw" coefficients (no standardization) for hardcoding
    # score = b + sum_i w_i * (x_i - mu_i) / sd_i
    #       = (b - sum_i w_i * mu_i / sd_i) + sum_i (w_i / sd_i) * x_i
    w_raw = w / sd
    b_raw = b - float(np.sum(w * mu / sd))

    print("\n--- Deployable raw linear weights (no standardization) ---")
    print(f"  RAW_BIAS = {b_raw:.6f}")
    for name, wi in zip(FEATURE_NAMES, w_raw):
        print(f"  RAW_W['{name}'] = {wi:+.6f}")

    # Save for reuse
    out = ROOT / "analysis" / "round1" / "osmium_ml_weights.npz"
    np.savez(out, w=w, b=b, mu=mu, sd=sd, w_raw=w_raw, b_raw=b_raw,
             feature_names=np.array(FEATURE_NAMES))
    print(f"\nSaved weights to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
