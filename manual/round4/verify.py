"""R4 "Vanilla Just Isn't Exotic Enough" manual challenge solver.

Problem
-------
Tradable: AETHER CRYSTAL (S0 = 50.000, mid of 49.975 / 50.025) and 10 derivatives
written on it. Each contract has size 3,000 (multiplier on payoff). Volume per
contract is capped by the displayed bid/ask size. We commit to side+volume
once and the contracts settle at expiry.

The 10 derivatives:
  - AC_50_P, AC_50_C       European put/call, K=50,  T=21    (vanilla pair)
  - AC_35_P, AC_40_P, AC_45_P  European puts at K=35/40/45, T=21
  - AC_60_C                    European call, K=60, T=21
  - AC_50_P_2, AC_50_C_2   European put/call, K=50, T=14    (shorter ATM pair)
  - AC_50_CO               Chooser (K=50, decide put/call at T=14, expires T=21)
  - AC_40_BP               Binary put (K=40, T=21, payoff = 10 if S_T < 40)
  - AC_45_KO               Down-and-out put (K=45, barrier=35, T=21)

Approach
--------
1. **Calibrate σ** to the 6 vanilla mids assuming GBM, r=0. Vanillas show K=50
   put = call (12 / 12.05 both sides), so put-call parity holds with r=0 → no
   drift correction needed for fair-value computation.
2. **Smile check**: also back out per-strike implied vol; if the smile is
   meaningful, propagate it into the exotics' fair values.
3. **Price every contract** in closed form:
     - Black-Scholes for puts/calls.
     - Rubinstein chooser: simple-chooser(S, K, T1, T2) = call(T2) + put(T1)
       when r = 0 (Rubinstein 1991).
     - Cash-or-nothing binary put: payoff · N(-d2).
     - Reiner-Rubinstein down-and-out put with K ≥ B (continuous monitoring):
       p_do = p_vanilla − p_di.
4. **Cross-check with Monte Carlo** (200k paths, daily steps × 8 substeps)
   so we trust the closed-form numbers.
5. **Decide BUY/SELL** by sign of edge:
     edge_BUY  = fair − ask    (positive ⇒ undervalued ⇒ lift the offer)
     edge_SELL = bid − fair    (positive ⇒ overvalued ⇒ hit the bid)
   Take the larger and use the displayed volume cap. Profit = edge · vol · 3000.
6. **Sensitivity** sweep on σ to make sure each decision survives the
   calibration uncertainty.

Usage:  py -3.13 manual/round4/verify.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.stats import norm


# ============================================================================
# Market data
# ============================================================================

CONTRACT_SIZE = 3000
S0 = (49.975 + 50.025) / 2.0  # underlying mid = 50.000

# Wiki specifies: 1 week = 5 trading days, 4 steps per trading day. So "T+21"
# (3 weeks) = 60 monitoring steps and "T+14" (2 weeks) = 40 monitoring steps.
# σ_year = 2.51, 252 trading days/year. Pricing only depends on σ²·T which is
# preserved if we keep the on-screen T (in "Solvenarian Days") as our time
# axis — but the KO put's barrier monitoring requires the *exact* step count.
WIKI_STEPS = {21: 60, 14: 40}


@dataclass
class Quote:
    name: str
    kind: str            # vanilla_call | vanilla_put | chooser | binary_put | ko_put | underlying
    K: Optional[float]
    T: Optional[float]   # days
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    barrier: Optional[float] = None
    choose_T: Optional[float] = None
    binary_payoff: Optional[float] = None


QUOTES: list[Quote] = [
    Quote("AC",        "underlying",   None, None, 49.975, 50.025, 200, 200),
    Quote("AC_50_P",   "vanilla_put",  50.0, 21,   12.0,   12.05,   50,  50),
    Quote("AC_50_C",   "vanilla_call", 50.0, 21,   12.0,   12.05,   50,  50),
    Quote("AC_35_P",   "vanilla_put",  35.0, 21,    4.33,   4.35,   50,  50),
    Quote("AC_40_P",   "vanilla_put",  40.0, 21,    6.50,   6.55,   50,  50),
    Quote("AC_45_P",   "vanilla_put",  45.0, 21,    9.05,   9.10,   50,  50),
    Quote("AC_60_C",   "vanilla_call", 60.0, 21,    8.80,   8.85,   50,  50),
    Quote("AC_50_P_2", "vanilla_put",  50.0, 14,    9.70,   9.75,   50,  50),
    Quote("AC_50_C_2", "vanilla_call", 50.0, 14,    9.70,   9.75,   50,  50),
    Quote("AC_50_CO",  "chooser",      50.0, 21,   22.20,  22.30,   50,  50, choose_T=14),
    Quote("AC_40_BP",  "binary_put",   40.0, 21,    5.00,   5.10,   50,  50, binary_payoff=10.0),
    Quote("AC_45_KO",  "ko_put",       45.0, 21,    0.15,   0.175, 500, 500, barrier=35.0),
]
QUOTES_BY_NAME = {q.name: q for q in QUOTES}


# ============================================================================
# Closed-form pricers (GBM, r = q = 0 unless specified)
# ============================================================================

def _d1(S, K, T, sigma, r=0.0):
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_call(S, K, T, sigma, r=0.0):
    if T <= 0:
        return max(S - K, 0.0)
    d1 = _d1(S, K, T, sigma, r)
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_put(S, K, T, sigma, r=0.0):
    if T <= 0:
        return max(K - S, 0.0)
    d1 = _d1(S, K, T, sigma, r)
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def chooser_simple(S, K, T1, T2, sigma, r=0.0, sigma_T1=None):
    """Rubinstein 1991 simple chooser. At T1, holder picks max(C, P) on a
    European pair with strike K and remaining time T2-T1. Closed form:

        chooser = c(S, K, T2, σ_T2) + p(S, K·e^{-r(T2-T1)}, T1, σ_T1)

    With r = 0 this collapses to c(T2, σ_T2) + p(T1, σ_T1). When `sigma_T1`
    is None we fall back to the same σ for both legs (single-σ model).
    """
    K_disc = K * math.exp(-r * (T2 - T1))
    sigma_call = sigma
    sigma_put = sigma if sigma_T1 is None else sigma_T1
    return bs_call(S, K, T2, sigma_call, r) + bs_put(S, K_disc, T1, sigma_put, r)


def binary_put(S, K, T, sigma, payoff=10.0, r=0.0):
    """Cash-or-nothing put: pays `payoff` if S_T < K."""
    if T <= 0:
        return payoff if S < K else 0.0
    d2 = (math.log(S / K) + (r - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return payoff * math.exp(-r * T) * norm.cdf(-d2)


def down_and_out_put_discrete_mc(S, K, B, T, sigma, n_steps, r=0.0,
                                 n_paths=400_000, seed=20260427):
    """Discrete-monitored down-and-out put: barrier checked at exactly
    n_steps equispaced points (matching the wiki's 4-steps-per-trading-day
    grid). Returns mean payoff and Monte-Carlo standard error.

    This is the *correct* fair value for the R4 manual challenge — closed
    form Reiner-Rubinstein assumes continuous monitoring and underestimates.
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    drift = (r - 0.5 * sigma * sigma) * dt
    sd = sigma * math.sqrt(dt)

    # Stream the path forward, tracking only running min — bounds memory.
    log_S = np.full(n_paths, math.log(S))
    log_min = log_S.copy()
    for _ in range(n_steps):
        log_S += drift + sd * rng.standard_normal(n_paths)
        np.minimum(log_min, log_S, out=log_min)
    S_T = np.exp(log_S)
    min_S = np.exp(log_min)
    knocked = min_S <= B
    payoff = np.where(knocked, 0.0, np.maximum(K - S_T, 0.0))
    payoff *= math.exp(-r * T)
    return payoff.mean(), payoff.std(ddof=1) / math.sqrt(n_paths)


def down_and_out_put(S, K, B, T, sigma, r=0.0):
    """Continuously-monitored down-and-out put. Assumes K >= B (otherwise the
    put is already in the dead zone). Reiner-Rubinstein / Hull eq. 26.13:

        p_do = p_vanilla − p_di

    where, for K >= B:
        p_di = -S·N(-x1) + K·e^{-rT}·N(-x1+σ√T)
               + S·(B/S)^{2λ}·[N(y) − N(y1)]
               − K·e^{-rT}·(B/S)^{2λ-2}·[N(y-σ√T) − N(y1-σ√T)]
        λ  = (r + σ²/2) / σ²
        x1 = ln(S/B)/σ√T + λ·σ√T
        y  = ln(B²/(S·K))/σ√T + λ·σ√T
        y1 = ln(B/S)/σ√T + λ·σ√T
    """
    if S <= B:
        return 0.0
    if T <= 0:
        return max(K - S, 0.0)

    sigT = sigma * math.sqrt(T)
    lam = (r + 0.5 * sigma * sigma) / (sigma * sigma)

    x1 = math.log(S / B) / sigT + lam * sigT
    y = math.log(B * B / (S * K)) / sigT + lam * sigT
    y1 = math.log(B / S) / sigT + lam * sigT

    p_di = (
        -S * norm.cdf(-x1)
        + K * math.exp(-r * T) * norm.cdf(-x1 + sigT)
        + S * (B / S) ** (2 * lam) * (norm.cdf(y) - norm.cdf(y1))
        - K * math.exp(-r * T) * (B / S) ** (2 * lam - 2)
        * (norm.cdf(y - sigT) - norm.cdf(y1 - sigT))
    )
    return bs_put(S, K, T, sigma, r) - p_di


# ============================================================================
# Implied vol (Brent on BS price)
# ============================================================================

def implied_vol(market, S, K, T, kind, r=0.0):
    """Brent's method for IV; kind ∈ {vanilla_call, vanilla_put}."""
    pricer = bs_call if kind == "vanilla_call" else bs_put
    intrinsic = max(S - K, 0.0) if kind == "vanilla_call" else max(K - S, 0.0)
    if market <= intrinsic + 1e-9:
        return float("nan")
    f = lambda s: pricer(S, K, T, s, r) - market
    try:
        return brentq(f, 1e-4, 5.0, xtol=1e-8)
    except ValueError:
        return float("nan")


# ============================================================================
# Calibration
# ============================================================================

def calibrate_flat_sigma(quotes, S, r=0.0):
    """Single σ minimising sum-of-squared price errors against vanilla mids."""
    vanillas = [q for q in quotes if q.kind in ("vanilla_call", "vanilla_put")]

    def loss(sigma):
        err = 0.0
        for q in vanillas:
            mid = 0.5 * (q.bid + q.ask)
            if q.kind == "vanilla_call":
                fv = bs_call(S, q.K, q.T, sigma, r)
            else:
                fv = bs_put(S, q.K, q.T, sigma, r)
            err += (fv - mid) ** 2
        return err

    res = minimize_scalar(loss, bounds=(0.01, 1.0), method="bounded",
                          options={"xatol": 1e-9})
    return res.x


def per_strike_iv(quotes, S, r=0.0):
    """Per-quote implied vol from mid price. Returns dict name → IV."""
    out = {}
    for q in quotes:
        if q.kind not in ("vanilla_call", "vanilla_put"):
            continue
        mid = 0.5 * (q.bid + q.ask)
        out[q.name] = implied_vol(mid, S, q.K, q.T, q.kind, r)
    return out


# ============================================================================
# Smile model: linear-in-K, separately per maturity. Used to look up the σ to
# feed into each exotic. For exotics whose effective strike straddles many
# levels (KO put), we do a sensitivity sweep instead.
# ============================================================================

def smile_lookup(strike, T, ivs_per_maturity):
    """Linear-interpolate σ at the given strike for the closest maturity."""
    closest_T = min(ivs_per_maturity.keys(), key=lambda t: abs(t - T))
    table = ivs_per_maturity[closest_T]  # list of (K, sigma)
    table = sorted(table)
    if strike <= table[0][0]:
        return table[0][1]
    if strike >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        K0, s0 = table[i]
        K1, s1 = table[i + 1]
        if K0 <= strike <= K1:
            w = (strike - K0) / (K1 - K0)
            return s0 + w * (s1 - s0)
    return table[-1][1]


def build_smile(quotes, S, r=0.0):
    ivs = {}
    for q in quotes:
        if q.kind not in ("vanilla_call", "vanilla_put"):
            continue
        mid = 0.5 * (q.bid + q.ask)
        sig = implied_vol(mid, S, q.K, q.T, q.kind, r)
        ivs.setdefault(q.T, []).append((q.K, sig))
    return ivs


# ============================================================================
# Monte Carlo cross-check
# ============================================================================

def mc_price_all(quotes, S, sigma_constant, r=0.0,
                 n_paths=200_000, n_steps_per_day=8, seed=20260427):
    """Price every contract on the same path bundle. Single σ (cross-check)."""
    rng = np.random.default_rng(seed)
    T_max = max(q.T for q in quotes if q.T is not None)
    n_steps = int(T_max * n_steps_per_day)
    dt = 1.0 / n_steps_per_day

    Z = rng.standard_normal((n_paths, n_steps))
    drift = (r - 0.5 * sigma_constant * sigma_constant) * dt
    diff = sigma_constant * math.sqrt(dt) * Z
    log_paths = np.log(S) + np.cumsum(drift + diff, axis=1)
    paths = np.exp(log_paths)
    running_min = np.minimum.accumulate(paths, axis=1)

    out = {}
    for q in quotes:
        if q.kind == "underlying":
            out[q.name] = S * math.exp(r * 0.0)  # placeholder
            continue
        idx_T = int(q.T * n_steps_per_day) - 1
        S_T = paths[:, idx_T]

        if q.kind == "vanilla_call":
            payoff = np.maximum(S_T - q.K, 0.0)
        elif q.kind == "vanilla_put":
            payoff = np.maximum(q.K - S_T, 0.0)
        elif q.kind == "chooser":
            idx_T1 = int(q.choose_T * n_steps_per_day) - 1
            S_T1 = paths[:, idx_T1]
            tau = q.T - q.choose_T
            sT = sigma_constant * math.sqrt(tau)
            d1 = (np.log(S_T1 / q.K) + (r + 0.5 * sigma_constant ** 2) * tau) / sT
            d2 = d1 - sT
            c_val = S_T1 * norm.cdf(d1) - q.K * math.exp(-r * tau) * norm.cdf(d2)
            p_val = q.K * math.exp(-r * tau) * norm.cdf(-d2) - S_T1 * norm.cdf(-d1)
            chosen = np.maximum(c_val, p_val)
            payoff = chosen * math.exp(-r * q.choose_T)
        elif q.kind == "binary_put":
            payoff = np.where(S_T < q.K, q.binary_payoff, 0.0)
        elif q.kind == "ko_put":
            min_to_T = running_min[:, idx_T]
            knocked = min_to_T <= q.barrier
            payoff = np.where(knocked, 0.0, np.maximum(q.K - S_T, 0.0))
        out[q.name] = payoff.mean() * math.exp(-r * q.T)
    return out


# ============================================================================
# Pricing wrapper that respects the smile
# ============================================================================

def price_with_sigma(q, S, sigma, r=0.0, ko_use_discrete=True):
    if q.kind == "vanilla_call":
        return bs_call(S, q.K, q.T, sigma, r)
    if q.kind == "vanilla_put":
        return bs_put(S, q.K, q.T, sigma, r)
    if q.kind == "chooser":
        return chooser_simple(S, q.K, q.choose_T, q.T, sigma, r)
    if q.kind == "binary_put":
        return binary_put(S, q.K, q.T, sigma, q.binary_payoff, r)
    if q.kind == "ko_put":
        if ko_use_discrete:
            n_steps = WIKI_STEPS[int(q.T)]
            fv, _ = down_and_out_put_discrete_mc(S, q.K, q.barrier, q.T,
                                                 sigma, n_steps=n_steps, r=r)
            return fv
        return down_and_out_put(S, q.K, q.barrier, q.T, sigma, r)
    return None


def price_with_smile(q, S, smile_ivs, r=0.0):
    """Pick σ for this contract from the smile."""
    if q.kind in ("vanilla_call", "vanilla_put", "binary_put"):
        sig = smile_lookup(q.K, q.T, smile_ivs)
        return price_with_sigma(q, S, sig, r)
    if q.kind == "chooser":
        # Use term-structure σ: σ_T1 for the put-leg, σ_T2 for the call-leg.
        sig_T2 = smile_lookup(q.K, q.T,         smile_ivs)
        sig_T1 = smile_lookup(q.K, q.choose_T,  smile_ivs)
        return chooser_simple(S, q.K, q.choose_T, q.T, sig_T2, r, sigma_T1=sig_T1)
    if q.kind == "ko_put":
        # Wiki: barrier monitored on the 4-steps-per-trading-day grid → use
        # discrete-monitoring MC, NOT the continuous closed-form (which
        # underestimates by ~30-50% in this regime).
        sig = smile_lookup(q.K, q.T, smile_ivs)
        n_steps = WIKI_STEPS[int(q.T)]
        fair, _ = down_and_out_put_discrete_mc(S, q.K, q.barrier, q.T, sig,
                                               n_steps=n_steps, r=r)
        return fair
    return None


# ============================================================================
# Decision engine
# ============================================================================

@dataclass
class Decision:
    name: str
    side: str           # BUY | SELL | SKIP
    volume: int
    fair: float
    edge_per_unit: float
    profit: float


def decide(q, fair):
    edge_buy = fair - q.ask
    edge_sell = q.bid - fair
    if edge_buy > 0 and edge_buy >= edge_sell:
        return Decision(q.name, "BUY", q.ask_size, fair, edge_buy,
                        edge_buy * q.ask_size * CONTRACT_SIZE)
    if edge_sell > 0:
        return Decision(q.name, "SELL", q.bid_size, fair, edge_sell,
                        edge_sell * q.bid_size * CONTRACT_SIZE)
    return Decision(q.name, "SKIP", 0, fair, 0.0, 0.0)


# ============================================================================
# Reports
# ============================================================================

def report_calibration():
    print("=" * 86)
    print("  1. CALIBRATION")
    print("=" * 86)
    sigma_flat = calibrate_flat_sigma(QUOTES, S0)
    ivs = per_strike_iv(QUOTES, S0)
    print(f"  S0 = {S0:.4f}    flat-σ LS fit = {sigma_flat:.5f} per √day")
    print(f"  Implied σ per vanilla mid (Brent):")
    for q in QUOTES:
        if q.name in ivs:
            mid = 0.5 * (q.bid + q.ask)
            print(f"    {q.name:<11}  K={q.K:>4.0f}  T={int(q.T):>2}  mid={mid:>6.3f}  σ_imp={ivs[q.name]:.5f}")
    smile_ivs = build_smile(QUOTES, S0)
    print(f"  Term + smile structure:")
    for T in sorted(smile_ivs):
        rows = sorted(smile_ivs[T])
        avg = sum(s for _, s in rows) / len(rows)
        spread = max(s for _, s in rows) - min(s for _, s in rows)
        print(f"    T={int(T):>2}d  count={len(rows)}  σ_mean={avg:.5f}  σ_spread={spread:.5f}")
    return sigma_flat, smile_ivs


def report_fair_values(sigma_flat, smile_ivs):
    print()
    print("=" * 86)
    print("  2. FAIR VALUES (closed-form, three sigma assumptions + Monte Carlo)")
    print("=" * 86)

    # MC under flat σ as a global cross-check.
    mc = mc_price_all(QUOTES, S0, sigma_flat)

    print(f"  {'Contract':<12}{'Bid':>8}{'Ask':>8}{'Mid':>8}"
          f"{'CF(flat σ)':>12}{'CF(smile)':>12}{'MC(flat)':>12}{'σ_used':>9}")
    for q in QUOTES:
        if q.kind == "underlying":
            continue
        mid = 0.5 * (q.bid + q.ask)
        fv_flat = price_with_sigma(q, S0, sigma_flat)
        fv_smile = price_with_smile(q, S0, smile_ivs)
        # which σ smile picked
        if q.kind == "ko_put":
            sig_smile = smile_lookup(q.K, q.T, smile_ivs)
        elif q.kind in ("vanilla_call", "vanilla_put", "binary_put", "chooser"):
            sig_smile = smile_lookup(q.K, q.T, smile_ivs)
        else:
            sig_smile = sigma_flat
        print(f"  {q.name:<12}{q.bid:>8.3f}{q.ask:>8.3f}{mid:>8.3f}"
              f"{fv_flat:>12.4f}{fv_smile:>12.4f}{mc[q.name]:>12.4f}{sig_smile:>9.5f}")
    return mc


def report_decisions(sigma_flat, smile_ivs, label="flat σ"):
    print()
    print("=" * 86)
    print(f"  3. TRADE DECISIONS ({label})")
    print("=" * 86)

    decisions = []
    print(f"  {'Contract':<12}{'Bid':>7}{'Ask':>7}{'Fair':>8}"
          f"{'Side':>6}{'Vol':>5}{'Edge/u':>9}{'Profit':>14}")
    total = 0.0
    for q in QUOTES:
        if q.kind == "underlying":
            continue
        if label == "flat σ":
            fair = price_with_sigma(q, S0, sigma_flat)
        elif label == "smile":
            fair = price_with_smile(q, S0, smile_ivs)
        else:
            raise ValueError(label)
        d = decide(q, fair)
        decisions.append(d)
        total += d.profit
        print(f"  {q.name:<12}{q.bid:>7.3f}{q.ask:>7.3f}{fair:>8.4f}"
              f"{d.side:>6}{d.volume:>5}{d.edge_per_unit:>+9.4f}{d.profit:>+14,.1f}")
    print(f"  {'-' * 80}")
    print(f"  {'TOTAL':<12}{'':>7}{'':>7}{'':>8}{'':>6}{'':>5}{'':>9}{total:>+14,.1f}  XIRECs")
    return decisions, total


def report_sensitivity(sigma_flat):
    print()
    print("=" * 86)
    print("  4. SIGMA SENSITIVITY — does each decision survive ±20% on σ?")
    print("=" * 86)
    sigmas = [sigma_flat * f for f in (0.80, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20)]
    rows = []
    for q in QUOTES:
        if q.kind == "underlying":
            continue
        row = [q.name]
        for s in sigmas:
            fv = price_with_sigma(q, S0, s)
            d = decide(q, fv)
            row.append(d.side + ("" if d.side == "SKIP" else f" {d.edge_per_unit:+.3f}"))
        rows.append(row)
    header = f"  {'Contract':<12}" + "".join(f"{s:>14.4f}" for s in sigmas)
    print(header)
    for r in rows:
        cells = "".join(f"{c:>14}" for c in r[1:])
        print(f"  {r[0]:<12}{cells}")


def report_total_variations(sigma_flat, smile_ivs):
    print()
    print("=" * 86)
    print("  5. TOTAL PROFIT UNDER DIFFERENT MODELS")
    print("=" * 86)
    print(f"  {'Model':<32}{'Total profit (XIRECs)':>26}")

    # flat σ
    _, total_flat = run_model(sigma_flat, smile_ivs, mode="flat")
    # smile
    _, total_smile = run_model(sigma_flat, smile_ivs, mode="smile")
    # σ ±5%
    _, total_low = run_model(sigma_flat * 0.95, smile_ivs, mode="flat")
    _, total_high = run_model(sigma_flat * 1.05, smile_ivs, mode="flat")
    # σ ±10%
    _, total_lo10 = run_model(sigma_flat * 0.90, smile_ivs, mode="flat")
    _, total_hi10 = run_model(sigma_flat * 1.10, smile_ivs, mode="flat")

    for label, val in [
        ("flat σ (LS fit)", total_flat),
        ("smile (per-strike σ)", total_smile),
        ("flat σ × 0.95", total_low),
        ("flat σ × 1.05", total_high),
        ("flat σ × 0.90", total_lo10),
        ("flat σ × 1.10", total_hi10),
    ]:
        print(f"  {label:<32}{val:>26,.0f}")


def run_model(sigma_flat, smile_ivs, mode="flat"):
    decisions = []
    total = 0.0
    for q in QUOTES:
        if q.kind == "underlying":
            continue
        if mode == "flat":
            fair = price_with_sigma(q, S0, sigma_flat)
        elif mode == "smile":
            fair = price_with_smile(q, S0, smile_ivs)
        else:
            raise ValueError(mode)
        d = decide(q, fair)
        decisions.append(d)
        total += d.profit
    return decisions, total


def report_submission(decisions):
    print()
    print("=" * 86)
    print("  8. SUBMISSION CANDIDATES")
    print("=" * 86)

    # Candidate A: model-EV-maximizing (naked sells / buys, smile-σ pricing)
    print("  --- Candidate A: model-EV-max (naked, no static hedges) ---")
    total_a = 0.0
    for d in decisions:
        if d.side == "SKIP":
            continue
        total_a += d.profit
        print(f"    {d.name:<12} {d.side:<5} {d.volume:>3} contracts  "
              f"(fair {d.fair:>7.4f}, edge {d.edge_per_unit:+.4f}/unit, "
              f"+{d.profit:>10,.0f} XIRECs)")
    print(f"    Expected total (A):  +{total_a:>10,.0f} XIRECs (high variance, exposed to model risk)")

    # Candidate B: chooser arbitrage + binary put + KO put
    chooser = QUOTES_BY_NAME["AC_50_CO"]
    call_T2 = QUOTES_BY_NAME["AC_50_C"]
    put_T1 = QUOTES_BY_NAME["AC_50_P_2"]
    bp = QUOTES_BY_NAME["AC_40_BP"]
    ko = QUOTES_BY_NAME["AC_45_KO"]
    arb_edge = chooser.bid - call_T2.ask - put_T1.ask
    print()
    print("  --- Candidate B: chooser static-hedge arb + naked binary/KO ---")
    print(f"    AC_50_CO     SELL  50  @ {chooser.bid:.3f}     "
          f"→ +{chooser.bid * 50 * CONTRACT_SIZE:>10,.0f}")
    print(f"    AC_50_C      BUY   50  @ {call_T2.ask:.3f}     "
          f"→ -{call_T2.ask * 50 * CONTRACT_SIZE:>10,.0f}")
    print(f"    AC_50_P_2    BUY   50  @ {put_T1.ask:.3f}      "
          f"→ -{put_T1.ask * 50 * CONTRACT_SIZE:>10,.0f}")
    arb_total = arb_edge * 50 * CONTRACT_SIZE
    print(f"      [chooser arb subtotal: {arb_total:+,.0f} XIRECs, near-zero variance]")
    bp_decision = next(d for d in decisions if d.name == "AC_40_BP")
    ko_decision = next(d for d in decisions if d.name == "AC_45_KO")
    print(f"    AC_40_BP     {bp_decision.side:<5} {bp_decision.volume:>2}  "
          f"(fair {bp_decision.fair:.4f}, edge {bp_decision.edge_per_unit:+.4f}/u) "
          f"→ +{bp_decision.profit:>10,.0f}")
    print(f"    AC_45_KO     {ko_decision.side:<5} {ko_decision.volume:>2} "
          f"(fair {ko_decision.fair:.4f}, edge {ko_decision.edge_per_unit:+.4f}/u) "
          f"→ +{ko_decision.profit:>10,.0f}")
    total_b = arb_total + bp_decision.profit + ko_decision.profit
    print(f"    Expected total (B):  +{total_b:>10,.0f} XIRECs (lower variance than A)")

    # Candidate C: pure arbitrage only (no model risk)
    print()
    print("  --- Candidate C: pure chooser arbitrage only (lowest risk) ---")
    print(f"    AC_50_CO     SELL  50, AC_50_C BUY 50, AC_50_P_2 BUY 50")
    print(f"    Expected total (C):  +{arb_total:>10,.0f} XIRECs (≈ riskless)")


def report_ko_monitoring(sigma_flat, smile_ivs):
    """The KO put fair value depends on barrier monitoring frequency.
    Continuous monitoring gives the lowest fair value (most knock-outs).
    Daily monitoring gives a higher value. Show both bounds."""
    print()
    print("=" * 86)
    print("  4b. KNOCK-OUT PUT — sensitivity to barrier monitoring frequency")
    print("=" * 86)
    q = QUOTES_BY_NAME["AC_45_KO"]
    sig = smile_lookup(q.K, q.T, smile_ivs)

    # Continuous monitoring (closed form)
    cf_cont = down_and_out_put(S0, q.K, q.barrier, q.T, sig)

    # Discrete monitoring via MC (n steps/day = 1, 4, 8, 50, 200)
    rng_seed = 20260427
    rows = []
    for steps in (1, 4, 8, 50, 200):
        n_steps = int(q.T * steps)
        # cap memory by adjusting path count for finer grids
        n_paths = min(200_000, max(20_000, 200_000_000 // n_steps))
        rng = np.random.default_rng(rng_seed)
        dt = 1.0 / steps
        # streaming min to avoid storing the full path tensor
        log_S = np.full(n_paths, math.log(S0))
        log_min = log_S.copy()
        drift = -0.5 * sig * sig * dt
        sd = sig * math.sqrt(dt)
        for _ in range(n_steps):
            log_S += drift + sd * rng.standard_normal(n_paths)
            np.minimum(log_min, log_S, out=log_min)
        S_T = np.exp(log_S)
        min_S = np.exp(log_min)
        knocked = min_S <= q.barrier
        payoff = np.where(knocked, 0.0, np.maximum(q.K - S_T, 0.0))
        rows.append((steps, n_paths, payoff.mean()))

    # Wiki's exact 60-step grid:
    fair_60, se_60 = down_and_out_put_discrete_mc(S0, q.K, q.barrier, q.T,
                                                  sig, n_steps=60,
                                                  n_paths=400_000)
    print(f"  σ used = {sig:.5f} (smile σ at K={q.K})")
    print(f"  closed form (continuous monitoring) : {cf_cont:.5f}  (LOWER bound)")
    print(f"  Monte Carlo by monitoring frequency:")
    for steps, n_paths, val in rows:
        period = "daily" if steps == 1 else f"{steps}/day"
        print(f"    n_steps_per_day = {steps:>3}  ({period:<8}, paths={n_paths:>6}) :  fair ≈ {val:.5f}")
    print()
    print(f"  >>> WIKI GRID (60 steps over T+21 = 4 steps/trading day × 15 trading days):")
    print(f"  >>> fair = {fair_60:.5f}  ± {se_60:.5f}  (400k paths)  <<< CANONICAL")
    print(f"  market: bid {q.bid}  ask {q.ask}")
    if fair_60 < q.bid:
        print(f"  → SELL profitable: edge = {q.bid - fair_60:+.4f}/unit "
              f"× 500 vol × 3000 = {(q.bid - fair_60) * 500 * CONTRACT_SIZE:+,.0f} XIRECs")
    elif fair_60 > q.ask:
        print(f"  → BUY profitable: edge = {fair_60 - q.ask:+.4f}/unit "
              f"× 500 vol × 3000 = {(fair_60 - q.ask) * 500 * CONTRACT_SIZE:+,.0f} XIRECs")
    else:
        print(f"  → SKIP: fair lies inside the spread "
              f"[{q.bid - fair_60:+.4f}, {fair_60 - q.ask:+.4f}]")


def report_chooser_arbitrage():
    """The Rubinstein chooser identity gives an (almost) static hedge:

        chooser(K, T1, T2) = call(K, T2) + put(K, T1)    [r = q = 0]

    holds *in expectation* under any pricing model the simulator uses for all
    three legs. Selling the chooser and buying the call_T2 + put_T1 legs is
    therefore a near-riskless trade as long as IMC marks all three to mean of
    the same path bundle.
    """
    print()
    print("=" * 86)
    print("  4c. CHOOSER STATIC-HEDGE ARBITRAGE")
    print("=" * 86)

    chooser = QUOTES_BY_NAME["AC_50_CO"]
    call_T2 = QUOTES_BY_NAME["AC_50_C"]      # T = 21 = T2
    put_T1 = QUOTES_BY_NAME["AC_50_P_2"]     # T = 14 = T1

    sell_chooser_revenue = chooser.bid
    buy_hedge_cost = call_T2.ask + put_T1.ask
    arb_per_unit = sell_chooser_revenue - buy_hedge_cost

    print(f"  Identity: chooser(K=50, T1=2w, T2=3w) = call(K=50, T2) + put(K=50, T1)")
    print(f"  Mids:     22.250  ?=?  12.025 + 9.725 = 21.750   (Δ = +0.500 — chooser overpriced)")
    print()
    print(f"  Hedged trade (at marketable prices):")
    print(f"    SELL chooser  @ {chooser.bid:>6.3f}                  → +{chooser.bid:.3f}/unit")
    print(f"    BUY  call_T2  @ {call_T2.ask:>6.3f} (= AC_50_C)        → -{call_T2.ask:.3f}/unit")
    print(f"    BUY  put_T1   @ {put_T1.ask:>6.3f} (= AC_50_P_2)      → -{put_T1.ask:.3f}/unit")
    print(f"    {'-' * 70}")
    print(f"    Net edge per unit:                            {arb_per_unit:>+7.3f}")
    print(f"    × 50 contracts × 3000 contract-size       =  {arb_per_unit * 50 * CONTRACT_SIZE:>+10,.0f} XIRECs")
    print()
    print(f"  Volume cap: 50 (chooser bid size = call ask size = put ask size).")
    print(f"  Variance: NOT exactly zero per-path (chooser cash flow is at T2,")
    print(f"            put_T1 cash flow is at T1; difference is the conditional")
    print(f"            martingale residual S_T1 - S_T2 in the put-chosen scenario).")
    print(f"            But IMC marks each contract to the *mean of 100 sims*, so")
    print(f"            the path-by-path residual averages to ~0; expected PnL is")
    print(f"            the static-hedge edge above with standard error ≈ "
          f"σ·S·√(T2-T1)/√100 ≈ {2.51 * 50 * math.sqrt(5/252) / 10:.2f}/unit.")
    print(f"  → much lower variance than the naked SELL chooser at edge +0.45.")


def report_robustness(sigma_flat):
    print()
    print("=" * 86)
    print("  7. EDGE ROBUSTNESS — minimum |edge| per contract over σ ∈ [0.80, 1.20] · σ̂")
    print("=" * 86)
    sigmas = np.linspace(0.80, 1.20, 17) * sigma_flat
    print(f"  {'Contract':<12}{'Side(σ̂)':>10}{'edge_min':>11}{'edge_max':>11}"
          f"{'sign-flips':>12}")
    for q in QUOTES:
        if q.kind == "underlying":
            continue
        edges = []
        sides = []
        for s in sigmas:
            fv = price_with_sigma(q, S0, s)
            edges.append(max(fv - q.ask, q.bid - fv))  # signed: sign of best edge
            d = decide(q, fv)
            sides.append(d.side)
        signs = set(sides) - {"SKIP"}
        flips = len([1 for i in range(1, len(sides)) if sides[i] != sides[i - 1]])
        side_at_hat = decide(q, price_with_sigma(q, S0, sigma_flat)).side
        print(f"  {q.name:<12}{side_at_hat:>10}"
              f"{min(edges):>11.4f}{max(edges):>11.4f}{flips:>12d}")


# ============================================================================
# Main
# ============================================================================

def main():
    sigma_flat, smile_ivs = report_calibration()
    report_fair_values(sigma_flat, smile_ivs)
    decisions_flat, _ = report_decisions(sigma_flat, smile_ivs, label="flat σ")
    decisions_smile, _ = report_decisions(sigma_flat, smile_ivs, label="smile")
    report_sensitivity(sigma_flat)
    report_ko_monitoring(sigma_flat, smile_ivs)
    report_chooser_arbitrage()
    report_robustness(sigma_flat)
    report_total_variations(sigma_flat, smile_ivs)
    # Final recommended submission uses the smile (more accurate for non-ATM).
    report_submission(decisions_smile)


if __name__ == "__main__":
    main()
