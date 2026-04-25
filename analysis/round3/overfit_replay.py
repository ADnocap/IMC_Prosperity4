"""Replay chester.py's schedule against the 368660 portal book snapshots
and estimate realistic PnL including book-walk slippage.

Each tick the portal log shows up to 3 book levels. We simulate chester's
aggressive cross by walking through the visible levels at their prices.
Anything beyond the 3rd level fills at a conservative estimated price
(level_3 + CROSS_BUFFER). Unfilled remainder carries over.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "tmp" / "portal_368660" / "368660.log"
sys.path.insert(0, str(ROOT / "traders" / "round3"))
sys.path.insert(0, str(ROOT / "traders"))  # expose datamodel for chester import
from chester import SCHEDULE, LIMITS, current_target, Trader


def load_book(path):
    obj = json.load(open(path, encoding="utf-8"))
    rdr = csv.DictReader(io.StringIO(obj["activitiesLog"]), delimiter=";")
    rows_by_ts = defaultdict(dict)
    for row in rdr:
        try:
            ts = int(row["timestamp"])
        except (ValueError, KeyError):
            continue
        prod = row["product"]
        bids = []
        asks = []
        for i in (1, 2, 3):
            bp = row.get(f"bid_price_{i}", "") or ""
            bv = row.get(f"bid_volume_{i}", "") or ""
            ap = row.get(f"ask_price_{i}", "") or ""
            av = row.get(f"ask_volume_{i}", "") or ""
            if bp and bv:
                bids.append((int(float(bp)), int(float(bv))))
            if ap and av:
                asks.append((int(float(ap)), int(float(av))))
        rows_by_ts[ts][prod] = {
            "bids": sorted(bids, key=lambda x: -x[0]),
            "asks": sorted(asks, key=lambda x: x[0]),
            "mid": float(row["mid_price"]),
        }
    return rows_by_ts


def fill_buy(book, qty, buffer_unused):
    """Walk asks up to qty across visible levels. Portal order expires
    if we price at ba+buffer but aren't hit by hidden liquidity — so
    realistic fill = min(qty, visible ask depth)."""
    asks = list(book["asks"])
    filled = 0
    spent = 0.0
    for p, v in asks:
        take = min(v, qty - filled)
        if take <= 0:
            break
        filled += take
        spent += take * p
    return filled, (spent / filled if filled else 0.0)


def fill_sell(book, qty, buffer_unused):
    bids = list(book["bids"])
    filled = 0
    received = 0.0
    for p, v in bids:
        take = min(v, qty - filled)
        if take <= 0:
            break
        filled += take
        received += take * p
    return filled, (received / filled if filled else 0.0)


def main():
    books = load_book(LOG)
    ts_sorted = sorted(books.keys())
    cur_pos = {p: 0 for p in SCHEDULE}
    cash = {p: 0.0 for p in SCHEDULE}
    trades = {p: 0 for p in SCHEDULE}
    units = {p: 0 for p in SCHEDULE}
    slippage_beyond_book = {p: 0 for p in SCHEDULE}

    buffer = Trader.CROSS_BUFFER

    for ts in ts_sorted:
        snapshot = books[ts]
        for prod in SCHEDULE:
            book = snapshot.get(prod)
            if book is None or not book["bids"] or not book["asks"]:
                continue
            target = current_target(prod, ts)
            diff = target - cur_pos[prod]
            if diff == 0:
                continue
            limit = LIMITS[prod]
            if diff > 0:
                room = limit - cur_pos[prod]
                want = min(diff, room)
                top_depth = sum(v for _, v in book["asks"])
                if want > top_depth:
                    slippage_beyond_book[prod] += (want - top_depth)
                filled, vwap = fill_buy(book, want, buffer)
                cash[prod] -= filled * vwap
                cur_pos[prod] += filled
                trades[prod] += 1
                units[prod] += filled
            else:
                room = limit + cur_pos[prod]
                want = min(-diff, room)
                top_depth = sum(v for _, v in book["bids"])
                if want > top_depth:
                    slippage_beyond_book[prod] += (want - top_depth)
                filled, vwap = fill_sell(book, want, buffer)
                cash[prod] += filled * vwap
                cur_pos[prod] -= filled
                trades[prod] += 1
                units[prod] += filled

    # Mark-to-market final positions using last mid per product
    last_mid = {}
    for ts in reversed(ts_sorted):
        for prod, book in books[ts].items():
            if prod not in last_mid and book.get("mid"):
                last_mid[prod] = book["mid"]
        if all(p in last_mid for p in SCHEDULE):
            break

    total = 0.0
    print(f"{'product':22s} {'pnl':>10s} {'trades':>7s} {'units':>7s} "
          f"{'end_pos':>8s} {'slip_beyond_book':>18s}")
    for prod in sorted(SCHEDULE):
        mtm = last_mid.get(prod, 0) * cur_pos[prod]
        pnl = cash[prod] + mtm
        total += pnl
        print(f"{prod:22s} {pnl:10.0f} {trades[prod]:7d} {units[prod]:7d} "
              f"{cur_pos[prod]:8d} {slippage_beyond_book[prod]:18d}")
    print(f"{'TOTAL':22s} {total:10.0f}")


if __name__ == "__main__":
    main()
