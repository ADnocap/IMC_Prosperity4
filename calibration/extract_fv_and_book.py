"""
Extract true FV and full order book from a hold-1-unit submission log.

Usage:
    py -3.13 extract_fv_and_book.py <submission_id> <product> [--download-dir DIR]
                                   [--trades-csv PATH [--trades-csv PATH ...]]

Input:  ~/Downloads/{submission_id}/  containing {id}.json
Output: calibration/<product_lower>/data/fv_and_book.json

Requires a submission where we buy exactly 1 unit of <product> at t=0 and hold.
PnL(t) = -buy_price + 1 * server_fv(t), so server_fv = pnl + buy_price.

If --trades-csv is given (repeatable), market trades for <product> are merged
into the output JSON under a "trades" key so Stage 6 (trade-bot model) has input.
Trade CSVs are the historical semicolon-delimited files under data/prosperity*/round*/
with columns: timestamp;buyer;seller;symbol;currency;price;quantity.
"""

import csv, json, sys, argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Extract FV and order book from hold-1-unit submission")
parser.add_argument("submission_id", help="Submission ID (folder and JSON name)")
parser.add_argument("product", help="Product symbol (e.g. TOMATOES, ROSES)")
parser.add_argument("--download-dir", default=None,
                    help="Directory containing submission folder (default: ~/Downloads)")
parser.add_argument("--trades-csv", action="append", default=[],
                    help="Optional trade CSV(s) to merge. Repeatable for multi-day datasets.")
args = parser.parse_args()

download_dir = Path(args.download_dir) if args.download_dir else Path.home() / "Downloads"
submission_dir = download_dir / args.submission_id
json_path = submission_dir / f"{args.submission_id}.json"

product = args.product.upper()
output_dir = Path(__file__).parent / product.lower() / "data"
output_dir.mkdir(parents=True, exist_ok=True)

if not json_path.exists():
    print(f"ERROR: {json_path} not found")
    print(f"  Expected submission log at: {json_path}")
    print(f"  Download it from the portal and place it in {submission_dir}/")
    sys.exit(1)

with open(json_path) as f:
    data = json.load(f)

act_lines = data["activitiesLog"].strip().split("\n")

# Find the ask price at t=0 (our buy price)
buy_price = None
for line in act_lines[1:]:
    cols = line.split(";")
    if len(cols) < 17 or cols[2] != product:
        continue
    if int(cols[1]) == 0:
        buy_price = int(cols[9])  # ask_price_1
        break

if buy_price is None:
    print(f"ERROR: Could not find {product} at t=0 in submission log")
    print("  Make sure trader_hold1.py bought 1 unit of this product")
    sys.exit(1)

print(f"Product: {product}")
print(f"Buy price: {buy_price}")

rows = []
for line in act_lines[1:]:
    cols = line.split(";")
    if len(cols) < 17 or cols[2] != product:
        continue
    ts = int(cols[1])
    pnl = float(cols[16])

    bids = []
    bid_vols = []
    for i, vi in [(3, 4), (5, 6), (7, 8)]:
        if cols[i]:
            bids.append(int(cols[i]))
            bid_vols.append(int(cols[vi]))

    asks = []
    ask_vols = []
    for i, vi in [(9, 10), (11, 12), (13, 14)]:
        if cols[i]:
            asks.append(int(cols[i]))
            ask_vols.append(int(cols[vi]))

    fv = pnl + buy_price if ts > 0 else None

    rows.append({
        "ts": ts,
        "fv": fv,
        "bids": sorted(bids, reverse=True),
        "asks": sorted(asks),
        "bid_vols": dict(zip(bids, bid_vols)),
        "ask_vols": dict(zip(asks, ask_vols)),
        "mid_price": float(cols[15]),
    })

trades = []
for tpath in args.trades_csv:
    tpath = Path(tpath)
    if not tpath.exists():
        print(f"WARN: trades CSV {tpath} not found, skipping")
        continue
    with open(tpath, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        n_before = len(trades)
        for row in reader:
            if row.get("symbol") != product:
                continue
            trades.append({
                "ts": int(row["timestamp"]),
                "buyer": row.get("buyer") or None,
                "seller": row.get("seller") or None,
                "price": float(row["price"]),
                "quantity": int(row["quantity"]),
                "currency": row.get("currency") or None,
                "source": tpath.name,
            })
        print(f"  merged {len(trades) - n_before} {product} trades from {tpath.name}")

out = {"product": product, "buy_price": buy_price, "rows": rows}
if trades:
    out["trades"] = trades

outpath = output_dir / "fv_and_book.json"
with open(outpath, "w") as f:
    json.dump(out, f)

print(f"Wrote {len(rows)} rows to {outpath}")
if trades:
    print(f"  + {len(trades)} trades")
fv_rows = [r for r in rows if r["fv"] is not None]
if fv_rows:
    print(f"FV range: {min(r['fv'] for r in fv_rows):.4f} to {max(r['fv'] for r in fv_rows):.4f}")
