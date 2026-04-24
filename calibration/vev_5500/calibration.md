# VEV_5500 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.0001 |
| drift | 0 |
| sigma | 0.0808104 |
| mean | 6.387 |
| n_ticks | 999 |
| residual Ljung p | 0.4083 |
| residual skew z | 1.318 |
| residual kurt z | -0.786 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv * (1 - 1.2020e-02))` |
| Ask formula | `ceil(fv * (1 + 1.2020e-02))` |
| Offset type | proportional |
| Offset band (bid) | [-1.50, 0.50] |
| Offset band (ask) | [-0.50, 1.50] |
| Volume | empirical, range [2, 30] |
| Sides tied | False |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.999 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.941942
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.999
- `bid_ask_indep_p` = 1

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:14:42Z
