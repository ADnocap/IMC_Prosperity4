# VELVETFRUIT_EXTRACT Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

**Position limit:** 200

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.00390625 |
| drift | 0 |
| sigma | 0.958347 |
| mean | 5262.38 |
| n_ticks | 999 |
| residual Ljung p | 0.4417 |
| residual skew z | 1.226 |
| residual kurt z | -1.387 |

## Bot `layer1` — Layer 1 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.75) - 2` |
| Ask formula | `floor(fv - 0.75) + 5` |
| Offset type | fixed |
| Offset band (bid) | [-4.50, -3.50] |
| Offset band (ask) | [3.50, 4.50] |
| Volume | uniform U(30, 50) |
| Sides tied | True |
| Presence (bid rate) | 0.114 |
| Presence (ask rate) | 0.138 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0.80052
- `ask_vol_uniform_p` = 0.735923
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.114
- `ask_presence_rate` = 0.138
- `bid_ask_indep_p` = 4.50277e-05

## Bot `layer2` — Layer 2 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 2` |
| Ask formula | `floor(fv - 0.5) + 4` |
| Offset type | fixed |
| Offset band (bid) | [-3.50, -2.50] |
| Offset band (ask) | [2.50, 3.50] |
| Volume | empirical, range [15, 75] |
| Sides tied | False |
| Presence (bid rate) | 0.999 |
| Presence (ask rate) | 0.999 |
| Presence model (bid) | deterministic |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0.214214
- `bid_presence_rate` = 0.999
- `ask_presence_rate` = 0.999
- `bid_ask_indep_p` = 1

## Bot `layer3` — Layer 3 (near-FV)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.75) - 1` |
| Ask formula | `floor(fv - 0.5) + 3` |
| Offset type | fixed |
| Offset band (bid) | [-2.50, -1.50] |
| Offset band (ask) | [1.50, 2.50] |
| Volume | uniform U(15, 25) |
| Sides tied | True |
| Presence (bid rate) | 0.403 |
| Presence (ask rate) | 0.384 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0.297756
- `ask_vol_uniform_p` = 0.247909
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.403
- `ask_presence_rate` = 0.384
- `bid_ask_indep_p` = 0

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:10:25Z
