# Prosperity4 Optimizer

Study-based parameter optimization over Monte Carlo simulated PnL. Built on
Optuna. Designed to stay useful across rounds, products, and trader rewrites —
the trader contract is minimal and the study format is declarative.

## Quick start

```bash
# One-time: install the project so `prosperity4opt` is on PATH.
pip install -e .

# Run the reference study.
prosperity4opt studies/demo_osmium.yaml --n-trials 40 --n-jobs 4 --fresh

# Browse results in the dashboard — starts the visualizer with the Optimize tab.
./run.sh           # or .\run.ps1 on Windows
# Open http://localhost:5555/optimize
```

Outputs land under `tmp/optimizer/<study_name>/`:

- `study.db` — Optuna SQLite storage (resumable, browsable with `optuna-dashboard`)
- `results.parquet` — wide table of every trial + params + metrics for ad-hoc analysis
- `top_trials.csv` — top-K trials sorted by objective (by `test_score` when splits enabled, else training `value`)
- `retest.json` — end-of-study test metrics for the top-K (when `sim.test_sessions > 0`)
- `validators.json` — DSR, PBO, cluster stability, fANOVA importance
- `trials/trial_NNNNN/` — per-trial `session_summary.csv`, `run_summary.csv`, `stdout.log`, and (if retested) `test/session_summary.csv`

## Trader contract

For the optimizer to tune a trader, the trader must source its tunable
constants from a dict that's merged with `PROSPERITY_PARAMS` (a JSON object in
an env var). Copy this snippet into any trader you want to optimize:

```python
import json, os

def _load_param_overrides():
    raw = os.environ.get("PROSPERITY_PARAMS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

class Trader:
    PARAMS = {
        "MAKE_SPREAD":   3,
        "TAKE_EDGE":     2,
        "SOFT_POS_CAP": 40,
    }

    def __init__(self):
        self.p = {**self.PARAMS, **_load_param_overrides()}

    def run(self, state):
        spread = self.p["MAKE_SPREAD"]
        ...
```

Portal submissions: the env var is never set → `self.p` equals `PARAMS`. So
the same file is submittable and tunable. No conditional logic, no sidecar
files, no build step.

## Study YAML schema

```yaml
name: <study-id>                  # storage dir name under tmp/optimizer/
trader: <path/to/trader.py>       # single-file submission (contract above)

sim:
  # --- single-budget form (no out-of-sample) ---
  sessions: <int>                 # MC sessions per trial (default 100)

  # --- split-budget form (Phase 2: train/val/test, OOS reporting) ---
  # If BOTH train_sessions and val_sessions are > 0, one MC subprocess per
  # trial runs (train+val) sessions and the result is sliced. The Optuna
  # sampler only sees the train score; val is a per-trial OOS sanity check.
  # `test_sessions` is NOT run per-trial — only at end-of-study, top-K
  # trials are re-run on a fresh `test_seed` for the honest headline number.
  train_sessions: <int>
  val_sessions:   <int>
  test_sessions:  <int>           # 0 = skip end-of-study retest
  test_seed:      <int?>          # defaults to sim.seed + 10_000_019 (disjoint from training)

  ticks_per_day: <int?>           # 10000 = portal final-eval scale (default)
  seed: <int?>                    # base RNG seed for training MC
  quote_fraction: <float?>        # 0.8 loser / 1.25 MAF winner (R2)
  maf_bid: <int?>                 # deducted from total PnL per session
  fv_mode: simulate | replay
  trade_mode: simulate | replay-times
  flags:                          # per-asset flags (no leading --)
    intarian-pepper-root-start-fv: 13000

params:                           # search space
  MAKE_SPREAD:    { type: int,   low: 1,    high: 8 }
  EDGE_THRESH:    { type: float, low: 0.05, high: 0.30, log: false }
  MIN_COUNT:      { type: int,   low: 100,  high: 1000, log: true }
  STRATEGY_FLAG:  { type: categorical, choices: [a, b, c] }

constraints:                      # Python expressions over param names
  - "OFFSET_1 < OFFSET_2"

objective:                        # scalar, always maximized
  # shorthand forms:
  #   mean_pnl
  #   { metric: sharpe }
  # full form:
  terms:
    - { name: mean_pnl, weight: 1.0 }
    - { name: cvar_5,   weight: 0.1 }   # value is bottom-5% mean; + weight = prefer higher
    - { name: "mean_pnl[ASH_COATED_OSMIUM]", weight: 0.0 }  # reported, not scored

search:
  sampler: tpe                    # random | tpe | cmaes | qmc
  n_trials: 200
  n_jobs: 4                       # concurrent trials (each spawns its own MC subprocess)
  seed: 42                        # sampler seed (reproducibility)
  sampler_options:
    n_startup_trials: 20          # TPE warmup via random/LHS-like design

report:
  top_k: 10
```

### Available metrics

Registered in `optimizer/objective.py::METRIC_REGISTRY`:

| Name              | Meaning                                                   |
| ----------------- | --------------------------------------------------------- |
| `mean_pnl`        | Mean total PnL across sessions                            |
| `median_pnl`      | Median total PnL                                          |
| `std_pnl`         | Sample std of total PnL                                   |
| `sharpe`          | `mean_pnl / std_pnl` (per-session, not annualized)        |
| `cvar_5`          | Mean of bottom-5% session PnL (tail loss)                 |
| `cvar_10`         | Mean of bottom-10% session PnL                            |
| `min_pnl`         | Worst session                                             |
| `p05_pnl`         | 5th percentile session PnL                                |
| `mean_pnl[SYM]`   | Mean PnL for a specific symbol (e.g. `mean_pnl[OSMIUM]`)  |

Add a metric by writing `(TrialResult) -> float` in `objective.py` and
registering it in `METRIC_REGISTRY`.

### Samplers

| Name     | Use when                                                                 |
| -------- | ------------------------------------------------------------------------ |
| `random` | Baseline, fully parallel, no assumptions about landscape                 |
| `tpe`    | Default. Multivariate TPE with LHS-like startup. Strong for mixed spaces |
| `cmaes`  | Smooth continuous landscapes, no categoricals                            |
| `qmc`    | Quasi-random space-filling (Sobol by default) — good as a warmup         |

## CLI

```
prosperity4opt STUDY_FILE [OPTIONS]

  --n-trials INT        Override search.n_trials
  --n-jobs INT          Override search.n_jobs
  --sessions INT        Override sim.sessions (for dev iteration)
  --name TEXT           Override study name (storage dir)
  --storage-root PATH   Root dir for study storage (default tmp/optimizer/)
  --fresh               Start a fresh run (stamps timestamp into name to avoid
                        resuming from existing SQLite)
```

## Anti-overfitting diagnostics (`validators.json`)

When a study finishes, four independent checks run against the final trial
set. Results go to console + `validators.json`. None of these gate the
optimizer — they're warning lights for the human reading the report.

### Deflated Sharpe Ratio (DSR)

Corrects the best trial's in-sample Sharpe for multiple-testing bias. Output
is `P(true Sharpe > 0)` after accounting for how many configurations the
sampler tried, the non-normality of returns (skew + excess kurtosis), and
the sample size.

- **PASS**: `P >= 0.95` — winner is statistically meaningful.
- **FLAG**: `P < 0.95` — winner's Sharpe is within what you'd expect from
  searching this many trials under the null.

Reference: Bailey & López de Prado (2014).

### Probability of Backtest Overfitting (PBO) via CSCV

Splits the per-session PnL matrix into random disjoint halves. For each
partition: find the best trial on half A, record its rank on half B. PBO =
fraction of partitions where the in-sample winner ranks below median OOS.

- **PASS**: `PBO < 0.25` — winners generalize.
- **CAUTION**: `0.25 <= PBO < 0.5` — treat winners as one candidate, not the answer.
- **FAIL**: `PBO >= 0.5` — severe overfitting. Throw the study out.

Reference: Bailey, Borwein, López de Prado & Zhu (2014).

### Cluster stability

Ratio of median pairwise Euclidean distance in top-K trials vs a random-K
sample, in z-scored numeric-param space. `ratio < 1` = top-K tighter than
random → robust basin. `ratio > 1` = winners scattered → each is a noisy
local peak. Categorical params are skipped.

### fANOVA param importance

Optuna's built-in `get_param_importances`. Variance of the objective
decomposed across params, normalized to sum 1. Params with near-zero
importance can be frozen in future studies — you're burning trials on
knobs that don't move the dial.

## Train/val/test caveats

Two things worth knowing:

1. **Same-seed across trials is intentional.** The training MC uses one
   `sim.seed` for every trial — the Common Random Numbers technique. It
   drastically reduces variance in trial-vs-trial comparison, so small
   param effects are easier to detect. Different seeds would give broader
   market coverage but noisier comparison.

2. **Val is not a fresh sample.** With splits enabled, train and val come
   from the same MC subprocess (sessions [0, n_train) and [n_train, n_train
   + n_val)). Sessions are IID draws, so the slice is statistically sound,
   but val is not a re-run on different markets — it's a held-out fraction
   of the same simulation. For honest OOS, use `test_sessions` (runs on a
   disjoint `test_seed`).

3. **PBO operates on the training PnL matrix** — it measures whether
   trial rankings are robust across session halves within the training
   budget. That's the right thing statistically: it diagnoses whether the
   sampler's winners are reliable under the evaluation it saw.

## Parallelism notes

Trials run on `n_jobs` threads. Each thread spawns one `prosperity4mcbt`
subprocess. The Rust MC internally multi-threads across sessions. Physical
core budget:

```
n_jobs × (rust threads per run) ≤ physical cores
```

For 8-core machines: `n_jobs=4` with the default Rust threading works well.
Push `n_jobs` higher only if you see idle CPU at runtime.

## Roadmap

Phase 1 (shipped):
- ✅ ParamSpace + constraints
- ✅ Trader contract + env-var injection
- ✅ MC subprocess runner (parallel-safe, per-trial dirs)
- ✅ Metric registry + composite objectives
- ✅ Optuna samplers (random / TPE / CMA-ES / QMC)
- ✅ SQLite storage + Parquet + CSV reports
- ✅ `prosperity4opt` CLI + YAML schema

Phase 2 (shipped):
- ✅ Train/val/test seed splits — honest out-of-sample reporting via end-of-study retest
- ✅ Deflated Sharpe Ratio (DSR) with multiple-testing correction
- ✅ Probability of Backtest Overfitting (PBO / CSCV)
- ✅ Cluster-stability check over top-K winners
- ✅ fANOVA param-importance export

Phase 3 (shipped):
- ✅ "Optimize" tab in the visualizer reading the study dir
- ✅ Study picker + validators card (DSR / PBO / cluster / importance verdicts)
- ✅ Convergence chart (trial score + best-so-far + OOS test overlay)
- ✅ Param importance bar chart (fANOVA)
- ✅ Per-param marginal effect scatters (one chart per numeric param)
- ✅ 2D slice scatter — any (x, y) param pair, coloured by objective
- ✅ Top-K trials table with train/val/test columns

Phase 4:
- Resume-from-crash hardening (trial checkpointing)
- Distributed workers (multi-machine via shared SQLite or Redis)
- Multi-objective NSGA-II for Pareto fronts
