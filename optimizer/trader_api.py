"""Trader param-injection contract.

**For the optimizer**: this module provides `load_param_overrides()`, which the
optimizer does not call directly — it is the shared implementation that
traders embed (verbatim, by copy-paste) to honour the contract.

**For traders**: submission files can't import from this repo (single-file
constraint), so traders embed the tiny loader below as a standalone function.
The canonical snippet is in the module docstring of `optimizer.trader_api` and
also in `optimizer/README.md` under "Trader contract".

The contract
============

1. The `Trader` class defines a `PARAMS` dict with the defaults used when no
   overrides are present (i.e. in portal submissions).

2. `Trader.__init__` merges `os.environ["PROSPERITY_PARAMS"]` (a JSON object)
   on top of `PARAMS` and exposes the result as `self.p`.

3. All tunable constants in `run()` are read from `self.p["..."]`, never from
   class attributes or magic numbers.

Example trader skeleton::

    import json, os

    def _load_param_overrides() -> dict:
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
            "SIGNAL_EDGE_ON":  0.16,
            "ACO_SOFT_POS":    30,
        }

        def __init__(self):
            self.p = {**self.PARAMS, **_load_param_overrides()}

        def run(self, state):
            edge_on = self.p["SIGNAL_EDGE_ON"]
            ...

The env var is used rather than a sidecar file so parallel optimizer workers
can each run a different point in param space without fighting over a shared
`params.json`.
"""

from __future__ import annotations

import json
import os
from typing import Any

ENV_VAR = "PROSPERITY_PARAMS"


def load_param_overrides() -> dict[str, Any]:
    """Reference implementation of the loader. Traders embed their own copy."""
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def encode_overrides(params: dict[str, Any]) -> str:
    """Serialize a param dict for the env var. Used by the MC runner."""
    return json.dumps(params, separators=(",", ":"), sort_keys=True)
