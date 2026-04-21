# Round 2 Analysis

Data-driven checks specific to Round 2. R2 shipped the same products as R1 (OSMIUM, PEPPER_ROOT), so deep market structure work is in `../round1/`. The only R2-specific finding worth re-validating is the PEPPER cross-round drift continuation.

## Scripts

- **`check_pepper_start.py`** — reads the hold-1 R2 FV trace (submission 274082, stored at `calibration/intarian_pepper_root/data/r2_day1_fv.json`) and confirms:
  1. PEPPER does not reset at R2 — day 1 starts at ~13,000, continuous from R1 day 0's ending FV
  2. Drift remains +0.1/tick, deterministic (residual std ≈ 0.0003 = quantization noise)
  3. First array entry is the buy-at-ask anchor, not a server-FV sample — skip it when computing drift

This is the evidence behind the `--ipr-start-fv 13000` flag on `prosperity4mcbt`. Re-run it whenever you want to re-verify against a fresh hold-1 portal submission.

```bash
PYTHONIOENCODING=utf-8 py -3.13 analysis/round2/check_pepper_start.py
```
