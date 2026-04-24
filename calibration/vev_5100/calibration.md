# VEV_5100 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.0001 |
| drift | 0 |
| sigma | 0.816726 |
| mean | 174.793 |
| n_ticks | 999 |
| residual Ljung p | 0.4305 |
| residual skew z | 1.223 |
| residual kurt z | -1.308 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 2` |
| Ask formula | `floor(fv - 0.5) + 4` |
| Offset type | fixed |
| Offset band (bid) | [-3.50, -2.50] |
| Offset band (ask) | [2.50, 3.50] |
| Volume | empirical, range [12, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.689 |
| Presence (ask rate) | 0.703 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.842239
- `bid_presence_rate` = 0.689
- `ask_presence_rate` = 0.703
- `bid_ask_indep_p` = 0

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 1` |
| Ask formula | `floor(fv - 0.5) + 3` |
| Offset type | fixed |
| Offset band (bid) | [-2.50, -1.50] |
| Offset band (ask) | [1.50, 2.50] |
| Volume | empirical, range [6, 36] |
| Sides tied | False |
| Presence (bid rate) | 0.746 |
| Presence (ask rate) | 0.763 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.64902
- `bid_presence_rate` = 0.746
- `ask_presence_rate` = 0.763
- `bid_ask_indep_p` = 0

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:13:02Z
