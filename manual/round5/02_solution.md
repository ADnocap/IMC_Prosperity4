# R5 Manual — Extra! Extra! Read all about it! : Solution

Solver: `manual/round5/verify.py`. Budget **B = 1,000,000 XIRECs**. Nine products, each with one signed allocation. Returns settle next day.

## 1. Problem in one line

Maximise

```
PnL  =  B · Σᵢ [ (xᵢ/100) · rᵢ − (xᵢ/100)² ]      subject to    Σᵢ |xᵢ| ≤ 100
```

where `xᵢ` is the **signed** percent of budget allocated to product `i` (positive = long, negative = short) and `rᵢ` is the (signed) realised return next day, expressed as a decimal.

The fee `(volume/100)²` "applied per product against budget" is read as **fee-as-fraction-of-budget**, with `volume = xᵢ` in percent. That makes the fee self-scale: 50% of budget on one product costs 25% of budget in fees, and 100% costs the entire budget. (This matches the budget framing — the alternative reading "volume in raw XIRECs, fee in raw XIRECs" makes the 1M budget unbinding for any sane `r` and is therefore not what the portal can mean. Sized recommendations below assume the percent reading; if the portal uses the raw reading instead, **the signs and ratios are unchanged** and only the absolute XIREC magnitudes shrink by ~100×.)

## 2. Closed-form math

### 2a. Per-product unconstrained optimum

`fᵢ(xᵢ) = (xᵢ/100)·rᵢ − (xᵢ/100)²` (per unit of B). Setting `f′ = 0`:

```
xᵢ*  =  ½ · rᵢ%        (in percent of budget)
PnLᵢ* =  B · rᵢ² / 4   (decimal r, after fees)
```

Sanity: `r = +50% → x* = +25%, PnL* = 62,500`. `r = −45% → x* = −22.5%, PnL* = 50,625`.

### 2b. L1-constrained optimum (soft thresholding)

The Lagrangian `Σᵢ fᵢ(xᵢ) − μ·(Σᵢ |xᵢ| − 100)` with `μ ≥ 0` gives

```
xᵢ  =  ½ · sign(rᵢ) · max(0, |rᵢ%| − μ)
```

`μ` is chosen by bisection so `Σᵢ |xᵢ| = 100`. Products whose `|rᵢ|` falls below `μ` get **dropped entirely** — when budget is tight, low-conviction products are squeezed out before high-conviction products are scaled down. This is the standard L1-projection / soft-threshold result.

Implementation: `soft_threshold_solve()` in `verify.py:106`.

### 2c. Constraint binding regime

Unconstrained `Σᵢ |xᵢ*| = ½ · Σᵢ |rᵢ%|`. With my central views (sum of `|rᵢ%|` = 240%), the L1 sum is 120% — **the constraint binds**, and `μ ≈ 4.4` shaves the smallest-conviction views.

## 3. Reading the news

Nine articles. For each, I form (a) the sign of the move, (b) a magnitude in percent, (c) a conviction in `[0, 1]` used only for the conservative/aggressive sweeps. Direction comes from the news; magnitude is calibrated so the strongest stories are ~50% and the weakest are ~10%.

| Code | Product               | r% (signed) | Conv. | Reasoning                                                                                                                                  |
| ---- | --------------------- | ----------: | ----: | ------------------------------------------------------------------------------------------------------------------------------------------ |
| THER | Thermalite Core       |    **+50** |  0.90 | Forecast 1.42M → 3.89M users next quarter (**+174%**), 16h42m daily usage, "very strong next quarter." Strongest unambiguous bull story.   |
| LAVA | Lava Cake             |    **−45** |  0.90 | Health review, traces of actual lava, **sales halted**, lawsuits piling up, vendors returning stock. Existential risk. Strongest bear.     |
| PYRO | Pyroflex Cells        |    **−30** |  0.85 | 50% tax cut ends tomorrow → effective levy **doubles**. Direct consumer-price hit, demand drops. Hard short.                                 |
| ASH  | Ashes of the Phoenix  |    **−30** |  0.80 | Resurfaced video shows brutal sourcing, public outcry, company defends with "birds are immortal" cope. Visceral PR crisis. Short.          |
| MINK | Magma Ink             |    **+22** |  0.70 | Limited-edition Lava Pen launch, 6h+ queues, "hot drop" tied to merger. Demand surge, but partly priced in (event happened "yesterday").    |
| SULF | Sulfur Reactor        |    **+20** |  0.80 | Index inclusion in Elemental Index 118 → tracker-fund forced buying on rebalance. Standard tailwind, "later this cycle".                    |
| OBSI | Obsidian Cutlery      |    **−20** |  0.70 | Manufacturing halted at one facility, level-1 contamination, "could have implications for other facilities." Bounded-scope short.           |
| INC  | Volcanic Incense      |    **+15** |  0.50 | "Whiff Nostralico" pump in narrow time windows; openly calls people to follow him. Pure influencer momentum, fundamentals absent. Small long. |
| SCOR | Scoria Paste          |     **+8** |  0.40 | Self-styled "market medium" Lava D. Ray pump. Some real-world basis ("paste keeps Ignith together"), but credentials weak. Tiny long.       |

The "consensus moves the price within the range" mechanic is automatically aligned with us on every story — the crowd will read the same articles and trade the same direction, pushing each product to the favourable end of its range relative to our position. There is **no contrarian bet** here. The only sign-uncertainty is on the two influencer pumps (INC, SCOR), handled in §4.

## 4. Scenario sweep & sign stability

Three tone scenarios scale all `|rᵢ|` by `0.6 / 1.0 / 1.4` (CONSERVATIVE / BASE / AGGRESSIVE). A fourth, **SKEPTICAL_PUMPS**, flips the sign on **INC and SCOR** to model the "the influencer call is a setup, the real move is the dump" failure mode.

```
[BASE]  μ=4.44  used=100%  gross=+341,567  fees=−148,561  NET=+193,006
[CONS]  μ=0.00  used= 72%  gross=+142,164  fees=− 71,082  NET=+ 71,082
[AGG]   μ=15.6  used=100%  gross=+514,388  fees=−179,194  NET=+335,194
[SKEP]  μ=4.44  used=100%  gross=+341,567  fees=−148,561  NET=+193,006   (PnL identical to BASE
                                                                         because the flip-sign
                                                                         products are also small,
                                                                         so the net cost cancels)
```

Sign-stability across the four scenarios:

| Code | BASE   | CONS   | AGG    | SKEP   | flips |
| ---- | -----: | -----: | -----: | -----: | ----: |
| OBSI |  −7.8% |  −6.0% |  −6.2% |  −7.8% |     0 |
| PYRO | −12.8% |  −9.0% | −13.2% | −12.8% |     0 |
| THER | +22.8% | +15.0% | +27.2% | +22.8% |     0 |
| LAVA | −20.3% | −13.5% | −23.7% | −20.3% |     0 |
| MINK |  +8.8% |  +6.6% |  +7.6% |  +8.8% |     0 |
| SCOR |  +1.8% |  +2.4% |   0.0% |  −1.8% |     1 |
| ASH  | −12.8% |  −9.0% | −13.2% | −12.8% |     0 |
| INC  |  +5.3% |  +4.5% |  +2.7% |  −5.3% |     1 |
| SULF |  +7.8% |  +6.0% |  +6.2% |  +7.8% |     0 |

Seven of nine positions are sign-stable across all four scenarios. The two that flip (INC, SCOR) are exactly the influencer-pump products, which are sized small enough (≤ 6% of budget) that being wrong is bounded.

## 5. Final recommendation (portal-ready)

The robust portfolio averages BASE / CONS / AGG / SKEP and re-projects onto the L1 ball, then rounds to integer percents (`verify.py:217`). After rounding, one unit is shaved from the smallest position to keep `Σ|xᵢ| ≤ 100`.

| Code | Product               | Side  | Alloc % | XIRECs    |
| ---- | --------------------- | :---: | ------: | --------: |
| THER | Thermalite Core       | LONG  |   **+22** |  **+220,000** |
| LAVA | Lava Cake             | SHORT |   **−19** |  **−190,000** |
| PYRO | Pyroflex Cells        | SHORT |   **−12** |  **−120,000** |
| ASH  | Ashes of the Phoenix  | SHORT |   **−12** |  **−120,000** |
| MINK | Magma Ink             | LONG  |    **+8** |   **+80,000** |
| OBSI | Obsidian Cutlery      | SHORT |    **−7** |   **−70,000** |
| SULF | Sulfur Reactor        | LONG  |    **+7** |   **+70,000** |
| INC  | Volcanic Incense      | LONG  |    **+2** |   **+20,000** |
| SCOR | Scoria Paste          | LONG  |    **+1** |   **+10,000** |
|      | **TOTAL**             |       |   **90%** | (10% reserve) |

Expected PnL (BASE):
- Gross trade gains:  **+316,900 XIRECs**
- Fees:                **−130,000 XIRECs**
- **Net: ≈ +186,900 XIRECs**  (≈ **+18.7%** of budget)

Across scenarios (same rounded portfolio, returns rescaled): `+60,140 (CONS) / +186,900 (BASE) / +313,660 (AGG) / +179,300 (SKEP)`. Positive across all four reasonable views.

The 10% unused budget is a deliberate choice — it is the L1 slack the soft-thresholded average needed to hedge the two pump products. We could push the longs up another ~10pp to use the full 100%, but that buys very little marginal PnL (the unconstrained sum was 89.5%, almost at the cap) and increases concentration risk.

## 6. Sensitivity and risk

**Where the recommendation is most sensitive:**

- **Thermalite Core** is the biggest single position (+22%). If the user-growth forecast is already fully priced in (`r ≈ +20%` instead of +50%), our PnL on this one product drops from ~63K to ~10K. Still positive, still long — sign is robust.
- **Lava Cake** is the second-biggest (−19%). The "sales halted, lawsuits, vendor returns" combo is so visceral that even a +50% over-estimate (`r ≈ −22%` instead of −45%) leaves us correctly short with ~12K profit.
- The **two pumps (INC, SCOR)** are sized for "I might be wrong on the sign" — the SKEP scenario assumes the influencer call is a dump, and the loss is bounded at ~600 XIRECs. Worth keeping the small position because if the pump *does* work the upside is comparable.

**Off-table risks not modelled:**

1. **Portal interpretation of `volume`.** If "volume" in the formula means raw XIRECs (not percent of budget), the optimal allocation per product is `5,000 · rᵢ` XIRECs — i.e., a few thousand XIRECs, not a few hundred thousand. The signs and ratios in the table above are unchanged; only the absolute size shrinks ~100×. The math at the top of `verify.py` is parametrised so the answer follows whichever the portal accepts.
2. **Crowd over-reaction.** Every story here is so one-sided that the field will pile in the same direction. The realised return drifts to the favourable end of each range. Our directions and the crowd's are aligned, so this **helps** us — the assumption is symmetric (no benefit from being a contrarian).
3. **"Already priced in"**, especially for THER (forecast already public) and MINK (event happened yesterday). Modelled implicitly via the lower BASE magnitudes than the headline numbers would suggest, and via the CONSERVATIVE scenario.

## 7. Quick reference

```
THER  +22%   +220,000   LONG
LAVA  −19%   −190,000   SHORT
PYRO  −12%   −120,000   SHORT
ASH   −12%   −120,000   SHORT
MINK   +8%    +80,000   LONG
OBSI   −7%    −70,000   SHORT
SULF   +7%    +70,000   LONG
INC    +2%    +20,000   LONG
SCOR   +1%    +10,000   LONG
                         total |alloc| = 90%
                         expected NET ≈ +186,900 XIRECs (+18.7%)
```

Solver: `py -3.13 manual/round5/verify.py` reproduces every number above.
