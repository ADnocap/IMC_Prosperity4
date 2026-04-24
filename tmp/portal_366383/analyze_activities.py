"""Compare HYDROGEL_PACK book stats: portal vs sim calibration assumptions."""
import json
import csv
from pathlib import Path
from collections import Counter, defaultdict
from io import StringIO
import statistics as st

HERE = Path(__file__).parent
REPO = HERE.parent.parent

j = json.loads((HERE / "366383.json").read_text())
acts_text = j["activitiesLog"]
graph = j["graphLog"]
positions = j["positions"]

print("FINAL POSITIONS:")
for p in positions:
    print(f"  {p['symbol']}: {p['quantity']}")
print()

# Parse activities
rows = list(csv.DictReader(StringIO(acts_text), delimiter=";"))
print(f"total rows: {len(rows)}")
print(f"days: {sorted(set(r['day'] for r in rows))}")
print(f"products: {sorted(set(r['product'] for r in rows))}")
print(f"timestamps per product: {len([r for r in rows if r['product']=='HYDROGEL_PACK'])}")
print()

# Per-asset stats: spread distribution + book-depth presence + final PnL
ASSETS = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500",
          "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400",
          "VEV_5500", "VEV_6000", "VEV_6500"]

def to_int(s):
    if s is None or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None

print("=== PORTAL BOOK STATS ===")
print(f"{'asset':<22} {'n':>5} {'spread_mean':>11} {'spread_med':>10} "
      f"{'L2_bid_pct':>10} {'L2_ask_pct':>10} {'final_pnl':>10}")
for asset in ASSETS:
    arows = [r for r in rows if r["product"] == asset]
    spreads = []
    has_L2_bid = 0
    has_L2_ask = 0
    final_pnl = float(arows[-1]["profit_and_loss"]) if arows else 0
    for r in arows:
        b1 = to_int(r["bid_price_1"]); a1 = to_int(r["ask_price_1"])
        b2 = to_int(r["bid_price_2"]); a2 = to_int(r["ask_price_2"])
        if b1 is not None and a1 is not None:
            spreads.append(a1 - b1)
        if b2 is not None: has_L2_bid += 1
        if a2 is not None: has_L2_ask += 1
    if not spreads:
        continue
    print(f"{asset:<22} {len(arows):>5} {st.mean(spreads):>11.2f} "
          f"{st.median(spreads):>10.2f} "
          f"{100*has_L2_bid/len(arows):>9.1f}% "
          f"{100*has_L2_ask/len(arows):>9.1f}% "
          f"{final_pnl:>10.1f}")
