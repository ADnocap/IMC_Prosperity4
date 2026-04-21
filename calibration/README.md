# Calibration

Reverse-engineered bot models for the Prosperity 4 exchange. Each asset we've traded so far gets its own directory with calibration notes, extracted book/FV data, and the scripts that produced the calibration.

## Layout

```
calibration/
├── ANALYSIS_PHILOSOPHY.md       Methodology (condition on everything, stat tests, no eyeballing)
├── README.md                    This file
├── validate.py                  Asset-agnostic statistical validation harness
├── extract_fv_and_book.py       Asset-agnostic hold-1 FV + book extractor (from portal submission log)
├── audit_portal_log.py          Audit a portal log against current Rust bot formulas
├── emeralds/                    Round 0 constant-FV product
├── tomatoes/                    Round 0 random-walk product (reference calibration)
├── ash_coated_osmium/           Round 1/2 random-walk product
└── intarian_pepper_root/        Round 1/2 deterministic-drift product
```

## Per-asset summary

| Asset | FV process | Bot layout | Key calibration insight |
|---|---|---|---|
| EMERALDS | constant 10,000 | outer ±10, inner ±8 | No modelling needed |
| TOMATOES | Gaussian RW, σ=0.496/tick | Bot1 ±8, Bot2 asymmetric round, Bot3 noise | Bot presence ≈ 100% |
| ASH_COATED_OSMIUM | Gaussian RW, σ=0.312/tick | Bot1 floor/ceil ±10, Bot2 round ±8 | Bots present ~80% per side (iid Bernoulli) |
| INTARIAN_PEPPER_ROOT | deterministic drift +0.1/tick | Bot1 K=3/4000, Bot2 K=1/2000 | **Proportional offsets** — must scale with FV; fixed offsets fail at wide FV ranges |

## Workflow for a new asset

1. Submit `traders/trader_hold1.py` (asset-agnostic hold-1 trader) to extract true server FV from PnL
2. Run `calibration/extract_fv_and_book.py <submission_id> <PRODUCT>` to build `<asset>/data/fv_and_book.json`
3. Clone `ash_coated_osmium/scripts/calibrate.py` or `intarian_pepper_root/scripts/calibrate.py` as a template, adapt for the new asset
4. Validate with `calibration/validate.py` (add the new product to its `PRODUCTS` list)
5. Port the formulas into `rust_simulator/src/main.rs`
6. Run `calibration/audit_portal_log.py <portal_log>` against a fresh portal submission to verify match-rates hold
