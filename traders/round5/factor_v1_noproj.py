"""Round 5 factor-neutral residual-alpha trader (v1).

Strategy
========
For each asset i:
  fv_i  = EMA of mid_price (half-life HL ticks)
  alpha_i = clip((fv_i - mid_i) / sigma_i, -ALPHA_CAP, +ALPHA_CAP)
  raw target position = round(KAPPA * alpha_i), clipped to [-10, +10]

Then we project the raw target vector onto the null space of:
  - 3 stable PCA factors (snackpack triplet, pebble basket, CHOC/VAN pair)
  - 1 dollar-neutral row (current per-asset mid prices)

The projection makes the portfolio's exposure to each of those factors zero
(in dollar variance terms) at every tick. What remains in the position vector
is the residual-alpha portfolio.

Execution
---------
Once we have a target_i, the desired trade is delta_i = target_i - position_i.
We close the gap with a directional limit order at penny-jump price
(best_bid + 1 for buys, best_ask - 1 for sells), capped by the position-limit
worst-case math (Î£ buys â‰¤ 10 - position, Î£ sells â‰¤ 10 + position).

State persistence: traderData = JSON dict {symbol: fair_value} so EMAs survive
across ticks.

Parameters (v1, conservative defaults):
  HL_TICKS  = 1500   # EMA half-life â€” close to median OU half-life
  KAPPA     = 4.0    # alpha-to-position scale (max alpha 3 â†’ Â±12 â†’ clipped to Â±10)
  ALPHA_CAP = 3.0    # cap absolute alpha at 3Ïƒ
  N_FACTORS = 3      # PCA factors to neutralise (PC4 borderline-stable, dropped)
  PROJ_PASSES = 5    # alternating-projection iterations
  MIN_DELTA = 1      # don't trade if |target - pos| < 1
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState


# ---------------------------------------------------------------------------
# Embedded factor-model constants (auto-generated; see analysis/round5/FACTOR_MODEL.md)
# ---------------------------------------------------------------------------
FACTOR_LABELS = ('triplet', 'pebble_basket', 'choc_van_pair', 'mixed')

ASSETS = (
    'GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES',
    'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS',
    'GALAXY_SOUNDS_SOLAR_FLAMES', 'SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON',
    'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
    'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE', 'PEBBLES_XS', 'PEBBLES_S',
    'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL', 'ROBOT_VACUUMING',
    'ROBOT_MOPPING', 'ROBOT_DISHES', 'ROBOT_LAUNDRY', 'ROBOT_IRONING',
    'UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE', 'UV_VISOR_RED',
    'UV_VISOR_MAGENTA', 'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK',
    'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST',
    'TRANSLATOR_VOID_BLUE', 'PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4',
    'PANEL_2X4', 'PANEL_4X4', 'OXYGEN_SHAKE_MORNING_BREATH',
    'OXYGEN_SHAKE_EVENING_BREATH', 'OXYGEN_SHAKE_MINT',
    'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC', 'SNACKPACK_CHOCOLATE',
    'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY',
    'SNACKPACK_RASPBERRY',
)
N_ASSETS = 50
ASSET_IDX = {s: i for i, s in enumerate(ASSETS)}

# Per-asset 1-tick mid-diff std (raw $ price units, days 2/3/4 historical)
SIGMA = (
    10.2457, 11.4797, 10.8791, 10.5392, 11.0946, 11.4217, 10.7125, 11.8908,
    9.6210, 11.6766, 9.2342, 12.4780, 20.7075, 13.1303, 14.5040, 15.0524,
    15.0203, 15.1336, 15.0255, 30.3142, 9.2356, 11.1458, 17.7795, 9.8223,
    10.4437, 11.0062, 8.0050, 10.4606, 11.0305, 11.2025, 9.4238, 9.4489,
    9.8573, 10.1300, 10.8332, 9.0543, 9.5962, 9.4831, 11.2892, 9.9571,
    10.1008, 10.9833, 9.8836, 10.8903, 12.0146, 6.5756, 6.5131, 5.2378,
    8.1330, 8.0918,
)

# B_EXPOSURE[k][i] = sigma_i * V_corr[k, i] â€” exposure of asset i to factor k
# (variance contribution per unit position, in $).
# Source: PCA on tick-tick mid diffs, days 2/3/4 (corr-PCA).
B_EXPOSURE_FULL: Tuple[Tuple[float, ...], ...] = (
    # PC1 â€” snackpack triplet (PIS / STRAW / RASP)
    (-0.04242, -0.05476, -0.16199, -0.04178, -0.07688, +0.07810, -0.03242,
     -0.03790, +0.04405, -0.05963, +0.06564, +0.01192, -0.03342, +0.07121,
     -0.00934, +0.01178, +0.01504, +0.13286, -0.11489, -0.06517, -0.04491,
     +0.16316, +0.04435, +0.00442, -0.01082, -0.05234, -0.05905, -0.11866,
     -0.17184, -0.14832, -0.04379, -0.14695, -0.12591, +0.01089, -0.09352,
     -0.08029, -0.02922, -0.02901, -0.03665, -0.01197, +0.00378, -0.00843,
     -0.04003, -0.08570, +0.03752, +0.04689, -0.15026, -2.98459, -4.79197,
     +4.61541),
    # PC2 â€” pebble basket (XL vs M/L/XS/S)
    (-0.11663, -0.00563, -0.05082, +0.14079, -0.02964, +0.11567, +0.00687,
     +0.04705, -0.04170, -0.01290, +0.06882, +0.04656, -0.13081, +0.03864,
     +0.05485, -5.27525, -5.21843, -5.53792, -5.31365, +21.25512, +0.08053,
     +0.00441, -0.09549, -0.00715, -0.00712, -0.09703, -0.05817, +0.10129,
     +0.15740, -0.07108, +0.05235, +0.02292, -0.10692, -0.08099, +0.15382,
     -0.08394, -0.09172, +0.02224, -0.10031, +0.03062, +0.04866, -0.04137,
     -0.02529, +0.01701, -0.09125, -0.28754, +0.28920, -0.01735, -0.01641,
     +0.01195),
    # PC3 â€” snackpack CHOC/VAN pair
    (+0.03997, +0.11265, +0.06184, +0.10426, +0.04659, +0.01816, +0.01435,
     +0.08578, +0.08922, +0.09054, -0.00010, +0.03755, +0.22334, +0.04241,
     -0.19217, -0.04138, -0.34663, -0.61386, -0.32681, +1.33187, -0.00175,
     +0.03601, +0.10585, +0.00648, +0.06072, +0.03766, +0.02055, -0.03155,
     +0.12881, -0.07385, -0.09250, -0.07362, +0.04298, +0.13034, -0.07736,
     -0.08032, +0.04337, +0.08547, -0.00716, -0.08370, +0.11868, -0.01879,
     -0.21404, +0.07273, +0.05418, +4.63716, -4.58363, +0.06465, +0.10583,
     -0.08923),
    # PC4 â€” weak broad mixed factor (borderline stable, kept commented for reference)
    # (-2.20988, -2.27509, -1.96213, -1.92700, -2.13531, ...)
)

# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------
POS_LIMIT = 10
HL_TICKS = 1500           # EMA half-life
EMA_ALPHA = 1.0 - 2.0 ** (-1.0 / HL_TICKS)
KAPPA = 4.0               # alpha-to-position scale
ALPHA_CAP = 3.0           # cap |alpha| at 3 sigma
MIN_DELTA = 1             # don't trade for |target - pos| < this
PROJ_PASSES = 5           # iterative projection passes (clip-then-reproject)
N_FACTORS_USED = 0        # use first 3 stable PCs (drop PC4)


# ---------------------------------------------------------------------------
# Linear-algebra helpers (pure Python â€” keeps the file dependency-light)
# ---------------------------------------------------------------------------
def _mat_mul(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    rows_A, cols_A = len(A), len(A[0])
    cols_B = len(B[0])
    out = [[0.0] * cols_B for _ in range(rows_A)]
    for i in range(rows_A):
        Ai = A[i]
        for k in range(cols_A):
            a = Ai[k]
            if a == 0.0:
                continue
            Bk = B[k]
            outi = out[i]
            for j in range(cols_B):
                outi[j] += a * Bk[j]
    return out


def _mat_vec(A: List[List[float]], x: List[float]) -> List[float]:
    return [sum(A[i][j] * x[j] for j in range(len(x))) for i in range(len(A))]


def _solve_linsys(A: List[List[float]], b: List[float]) -> List[float]:
    """Solve A x = b for square A via Gauss-Jordan with partial pivoting.
    A and b are mutated."""
    n = len(A)
    # augment
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        # pivot
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            # singular; fall back to zero solution
            return [0.0] * n
        M[col], M[pivot] = M[pivot], M[col]
        # normalize pivot row
        inv_p = 1.0 / M[col][col]
        for j in range(col, n + 1):
            M[col][j] *= inv_p
        # eliminate other rows
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                M[r][j] -= factor * M[col][j]
    return [M[i][n] for i in range(n)]


def project_to_null_space(p: List[float], B: List[List[float]]) -> List[float]:
    """Return p - B^T (B B^T)^(-1) (B p). I.e. orthogonal projection onto null(B).

    B is K x N, p is length N. K << N (here K=4)."""
    K = len(B)
    N = len(p)
    # g = B p  (length K)
    g = [sum(B[k][i] * p[i] for i in range(N)) for k in range(K)]
    # M = B B^T (K x K)
    BBT = [[sum(B[k1][i] * B[k2][i] for i in range(N)) for k2 in range(K)] for k1 in range(K)]
    # solve M x = g  (length K)
    x = _solve_linsys(BBT, g)
    # adjustment: a_i = -sum_k B[k,i] * x[k]
    return [p[i] - sum(B[k][i] * x[k] for k in range(K)) for i in range(N)]


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        # ---- 1. Restore EMA state from traderData ----
        try:
            fv_state: Dict[str, float] = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            fv_state = {}

        # ---- 2. Update EMAs and gather mids ----
        mids: Dict[str, float] = {}
        for sym in ASSETS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            mid = 0.5 * (best_bid + best_ask)
            mids[sym] = mid
            if sym in fv_state:
                fv_state[sym] = (1.0 - EMA_ALPHA) * fv_state[sym] + EMA_ALPHA * mid
            else:
                fv_state[sym] = mid  # initialise

        # ---- 3. Compute alpha and raw target position per asset ----
        raw_target = [0.0] * N_ASSETS
        for i, sym in enumerate(ASSETS):
            mid = mids.get(sym)
            if mid is None:
                continue
            fv = fv_state[sym]
            sigma = SIGMA[i]
            if sigma <= 0:
                continue
            z = (fv - mid) / sigma
            if z > ALPHA_CAP:
                z = ALPHA_CAP
            elif z < -ALPHA_CAP:
                z = -ALPHA_CAP
            t = KAPPA * z
            if t > POS_LIMIT:
                t = POS_LIMIT
            elif t < -POS_LIMIT:
                t = -POS_LIMIT
            raw_target[i] = t

        # ---- 4. Build dollar-neutral row from current mids ----
        dollar_row = [mids.get(s, 10000.0) for s in ASSETS]
        # Scale dollar row down so its norm is comparable to PCA loadings
        max_abs = max(abs(x) for x in dollar_row) or 1.0
        dollar_row = [x / max_abs for x in dollar_row]

        # ---- 5. Iterative projection: project, clip, re-project ----
        B = [list(B_EXPOSURE_FULL[k]) for k in range(N_FACTORS_USED)]
        B.append(dollar_row)  # K = N_FACTORS_USED + 1 rows

        target = list(raw_target)
        for _ in range(PROJ_PASSES):
            target = project_to_null_space(target, B)
            # clip and check whether anything was clipped
            clipped = False
            for i in range(N_ASSETS):
                if target[i] > POS_LIMIT:
                    target[i] = float(POS_LIMIT)
                    clipped = True
                elif target[i] < -POS_LIMIT:
                    target[i] = float(-POS_LIMIT)
                    clipped = True
            if not clipped:
                break

        # Round to int for orders
        target_int = [int(round(t)) for t in target]
        for i in range(N_ASSETS):
            if target_int[i] > POS_LIMIT:
                target_int[i] = POS_LIMIT
            elif target_int[i] < -POS_LIMIT:
                target_int[i] = -POS_LIMIT

        # ---- 6. Generate orders to close gap toward target ----
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        for i, sym in enumerate(ASSETS):
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            if best_ask - best_bid < 2:
                continue  # market too tight, skip penny-jump
            pos = state.position.get(sym, 0)
            tgt = target_int[i]
            delta = tgt - pos
            if abs(delta) < MIN_DELTA:
                continue
            orders: List[Order] = []
            if delta > 0:
                # Buy: cap by worst-case BUY budget = POS_LIMIT - pos
                qty = min(delta, POS_LIMIT - pos)
                if qty > 0:
                    orders.append(Order(sym, best_bid + 1, qty))
            else:
                # Sell: cap by worst-case SELL budget = POS_LIMIT + pos
                qty = min(-delta, POS_LIMIT + pos)
                if qty > 0:
                    orders.append(Order(sym, best_ask - 1, -qty))
            if orders:
                result[sym] = orders

        # ---- 7. Persist EMA state ----
        trader_data = json.dumps(fv_state, separators=(",", ":"))
        return result, 0, trader_data
