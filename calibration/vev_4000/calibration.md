# VEV_4000 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.00390625 |
| drift | 0 |
| sigma | 0.958341 |
| mean | 1262.38 |
| n_ticks | 999 |
| residual Ljung p | 0.4422 |
| residual skew z | 1.226 |
| residual kurt z | -1.387 |

## Bot `layer1` — Layer 1 (outer)

| Property | Value |
|---|---|
| Bid formula | `floor(fv * (1 - 1.0001e-02))` |
| Ask formula | `ceil(fv * (1 + 1.0001e-02))` |
| Offset type | proportional |
| Offset band (bid) | [-14.50, -12.50] |
| Offset band (ask) | [12.50, 14.50] |
| Volume | uniform U(15, 30) |
| Sides tied | True |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.994 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0.533496
- `ask_vol_uniform_p` = 0.575383
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.994
- `bid_ask_indep_p` = 1

## Bot `layer2` — Layer 2 (outer)

| Property | Value |
|---|---|
| Bid formula | `floor(fv * (1 - 8.0049e-03))` |
| Ask formula | `ceil(fv * (1 + 7.9954e-03))` |
| Offset type | proportional |
| Offset band (bid) | [-11.50, -9.50] |
| Offset band (ask) | [9.50, 11.50] |
| Volume | uniform U(7, 15) |
| Sides tied | True |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.999 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0.954676
- `ask_vol_uniform_p` = 0.954676
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.999
- `bid_ask_indep_p` = 1

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:10:55Z
