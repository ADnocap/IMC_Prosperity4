"""Convert Workshop CSV data to Parquet for faster browser loads.

Walks `data/prosperity{3,4}/round*/` and writes a `.parquet` alongside each
`.csv`, using pyarrow's CSV reader (auto-detects `;` vs `,` on a per-file
basis — prices/trades use `;`, observations use `,`).

The output is skipped when the `.parquet` is newer than the `.csv`, so this
is safe to run on every dashboard startup.

Usage: py -3.13 scripts/csv_to_parquet.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"


def _detect_delimiter(path: Path) -> str:
    with path.open("r", encoding="utf-8") as fh:
        first = fh.readline()
    return ";" if first.count(";") >= first.count(",") else ","


def _convert_one(csv_path: Path, force: bool) -> tuple[str, int]:
    """Returns (status, bytes_written). Status is 'wrote' | 'skipped' | 'failed'."""
    parquet_path = csv_path.with_suffix(".parquet")
    if not force and parquet_path.exists() and parquet_path.stat().st_mtime >= csv_path.stat().st_mtime:
        return ("skipped", 0)

    delimiter = _detect_delimiter(csv_path)
    try:
        table = pacsv.read_csv(
            csv_path,
            parse_options=pacsv.ParseOptions(delimiter=delimiter),
        )
    except pa.ArrowInvalid as exc:
        print(f"  ! failed to parse {csv_path.name}: {exc}", file=sys.stderr)
        return ("failed", 0)

    # Downcast int64 -> int32 where it fits. Prosperity prices/volumes/timestamps
    # all sit well inside int32 range, and on the browser side this means the
    # column decodes to plain `number` instead of being boxed as BigInt (which
    # is roughly 3-5x slower to read through and defeats V8 SMI optimizations).
    new_cols = []
    for field, col in zip(table.schema, table.columns):
        if pa.types.is_int64(field.type):
            new_cols.append(col.cast(pa.int32(), safe=True))
        else:
            new_cols.append(col)
    table = pa.table(new_cols, names=table.schema.names)

    pq.write_table(table, parquet_path, compression="snappy")
    return ("wrote", parquet_path.stat().st_size)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-convert even when parquet is newer")
    parser.add_argument("--quiet", action="store_true", help="Only print summary")
    args = parser.parse_args()

    if not DATA_ROOT.is_dir():
        print(f"data root not found: {DATA_ROOT}", file=sys.stderr)
        return 1

    csv_files = sorted(DATA_ROOT.glob("prosperity*/round*/**/*.csv"))
    if not csv_files:
        print("no CSVs found under data/")
        return 0

    wrote = skipped = failed = 0
    total_bytes = 0
    for csv_path in csv_files:
        status, size = _convert_one(csv_path, args.force)
        if status == "wrote":
            wrote += 1
            total_bytes += size
            if not args.quiet:
                rel = csv_path.relative_to(DATA_ROOT)
                print(f"  + {rel} -> {size/1024:.0f} KB")
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1

    print(f"parquet: wrote {wrote}, skipped {skipped}, failed {failed} ({total_bytes/1024/1024:.1f} MB total)")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
