"""Compare b.py portal sub 367301 vs sim prediction + extract our log lines."""
import json
import csv
from pathlib import Path
from io import StringIO
import re

HERE = Path(__file__).parent

j = json.loads((HERE / "367301.json").read_text())
print("keys:", list(j.keys()))
print(f"profit: {j.get('profit')}")
print(f"positions: {j.get('positions')}")
print()

# activitiesLog → per-asset PnL (mid_price * pos + cash_change)
acts_text = j["activitiesLog"]
rows = list(csv.DictReader(StringIO(acts_text), delimiter=";"))

# Final PnL per asset
print("=== PER-ASSET FINAL PnL (b.py portal) ===")
A_SIM = {'HYDROGEL_PACK': 514, 'VELVETFRUIT_EXTRACT': 362, 'VEV_4000': 136, 'VEV_4500': 94,
         'VEV_5000': 22, 'VEV_5100': 15, 'VEV_5200': 2, 'VEV_5300': 0, 'VEV_5400': 0, 'VEV_5500': 0,
         'VEV_6000': 0, 'VEV_6500': 0}
B_SIM = {'HYDROGEL_PACK': 543, 'VELVETFRUIT_EXTRACT': 475, 'VEV_4000': 136, 'VEV_4500': 93,
         'VEV_5000': 22, 'VEV_5100': 15, 'VEV_5200': 2, 'VEV_5300': 0, 'VEV_5400': 0, 'VEV_5500': 0,
         'VEV_6000': 0, 'VEV_6500': 0}
A_PORTAL = {'HYDROGEL_PACK': 569, 'VELVETFRUIT_EXTRACT': 429, 'VEV_4000': 134, 'VEV_4500': 99,
            'VEV_5000': 25, 'VEV_5100': 12, 'VEV_5200': 5, 'VEV_5300': 0, 'VEV_5400': 0, 'VEV_5500': 0,
            'VEV_6000': 0, 'VEV_6500': 0}

assets = sorted(set(r['product'] for r in rows))
final_pnl = {}
for a in assets:
    arows = [r for r in rows if r["product"] == a]
    if arows:
        final_pnl[a] = float(arows[-1]["profit_and_loss"])
print(f"{'asset':<22} {'a.py portal':>12} {'b.py predicted':>16} {'b.py portal':>13} {'b/a portal':>11}")
total_a = total_pred = total_b = 0
for a in sorted(final_pnl):
    pa = A_PORTAL.get(a, 0)
    pb = final_pnl[a]
    pred = B_SIM.get(a, 0) / max(1, A_SIM.get(a, 1)) * pa if pa else B_SIM.get(a, 0)
    if not pa: pred = 0
    ratio = pb / pa if pa else float('nan')
    total_a += pa; total_pred += pred; total_b += pb
    print(f"{a:<22} {pa:>12.0f} {pred:>16.0f} {pb:>13.1f} {ratio:>11.2f}")
print(f"{'TOTAL':<22} {total_a:>12.0f} {total_pred:>16.0f} {total_b:>13.1f} {total_b/total_a:>11.2f}")

# Look for our log lines in the JSON or .log file
print()
print("=== LOG LINES (search for 'B t=') ===")
log_text = (HERE / "367301.log").read_text()
log_lines = [l for l in log_text.splitlines() if 'B t=' in l]
print(f"found {len(log_lines)} log lines in .log")
for l in log_lines[:5]:
    print(" ", l[:200])
if len(log_lines) > 5:
    print(f"  ... and {len(log_lines)-5} more")

# Also look in JSON for sandbox log
for k, v in j.items():
    if isinstance(v, str) and 'B t=' in v:
        print(f"  found 'B t=' in field '{k}' ({len(v)} chars)")
