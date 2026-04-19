"""R2 "Invest & Expand" manual challenge solver.

Variables (all in %): r (Research), sc (Scale), sp (Speed), with r + sc + sp <= 100.

Pillars
  Research(r)  = 200_000 * ln(1+r) / ln(101)           # concave, saturates ~50%
  Scale(sc)    = 7 * sc / 100                           # linear
  Speed_mult(sp) rank-based in [0.1, 0.9]; depends on opponents.

Gross       = Research(r) * Scale(sc) * Speed_mult
BudgetUsed  = B * (r + sc + sp) / 100      # B is 50_000 or 100_000 (portal ambiguous)
Net         = Gross - BudgetUsed

Speed is the game-theoretic pillar. We cannot observe opponents' bids, so we
evaluate every candidate allocation under several assumed opponent sp
distributions and pick the allocation that is robust across them.

Usage:  py -3.13 manual/round2/verify.py
"""
from __future__ import annotations
import math
import statistics


LN_101 = math.log(101)

def research(r):
    return 200_000.0 * math.log(1.0 + r) / LN_101

def scale(sc):
    return 7.0 * sc / 100.0


# --------------------------------------------------- opponent speed models

# Each model is a CDF F(sp) = P(opponent_sp <= sp).
# Our Speed_mult = 0.1 + 0.8 * F(our_sp) in the large-N limit (the doc says
# "linearly interpolated by rank", and with many teams the interpolation
# converges to the CDF).

def cdf_uniform(lo, hi):
    def F(x):
        if x <= lo: return 0.0
        if x >= hi: return 1.0
        return (x - lo) / (hi - lo)
    return F

def cdf_spike(k):
    """Deterministic opponent allocation — everyone picks k exactly.

    Per spec: equal investments share the same rank. So if WE are also at k,
    we are in the tie and share rank 1 (the best). That means F(k) = 1.0
    (all opponents satisfy opp_sp <= our_sp). Going below (x < k) puts us
    strictly last -> F = 0. Going above also wins rank 1 -> F = 1.
    """
    def F(x):
        if x < k:  return 0.0
        return 1.0
    return F

def cdf_mixture(components):
    """Weighted average of sub-CDFs; components is [(weight, F), ...]."""
    def F(x):
        return sum(w * sub(x) for w, sub in components)
    return F

def speed_mult(sp, cdf):
    return 0.1 + 0.8 * cdf(sp)


# ----------------------------------------------------------- core evaluator

def net_pnl(r, sc, sp, budget, cdf):
    s = speed_mult(sp, cdf)
    gross = research(r) * scale(sc) * s
    used = budget * (r + sc + sp) / 100.0
    return gross - used, gross, s


# ------------------------------------------------------------- grid search

def optimize(budget, cdf, step=1):
    best = (-1e18, None)
    for r in range(0, 101, step):
        for sc in range(0, 101 - r, step):
            max_sp = 100 - r - sc
            for sp in range(0, max_sp + 1, step):
                net, gross, s = net_pnl(r, sc, sp, budget, cdf)
                if net > best[0]:
                    best = (net, (r, sc, sp, gross, s))
    return best


def fine_tune(r, sc, sp, budget, cdf, radius=5, step=1):
    """Local refinement at integer step around a coarse optimum."""
    best = (-1e18, None)
    for dr in range(-radius, radius + 1, step):
        for dsc in range(-radius, radius + 1, step):
            for dsp in range(-radius, radius + 1, step):
                rr, scc, spp = r + dr, sc + dsc, sp + dsp
                if rr < 0 or scc < 0 or spp < 0: continue
                if rr + scc + spp > 100: continue
                if rr > 100 or scc > 100 or spp > 100: continue
                net, gross, s = net_pnl(rr, scc, spp, budget, cdf)
                if net > best[0]:
                    best = (net, (rr, scc, spp, gross, s))
    return best


# --------------------------------------------------------- scenario runner

def cdf_gaussian(mu, sigma, lo=0, hi=100):
    """Truncated-Gaussian CDF approximated by Monte Carlo (deterministic grid)."""
    # Integrate the Gaussian PDF on a fine grid [lo, hi] and normalize.
    import math
    N = 1001
    step = (hi - lo) / (N - 1)
    xs = [lo + i * step for i in range(N)]
    # pdf values
    def pdf(x):
        return math.exp(-0.5 * ((x - mu) / sigma) ** 2)
    weights = [pdf(x) for x in xs]
    # normalize so it's a valid truncated CDF
    total = sum(weights)
    # cumulative
    cumw = [0.0] * N
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        cumw[i] = acc / total
    def F(x):
        if x <= lo: return 0.0
        if x >= hi: return 1.0
        # linear interpolation
        idx = (x - lo) / step
        i0 = int(idx); i1 = min(N - 1, i0 + 1)
        frac = idx - i0
        return cumw[i0] * (1 - frac) + cumw[i1] * frac
    return F


# Behavioral opponent model derived from P3 Containers (R2)/Suitcases (R4) history.
# Those challenges had identical structure (rank/crowd-dependent payoff). Observed
# pattern: ~60–70% of teams cluster on a small number of "focal" answers (textbook
# split, doc sketch, equal-thirds). ~20% do proper analysis. ~10–15% contrarian.
#
# For our Speed: the focal points in the problem statement are
#   - "50 / 25 / 25"  (the doc's sketch) -> sp = 25
#   - "balanced 33/33/34"                -> sp = 33 or 34
#   - "speed is king" gut-feel           -> sp = 50
#   - "budget-saver"                     -> sp near 0

BEHAVIORAL_OPPONENTS = [
    (0.20, cdf_spike(25)),                   # "doc sketch" copycats
    (0.20, cdf_spike(33)),                   # "equal thirds / textbook balanced"
    (0.10, cdf_spike(50)),                   # "speed-is-king" gut-feel
    (0.05, cdf_spike(10)),                   # "budget-saver" (low all-pay)
    (0.20, cdf_gaussian(35, 6)),             # solver-users cluster around solver pick
    (0.15, cdf_uniform(15, 45)),             # "balanced-ish" uninformed
    (0.10, cdf_uniform(0, 80)),              # random / naive
]

SCENARIOS = {
    # Simple baselines
    "Uniform [0, 25] (under-invested field)":         cdf_uniform(0, 25),
    "Uniform [0, 50] (aggressive field)":             cdf_uniform(0, 50),
    # Gaussian assumptions
    "Gaussian(mu=25, sig=12)":                        cdf_gaussian(25, 12),
    "Gaussian(mu=33, sig=10)":                        cdf_gaussian(33, 10),
    "Gaussian(mu=40, sig=12)":                        cdf_gaussian(40, 12),
    # Focal points
    "Herd at 25 (doc sketch)":                        cdf_spike(25),
    "Herd at 33 (textbook)":                          cdf_spike(33),
    "Herd at 34 (solver's pick)":                     cdf_spike(34),
    # Realistic mixture based on P3 Container/Suitcase behavior
    "Behavioral (P3-based mixture)":                  cdf_mixture(BEHAVIORAL_OPPONENTS),
}


def report(budget):
    print(f"\n{'='*78}\n  BUDGET = {budget:,}\n{'='*78}")
    results = []
    for name, cdf in SCENARIOS.items():
        net, params = optimize(budget, cdf, step=1)
        r, sc, sp, gross, s = params
        results.append((name, r, sc, sp, gross, s, net))
        print(f"\n  scenario: {name}")
        print(f"    alloc (r, sc, sp) = ({r:>3}, {sc:>3}, {sp:>3})    "
              f"total={r+sc+sp:>3}%    speed_mult={s:.2f}")
        print(f"    gross = {gross:>14,.0f}    net = {net:>14,.0f}")

    # Summary
    print(f"\n{'-'*78}\n  SUMMARY (budget {budget:,})\n{'-'*78}")
    print(f"  {'scenario':<50} {'r':>3} {'sc':>3} {'sp':>3} {'s':>5} {'net':>12}")
    for (name, r, sc, sp, gross, s, net) in results:
        print(f"  {name:<50} {r:>3} {sc:>3} {sp:>3} {s:>5.2f} {net:>12,.0f}")

    # Also find the MEAN-MAXIMIZING allocation via exhaustive search
    best_mean = (-1e18, None)
    best_maxmin = (-1e18, None)
    for r in range(0, 101):
        for sc in range(0, 101 - r):
            max_sp = 100 - r - sc
            for sp in range(0, max_sp + 1):
                nets = []
                for cdf in SCENARIOS.values():
                    net, *_ = net_pnl(r, sc, sp, budget, cdf)
                    nets.append(net)
                m = statistics.mean(nets)
                w = min(nets)
                if m > best_mean[0]:
                    best_mean = (m, (r, sc, sp))
                if w > best_maxmin[0]:
                    best_maxmin = (w, (r, sc, sp))
    r, sc, sp = best_mean[1]
    print(f"\n  EXHAUSTIVE MEAN-MAXIMIZER: ({r}, {sc}, {sp}) -> mean Net = {best_mean[0]:,.0f}")
    r, sc, sp = best_maxmin[1]
    print(f"  EXHAUSTIVE MAXMIN:          ({r}, {sc}, {sp}) -> worst Net = {best_maxmin[0]:,.0f}")

    # Which allocations are robust? Pick the one with best worst-case net
    print(f"\n  Robust choice — evaluate a few candidates against all scenarios:")
    candidates = sorted(set((r, sc, sp) for (_, r, sc, sp, *_ ) in results))
    candidates.append(best_mean[1])
    candidates.append(best_maxmin[1])
    # Add a few manual candidates
    extras = [(50, 25, 25), (40, 30, 30), (45, 30, 25), (35, 35, 30),
              (50, 30, 20), (40, 40, 20), (16, 48, 36), (15, 47, 38),
              (14, 45, 41), (16, 49, 35)]
    for e in extras:
        if e not in candidates:
            candidates.append(e)

    print(f"  {'alloc':<15} " + " ".join(f"{i:>8}" for i in range(len(SCENARIOS))) + "  worst   mean")
    best_worst = (-1e18, None)
    for (r, sc, sp) in candidates:
        if r + sc + sp > 100: continue
        nets = []
        for cdf in SCENARIOS.values():
            net, *_ = net_pnl(r, sc, sp, budget, cdf)
            nets.append(net)
        worst = min(nets)
        mean = statistics.mean(nets)
        if worst > best_worst[0]:
            best_worst = (worst, (r, sc, sp, mean))
        label = f"({r},{sc},{sp})"
        print(f"  {label:<15} " + " ".join(f"{n:>8,.0f}" for n in nets) + f"  {worst:>7,.0f} {mean:>8,.0f}")

    r, sc, sp, mean = best_worst[1]
    print(f"\n  MAXMIN (best worst-case): ({r}, {sc}, {sp}) with worst={best_worst[0]:,.0f} mean={mean:,.0f}")


def sensitivity_near(r, sc, sp, budget, radius=5):
    """Show how Net changes if we tweak each axis by +/- radius, holding others fixed.
    Uses the average Net across all SCENARIOS as the summary metric."""
    def avg_net(rr, ss, pp):
        nets = []
        for cdf in SCENARIOS.values():
            net, *_ = net_pnl(rr, ss, pp, budget, cdf)
            nets.append(net)
        return statistics.mean(nets)

    print(f"\n  Local sensitivity at ({r}, {sc}, {sp}) — mean Net across scenarios:")
    base = avg_net(r, sc, sp)
    print(f"    baseline mean = {base:,.0f}")
    print(f"    +/- 1% sweeps (holding total = 100% by compensating on sp):")
    for dr in range(-3, 4):
        # Shift r, compensate with sp so total stays at 100
        rr = r + dr; spp = sp - dr
        if rr < 0 or spp < 0 or rr + sc + spp > 100: continue
        m = avg_net(rr, sc, spp)
        print(f"      r={rr:>3}, sc={sc:>3}, sp={spp:>3} -> mean Net = {m:>10,.0f}  ({m-base:+,.0f})")
    for dsc in range(-3, 4):
        rr = r; scc = sc + dsc; spp = sp - dsc
        if scc < 0 or spp < 0 or rr + scc + spp > 100: continue
        m = avg_net(rr, scc, spp)
        print(f"      r={rr:>3}, sc={scc:>3}, sp={spp:>3} -> mean Net = {m:>10,.0f}  ({m-base:+,.0f})")


def iterated_best_response(budget, frac_solvers=0.2, frac_textbook=0.3,
                           frac_doc=0.2, frac_other=0.3, max_iters=10):
    """Iterated best response on the Speed game, seeded with a behavioral mix.

    Assume a fraction `frac_solvers` of opponents are solver-users who converge
    to our strategy. The remaining fraction follows a fixed behavioral mix. At
    each iteration, compute the best response against (behavioral_mix +
    solver_crowd_at_last_answer), update, repeat. A fixed point = Bayesian
    best response assuming known opponent types.
    """
    behavioral = cdf_mixture([
        (frac_doc / (frac_doc + frac_textbook + frac_other), cdf_spike(25)),
        (frac_textbook / (frac_doc + frac_textbook + frac_other), cdf_spike(33)),
        (0.5 * frac_other / (frac_doc + frac_textbook + frac_other), cdf_uniform(15, 45)),
        (0.2 * frac_other / (frac_doc + frac_textbook + frac_other), cdf_spike(50)),
        (0.3 * frac_other / (frac_doc + frac_textbook + frac_other), cdf_uniform(0, 80)),
    ])
    # Seed
    r, sc, sp = 16, 50, 34
    print(f"\n  Iterated Best Response (solvers assumed {frac_solvers:.0%} of field):")
    seen = set()
    for it in range(max_iters):
        # Opponent CDF = (1 - frac_solvers) * behavioral + frac_solvers * spike(current sp)
        cdf = cdf_mixture([(1 - frac_solvers, behavioral),
                           (frac_solvers, cdf_spike(sp))])
        # Best response
        best = (-1e18, None)
        for rr in range(0, 101):
            for scc in range(0, 101 - rr):
                for spp in range(0, 101 - rr - scc):
                    net, *_ = net_pnl(rr, scc, spp, budget, cdf)
                    if net > best[0]:
                        best = (net, (rr, scc, spp))
        new_r, new_sc, new_sp = best[1]
        print(f"    iter {it}: ({r:>3}, {sc:>3}, {sp:>3}) -> best response "
              f"({new_r:>3}, {new_sc:>3}, {new_sp:>3})  Net = {best[0]:,.0f}")
        if (new_r, new_sc, new_sp) in seen:
            print(f"    cycle detected; fixed point reached")
            return (new_r, new_sc, new_sp)
        seen.add((new_r, new_sc, new_sp))
        if (new_r, new_sc, new_sp) == (r, sc, sp):
            print(f"    FIXED POINT: ({new_r}, {new_sc}, {new_sp})")
            return (new_r, new_sc, new_sp)
        r, sc, sp = new_r, new_sc, new_sp
    return (r, sc, sp)


def main():
    print("R2 MANUAL — Invest & Expand  (budget = 50,000 confirmed)")
    report(50_000)

    print("\n" + "="*78)
    print("  ITERATED BEST RESPONSE (game-theoretic fixed points)")
    print("="*78)
    # Try different assumed solver-penetration rates
    for frac in (0.1, 0.2, 0.3, 0.5):
        iterated_best_response(50_000, frac_solvers=frac)

    print("\n" + "="*78)
    print("  LOCAL SENSITIVITY near key candidates")
    print("="*78)
    sensitivity_near(16, 49, 35, 50_000)
    sensitivity_near(15, 46, 39, 50_000)


if __name__ == "__main__":
    main()
