"""
Brute-force calibrate bot formulas separately for each day.
Uses PEPPER_ROOT's deterministic FV to test formulas without PnL data.
"""

import csv, math
from pathlib import Path
from collections import Counter, defaultdict

DATA_DIR = Path(__file__).parents[3] / "data" / "prosperity4" / "round1"

PEPPER_FV_START = {-2: 10000, -1: 11000, 0: 12000}


def load_pepper(day):
    fname = DATA_DIR / f"prices_round_1_day_{day}.csv"
    rows = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "INTARIAN_PEPPER_ROOT":
                continue
            ts = int(row["timestamp"])
            bids, asks = [], []
            bid_vols, ask_vols = {}, {}
            for i in [1, 2, 3]:
                bp = row[f"bid_price_{i}"]
                if bp:
                    bp = int(bp)
                    bids.append(bp)
                    bid_vols[bp] = int(row[f"bid_volume_{i}"])
                ap = row[f"ask_price_{i}"]
                if ap:
                    ap = int(ap)
                    asks.append(ap)
                    ask_vols[ap] = int(row[f"ask_volume_{i}"])
            fv = PEPPER_FV_START[day] + 0.1 * (ts / 100)
            rows.append({"ts": ts, "fv": fv, "bids": bids, "asks": asks,
                         "bid_vols": bid_vols, "ask_vols": ask_vols})
    return rows


def std_round(x):
    """Standard rounding (round half up), not banker's."""
    return math.floor(x + 0.5)


def extract_bot_levels(rows, b1_vol_lo, b1_vol_hi, b2_vol_lo, b2_vol_hi):
    """Separate levels by volume range."""
    b1_bids, b1_asks = [], []
    b2_bids, b2_asks = [], []

    for r in rows:
        fv = r["fv"]
        # Sort levels by volume to identify bots
        for bp in r["bids"]:
            vol = r["bid_vols"].get(bp, 0)
            if b1_vol_lo <= vol <= b1_vol_hi:
                b1_bids.append((fv, bp, vol))
            elif b2_vol_lo <= vol <= b2_vol_hi:
                b2_bids.append((fv, bp, vol))
        for ap in r["asks"]:
            vol = r["ask_vols"].get(ap, 0)
            if b1_vol_lo <= vol <= b1_vol_hi:
                b1_asks.append((fv, ap, vol))
            elif b2_vol_lo <= vol <= b2_vol_hi:
                b2_asks.append((fv, ap, vol))

    return b1_bids, b1_asks, b2_bids, b2_asks


def brute_force_formula(data, side="bid"):
    """Find the best formula from a list of (fv, actual_price) pairs."""
    best = (0, "", None)
    results = []

    for rnd_name, rnd_func in [("floor", math.floor), ("ceil", math.ceil),
                                  ("round", round), ("std_round", std_round)]:
        for shift in [x * 0.25 for x in range(-4, 5)]:
            rng = range(-15, -3) if side == "bid" else range(3, 16)
            for offset in rng:
                matches = sum(1 for fv, actual, _ in data
                              if rnd_func(fv + shift) + offset == actual)
                label = f"{rnd_name}(FV+{shift:+.2f}){offset:+d}"
                results.append((matches, label))
                if matches > best[0]:
                    best = (matches, label, None)

    n = len(data)
    results.sort(reverse=True)
    return best, results[:5], n


for day in [-2, -1, 0]:
    rows = load_pepper(day)
    print(f"\n{'=' * 80}")
    print(f"  PEPPER Day {day} — Brute-force formula search ({len(rows)} ticks)")
    print(f"  FV range: {PEPPER_FV_START[day]} → {PEPPER_FV_START[day] + 0.1 * (len(rows)-1):.0f}")
    print(f"{'=' * 80}")

    b1_bids, b1_asks, b2_bids, b2_asks = extract_bot_levels(rows, 15, 25, 8, 12)

    print(f"\n  Bot 1 (vol 15-25): {len(b1_bids)} bids, {len(b1_asks)} asks")
    print(f"  Bot 2 (vol 8-12):  {len(b2_bids)} bids, {len(b2_asks)} asks")

    for label, data, side in [("Bot 1 BID", b1_bids, "bid"), ("Bot 1 ASK", b1_asks, "ask"),
                                ("Bot 2 BID", b2_bids, "bid"), ("Bot 2 ASK", b2_asks, "ask")]:
        if not data:
            print(f"\n  {label}: no data")
            continue
        best, top5, n = brute_force_formula(data, side)
        print(f"\n  {label}: best = {best[1]}  →  {best[0]}/{n} ({best[0]/n*100:.1f}%)")
        for m, f in top5:
            print(f"    {f:<35} {m}/{n} ({m/n*100:.1f}%)")

    # Also check: what's the actual offset distribution?
    print(f"\n  ── Actual offset analysis ──")
    for label, data in [("Bot 1 BID", b1_bids), ("Bot 1 ASK", b1_asks),
                          ("Bot 2 BID", b2_bids), ("Bot 2 ASK", b2_asks)]:
        if not data:
            continue
        offsets = [actual - fv for fv, actual, _ in data]
        binned = Counter(round(o * 2) / 2 for o in offsets)
        top = sorted(binned.items(), key=lambda x: -x[1])[:5]
        print(f"  {label}: mean_off={sum(offsets)/len(offsets):+.2f}  top offsets: {', '.join(f'{o:+.1f}({c})' for o,c in top)}")
