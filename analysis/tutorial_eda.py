"""
Exploratory Data Analysis for IMC Prosperity 4 Tutorial Round
Products: EMERALDS, TOMATOES
"""
import csv
import statistics
from collections import defaultdict


def load_prices(filepath: str) -> list[dict]:
    """Load semicolon-delimited price CSV."""
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(row)
    return rows


def load_trades(filepath: str) -> list[dict]:
    """Load semicolon-delimited trade CSV."""
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(row)
    return rows


def analyze_prices(rows: list[dict], label: str):
    """Analyze price data per product."""
    by_product = defaultdict(list)
    for row in rows:
        product = row["product"]
        mid = float(row["mid_price"])
        by_product[product].append(mid)

    print(f"\n{'='*60}")
    print(f"  PRICE ANALYSIS: {label}")
    print(f"{'='*60}")

    for product, mids in sorted(by_product.items()):
        print(f"\n  {product}")
        print(f"  {'─'*40}")
        print(f"  Count:   {len(mids)}")
        print(f"  Mean:    {statistics.mean(mids):.2f}")
        print(f"  Median:  {statistics.median(mids):.2f}")
        print(f"  Stdev:   {statistics.stdev(mids):.2f}")
        print(f"  Min:     {min(mids):.2f}")
        print(f"  Max:     {max(mids):.2f}")
        print(f"  Range:   {max(mids) - min(mids):.2f}")
        print(f"  Start:   {mids[0]:.2f}")
        print(f"  End:     {mids[-1]:.2f}")
        print(f"  Drift:   {mids[-1] - mids[0]:.2f}")

        # Spread analysis
    spreads_by_product = defaultdict(list)
    for row in rows:
        product = row["product"]
        bid1 = row.get("bid_price_1", "")
        ask1 = row.get("ask_price_1", "")
        if bid1 and ask1:
            spreads_by_product[product].append(float(ask1) - float(bid1))

    print(f"\n  SPREAD ANALYSIS:")
    for product, spreads in sorted(spreads_by_product.items()):
        print(f"  {product}: mean={statistics.mean(spreads):.2f}, "
              f"min={min(spreads):.2f}, max={max(spreads):.2f}, "
              f"stdev={statistics.stdev(spreads):.2f}")


def analyze_trades(rows: list[dict], label: str):
    """Analyze trade data per product."""
    by_product = defaultdict(list)
    for row in rows:
        symbol = row["symbol"]
        price = float(row["price"])
        qty = int(row["quantity"])
        by_product[symbol].append((price, qty))

    print(f"\n{'='*60}")
    print(f"  TRADE ANALYSIS: {label}")
    print(f"{'='*60}")

    for product, trades in sorted(by_product.items()):
        prices = [t[0] for t in trades]
        qtys = [t[1] for t in trades]
        vwap = sum(p * q for p, q in trades) / sum(qtys)

        print(f"\n  {product}")
        print(f"  {'─'*40}")
        print(f"  Trade count: {len(trades)}")
        print(f"  Total volume: {sum(qtys)}")
        print(f"  Avg qty:     {statistics.mean(qtys):.1f}")
        print(f"  VWAP:        {vwap:.2f}")
        print(f"  Price range: {min(prices):.0f} - {max(prices):.0f}")
        print(f"  Price stdev: {statistics.stdev(prices):.2f}")


if __name__ == "__main__":
    import os

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data", "round0")

    # Analyze both days
    for day in [-2, -1]:
        price_file = os.path.join(data_dir, f"prices_round_0_day_{day}.csv")
        trade_file = os.path.join(data_dir, f"trades_round_0_day_{day}.csv")

        if os.path.exists(price_file):
            prices = load_prices(price_file)
            analyze_prices(prices, f"Day {day}")

        if os.path.exists(trade_file):
            trades = load_trades(trade_file)
            analyze_trades(trades, f"Day {day}")
