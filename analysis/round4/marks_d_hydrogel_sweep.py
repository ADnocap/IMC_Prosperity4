"""Sweep MARK_TAKE_SIZE on HYDROGEL-only marks_d_fallback variant.

The full marks_d_fallback (size 8) lost 11,175 on HYDROGEL alone. Maybe a
much smaller size + longer cooldown could recover some PnL — or at least
break even.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "traders" / "round4" / "marks_d_fallback.py"
PROJECT_ROOT = REPO

SIZES = [1, 2, 3, 5]
COOLDOWNS = [50, 100, 200]


def run_one(size: int, cooldown: int) -> dict:
    src_text = SRC.read_text()
    new_text = re.sub(r"^MARK_TAKE_SIZE = \d+",
                      f"MARK_TAKE_SIZE = {size}",
                      src_text, count=1, flags=re.MULTILINE)
    new_text = re.sub(r"^MARK_TAKE_COOLDOWN = \d+",
                      f"MARK_TAKE_COOLDOWN = {cooldown}",
                      new_text, count=1, flags=re.MULTILINE)
    new_text = re.sub(r"^MARK_DISABLE_FOR: set = .*$",
                      "MARK_DISABLE_FOR: set = {VEV_4000, VEV_4500}",
                      new_text, count=1, flags=re.MULTILINE)
    tmp = REPO / "tmp" / f"marks_d_hyonly_size{size}_cd{cooldown}.py"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(new_text)
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
    print(f"{'Size':>5} {'CD':>4} {'D1':>9} {'D2':>9} {'D3':>9} "
          f"{'Total':>9} {'D-base':>9} {'HY-3d':>9}")
    print(f"{'BASE':>5} {'-':>4} {'14,675':>9} {'2,946':>9} {'12,312':>9} "
          f"{'29,934':>9} {'0':>9} {'8,861':>9}")
    for size in SIZES:
        for cd in COOLDOWNS:
            r = run_one(size, cd)
            d1 = r.get(1, {}).get("TOTAL", 0)
            d2 = r.get(2, {}).get("TOTAL", 0)
            d3 = r.get(3, {}).get("TOTAL", 0)
            tot = d1 + d2 + d3
            hy = sum(r.get(d, {}).get("HYDROGEL_PACK", 0) for d in (1, 2, 3))
            print(f"{size:>5} {cd:>4} {d1:>9,} {d2:>9,} {d3:>9,} "
                  f"{tot:>9,} {tot-29934:>+9,} {hy:>9,}")


if __name__ == "__main__":
    main()
