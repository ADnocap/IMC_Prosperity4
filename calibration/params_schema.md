# Calibration `params.json` Schema

Every calibrated asset has a `calibration/<asset>/params.json` describing the bot model. The Calibration Workshop tab reads this to render the validation dashboard; Stage 8 of the discovery pipeline writes it.

## Top-level shape

```jsonc
{
  "asset": "ASH_COATED_OSMIUM",         // product symbol (must match folder name upper-case)
  "position_limit": 80,                  // for reference; not used in validation
  "fv_process": { ... },
  "bots": [ ... ],                       // variable N — pipeline infers count
  "noise_layer": { ... } | null,         // optional — quotes outside all main clusters
  "trade_bot": { ... } | null,           // optional — needs trades in fv_and_book.json
  "metadata": { ... }                    // calibrated_from, match_rates, notes
}
```

## `fv_process`

```jsonc
{
  "type": "random_walk" | "linear_drift" | "constant" | "ar1",
  "params": {
    "sigma": 0.3117,        // RW / AR1 — innovation std
    "drift": 0.0,           // RW / linear_drift — per-tick mean step
    "mean": 10000.0,        // constant or RW starting level
    "ar1_coef": 0.0,        // AR1 only
    "quantization": 0.0009765625   // detected grid (1/1024 on Prosperity)
  },
  "diagnostics": {          // populated by Stage 0
    "bic": -1234.5,
    "shapiro_p": 0.12,
    "ljung_box_p": 0.34,
    "n_ticks": 1000
  }
}
```

## `bots[]`

Each entry describes one market-maker bot layer. Number of entries is discovered in Stage 1, not fixed.

```jsonc
{
  "id": "bot1",                                // unique string id
  "name": "Outer Wall",                         // human label
  "offset_type": "fixed" | "proportional",
  "bid_formula_str": "floor(fv) - 10",          // human-readable (docs)
  "ask_formula_str": "ceil(fv) + 10",
  "formula_spec": {                             // machine-evaluable form
    "bid": {
      "round_fn": "floor" | "ceil" | "round" | "banker",
      "shift": 0.0,                             // fv + shift before rounding (fixed only)
      "constant": -10,                          // offset added after rounding (fixed only)
      "K": null                                 // proportional coefficient (proportional only)
    },
    "ask": { ... }
  },
  "volume": {
    "distribution": "uniform" | "discrete_normal" | "poisson" | "empirical",
    "low": 20, "high": 30,                      // uniform bounds inclusive
    "mean": null, "std": null,                  // for discrete_normal
    "lambda": null,                             // for poisson
    "pmf": null,                                // {v: p} for empirical
    "sides_tied": true                          // bid_vol == ask_vol per tick when both present
  },
  "presence": {
    "rate": 0.80,                               // P(bot quotes on a given side per tick)
    "iid": true,                                // passes Ljung-Box + runs test
    "bid_ask_independent": true                 // bid ∥ ask χ² passes
  },
  "offset_band": {                              // classification bands used by Stage 1
    "bid": [-20.5, -9.0],                       // (low, high) for bid-side quote offsets from FV
    "ask": [9.0, 20.5]
  },
  "diagnostics": {                              // populated by Stages 2-4
    "bid_match_rate": 0.997, "bid_match_ci": [0.992, 0.999],
    "ask_match_rate": 1.000, "ask_match_ci": [0.995, 1.000],
    "volume_chi2_p": 0.22,
    "presence_ljung_p": 0.49
  }
}
```

### Formula interpretation

For `offset_type == "fixed"`:
```
price = round_fn(fv + shift) + constant
```

For `offset_type == "proportional"` (with side sign `s = -1` for bid, `+1` for ask):
```
price = round_fn(fv * (1 + s * K))
```

## `noise_layer`

```jsonc
{
  "presence_rate": 0.076,              // fraction of ticks with any noise activity
  "single_sided_rate": 1.0,            // fraction of noise events that are single-sided
  "offsets": {                         // empirical offset histograms (from round(fv))
    "bid": {"-3": 0.25, "-2": 0.25, "1": 0.25, "2": 0.25},
    "ask": { ... }
  },
  "crossing_vol": { "distribution": "uniform", "low": 4, "high": 10 },
  "passive_vol":  { "distribution": "uniform", "low": 1, "high": 5 },
  "run_length": { "mean": 1.15, "single_tick_rate": 0.87 }
}
```

## `trade_bot`

```jsonc
{
  "rate_per_tick": 0.04,               // P(≥1 trade on a tick)
  "count_distribution": "poisson" | "empirical",
  "poisson_lambda": 0.04,
  "quantity_model": {
    "type": "uniform" | "bimodal" | "empirical",
    "modes": [
      { "low": 2, "high": 6, "weight": 0.6 },
      { "low": 7, "high": 10, "weight": 0.4 }
    ],
    "pmf": null                        // empirical {q: p}
  }
}
```

## `metadata`

Free-form provenance and summary:

```jsonc
{
  "calibrated_from": "submission 103017 + R1 day 0/1/-1 CSVs (n=30,987 ticks)",
  "pipeline_version": "1.0.0",
  "timestamp": "2026-04-23T14:30:00Z",
  "overall_match_rate": 0.998,
  "fisher_combined_p": 0.41,
  "notes": "..."
}
```
