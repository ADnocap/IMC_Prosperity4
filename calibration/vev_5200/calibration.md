# VEV_5200 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.0001 |
| drift | 0 |
| sigma | 0.627381 |
| mean | 101.283 |
| n_ticks | 999 |
| residual Ljung p | 0.4551 |
| residual skew z | 1.226 |
| residual kurt z | -1.197 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 1` |
| Ask formula | `floor(fv - 0.5) + 3` |
| Offset type | fixed |
| Offset band (bid) | [-2.50, -1.50] |
| Offset band (ask) | [1.50, 2.50] |
| Volume | empirical, range [12, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.754 |
| Presence (ask rate) | 0.781 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.158582
- `bid_presence_rate` = 0.754
- `ask_presence_rate` = 0.781
- `bid_ask_indep_p` = 3.33067e-15

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv + 0.5) - 1` |
| Ask formula | `floor(fv - 0.5) + 2` |
| Offset type | fixed |
| Offset band (bid) | [-1.50, -0.50] |
| Offset band (ask) | [0.50, 1.50] |
| Volume | empirical, range [2, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.509 |
| Presence (ask rate) | 0.478 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.921053
- `bid_presence_rate` = 0.509
- `ask_presence_rate` = 0.478
- `bid_ask_indep_p` = 0

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:13:32Z
