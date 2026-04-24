"""Extract activitiesLog (CSV) + own trades from portal JSON into parquet/csv."""
import json
import csv
import sys
from pathlib import Path

HERE = Path(__file__).parent
P = HERE / "366383.json"

j = json.loads(P.read_text())
print("keys:", list(j.keys()))
for k in j:
    v = j[k]
    if isinstance(v, str):
        print(f"  {k}: str, len={len(v)}, head={v[:80]!r}")
    else:
        print(f"  {k}: {type(v).__name__}", repr(v)[:120])

# activitiesLog is the price/orderbook CSV
acts = j["activitiesLog"]
(HERE / "activities.csv").write_text(acts, encoding="utf-8")
print(f"wrote activities.csv ({len(acts.splitlines())} lines)")

# trades may be in another field — let's see
for k in j:
    if "rade" in k.lower() or "fill" in k.lower():
        print(f"trade field: {k}")
