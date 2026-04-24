# VEV_4500 Calibration

Round 3 product. Calibrated by `calibration/run_pipeline.py`
(Python port of the visualizer 9-stage pipeline).

**Position limit:** 300

## Fair Value process

| Property | Value |
|---|---|
| Type | random_walk |
| quantization | 0.00390625 |
| drift | 0 |
| sigma | 0.958338 |
| mean | 762.383 |
| n_ticks | 999 |
| residual Ljung p | 0.4422 |
| residual skew z | 1.226 |
| residual kurt z | -1.387 |

## Bot `layer1` — Layer 1 (outer)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 9` |
| Ask formula | `round(fv * (1 + 1.3155e-02))` |
| Offset type | proportional |
| Offset band (bid) | [-10.50, -9.50] |
| Offset band (ask) | [9.50, 11.50] |
| Volume | empirical, range [12, 24] |
| Sides tied | True |
| Presence (bid rate) | 0.927 |
| Presence (ask rate) | 0.971 |
| Presence model (bid) | iid_bernoulli |
| Presence model (ask) | deterministic |

Diagnostics:

- `bid_vol_uniform_p` = 0.0441596
- `ask_vol_uniform_p` = 0.140645
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.927
- `ask_presence_rate` = 0.971
- `bid_ask_indep_p` = 1

## Bot `layer2` — Layer 2 (outer)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 8` |
| Ask formula | `floor(fv - 0.5) + 10` |
| Offset type | fixed |
| Offset band (bid) | [-9.50, -8.50] |
| Offset band (ask) | [8.50, 9.50] |
| Volume | empirical, range [6, 24] |
| Sides tied | False |
| Presence (bid rate) | 0.141 |
| Presence (ask rate) | 0.168 |
| Presence model (bid) | iid_bernoulli |
| Presence model (ask) | empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0
- `ask_vol_uniform_p` = 0
- `sides_tied_rate` = 0
- `bid_presence_rate` = 0.141
- `ask_presence_rate` = 0.168
- `bid_ask_indep_p` = 0.521043

## Bot `layer3` — Layer 3 (inner)

| Property | Value |
|---|---|
| Bid formula | `floor(fv - 0.5) - 7` |
| Ask formula | `floor(fv - 0.5) + 9` |
| Offset type | fixed |
| Offset band (bid) | [-8.50, -7.50] |
| Offset band (ask) | [7.50, 8.50] |
| Volume | empirical, range [6, 12] |
| Sides tied | True |
| Presence (bid rate) | 0.885 |
| Presence (ask rate) | 0.854 |
| Presence model (bid) | joint_empirical |
| Presence model (ask) | joint_empirical |

Diagnostics:

- `bid_vol_uniform_p` = 0.0318738
- `ask_vol_uniform_p` = 0.0416947
- `sides_tied_rate` = 1
- `bid_presence_rate` = 0.885
- `ask_presence_rate` = 0.854
- `bid_ask_indep_p` = 2.30959e-05

## Provenance

- **Source**: hold-1 portal submission 364522 + 3-day R3 trade CSVs
- **Pipeline**: `calibration/run_pipeline.py` (Python port of visualizer 9-stage pipeline)
- **Generated**: 2026-04-24T12:11:43Z
