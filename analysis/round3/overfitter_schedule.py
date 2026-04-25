"""Compute optimal overfitted swing schedule from portal log 368660.

Algorithm:
  1. For each product, extract mid prices per timestamp.
  2. Run a zig-zag turning-point filter with min-retracement = half_spread.
     This tolerates noise: a "peak" is only confirmed once price retraces
     by at least half_spread from the running max.
  3. Build a schedule: at each trough set target = +limit, at each peak
     set -limit, flip at the last point to close at 0.
  4. Compute theoretical PnL assuming we fill at mid ± half_spread on
     each flip.
  5. Also report the "one-sided long only" alternative for comparison.

Outputs:
  analysis/round3/overfit_schedule.py  — SCHEDULE dict for trader
  analysis/round3/overfit_report.txt
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "tmp" / "portal_368660" / "368660.log"
OUT_PY = ROOT / "analysis" / "round3" / "overfit_schedule.py"
OUT_REPORT = ROOT / "analysis" / "round3" / "overfit_report.txt"

LIMITS = {
    "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}
DEAD = {"VEV_6000", "VEV_6500"}


def load_portal(path):
    obj = json.load(open(path, encoding="utf-8"))
    rdr = csv.DictReader(io.StringIO(obj["activitiesLog"]), delimiter=";")
    per_prod = defaultdict(list)
    for row in rdr:
        try:
            ts = int(row["timestamp"])
            bb = float(row["bid_price_1"] or 0)
            ba = float(row["ask_price_1"] or 0)
            mid = float(row["mid_price"])
        except (ValueError, KeyError):
            continue
        per_prod[row["product"]].append({"ts": ts, "mid": mid, "bb": bb, "ba": ba})
    for p in per_prod:
        per_prod[p].sort(key=lambda r: r["ts"])
    return per_prod


def zig_zag(series, thresh):
    """Emit turning points: ('peak'|'trough', idx, mid).

    Only declares a peak/trough after price retraces by `thresh` from the
    running extremum. First point is the starting trough/peak based on
    initial direction.
    """
    n = len(series)
    if n < 2:
        return []
    mids = [r["mid"] for r in series]
    points = []
    # State: 0 = initial, 1 = trending up, -1 = trending down
    direction = 0
    run_max = mids[0]; run_max_i = 0
    run_min = mids[0]; run_min_i = 0
    for i in range(1, n):
        m = mids[i]
        if direction >= 0:
            if m >= run_max:
                run_max = m
                run_max_i = i
        if direction <= 0:
            if m <= run_min:
                run_min = m
                run_min_i = i
        # Confirm turning points
        if direction >= 0 and (run_max - m) >= thresh:
            # We were trending up; running max is confirmed peak
            if direction == 0:
                # Initial: also emit the starting trough at run_min_i (the low before the rise)
                points.append(("trough", run_min_i, run_min))
            points.append(("peak", run_max_i, run_max))
            direction = -1
            run_min = m; run_min_i = i
        elif direction <= 0 and (m - run_min) >= thresh:
            if direction == 0:
                points.append(("peak", run_max_i, run_max))
            points.append(("trough", run_min_i, run_min))
            direction = 1
            run_max = m; run_max_i = i
    # Close with the final running extremum on the leading direction, so we
    # have a complete last swing to unwind into.
    if direction == 1:
        points.append(("peak", run_max_i, run_max))
    elif direction == -1:
        points.append(("trough", run_min_i, run_min))
    return points


def dedupe_consecutive(points):
    """Remove redundant consecutive same-kind points (keep extremum)."""
    out = []
    for p in points:
        if out and out[-1][0] == p[0]:
            if p[0] == "peak" and p[2] > out[-1][2]:
                out[-1] = p
            elif p[0] == "trough" and p[2] < out[-1][2]:
                out[-1] = p
        else:
            out.append(p)
    return out


def build_schedule(series, limit, spread, strategy="flip"):
    """Return {timestamp: target_pos}. Strategy = 'flip' (long/short) or 'long_only'."""
    half = spread / 2.0
    thresh = max(half * 1.5, 1.5)  # need a real move to justify crossing
    pts = dedupe_consecutive(zig_zag(series, thresh))
    if not pts:
        return {}, []
    sched = {}
    if strategy == "flip":
        for kind, idx, _ in pts:
            target = +limit if kind == "trough" else -limit
            sched[series[idx]["ts"]] = target
    else:  # long_only: at troughs +limit, at peaks 0
        for kind, idx, _ in pts:
            target = +limit if kind == "trough" else 0
            sched[series[idx]["ts"]] = target
    # Close the final position at the last tick to avoid MTM mark
    last_ts = series[-1]["ts"]
    sched[last_ts] = 0
    return sched, pts


def theoretical_pnl(series, sched, spread):
    half = spread / 2.0
    cash = 0.0
    pos = 0
    trades = 0
    total_units = 0
    for row in series:
        target = sched.get(row["ts"])
        if target is None:
            continue
        diff = target - pos
        if diff == 0:
            continue
        fill_price = row["mid"] + (half if diff > 0 else -half)
        cash -= fill_price * diff
        pos += diff
        trades += 1
        total_units += abs(diff)
    final_mtm = series[-1]["mid"] * pos
    return {"pnl": cash + final_mtm, "trades": trades, "units": total_units,
            "final_pos": pos}


def main():
    per_prod = load_portal(LOG)
    report = [f"# Overfit schedule from portal log 368660", ""]
    schedules = {}
    total_flip = 0.0
    total_long = 0.0

    for prod, series in sorted(per_prod.items()):
        if prod in DEAD or prod not in LIMITS:
            continue
        limit = LIMITS[prod]
        spreads = [r["ba"] - r["bb"] for r in series if r["bb"] and r["ba"]]
        spread = sum(spreads) / max(len(spreads), 1)

        sched_flip, pts = build_schedule(series, limit, spread, "flip")
        sched_long, _ = build_schedule(series, limit, spread, "long_only")
        flip_m = theoretical_pnl(series, sched_flip, spread)
        long_m = theoretical_pnl(series, sched_long, spread)
        total_flip += flip_m["pnl"]
        total_long += long_m["pnl"]

        mids = [r["mid"] for r in series]
        report.append(
            f"{prod:22s} spread={spread:5.2f}  "
            f"mid_width={max(mids)-min(mids):6.2f}  "
            f"turning_pts={len(pts):3d}  "
            f"flip_PnL={flip_m['pnl']:+10,.0f}  "
            f"long_PnL={long_m['pnl']:+10,.0f}"
        )
        # Keep the better of the two
        if flip_m["pnl"] >= long_m["pnl"]:
            schedules[prod] = sched_flip
        else:
            schedules[prod] = sched_long

    report.append("")
    report.append(f"TOTAL flip-strategy PnL:     {total_flip:+,.0f} XIRECs")
    report.append(f"TOTAL long-only PnL:         {total_long:+,.0f} XIRECs")

    selected_total = sum(
        theoretical_pnl(per_prod[p], schedules[p],
                        sum(r["ba"] - r["bb"] for r in per_prod[p] if r["bb"] and r["ba"])
                        / max(len([r for r in per_prod[p] if r["bb"] and r["ba"]]), 1))["pnl"]
        for p in schedules
    )
    report.append(f"TOTAL picking best-per-asset: {selected_total:+,.0f} XIRECs")
    report.append("")
    report.append("(Gross = fill at mid ± half_spread. Real fills walk the book "
                  "and pay additional slippage on flip size > top-of-book depth.)")

    text = "\n".join(report)
    OUT_REPORT.write_text(text, encoding="utf-8")
    print(text)

    lines = [
        "# Auto-generated by analysis/round3/overfitter_schedule.py",
        "# {product: {timestamp: target_position}}  — chronologically sorted",
        "SCHEDULE = {",
    ]
    for prod in sorted(schedules):
        lines.append(f"    {prod!r}: {{")
        for ts in sorted(schedules[prod].keys()):
            lines.append(f"        {ts}: {schedules[prod][ts]},")
        lines.append("    },")
    lines.append("}")
    OUT_PY.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSchedule written to {OUT_PY}")


if __name__ == "__main__":
    main()
