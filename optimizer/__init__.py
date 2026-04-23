"""Prosperity4 parameter optimization framework.

Study-based hyperparameter tuning over Monte Carlo simulated PnL. Optuna under
the hood, with domain-specific param specs, trader param injection, MC
subprocess orchestration, and statistically honest objective construction.

Public entry point: the `prosperity4opt` CLI. See `optimizer/README.md`.
"""

__version__ = "0.1.0"
