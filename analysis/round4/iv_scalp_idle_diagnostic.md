# IV-Scalp Idle-Phase Diagnostic (V2 params, 10K-tick replay)
**Question:** is the IV-scalp gate (`switch_mean >= 1.0865`) frequently OFF on full 10K-tick days? If yes, a subordinate Mark-counterparty fallback could pick up PnL during idle stretches.
Source data: `data/prosperity4/round4/prices_round_4_day_{1,2,3}.csv`. Re-uses the exact V2 tuned constants from `traders/round4/submission.py` and computes online state in lock-step.

## Day 1 (10000 ticks)
| Voucher | Active% | Idle% | Trigger fires | Longest idle | #idle runs | Mean idle run | Max switch_mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 4.3% | 95.7% | 62 | 9519 | 2 | 4783.5 | 2.770 |
| VEV_5100 | 5.2% | 94.8% | 246 | 9436 | 2 | 4739.0 | 3.865 |
| VEV_5200 | 5.7% | 94.3% | 344 | 9389 | 2 | 4714.0 | 4.728 |
| VEV_5300 | 5.8% | 94.2% | 370 | 9382 | 2 | 4712.0 | 4.831 |
| VEV_5400 | 5.1% | 94.9% | 373 | 9443 | 2 | 4744.5 | 4.313 |
| VEV_5500 | 4.3% | 95.7% | 329 | 9516 | 2 | 4784.5 | 3.306 |

**All-vouchers-idle ticks**: 9421 of 10000 (94.2%) — i.e. for that fraction of the day, NO voucher has the gate open, so a subordinate Mark fallback could fire freely.

**Idle % per decile of the day** (tick range divided into 10 equal buckets, % of bucket where gate is OFF):

| Voucher | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 56% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5100 | 47% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5200 | 42% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5300 | 42% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5400 | 48% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5500 | 56% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

## Day 2 (10000 ticks)
| Voucher | Active% | Idle% | Trigger fires | Longest idle | #idle runs | Mean idle run | Max switch_mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 4.1% | 95.9% | 64 | 9545 | 2 | 4796.5 | 2.922 |
| VEV_5100 | 5.3% | 94.7% | 233 | 9429 | 2 | 4735.0 | 4.254 |
| VEV_5200 | 6.0% | 94.0% | 355 | 9360 | 2 | 4698.0 | 5.416 |
| VEV_5300 | 5.9% | 94.1% | 400 | 9372 | 2 | 4704.5 | 5.457 |
| VEV_5400 | 5.5% | 94.5% | 415 | 9409 | 2 | 4723.5 | 4.896 |
| VEV_5500 | 4.9% | 95.1% | 360 | 9462 | 2 | 4753.0 | 3.833 |

**All-vouchers-idle ticks**: 9396 of 10000 (94.0%) — i.e. for that fraction of the day, NO voucher has the gate open, so a subordinate Mark fallback could fire freely.

**Idle % per decile of the day** (tick range divided into 10 equal buckets, % of bucket where gate is OFF):

| Voucher | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 59% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5100 | 47% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5200 | 39% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5300 | 40% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5400 | 44% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5500 | 50% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

## Day 3 (10000 ticks)
| Voucher | Active% | Idle% | Trigger fires | Longest idle | #idle runs | Mean idle run | Max switch_mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 3.7% | 96.3% | 27 | 9576 | 2 | 4813.0 | 2.671 |
| VEV_5100 | 5.1% | 94.9% | 208 | 9451 | 2 | 4746.0 | 4.118 |
| VEV_5200 | 6.1% | 93.9% | 365 | 9350 | 2 | 4693.5 | 5.507 |
| VEV_5300 | 6.5% | 93.5% | 447 | 9317 | 2 | 4675.5 | 6.256 |
| VEV_5400 | 5.9% | 94.1% | 446 | 9373 | 2 | 4704.5 | 5.903 |
| VEV_5500 | 5.1% | 94.9% | 390 | 9453 | 2 | 4746.5 | 4.701 |

**All-vouchers-idle ticks**: 9351 of 10000 (93.5%) — i.e. for that fraction of the day, NO voucher has the gate open, so a subordinate Mark fallback could fire freely.

**Idle % per decile of the day** (tick range divided into 10 equal buckets, % of bucket where gate is OFF):

| Voucher | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| VEV_5000 | 62% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5100 | 49% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5200 | 38% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5300 | 35% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5400 | 40% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| VEV_5500 | 49% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

## Verdict

- Across all 3 days: **28168/30000 = 93.9% of ticks have ALL six vouchers idle simultaneously**.
- `VEV_5000`: idle 28786/30000 = 96.0% of all ticks.
- `VEV_5100`: idle 28440/30000 = 94.8% of all ticks.
- `VEV_5200`: idle 28211/30000 = 94.0% of all ticks.
- `VEV_5300`: idle 28184/30000 = 93.9% of all ticks.
- `VEV_5400`: idle 28345/30000 = 94.5% of all ticks.
- `VEV_5500`: idle 28568/30000 = 95.2% of all ticks.
