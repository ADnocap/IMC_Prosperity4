"""
Extract true FV and full order book from hold-1-unit submission for Round 1.

Input:  tmp/submission_103017/103017.json
Output: calibration/round1/data/{product}_fv_and_book.json (one per product)

We bought 1 unit of each new product at t=0.
PnL(t) = -buy_price + 1 * server_fv(t), so server_fv = pnl + buy_price.
"""

import json
from pathlib import Path

SUBMISSION = Path(__file__).parents[3] / "tmp" / "submission_103017" / "103017.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with open(SUBMISSION) as f:
    data = json.load(f)

lines = data["activitiesLog"].strip().split("\n")

# Parse all rows, grouped by product
products = {}
for line in lines[1:]:
    cols = line.split(";")
    if len(cols) < 17:
        continue
    ts = int(cols[1])
    prod = cols[2]
    pnl = float(cols[16])

    bids, asks = [], []
    bid_vols, ask_vols = {}, {}
    for i, vi in [(3, 4), (5, 6), (7, 8)]:
        if cols[i]:
            p = int(cols[i])
            v = int(cols[vi])
            bids.append(p)
            bid_vols[p] = v
    for i, vi in [(9, 10), (11, 12), (13, 14)]:
        if cols[i]:
            p = int(cols[i])
            v = int(cols[vi])
            asks.append(p)
            ask_vols[p] = v

    if prod not in products:
        products[prod] = []
    products[prod].append({
        "ts": ts,
        "pnl": pnl,
        "bids": sorted(bids, reverse=True),
        "asks": sorted(asks),
        "bid_vols": bid_vols,
        "ask_vols": ask_vols,
        "mid_price": float(cols[15]),
    })

# Compute FV and save per product
for prod, rows in sorted(products.items()):
    buy_price = rows[0]["asks"][0]  # best ask at t=0
    print(f"\n=== {prod} ===")
    print(f"Buy price: {buy_price}")

    out_rows = []
    for r in rows:
        fv = r["pnl"] + buy_price if r["ts"] > 0 else None
        out_rows.append({
            "ts": r["ts"],
            "fv": fv,
            "bids": r["bids"],
            "asks": r["asks"],
            "bid_vols": r["bid_vols"],
            "ask_vols": r["ask_vols"],
            "mid_price": r["mid_price"],
        })

    fvs = [r["fv"] for r in out_rows if r["fv"] is not None]
    out = {"product": prod, "buy_price": buy_price, "rows": out_rows}
    fname = prod.lower().replace(" ", "_") + "_fv_and_book.json"
    outpath = OUTPUT_DIR / fname
    with open(outpath, "w") as f:
        json.dump(out, f)

    print(f"Wrote {len(out_rows)} rows to {outpath}")
    print(f"FV range: {min(fvs):.4f} to {max(fvs):.4f}")

    # FV step stats
    steps = [fvs[i] - fvs[i - 1] for i in range(1, len(fvs))]
    import statistics
    print(f"FV step: mean={statistics.mean(steps):.6f}  std={statistics.stdev(steps):.6f}")
