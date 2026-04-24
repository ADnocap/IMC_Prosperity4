"""Convenience launcher for the calibration pipeline.

Equivalent to `py -3.13 -m calibration.pipeline.cli`.

Examples:
    py -3.13 calibration/run_pipeline.py ASH_COATED_OSMIUM
    py -3.13 calibration/run_pipeline.py --all --report tmp/calib_summary.md
    py -3.13 calibration/run_pipeline.py VEV_5300 --no-write
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration.pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
