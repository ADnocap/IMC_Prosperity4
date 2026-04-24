# VEV_6500 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | constant |
| quantization | 0.0001 |
| mean | 0 |
| sigma | 0 |
| n_ticks | 999 |
| residual Ljung p | 1.0000 |
| residual skew z | 0.000 |
| residual kurt z | 0.000 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `ceil(fv + 0.25) - 1` |
| Ask formula | `floor(fv - 0.75) + 2` |
| Offset type | fixed |
| Offset band (bid) | [-0.50, 0.50] |
| Offset band (ask) | [0.50, 1.50] |
| Volume | empirical, range [7, 25] |
| Sides tied | True |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.999 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.978979
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.999
- `bid_ask_indep_p` = 1

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:16:33Z
