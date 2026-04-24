"""R3 "Celestial Gardeners' Guild" manual challenge solver.

Problem
-------
Counterparties' reserve prices r are uniform on the 5-grid {670, 675, ..., 920} (51 values).
You submit two integer bids b1 < b2. For each counterparty with reserve r:
  - If b1 > r: trade at b1, margin = 920 - b1.
  - Else if b2 > r: trade at b2, margin = (920 - b2) * penalty(b2, avg_b2).
  - Else: no trade.
  penalty(b2, avg_b2) = 1                                        if b2 >= avg_b2
                     = ((920 - avg_b2) / (920 - b2))**3          otherwise

avg_b2 is the field's mean second bid. Unknown to us — the core game-theoretic lever.

We compute expected profit PER COUNTERPARTY (i.e., averaged over the 51 reserves).
Scale by the actual counterparty count for XIRECs totals.

Usage:  py -3.13 manual/round3/verify.py
"""
from __future__ import annotations
import math
import statistics


RESERVES = [670 + 5 * k for k in range(51)]  # {670, 675, ..., 920}
BUYBACK = 920


# ------------------------------------------------------------------ primitives

def count_lt(b):
    """Number of reserves strictly less than b."""
    return sum(1 for r in RESERVES if r < b)


def count_in(lo, hi):
    """Number of reserves in [lo, hi) (i.e., lo <= r < hi)."""
    return sum(1 for r in RESERVES if lo <= r < hi)


def penalty(b2, avg_b2):
    if b2 >= avg_b2:
        return 1.0
    if b2 >= BUYBACK:
        return 0.0
    return ((BUYBACK - avg_b2) / (BUYBACK - b2)) ** 3


def profit(b1, b2, avg_b2):
    """Expected profit per the 51-reserve grid (sum over all reserves)."""
    k1 = count_lt(b1)
    k2 = count_in(b1, b2)
    p = penalty(b2, avg_b2)
    return k1 * (BUYBACK - b1) + k2 * (BUYBACK - b2) * p


def profit_unpenalized(b1, b2):
    return profit(b1, b2, avg_b2=0)  # penalty = 1 since b2 >= 0 trivially


# ---------------------------------------------------------------- optimization

def integer_bid_range():
    """Useful integer bids — b = 671..920 can capture at least one reserve."""
    return list(range(670, 921))


def grid_bid_range():
    """Bids constrained to the 5-grid {670, 675, ..., 920}."""
    return list(RESERVES)


def optimize(avg_b2, bids):
    """Return best (profit, b1, b2) over integer bid pairs for given avg_b2."""
    best = (-1e18, None, None)
    for b1 in bids:
        for b2 in bids:
            if b2 <= b1:
                continue
            p = profit(b1, b2, avg_b2)
            if p > best[0]:
                best = (p, b1, b2)
    return best


# ----------------------------------------------------------- iterated best response

def iterated_best_response(frac_solvers=0.5, behavioral_avg=870, seed=(751, 836), max_iters=20):
    """Find symmetric equilibrium assuming a mix of solver-copycats and behavioral crowd.

    Opponent model:
      - frac_solvers of the field plays our current strategy (b1, b2).
      - (1 - frac_solvers) of the field has a fixed behavioral avg_b2 = behavioral_avg.
    So the field's avg_b2 = frac_solvers * our_b2 + (1 - frac_solvers) * behavioral_avg.

    Iterate: given current avg_b2, find best response (b1, b2), update avg_b2, repeat.
    Returns fixed point.
    """
    b1, b2 = seed
    seen = set()
    bids = integer_bid_range()
    for it in range(max_iters):
        field_avg = frac_solvers * b2 + (1 - frac_solvers) * behavioral_avg
        _, new_b1, new_b2 = optimize(field_avg, bids)
        if (new_b1, new_b2) == (b1, b2):
            return (b1, b2, field_avg, it)
        if (new_b1, new_b2) in seen:
            return (new_b1, new_b2, field_avg, it)  # cycle
        seen.add((new_b1, new_b2))
        b1, b2 = new_b1, new_b2
    return (b1, b2, field_avg, max_iters)


# -------------------------------------------------------------- sensitivity / reports

def report_unpenalized():
    print("=" * 78)
    print("  1. UNPENALIZED OPTIMUM (avg_b2 <= b2, penalty = 1)")
    print("=" * 78)
    p_int, b1, b2 = optimize(0, integer_bid_range())
    print(f"  integer bids: b1 = {b1}, b2 = {b2}, profit/51 = {p_int}")
    k1 = count_lt(b1)
    k2 = count_in(b1, b2)
    print(f"    b1 captures {k1} reserves at margin {BUYBACK - b1}: {k1 * (BUYBACK - b1):,}")
    print(f"    b2 captures {k2} reserves at margin {BUYBACK - b2}: {k2 * (BUYBACK - b2):,}")

    p_grid, g1, g2 = optimize(0, grid_bid_range())
    print(f"  5-grid bids: b1 = {g1}, b2 = {g2}, profit/51 = {p_grid}")


def report_scenarios():
    print("\n" + "=" * 78)
    print("  2. BEST RESPONSE vs. ASSUMED FIELD avg_b2")
    print("=" * 78)
    print(f"  {'avg_b2':>6} {'b1*':>6} {'b2*':>6} {'profit/51':>12} {'penalty':>9}")
    for avg in [750, 800, 820, 836, 850, 870, 880, 890, 900, 910, 919]:
        p, b1, b2 = optimize(avg, integer_bid_range())
        pen = penalty(b2, avg)
        print(f"  {avg:>6} {b1:>6} {b2:>6} {p:>12.1f} {pen:>9.3f}")


def report_robustness():
    print("\n" + "=" * 78)
    print("  3. ROBUSTNESS — fixed candidate bids vs a range of field avg_b2")
    print("=" * 78)
    candidates = [
        (751, 836),   # unpenalized optimum / symmetric Nash
        (751, 851),
        (751, 861),
        (751, 871),
        (751, 881),
        (751, 891),
        (751, 901),
        (751, 911),
        (771, 871),
        (801, 901),
        (850, 900),   # naive "bid high, safe"
        (900, 915),   # "beat the mean" paranoid
    ]
    scenarios = [800, 820, 836, 850, 870, 880, 890, 900]
    header = "  " + "candidate".ljust(14) + " ".join(f"avg{s}".rjust(8) for s in scenarios) + "   worst    mean"
    print(header)
    best_mean = (-1e18, None)
    best_worst = (-1e18, None)
    for b1, b2 in candidates:
        profits = [profit(b1, b2, avg) for avg in scenarios]
        worst, mean = min(profits), statistics.mean(profits)
        label = f"({b1},{b2})"
        print(f"  {label:<14}" + " ".join(f"{p:>8.0f}" for p in profits) + f"  {worst:>7.0f} {mean:>7.0f}")
        if mean > best_mean[0]:
            best_mean = (mean, (b1, b2))
        if worst > best_worst[0]:
            best_worst = (worst, (b1, b2))
    print(f"\n  MEAN maximizer among listed:  {best_mean[1]}  mean = {best_mean[0]:,.1f}")
    print(f"  WORST maximizer among listed: {best_worst[1]}  worst = {best_worst[0]:,.1f}")


def report_exhaustive_meanmax(scenarios):
    print("\n" + "=" * 78)
    print("  4. EXHAUSTIVE mean-max / max-min over ALL integer (b1, b2)")
    print("=" * 78)
    best_mean = (-1e18, None)
    best_worst = (-1e18, None)
    bids = integer_bid_range()
    for b1 in bids:
        for b2 in bids:
            if b2 <= b1:
                continue
            profits = [profit(b1, b2, avg) for avg in scenarios]
            m = statistics.mean(profits)
            w = min(profits)
            if m > best_mean[0]:
                best_mean = (m, (b1, b2))
            if w > best_worst[0]:
                best_worst = (w, (b1, b2))
    b1, b2 = best_mean[1]
    print(f"  mean-max:  b1 = {b1}, b2 = {b2}  mean profit/51 = {best_mean[0]:,.1f}")
    b1, b2 = best_worst[1]
    print(f"  max-min:   b1 = {b1}, b2 = {b2}  worst profit/51 = {best_worst[0]:,.1f}")


def report_ibr():
    print("\n" + "=" * 78)
    print("  5. ITERATED BEST RESPONSE (symmetric-population fixed point)")
    print("=" * 78)
    print("  Model: fraction of field plays the solver's answer; rest is 'behavioral' avg.")
    print(f"  {'solver %':>10} {'behavioral avg':>16} {'fixed pt b1':>12} {'b2':>6} {'field avg':>10}")
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        for beh_avg in (820, 870, 900):
            b1, b2, favg, _ = iterated_best_response(frac_solvers=frac, behavioral_avg=beh_avg)
            print(f"  {frac:>9.0%} {beh_avg:>16} {b1:>12} {b2:>6} {favg:>10.1f}")


def main():
    report_unpenalized()
    report_scenarios()
    report_robustness()
    report_exhaustive_meanmax(scenarios=[800, 820, 836, 850, 870, 880, 890, 900])
    report_ibr()


if __name__ == "__main__":
    main()
