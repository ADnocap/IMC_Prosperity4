# EMERALDS Calibration

Round 0 tutorial product. Stationary, no modelling complexity.

| Property | Value |
|---|---|
| FV process | constant |
| FV value | 10,000 |
| Position limit | 80 |

## Bot layout

- **Bot 1 (outer wall)**: bid = 9,990, ask = 10,010 (±10), volume U(15, 25)
- **Bot 2 (inner wall)**: bid = 9,992, ask = 10,008 (±8), volume U(5, 10)
- **Bot 3 (noise)**: same distribution as TOMATOES Bot 3 — rare single-sided quote inside Bot 2's spread

Volume distributions match TOMATOES bots. See `../tomatoes/` for the full distributional analysis that applies here too.

## Strategy

Fixed-fair-value market making at 10,000 ± spread. No scripts required — a one-line FV rule is enough.
