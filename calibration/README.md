# Calibration

Reverse-engineered bot models for the Prosperity 4 exchange. Each asset we've traded gets its own directory with extracted book/FV data (`data/fv_and_book.json`), a machine-readable bot model (`params.json`), and human-readable calibration notes.

Two ways in:

- **Manual** — extract data with `extract_fv_and_book.py`, clone a per-asset `scripts/calibrate.py`, write `params.json` by hand, validate with `test_acceptance.py`. This is how the OSMIUM / PEPPER models were built.
- **Guided** — open the **Calibration** tab in the visualizer (`./run.sh` / `.\run.ps1`). A 9-stage discovery pipeline walks you through FV-process fitting, layer detection, formula search, volume / presence / noise / trade-bot modelling, multiple-testing-corrected validation, and a one-click export to `calibration/<asset>/params.json`. All stats are computed in WASM kernels shared with the backend acceptance tests.

## Layout

```
calibration/
├── ANALYSIS_PHILOSOPHY.md       Methodology (condition on everything, stat tests, no eyeballing)
├── README.md                    This file
├── params_schema.md             params.json schema reference (Stage 8 output)
├── validate.py                  Asset-agnostic statistical validation harness
├── extract_fv_and_book.py       Hold-1 FV + book extractor (also merges trade CSVs for Stage 6)
├── audit_portal_log.py          Audit a portal log against current Rust bot formulas
├── test_acceptance.py           Regression test — re-evaluates every params.json against its fv_and_book.json
├── emeralds/                    Round 0 constant-FV product (no params.json — no modelling needed)
├── tomatoes/                    Round 0 random-walk product (reference calibration)
├── ash_coated_osmium/           Round 1/2 random-walk product (params.json + data/)
└── intarian_pepper_root/        Round 1/2 deterministic-drift product (params.json + data/)
```

Each calibrated asset contains:

```
<asset>/
├── calibration.md             human-readable findings
├── data/fv_and_book.json      hold-1 extraction (FV + order book per tick; optionally + trades)
├── params.json                machine-readable bot model — see params_schema.md
└── scripts/                   one-off calibration scripts used while building the model
```

## Per-asset summary

| Asset | FV process | Bot layout | Key calibration insight |
|---|---|---|---|
| EMERALDS | constant 10,000 | outer ±10, inner ±8 | No modelling needed |
| TOMATOES | Gaussian RW, σ=0.496/tick | Bot1 ±8, Bot2 asymmetric round, Bot3 noise | Bot presence ≈ 100% |
| ASH_COATED_OSMIUM | Gaussian RW, σ=0.312/tick | Bot1 `floor/ceil ±10`, Bot2 `round ±8` | Bots present ~80% per side (iid Bernoulli) |
| INTARIAN_PEPPER_ROOT | deterministic drift +0.1/tick | Bot1 K=3/4000, Bot2 K=1/2000 | **Proportional offsets** — must scale with FV; fixed offsets fail at wide FV ranges |

## `params.json`

`params.json` is the single source of truth for a calibrated bot model. It has a variable number of bots (the pipeline discovers `N`, it does not assume the OSMIUM/PEPPER 2-bot layout). Consumed by:

- The Calibration tab (renders the validation dashboard and seeds the UI when re-running discovery)
- `test_acceptance.py` (re-evaluates every documented formula against extracted data — currently 8/8 bot sides match at ≥99.7%)
- The Rust simulator (ground-truth fixture while porting a bot to `rust_simulator/src/assets/<asset>.rs`)
- `audit_portal_log.py` (checks live portal logs against the documented formulas)

Schema: [`params_schema.md`](params_schema.md).

## Workflow for a new asset

1. Submit `traders/trader_hold1.py` to extract true server FV from PnL.
2. Run `py -3.13 calibration/extract_fv_and_book.py <submission_id> <PRODUCT>` to build `<asset>/data/fv_and_book.json`. Add `--trades-csv <path>` (repeatable) to merge market-trade CSVs for Stage 6 (trade-bot model).
3. Either:
    - **Guided** — open the Calibration tab, select the asset, and step through stages 0–8. Stage 8 POSTs the generated `params.json` to the server (`/__prosperity4mcbt__/calibration/params`), which writes it to `calibration/<asset>/params.json`.
    - **Manual** — clone `ash_coated_osmium/scripts/calibrate.py` or `intarian_pepper_root/scripts/calibrate.py` as a template, produce a `params.json` by hand, and validate with `calibration/validate.py`.
4. Run `py -3.13 calibration/test_acceptance.py` — it enumerates every `.rs` under `rust_simulator/src/assets/` and re-evaluates each bot formula against the extracted data. All bot sides must match ≥98%.
5. Port the formulas into a new `rust_simulator/src/assets/<asset_lower>.rs` module (copy one of the existing files as a template) and register it in `rust_simulator/src/assets/mod.rs`. `cargo build --release` and you're done — the trader's `NEW = "YOUR_SYMBOL"` declaration auto-activates the asset.
6. Run `calibration/audit_portal_log.py <portal_log>` against a fresh portal submission to confirm match-rates hold in the wild.

See `BACKTEST.md` for the full asset-integration workflow and the `AssetSim` trait contract (in `rust_simulator/src/asset.rs`).

## Stats kernels & endpoints (reference)

- WASM kernels: `wasm_compute/src/calibration.rs` (chi², 2-sample KS, Wilson CI, Ljung-Box, Wald-Wolfowitz runs, Geometric run-length KS, 2×2 and N×N independence, OLS + t-stat, KDE + peak detection, Fisher combined, Benjamini-Hochberg FDR, normal / inverse-normal / Wilson-Hilferty χ² CDFs) and `wasm_compute/src/formula_search.rs` (Stage 2 brute-force formula discovery with 2-fold CV, Wilson CIs, residual histogram, FV-decile match heatmap). Native unit tests cover the OSMIUM `floor(fv)-10` and PEPPER `K=3/4000` recoveries.
- Server endpoints (`backtester/dashboard_server.py`):
  - `GET /__prosperity4mcbt__/calibration/assets` — list assets with `rust_simulator/src/assets/<x>.rs`, plus `hasData`/`hasParams` booleans.
  - `GET /__prosperity4mcbt__/calibration/data?asset=<SYM>` — serve `fv_and_book.json`.
  - `GET /__prosperity4mcbt__/calibration/params?asset=<SYM>` — serve existing `params.json` (404 if not yet written).
  - `POST /__prosperity4mcbt__/calibration/params?asset=<SYM>` — write `params.json` (used by Stage 8 export).
