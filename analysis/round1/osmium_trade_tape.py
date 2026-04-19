"""OSMIUM trade-tape analysis.

Angle: we've never used state.market_trades as a feature source. Buyer/seller
fields are empty in Prosperity data, but aggressor direction can be inferred
from trade_price vs L1 bid/ask.

Two-stage probe:
  1. Compute per-tick trade-tape features (aggressor imbalance, recent large
     trades, time-since-trade, etc.) joined to the book state.
  2. Logistic regression on next-50-tick FV sign WITH + WITHOUT trade features.
     Compare AUC. If the trade tape adds > 0.02 AUC residual (beyond center_dist
     + book features), it is worth deploying.
"""
from __future__ import annotations
import csv
import math
from pathlib import Path
from collections import deque

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
R1 = ROOT / "data" / "prosperity4" / "round1"
R2 = ROOT / "data" / "prosperity4" / "round2"

DAYS = [
    (R1, 1, -2), (R1, 1, -1), (R1, 1, 0),
    (R2, 2, -1), (R2, 2, 0), (R2, 2, 1),
]

SYMBOL = "ASH_COATED_OSMIUM"
HORIZON = 50
TICK_STEP = 100  # ts per tick


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


def load_trades(dir_, rnd, day):
    path = dir_ / f"trades_round_{rnd}_day_{day}.csv"
    out = []
    with path.open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["symbol"] != SYMBOL:
                continue
            out.append({
                "ts": int(r["timestamp"]),
                "price": float(r["price"]),
                "qty": int(r["quantity"]),
            })
    return out


# -------------------------------------------------------- FV reconstruction

def fv_from_book(b, prev_fv):
    bids = [(b["bp1"], b["bv1"]), (b["bp2"], b["bv2"]), (b["bp3"], b["bv3"])]
    asks = [(b["ap1"], b["av1"]), (b["ap2"], b["av2"]), (b["ap3"], b["av3"])]
    bids = [(p, v) for p, v in bids if p is not None]
    asks = [(p, v) for p, v in asks if p is not None]
    if not bids and not asks:
        return prev_fv
    if bids and asks and (asks[0][0] - bids[0][0]) == 16:
        bv1 = bids[0][1]; av1 = asks[0][1]
        if 10 <= bv1 <= 15 and 10 <= av1 <= 15:
            return (bids[0][0] + asks[0][0]) / 2
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


# ------------------------------------------------------- aggressor inference

def classify_trade(trade, book):
    """Classify trade aggressor by price vs book L1. Returns (+1, -1, 0)."""
    price = trade["price"]
    ap1 = book["ap1"]
    bp1 = book["bp1"]
    if ap1 is not None and price >= ap1:
        return 1   # buyer-aggressor (hit the ask)
    if bp1 is not None and price <= bp1:
        return -1  # seller-aggressor (hit the bid)
    # Between bid/ask: ambiguous — treat as neutral
    return 0


# --------------------------------------------------------- feature extraction

BOOK_FEATURES = [
    "center_dist", "ret1", "ret5", "ret20",
    "bid_gap", "ask_gap", "l2_gap_sign", "spread", "obi", "log_l1_vol",
]

TAPE_FEATURES = [
    "last_agg",          # +1 / -1 / 0
    "tape_net_5",        # sum of aggressor*qty over last 5 trades
    "tape_net_20",       # sum over last 20 trades
    "tape_abs_dev_5",    # |price - fv| signed by aggressor, last 5 trades
    "trades_in_10t",     # count of trades in last 10 ticks
    "ticks_since_trade", # ticks since last trade (capped at 20)
    "big_trade_flag",    # 1 if any trade qty >= 8 in last 10 ticks
]

ALL_FEATURES = BOOK_FEATURES + TAPE_FEATURES


def build_features(books, trades):
    n = len(books)

    # Index trades by ts for fast lookup
    trades_by_ts = {}
    for t in trades:
        trades_by_ts.setdefault(t["ts"], []).append(t)

    # Precompute FV
    fvs = []
    prev = None
    for b in books:
        fv = fv_from_book(b, prev)
        fvs.append(fv)
        if fv is not None:
            prev = fv
    fv_r_arr = np.array([int(round(x)) if x is not None else 0 for x in fvs], dtype=np.float64)

    # Classify all trades into aggressor signed-size
    trade_events = []  # (ts, aggressor in {-1,0,+1}, qty, price)
    for b in books:
        ts = b["ts"]
        for tr in trades_by_ts.get(ts, []):
            agg = classify_trade(tr, b)
            trade_events.append((ts, agg, tr["qty"], tr["price"]))

    # Rolling buffers keyed by trade sequence
    recent_trades = deque(maxlen=20)  # [(ts, agg, qty, price, fv_at_tick)]

    # Walk ticks in order
    start = 20
    end = n - HORIZON

    X, y, meta = [], [], []

    trade_ptr = 0
    trade_events.sort(key=lambda x: x[0])

    for t in range(n):
        b = books[t]
        ts = b["ts"]
        fr = fv_r_arr[t]

        # Ingest any trades whose ts <= current tick ts (they complete during this tick)
        while trade_ptr < len(trade_events) and trade_events[trade_ptr][0] <= ts:
            tev = trade_events[trade_ptr]
            recent_trades.append((tev[0], tev[1], tev[2], tev[3], fr))
            trade_ptr += 1

        if t < start or t >= end:
            continue
        if fvs[t] is None or fvs[t-1] is None or fvs[t-5] is None or fvs[t-20] is None:
            continue
        if fvs[t + HORIZON] is None:
            continue

        # Book features
        fv_1 = fv_r_arr[t-1]; fv_5 = fv_r_arr[t-5]; fv_20 = fv_r_arr[t-20]
        center_dist = fr - 10000
        ret1 = fr - fv_1; ret5 = fr - fv_5; ret20 = fr - fv_20

        bp1 = b["bp1"] or 0; bp2 = b["bp2"] or 0
        ap1 = b["ap1"] or 0; ap2 = b["ap2"] or 0
        bv1 = b["bv1"]; av1 = b["av1"]

        bid_gap = (bp1 - bp2) if (bp1 and bp2) else 0
        ask_gap = (ap2 - ap1) if (ap1 and ap2) else 0
        if bid_gap == 2 and ask_gap == 3:
            l2_gap_sign = 1
        elif bid_gap == 3 and ask_gap == 2:
            l2_gap_sign = -1
        else:
            l2_gap_sign = 0
        spread = (ap1 - bp1) if (ap1 and bp1) else 16
        total = bv1 + av1
        obi = (bv1 - av1) / total if total > 0 else 0.0
        log_l1 = math.log1p(total)

        # Tape features
        if recent_trades:
            last = recent_trades[-1]
            last_agg = last[1]
            ticks_since = min(20, (ts - last[0]) // TICK_STEP)
        else:
            last_agg = 0
            ticks_since = 20

        last5 = list(recent_trades)[-5:]
        last20 = list(recent_trades)
        tape_net_5 = sum(agg * qty for _, agg, qty, _, _ in last5)
        tape_net_20 = sum(agg * qty for _, agg, qty, _, _ in last20)

        # price deviation signed by aggressor: buyer-agg at high price => +
        tape_abs_dev_5 = 0.0
        for _, agg, qty, pr, fv_at in last5:
            if agg != 0:
                tape_abs_dev_5 += agg * (pr - fv_at)
        # Window: trades in last 10 ticks (ts_now - 10*TICK_STEP)
        cutoff_ts = ts - 10 * TICK_STEP
        trades_in_10t = sum(1 for rt in recent_trades if rt[0] >= cutoff_ts)
        big_trade_flag = 1 if any(qty >= 8 and rt[0] >= cutoff_ts for rt in recent_trades for (_, _, qty, _, _) in [rt]) else 0

        future = fv_r_arr[t + HORIZON]
        diff = future - fr
        if diff > 0:
            lbl = 1
        elif diff < 0:
            lbl = -1
        else:
            lbl = 0

        X.append([
            center_dist, ret1, ret5, ret20,
            bid_gap, ask_gap, l2_gap_sign, spread, obi, log_l1,
            last_agg, tape_net_5, tape_net_20, tape_abs_dev_5,
            trades_in_10t, ticks_since, big_trade_flag,
        ])
        y.append(lbl)
        meta.append(ts)

    return np.array(X, dtype=np.float64), np.array(y, dtype=np.int8), np.array(meta, dtype=np.int64)


# ------------------------------------------------------------------- LR utils

def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(X, y, reg=1.0, iters=600, lr_init=0.2):
    n, d = X.shape
    mu = X.mean(0)
    sd = X.std(0) + 1e-9
    Xn = (X - mu) / sd
    w = np.zeros(d); b = 0.0
    for it in range(iters):
        z = Xn @ w + b
        p = sigmoid(z)
        grad_w = Xn.T @ (p - y) / n + reg * w / n
        grad_b = (p - y).mean()
        step = lr_init / (1 + it * 0.01)
        w -= step * grad_w; b -= step * grad_b
    return w, b, mu, sd


def auc(y_true, scores):
    pos_idx = np.where(y_true == 1)[0]
    neg_idx = np.where(y_true == 0)[0]
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return float("nan")
    combined = np.concatenate([scores[pos_idx], scores[neg_idx]])
    order = np.argsort(combined)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(combined) + 1)
    rank_sum_pos = ranks[:len(pos_idx)].sum()
    return (rank_sum_pos - len(pos_idx) * (len(pos_idx) + 1) / 2) / (len(pos_idx) * len(neg_idx))


def cv_eval(day_data, feat_idx, label):
    aucs = []
    for i, (_, Xte, yte) in enumerate(day_data):
        Xtr = np.vstack([d[1] for j, d in enumerate(day_data) if j != i])
        ytr = np.concatenate([d[2] for j, d in enumerate(day_data) if j != i])
        Xtr_sub = Xtr[:, feat_idx]
        Xte_sub = Xte[:, feat_idx]
        ytr_b = (ytr == 1).astype(np.float64)
        yte_b = (yte == 1).astype(np.float64)
        w, b, mu, sd = fit_logistic(Xtr_sub, ytr_b)
        p = sigmoid(((Xte_sub - mu) / sd) @ w + b)
        aucs.append(auc(yte_b, p))
    return np.array(aucs)


def main():
    print(f"OSMIUM trade-tape analysis — 6 days, H={HORIZON}")
    day_data = []
    trade_stats = []
    for dir_, rnd, day in DAYS:
        books = load_books(dir_, rnd, day)
        trades = load_trades(dir_, rnd, day)
        X, y, _ = build_features(books, trades)
        mask = y != 0
        day_data.append((f"r{rnd}d{day}", X[mask], y[mask]))

        # Aggressor distribution
        classified = [classify_trade(t, {"bp1": None, "ap1": None}) for t in trades]
        buyer_agg = sum(1 for ev in day_data for _ in [0] if False)  # placeholder
        # Re-classify with real books indexed by ts
        book_by_ts = {b["ts"]: b for b in books}
        agg_counts = {1: 0, -1: 0, 0: 0}
        for t in trades:
            agg_counts[classify_trade(t, book_by_ts.get(t["ts"], {"bp1": None, "ap1": None}))] += 1
        print(f"  r{rnd} day {day:>2}: {len(trades)} trades "
              f"(buyer-agg={agg_counts[1]}, seller-agg={agg_counts[-1]}, mid={agg_counts[0]})")
        trade_stats.append(agg_counts)

    # Totals
    total = {k: sum(s[k] for s in trade_stats) for k in (-1, 0, 1)}
    tot = sum(total.values())
    print(f"  TOTAL: {tot} trades — buyer-agg={total[1]} ({total[1]/tot:.1%}), "
          f"seller-agg={total[-1]} ({total[-1]/tot:.1%}), mid={total[0]} ({total[0]/tot:.1%})")

    n_book = len(BOOK_FEATURES)
    n_tape = len(TAPE_FEATURES)
    idx_book = list(range(n_book))
    idx_tape = list(range(n_book, n_book + n_tape))
    idx_all = idx_book + idx_tape

    print("\n--- CV AUC by feature set ---")
    aucs_book = cv_eval(day_data, idx_book, "book-only")
    aucs_all = cv_eval(day_data, idx_all, "book+tape")
    print(f"  book only  ({len(idx_book)} feat): mean AUC={aucs_book.mean():.4f}  per-fold={np.round(aucs_book, 3).tolist()}")
    print(f"  book+tape  ({len(idx_all)} feat): mean AUC={aucs_all.mean():.4f}  per-fold={np.round(aucs_all, 3).tolist()}")
    print(f"  delta = {aucs_all.mean() - aucs_book.mean():+.4f}")

    # Residual: drop center_dist to force tape to fight on its own
    idx_res_book = [i for i in idx_book if BOOK_FEATURES[i] != "center_dist"]
    idx_res_all = idx_res_book + idx_tape
    aucs_rb = cv_eval(day_data, idx_res_book, "res-book")
    aucs_ra = cv_eval(day_data, idx_res_all, "res-book+tape")
    print(f"\n  residual book ({len(idx_res_book)} feat): mean AUC={aucs_rb.mean():.4f}")
    print(f"  residual book+tape ({len(idx_res_all)} feat): mean AUC={aucs_ra.mean():.4f}")
    print(f"  residual delta = {aucs_ra.mean() - aucs_rb.mean():+.4f}")

    # Tape-only
    aucs_tape = cv_eval(day_data, idx_tape, "tape-only")
    print(f"\n  tape only ({len(idx_tape)} feat): mean AUC={aucs_tape.mean():.4f}")

    # Fit final (all days, all features) to see weights
    Xall = np.vstack([d[1] for d in day_data])
    yall = np.concatenate([d[2] for d in day_data])
    yall_b = (yall == 1).astype(np.float64)
    w, b, mu, sd = fit_logistic(Xall, yall_b, iters=800)

    # Convert to raw weights
    w_raw = w / sd
    b_raw = b - float(np.sum(w * mu / sd))

    print("\n--- Full-feature raw weights (trained on all 6 days) ---")
    print(f"  RAW_BIAS = {b_raw:.6f}")
    for name, wi in zip(ALL_FEATURES, w_raw):
        print(f"  RAW_W['{name}'] = {wi:+.6f}")

    out = ROOT / "analysis" / "round1" / "osmium_tape_weights.npz"
    np.savez(out, w_raw=w_raw, b_raw=b_raw, features=np.array(ALL_FEATURES))
    print(f"\nSaved weights to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
