# VEV_5300 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.0001 |
| drift | 0 |
| sigma | 0.400957 |
| mean | 50.0611 |
| n_ticks | 999 |
| residual Ljung p | 0.4530 |
| residual skew z | 1.203 |
| residual kurt z | -1.124 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 1` |
| Ask formula | `floor(fv - 0.75) + 3` |
| Offset type | fixed |
| Offset band (bid) | [-2.50, -1.50] |
| Offset band (ask) | [1.50, 2.50] |
| Volume | empirical, range [10, 30] |
| Sides tied | False |
| Presence (bid rate) | 0.227 |
| Presence (ask rate) | 0.255 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 7.58723e-08
- `ask_vol_uniform_p` = 2.46322e-10
- `sides_tied_rate` = 0
- `bid_presence_rate` = 0.227
- `ask_presence_rate` = 0.255
- `bid_ask_indep_p` = 1.11022e-16

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv + 0.5) - 1` |
| Ask formula | `floor(fv - 0.5) + 2` |
| Offset type | fixed |
| Offset band (bid) | [-1.50, -0.50] |
| Offset band (ask) | [0.50, 1.50] |
| Volume | empirical, range [4, 30] |
| Sides tied | False |
| Presence (bid rate) | 0.917 |
| Presence (ask rate) | 0.896 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.630221
- `bid_presence_rate` = 0.917
- `ask_presence_rate` = 0.896
- `bid_ask_indep_p` = 0.00426924

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:13:59Z
