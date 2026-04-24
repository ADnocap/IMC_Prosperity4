# VEV_5000 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

**Position limit:** 300

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.000976562 |
| drift | 0 |
| sigma | 0.913782 |
| mean | 265.589 |
| n_ticks | 999 |
| residual Ljung p | 0.4382 |
| residual skew z | 1.204 |
| residual kurt z | -1.381 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 3` |
| Ask formula | `floor(fv - 0.5) + 5` |
| Offset type | fixed |
| Offset band (bid) | [-4.50, -3.50] |
| Offset band (ask) | [3.50, 4.50] |
| Volume | empirical, range [12, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.827 |
| Presence (ask rate) | 0.829 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.811263
- `bid_presence_rate` = 0.827
- `ask_presence_rate` = 0.829
- `bid_ask_indep_p` = 9.46801e-09

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 2` |
| Ask formula | `floor(fv - 0.5) + 4` |
| Offset type | fixed |
| Offset band (bid) | [-3.50, -2.50] |
| Offset band (ask) | [2.50, 3.50] |
| Volume | empirical, range [6, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.858 |
| Presence (ask rate) | 0.839 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.76361
- `bid_presence_rate` = 0.858
- `ask_presence_rate` = 0.839
- `bid_ask_indep_p` = 5.57225e-07

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:12:26Z
