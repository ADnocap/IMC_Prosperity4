# HYDROGEL_PACK Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.00390625 |
| drift | 0 |
| sigma | 1.91594 |
| mean | 9979.32 |
| n_ticks | 999 |
| residual Ljung p | 0.9417 |
| residual skew z | 0.369 |
| residual kurt z | -1.834 |

## Bot `layer1` — Layer 1 (outer)

| Property | Value |
|---|---|
| Bid formula | `floor(fv * (1 - 1.0001e-03))` |
| Ask formula | `ceil(fv * (1 + 1.0001e-03))` |
| Offset type | proportional |
| Offset band (bid) | [-11.50, -9.50] |
| Offset band (ask) | [9.50, 11.50] |
| Volume | uniform U(20, 30) |
| Sides tied | True |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.999 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0.994848
- `ask_vol_uniform_p` = 0.994848
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.999
- `bid_ask_indep_p` = 1

## Bot `layer2` — Layer 2 (inner)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 7` |
| Ask formula | `round(fv) + 8` |
| Offset type | fixed |
| Offset band (bid) | [-8.50, -7.50] |
| Offset band (ask) | [7.50, 8.50] |
| Volume | uniform U(10, 15) |
| Sides tied | True |
| Presence (bid rate) | 0.975 |
| Presence (ask rate) | 0.980 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0.700689
- `ask_vol_uniform_p` = 0.748234
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.975
- `ask_presence_rate` = 0.98
- `bid_ask_indep_p` = 1

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:10:03Z
