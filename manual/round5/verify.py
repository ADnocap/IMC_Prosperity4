"""R5 "Extra! Extra! Read all about it!" manual challenge solver.

Problem
-------
On the Ignith exchange, you have a one-day budget B = 1,000,000 XIRECs split
across 9 products. For each product i you submit a signed allocation x_i (in
percent of B; positive = long, negative = short), with the L1 budget constraint
    sum_i |x_i|  <=  100   (you may use less than 100%; you may not exceed 100%).

The fee per product is quadratic:
    fee_i  =  (|x_i| / 100)^2   * B    (i.e. (volume/100)^2 applied against budget)
so allocating 50% of budget to one product costs 25% of budget in fees, and
allocating 100% costs the entire budget in fees. This is the strong incentive
to spread risk.

Each product has an unknown next-day return r_i. The portal tells us r_i lives
in a [range_low, range_high] band around an "anchor", and the actual realised
r_i is pushed within that band by the field's aggregate flow ("if everyone is
buying, the realised return drifts to the upper end"). We don't observe the
ranges directly — we read the news and form a view.

Net PnL in XIRECs:
    PnL  =  sum_i  B * [ (x_i / 100) * r_i  -  (x_i / 100)^2 ]
         =  B * sum_i [ y_i * r_i  -  y_i^2 ]              with y_i = x_i / 100

Subject to: sum_i |y_i|  <=  1.

Closed-form unconstrained optimum (per product, ignoring budget):
    d/dy_i [y_i * r_i - y_i^2] = 0   =>   y_i*  =  r_i / 2
    PnL_i*  =  B * r_i^2 / 4
    |x_i|*  =  50 * |r_i|   (in percent of budget)

Constrained solution (Lagrangian on |y|):
    y_i  =  sign(r_i) * max(0,  (|r_i| - lambda) / 2)
where lambda >= 0 is chosen so sum_i |y_i| = 1 (or = 0 if unconstrained sum
already <= 1). Solve by bisection on lambda.

This is "soft thresholding": products whose |r_i| is below the multiplier
lambda get dropped entirely. Conviction matters — the marginal product gets
zero weight when budget is tight.

Strategy
--------
For each of the 9 articles we form a signed expected-return estimate r_i with
a confidence-weighted uncertainty band. We then run the optimisation under
three scenarios:
  - CONSERVATIVE: shrink all |r_i| toward zero (article story partly priced in)
  - BASE:        our central read of the news
  - AGGRESSIVE:  amplified |r_i| (crowd will pile on, return drifts to band edge)

We also flip the sign of a few "trap" articles (Volcanic Incense / Scoria
Paste pump-and-dump) under a "skeptical" scenario where the influencer call
is a setup rather than alpha.

Final recommendation: the BASE-scenario optimum, sanity-checked against the
others for sign stability and rounded to integer percentages so it can be
typed straight into the portal.

Usage:  py -3.13 manual/round5/verify.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


BUDGET = 1_000_000


# ----------------------------------------------------------------------- view
# Central per-article view. r_pct is signed expected return in PERCENT
# (e.g., +30 = +30%, -45 = -45%). conviction is 0..1 weight for sensitivity.

@dataclass
class Product:
    code: str            # short tag
    name: str            # display name
    r_pct: float         # central expected return in percent (signed)
    conviction: float    # 0..1, used for the conservative / aggressive sweeps
    rationale: str       # one-line note for printout

PRODUCTS: list[Product] = [
    Product(
        "OBSI", "Obsidian Cutlery",
        r_pct=-20.0, conviction=0.7,
        rationale="Manufacturing halted, contamination, evacuation. Production loss + regulatory headline risk. SHORT.",
    ),
    Product(
        "PYRO", "Pyroflex Cells",
        r_pct=-30.0, conviction=0.85,
        rationale="50% tax cut ends tomorrow -> levy effectively doubles, upgrade cycles slow, sector under pressure. SHORT.",
    ),
    Product(
        "THER", "Thermalite Core",
        r_pct=+50.0, conviction=0.9,
        rationale="Active users 1.42M -> 3.89M next quarter (~2.7x), 16h42m daily usage, 'very strong next quarter'. STRONG LONG.",
    ),
    Product(
        "LAVA", "Lava Cake",
        r_pct=-45.0, conviction=0.9,
        rationale="Health review, traces of actual lava, sales halted, lawsuits piling up, vendors returning stock. STRONG SHORT.",
    ),
    Product(
        "MINK", "Magma Ink",
        r_pct=+22.0, conviction=0.7,
        rationale="Limited-edition Lava Pen launch, 6h+ queues, 'hot drop' momentum, Magma Ink reservoir is the hook. LONG.",
    ),
    Product(
        "SCOR", "Scoria Paste",
        r_pct=+8.0,  conviction=0.4,
        rationale="Self-styled 'market medium' D. Ray pump on streaming. Fundamentals only the 'paste keeps Ignith together' cliche. SMALL LONG (crowd follows hype).",
    ),
    Product(
        "ASH",  "Ashes of the Phoenix",
        r_pct=-30.0, conviction=0.8,
        rationale="Resurfaced video shows brutal sourcing, public outcry, company defends with 'birds are immortal' cope. PR crisis. SHORT.",
    ),
    Product(
        "INC",  "Volcanic Incense",
        r_pct=+15.0, conviction=0.5,
        rationale="Whiff Nostralico pump in narrow time windows, openly calls people to follow. Pure influencer pump - momentum present, fundamentals absent. SMALL LONG.",
    ),
    Product(
        "SULF", "Sulfur Reactor",
        r_pct=+20.0, conviction=0.8,
        rationale="Index inclusion in Elemental Index 118 -> tracker funds forced to buy on rebalance. Classic index-add tailwind. LONG.",
    ),
]


# ----------------------------------------------------------------- core math

def pnl_from_pct(x_pcts: list[float], r_pcts: list[float], budget: float = BUDGET) -> float:
    """PnL given x_i in % of budget and r_i in % return.

    PnL = sum B * [ y r - y^2 ]   with y = x/100, r = r_pct/100.
    """
    total = 0.0
    for x, r in zip(x_pcts, r_pcts):
        y = x / 100.0
        rr = r / 100.0
        total += budget * (y * rr - y * y)
    return total


def fees_from_pct(x_pcts: list[float], budget: float = BUDGET) -> float:
    """Total fees in XIRECs."""
    return sum(budget * (x / 100.0) ** 2 for x in x_pcts)


def gross_pnl_from_pct(x_pcts: list[float], r_pcts: list[float], budget: float = BUDGET) -> float:
    """PnL before fees (i.e., x * r contribution only)."""
    total = 0.0
    for x, r in zip(x_pcts, r_pcts):
        total += budget * (x / 100.0) * (r / 100.0)
    return total


def soft_threshold_solve(r_pcts: list[float], cap_pct: float = 100.0) -> tuple[list[float], float]:
    """Closed-form constrained optimum for sum_i |x_i| <= cap_pct.

    Unconstrained optimum: x_i = 50 * r_i_decimal = 0.5 * r_pct_i.
    If sum 0.5 * |r_pct_i| <= cap_pct, we're done.
    Otherwise apply soft threshold: x_i = 0.5 * sign(r) * max(0, |r_pct_i| - mu).
    Bisect mu in [0, max|r_pct|] until sum |x_i| == cap_pct.

    Returns (x_pcts, mu).
    """
    abs_r = [abs(r) for r in r_pcts]
    unconstrained_sum = 0.5 * sum(abs_r)
    if unconstrained_sum <= cap_pct + 1e-9:
        return [0.5 * r for r in r_pcts], 0.0

    lo, hi = 0.0, max(abs_r)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        s = 0.5 * sum(max(0.0, ar - mid) for ar in abs_r)
        if s > cap_pct:
            lo = mid
        else:
            hi = mid
    mu = 0.5 * (lo + hi)
    x = []
    for r in r_pcts:
        sign = 1.0 if r > 0 else (-1.0 if r < 0 else 0.0)
        x.append(0.5 * sign * max(0.0, abs(r) - mu))
    return x, mu


# ------------------------------------------------------------------ scenarios

def scenario_returns(products: list[Product], scale: float = 1.0,
                     flip: Optional[set[str]] = None) -> list[float]:
    """Return r_pcts under a scenario.

    `scale` multiplies each |r| (1.0 = base, 0.6 = conservative, 1.4 = aggressive).
    `flip` is a set of codes whose sign we invert (used to model 'pump trap' cases
    where the crowd call is a setup rather than alpha).
    """
    flip = flip or set()
    out = []
    for p in products:
        r = p.r_pct * scale
        if p.code in flip:
            r = -r
        out.append(r)
    return out


SCENARIOS = {
    "BASE":              dict(scale=1.0, flip=set()),
    "CONSERVATIVE":      dict(scale=0.6, flip=set()),
    "AGGRESSIVE":        dict(scale=1.4, flip=set()),
    "SKEPTICAL_PUMPS":   dict(scale=1.0, flip={"INC", "SCOR"}),  # pump-trap crash variant
    "BIG_BAD_NEWS":      dict(scale=1.0, flip=set()),            # sized below in code
}


# ----------------------------------------------------------------- reporting

def fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else "-"
    return f"{sign}{abs(x):>5.1f}%"

def fmt_xirecs(x: float) -> str:
    sign = "+" if x >= 0 else "-"
    return f"{sign}{abs(x):>10,.0f}"


def report_scenario(name: str, products: list[Product], r_pcts: list[float]) -> dict:
    x_pcts, mu = soft_threshold_solve(r_pcts)
    pnl = pnl_from_pct(x_pcts, r_pcts)
    gross = gross_pnl_from_pct(x_pcts, r_pcts)
    fees = fees_from_pct(x_pcts)
    used = sum(abs(x) for x in x_pcts)

    print(f"\n  [{name}]   threshold mu = {mu:5.2f}    used = {used:5.1f}%   "
          f"gross = {fmt_xirecs(gross)}   fees = {fmt_xirecs(-fees)}   "
          f"NET = {fmt_xirecs(pnl)}")
    print(f"    {'code':<5} {'name':<24} {'view':>9}   {'alloc%':>8}    {'XIRECs':>11}")
    for p, r, x in zip(products, r_pcts, x_pcts):
        xirecs = x / 100.0 * BUDGET
        view = fmt_pct(r)
        alloc = fmt_pct(x) if abs(x) > 1e-6 else "   0.0%"
        print(f"    {p.code:<5} {p.name:<24} {view:>9}   {alloc:>8}    {fmt_xirecs(xirecs):>11}")
    return {"x_pcts": x_pcts, "pnl": pnl, "mu": mu}


# --------------------------------------------------------- robust portfolio

def robust_portfolio(products: list[Product]) -> list[float]:
    """Average BASE / CONSERVATIVE / AGGRESSIVE / SKEPTICAL_PUMPS allocations,
    then re-project onto the L1 ball of radius 100 (renormalize so |x| sums
    to no more than 100). Sign of each component is the sign of the average.
    """
    runs = []
    for name, kw in SCENARIOS.items():
        if name == "BIG_BAD_NEWS":
            continue
        rs = scenario_returns(products, **kw)
        x, _ = soft_threshold_solve(rs)
        runs.append(x)

    avg = [sum(r[i] for r in runs) / len(runs) for i in range(len(products))]
    s = sum(abs(a) for a in avg)
    if s > 100.0:
        avg = [a * 100.0 / s for a in avg]
    return avg


# ------------------------------------------------------------ sign stability

def sign_stability(products: list[Product]) -> None:
    """For each product, record the sign of the BASE alloc and check whether
    it survives in CONSERVATIVE / AGGRESSIVE / SKEPTICAL. Anything that
    flips sign is a candidate for caution."""
    base_x, _ = soft_threshold_solve(scenario_returns(products))
    rows = [(p.code, base_x[i]) for i, p in enumerate(products)]

    flips = {p.code: 0 for p in products}
    for name, kw in SCENARIOS.items():
        if name == "BIG_BAD_NEWS":
            continue
        rs = scenario_returns(products, **kw)
        x, _ = soft_threshold_solve(rs)
        for i, p in enumerate(products):
            sb = math.copysign(1, base_x[i]) if abs(base_x[i]) > 1e-6 else 0
            sx = math.copysign(1, x[i])      if abs(x[i])      > 1e-6 else 0
            if sb != 0 and sx != 0 and sb != sx:
                flips[p.code] += 1
            if abs(x[i]) < 1e-6 and abs(base_x[i]) > 1e-6:
                flips[p.code] += 0  # zero-out is OK, not a flip

    print(f"\n  sign-stability check (signed alloc per scenario):")
    header = f"    {'code':<5} {'BASE':>7}  {'CONS':>7}  {'AGG':>7}  {'SKEP':>7}  {'flips':>5}"
    print(header)
    for i, p in enumerate(products):
        cells = []
        for name, kw in SCENARIOS.items():
            if name == "BIG_BAD_NEWS":
                continue
            rs = scenario_returns(products, **kw)
            x, _ = soft_threshold_solve(rs)
            cells.append(f"{x[i]:>+6.1f}%")
        print(f"    {p.code:<5} " + "  ".join(cells) + f"  {flips[p.code]:>5}")


# -------------------------------------------------------------------- main

def main() -> None:
    print("=" * 78)
    print(" R5 MANUAL — Extra! Extra!  (Ignith exchange, 1-day hold, B = 1,000,000)")
    print("=" * 78)

    print("\nNews view (signed expected return, conviction in 0..1):")
    print(f"  {'code':<5} {'name':<24} {'r%':>7}  {'conv':>5}  rationale")
    for p in PRODUCTS:
        print(f"  {p.code:<5} {p.name:<24} {p.r_pct:>+6.1f}%  {p.conviction:>5.2f}  {p.rationale}")

    # Run each scenario
    print("\n" + "-" * 78)
    print(" Scenario-by-scenario optimum:")
    print("-" * 78)
    results = {}
    for name, kw in SCENARIOS.items():
        if name == "BIG_BAD_NEWS":
            continue
        r_pcts = scenario_returns(PRODUCTS, **kw)
        results[name] = report_scenario(name, PRODUCTS, r_pcts)

    # Sign-stability check
    print("\n" + "-" * 78)
    print(" Sign stability across scenarios (negative = short, positive = long):")
    print("-" * 78)
    sign_stability(PRODUCTS)

    # Robust (averaged) portfolio
    print("\n" + "-" * 78)
    print(" Robust portfolio (average of BASE / CONS / AGG / SKEP, L1-projected):")
    print("-" * 78)
    avg_x = robust_portfolio(PRODUCTS)
    base_r = scenario_returns(PRODUCTS)
    pnl_base = pnl_from_pct(avg_x, base_r)
    pnl_cons = pnl_from_pct(avg_x, scenario_returns(PRODUCTS, scale=0.6))
    pnl_agg  = pnl_from_pct(avg_x, scenario_returns(PRODUCTS, scale=1.4))
    pnl_skep = pnl_from_pct(avg_x, scenario_returns(PRODUCTS, scale=1.0,
                                                    flip={"INC", "SCOR"}))
    used = sum(abs(x) for x in avg_x)
    fees = fees_from_pct(avg_x)
    print(f"    used = {used:5.1f}%   fees = {fmt_xirecs(-fees)}")
    print(f"    PnL @ BASE = {fmt_xirecs(pnl_base)}    "
          f"@ CONS = {fmt_xirecs(pnl_cons)}    "
          f"@ AGG  = {fmt_xirecs(pnl_agg)}    "
          f"@ SKEP = {fmt_xirecs(pnl_skep)}")
    print(f"\n    {'code':<5} {'name':<24}   {'alloc%':>8}    {'XIRECs':>11}    side")
    for p, x in zip(PRODUCTS, avg_x):
        side = "LONG " if x > 0 else ("SHORT" if x < 0 else "  -- ")
        xirecs = x / 100.0 * BUDGET
        print(f"    {p.code:<5} {p.name:<24}   {fmt_pct(x):>8}    "
              f"{fmt_xirecs(xirecs):>11}    {side}")

    # Final integer-rounded recommendation
    print("\n" + "=" * 78)
    print(" PORTAL-READY recommendation (rounded to integer % of 1,000,000):")
    print("=" * 78)
    rounded = [round(x) for x in avg_x]
    # If rounding pushed sum over 100, trim the smallest allocation by 1pp.
    while sum(abs(x) for x in rounded) > 100:
        i_min = min(range(len(rounded)), key=lambda i: abs(rounded[i]) if rounded[i] != 0 else 999)
        rounded[i_min] = rounded[i_min] - (1 if rounded[i_min] > 0 else -1)
    pnl_final = pnl_from_pct(rounded, base_r)
    used_final = sum(abs(x) for x in rounded)
    fees_final = fees_from_pct(rounded)
    print(f"    used = {used_final}%   fees = {fmt_xirecs(-fees_final)}   "
          f"NET (BASE) = {fmt_xirecs(pnl_final)}")
    print(f"\n    {'code':<5} {'name':<24}   {'alloc%':>6}     {'XIRECs':>11}    side")
    for p, x in zip(PRODUCTS, rounded):
        side = "LONG" if x > 0 else ("SHORT" if x < 0 else "--")
        xirecs = x / 100.0 * BUDGET
        print(f"    {p.code:<5} {p.name:<24}   {x:>+6d}%     "
              f"{fmt_xirecs(xirecs):>11}    {side}")

    # Sanity reminder of the math
    print("\n" + "-" * 78)
    print(" Sanity (closed-form unconstrained optimum: x* = 0.5 * r%, PnL* = B*r^2/4):")
    print("-" * 78)
    for p in PRODUCTS:
        x_star = 0.5 * p.r_pct
        pnl_star = BUDGET * (p.r_pct / 100.0) ** 2 / 4.0
        print(f"    {p.code:<5} r = {p.r_pct:>+6.1f}%   x* = {x_star:>+6.1f}%   "
              f"PnL_unc = {fmt_xirecs(pnl_star)}")


if __name__ == "__main__":
    main()
