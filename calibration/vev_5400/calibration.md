# VEV_5400 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.0001 |
| drift | 0 |
| sigma | 0.184003 |
| mean | 16.0053 |
| n_ticks | 999 |
| residual Ljung p | 0.3258 |
| residual skew z | 1.350 |
| residual kurt z | -0.657 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv + 0.5) - 1` |
| Ask formula | `floor(fv - 0.5) + 2` |
| Offset type | fixed |
| Offset band (bid) | [-1.50, -0.50] |
| Offset band (ask) | [0.50, 1.50] |
| Volume | empirical, range [10, 30] |
| Sides tied | False |
| Presence (bid rate) | 0.735 |
| Presence (ask rate) | 0.774 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.817647
- `bid_presence_rate` = 0.735
- `ask_presence_rate` = 0.774
- `bid_ask_indep_p` = 0

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `ceil(fv) - 1` |
| Ask formula | `floor(fv - 0.5) + 1` |
| Offset type | fixed |
| Offset band (bid) | [-0.50, 0.50] |
| Offset band (ask) | [-0.50, 0.50] |
| Volume | empirical, range [1, 30] |
| Sides tied | False |
| Presence (bid rate) | 0.319 |
| Presence (ask rate) | 0.262 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0
- `bid_presence_rate` = 0.319
- `ask_presence_rate` = 0.262
- `bid_ask_indep_p` = 0

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:14:17Z
