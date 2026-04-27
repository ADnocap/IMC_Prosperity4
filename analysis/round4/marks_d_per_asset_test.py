"""Per-asset attribution: run marks_d_fallback with each Mark product
disabled in turn. Compare each disabling to the baseline submission.py.

Outputs the per-day per-asset PnL diffs to stdout.
"""
import shutil
import subprocess
import sys
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "traders" / "round4" / "marks_d_fallback.py"

VARIANTS = [
    ("d_full", "set()"),
    ("d_no_hydrogel", "{HYDROGEL}"),
    ("d_no_vev4000", "{VEV_4000}"),
    ("d_no_vev4500", "{VEV_4500}"),
    ("d_only_vev4000", "{HYDROGEL, VEV_4500}"),  # only VEV_4000 enabled
]

PROJECT_ROOT = REPO


def run_one(variant_name: str, disable_set: str) -> dict:
    src_text = SRC.read_text()
    new_text = re.sub(r"^MARK_DISABLE_FOR: set = .*$",
                      f"MARK_DISABLE_FOR: set = {disable_set}",
                      src_text, count=1, flags=re.MULTILINE)
    tmp = REPO / "tmp" / f"marks_d_variant_{variant_name}.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(new_text)
    print(f"\n=== {variant_name}: MARK_DISABLE_FOR = {disable_set} ===")
    result = subprocess.run(
        ["prosperity3bt", str(tmp), "4", "--merge-pnl",
         "--no-out", "--no-progress"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(PROJECT_ROOT),
    )
    return parse_output(result.stdout)


PROD_RX = re.compile(r"^([A-Z_0-9]+):\s+([-\d,]+)$")
DAY_RX = re.compile(r"on round 4 day (\d)$")


def parse_output(stdout: str) -> dict:
    """Parse `Backtesting ... day N\\nPRODUCT: pnl\\n...Total profit: T`."""
    days = {}
    cur_day = None
    cur_assets = {}
    for line in stdout.splitlines():
        line = line.strip()
        m = DAY_RX.search(line)
        if m:
            if cur_day is not None:
                days[cur_day] = cur_assets
            cur_day = int(m.group(1))
            cur_assets = {}
            continue
        if line.startswith("Total profit:"):
            tot = int(line.split(":")[1].strip().replace(",", ""))
            cur_assets["TOTAL"] = tot
            if cur_day is not None:
                days[cur_day] = cur_assets
                cur_day = None
                cur_assets = {}
            continue
        m = PROD_RX.match(line)
        if m and cur_day is not None:
            cur_assets[m.group(1)] = int(m.group(2).replace(",", ""))
    return days


def main():
    rows = {}
    for name, dis in VARIANTS:
        rows[name] = run_one(name, dis)

    # Print summary table per-day per-asset, plus 3-day total
    assets = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500",
              "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400",
              "VEV_5500", "VEV_6000", "VEV_6500", "TOTAL"]
    print("\n=== PER-DAY PER-ASSET TABLE ===")
    for day in (1, 2, 3):
        print(f"\nDay {day}:")
        hdr = f"  {'Asset':<22}" + "".join(f"{n:>16}" for n, _ in VARIANTS)
        print(hdr)
        for a in assets:
            vals = [rows[n].get(day, {}).get(a, 0) for n, _ in VARIANTS]
            print(f"  {a:<22}" + "".join(f"{v:>16,}" for v in vals))

    print("\n=== 3-DAY TOTAL PER ASSET ===")
    print(f"  {'Asset':<22}" + "".join(f"{n:>16}" for n, _ in VARIANTS))
    for a in assets:
        vals = []
        for n, _ in VARIANTS:
            tot = sum(rows[n].get(d, {}).get(a, 0) for d in (1, 2, 3))
            vals.append(tot)
        print(f"  {a:<22}" + "".join(f"{v:>16,}" for v in vals))


if __name__ == "__main__":
    main()
