"""Data-loading helpers — fv_and_book.json shape definition."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Row:
    ts: int
    fv: float | None
    bids: list
    asks: list
    bid_vols: dict
    ask_vols: dict
    mid_price: float


@dataclass
class Trade:
    ts: int
    buyer: str | None
    seller: str | None
    price: float
    quantity: int


@dataclass
class FvAndBook:
    product: str
    buy_price: int
    rows: list
    trades: list = field(default_factory=list)


def load_fv_and_book(path: Path) -> FvAndBook:
    with open(path) as f:
        d = json.load(f)
    rows = []
    for r in d["rows"]:
        bid_vols = {}
        for k, v in (r.get("bid_vols") or {}).items():
            bid_vols[int(k)] = int(v)
        ask_vols = {}
        for k, v in (r.get("ask_vols") or {}).items():
            ask_vols[int(k)] = int(v)
        rows.append(Row(
            ts=int(r["ts"]),
            fv=None if r.get("fv") is None else float(r["fv"]),
            bids=[int(b) for b in r.get("bids", [])],
            asks=[int(a) for a in r.get("asks", [])],
            bid_vols=bid_vols,
            ask_vols=ask_vols,
            mid_price=float(r.get("mid_price", 0.0)),
        ))
    trades = []
    for t in d.get("trades", []) or []:
        trades.append(Trade(
            ts=int(t["ts"]),
            buyer=t.get("buyer"),
            seller=t.get("seller"),
            price=float(t["price"]),
            quantity=int(t["quantity"]),
        ))
    return FvAndBook(
        product=d.get("product", ""),
        buy_price=int(d.get("buy_price", 0)),
        rows=rows,
        trades=trades,
    )
