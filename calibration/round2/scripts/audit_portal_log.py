"""Audit a portal submission log against the Rust Monte Carlo sim's bot models.

Usage:
    py -3.13 audit_portal_log.py <path_to_submission.log>

Computes:
  1. Bot formula match rate per side per depth for ASH_COATED_OSMIUM and INTARIAN_PEPPER_ROOT
  2. Bot presence rate per side per depth
  3. Drift verification for PEPPER (should be +0.1/tick)
  4. Per-tick PnL trajectory + extrapolated full-day PnL
  5. Trade summary (own/market, per product)

Output: markdown report printed to stdout, JSON summary written next to the input log.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


# Bot formulas from rust_simulator/src/main.rs
def ash_bot1(fv: float) -> tuple[int, int]:
    """Outer wall: bid = floor(FV) - 10, ask = ceil(FV) + 10."""
    return math.floor(fv) - 10, math.ceil(fv) + 10


def ash_bot2(fv: float) -> tuple[int, int]:
    """Inner wall: bid = floor(FV - 0.5) - 7, ask = floor(FV - 0.5) + 9."""
    r = math.floor(fv - 0.5)
    return r - 7, r + 9


def ipr_bot1(fv: float) -> tuple[int, int]:
    """Proportional K = 3/4000."""
    K = 3.0 / 4000.0
    return math.floor(fv * (1 - K)), math.ceil(fv * (1 + K))


def ipr_bot2(fv: float) -> tuple[int, int]:
    """Proportional K = 1/2000."""
    K = 1.0 / 2000.0
    return math.floor(fv * (1 - K)), math.ceil(fv * (1 + K))


def parse_log(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def rows_from_activities(activities: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(activities), delimiter=';'))


def infer_pepper_fv_day0(tick_index: int, start_fv: float = 12000.0) -> float:
    """PEPPER deterministic drift: FV(t) = start + 0.1 * t. start_fv is the FV at tick 0.

    From portal log 226828, tick 0 mid = 11998.5 with bid=11991 ask=12006.
    If bid=11991 is Bot1: floor(FV * (1 - 3/4000)) = 11991 ⇒ FV ∈ [11999.99, 12008.99).
    So start_fv ≈ 12000 is a good default.
    """
    return start_fv + 0.1 * tick_index


def audit_pepper(rows: list[dict], start_fv: float = 12000.0) -> dict:
    """For each tick, check which visible levels match Bot1/Bot2 formulas."""
    pepper_rows = [r for r in rows if r['product'] == 'INTARIAN_PEPPER_ROOT']
    pepper_rows.sort(key=lambda x: int(x['timestamp']))

    total_ticks = len(pepper_rows)
    bot1_bid_match = bot1_ask_match = bot2_bid_match = bot2_ask_match = 0
    bot1_bid_seen = bot1_ask_seen = bot2_bid_seen = bot2_ask_seen = 0
    bid_level_count = Counter()
    ask_level_count = Counter()
    offset_examples = {'bot1_bid': [], 'bot1_ask': [], 'bot2_bid': [], 'bot2_ask': []}

    for i, r in enumerate(pepper_rows):
        fv = infer_pepper_fv_day0(i, start_fv)
        b1_bid, b1_ask = ipr_bot1(fv)
        b2_bid, b2_ask = ipr_bot2(fv)

        bids = [(int(r[f'bid_price_{k}']), int(r[f'bid_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'bid_price_{k}') and r[f'bid_price_{k}'] != '']
        asks = [(int(r[f'ask_price_{k}']), int(r[f'ask_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'ask_price_{k}') and r[f'ask_price_{k}'] != '']
        bid_level_count[len(bids)] += 1
        ask_level_count[len(asks)] += 1

        # Match bot1 by checking all visible levels
        for p, v in bids:
            if p == b1_bid and 15 <= v <= 25:
                bot1_bid_match += 1
                bot1_bid_seen += 1
                break
            elif p == b2_bid and 8 <= v <= 12:
                bot2_bid_match += 1
                bot2_bid_seen += 1
                break
        # Also check second-pass for bot2 if not matched above
        for p, v in bids:
            if p == b2_bid and 8 <= v <= 12 and bot2_bid_seen < i + 1:
                # Only increment if not already counted
                pass  # simpler: just do separate passes

        # Simpler audit: count presence and match per bot independently
        bot1_bid_present = any(p == b1_bid for p, _ in bids)
        bot1_ask_present = any(p == b1_ask for p, _ in asks)
        bot2_bid_present = any(p == b2_bid for p, _ in bids)
        bot2_ask_present = any(p == b2_ask for p, _ in asks)

        # Record offset examples for misses (first few mismatches per bot per side)
        if not bot1_bid_present and bids and len(offset_examples['bot1_bid']) < 5:
            offsets = [p - b1_bid for p, _ in bids]
            offset_examples['bot1_bid'].append({'tick': i, 'fv': fv, 'expected': b1_bid, 'observed': bids, 'offsets': offsets})
        if not bot2_bid_present and bids and len(offset_examples['bot2_bid']) < 5:
            offsets = [p - b2_bid for p, _ in bids]
            offset_examples['bot2_bid'].append({'tick': i, 'fv': fv, 'expected': b2_bid, 'observed': bids, 'offsets': offsets})

    # Re-do clean count
    bot1_bid_seen = bot1_ask_seen = bot2_bid_seen = bot2_ask_seen = 0
    for i, r in enumerate(pepper_rows):
        fv = infer_pepper_fv_day0(i, start_fv)
        b1_bid, b1_ask = ipr_bot1(fv)
        b2_bid, b2_ask = ipr_bot2(fv)
        bids = [(int(r[f'bid_price_{k}']), int(r[f'bid_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'bid_price_{k}') and r[f'bid_price_{k}'] != '']
        asks = [(int(r[f'ask_price_{k}']), int(r[f'ask_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'ask_price_{k}') and r[f'ask_price_{k}'] != '']
        if any(p == b1_bid for p, _ in bids):
            bot1_bid_seen += 1
        if any(p == b1_ask for p, _ in asks):
            bot1_ask_seen += 1
        if any(p == b2_bid for p, _ in bids):
            bot2_bid_seen += 1
        if any(p == b2_ask for p, _ in asks):
            bot2_ask_seen += 1

    # Drift check: consecutive mid diffs
    mids = [float(r['mid_price']) for r in pepper_rows]
    deltas = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
    mean_drift = sum(deltas) / len(deltas) if deltas else 0.0

    return {
        'total_ticks': total_ticks,
        'mean_drift_per_tick': mean_drift,
        'bot1_bid_presence': bot1_bid_seen / total_ticks,
        'bot1_ask_presence': bot1_ask_seen / total_ticks,
        'bot2_bid_presence': bot2_bid_seen / total_ticks,
        'bot2_ask_presence': bot2_ask_seen / total_ticks,
        'bid_level_histogram': dict(bid_level_count),
        'ask_level_histogram': dict(ask_level_count),
        'bot1_bid_miss_samples': offset_examples['bot1_bid'][:3],
        'bot2_bid_miss_samples': offset_examples['bot2_bid'][:3],
    }


def audit_osmium(rows: list[dict]) -> dict:
    """OSMIUM FV is a random walk — no ground-truth without hold-1 submission.
    We approximate FV by: FV ≈ mid_price (from observed book).
    Then we check whether the *inner* level matches Bot2 formula given the outer level as Bot1 anchor.
    """
    osm_rows = [r for r in rows if r['product'] == 'ASH_COATED_OSMIUM']
    osm_rows.sort(key=lambda x: int(x['timestamp']))
    total = len(osm_rows)

    # Strategy: for each tick with at least 2 levels on a side, assume the outer is Bot1 and infer FV.
    # Bot1 bid = floor(FV) - 10  ⇒  FV ∈ [bid_outer + 10, bid_outer + 11)
    # Check if inner matches Bot2 formula: bid_inner = floor(FV - 0.5) - 7
    bot2_bid_match_when_known = 0
    bot2_bid_eligible = 0
    bot2_ask_match_when_known = 0
    bot2_ask_eligible = 0

    bid_level_count = Counter()
    ask_level_count = Counter()
    vol_at_each_level = defaultdict(list)

    for r in osm_rows:
        bids = [(int(r[f'bid_price_{k}']), int(r[f'bid_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'bid_price_{k}') and r[f'bid_price_{k}'] != '']
        asks = [(int(r[f'ask_price_{k}']), int(r[f'ask_volume_{k}'])) for k in (1, 2, 3)
                if r.get(f'ask_price_{k}') and r[f'ask_price_{k}'] != '']
        bid_level_count[len(bids)] += 1
        ask_level_count[len(asks)] += 1
        for i, (_, v) in enumerate(bids):
            vol_at_each_level[f'bid_{i+1}'].append(v)
        for i, (_, v) in enumerate(asks):
            vol_at_each_level[f'ask_{i+1}'].append(v)

        # Infer FV from outer bid (largest depth among bids with volume 20-30 suggests Bot1)
        bot1_bid_candidates = [p for p, v in bids if 20 <= v <= 30]
        if bot1_bid_candidates and len(bids) >= 2:
            # Outer wall = deepest (largest vol) OR rightmost by price-descending-order sort
            # Take the min price among Bot1 candidates
            fv_low = min(bot1_bid_candidates) + 10  # FV ≥ this
            # Look for Bot2: inner bid should satisfy floor(FV-0.5) - 7 = inner_bid_price
            # With FV in [fv_low, fv_low+1), Bot2 bid is either fv_low - 8 or fv_low - 7
            expected_b2_bid = {fv_low - 8, fv_low - 7}
            inner_bids = [(p, v) for p, v in bids if p > min(bot1_bid_candidates)]
            if inner_bids:
                bot2_bid_eligible += 1
                if any(p in expected_b2_bid and 10 <= v <= 15 for p, v in inner_bids):
                    bot2_bid_match_when_known += 1

        bot1_ask_candidates = [p for p, v in asks if 20 <= v <= 30]
        if bot1_ask_candidates and len(asks) >= 2:
            fv_high = max(bot1_ask_candidates) - 10  # FV ≤ this
            expected_b2_ask = {fv_high + 7, fv_high + 8, fv_high + 9}  # depending on FV fractional
            inner_asks = [(p, v) for p, v in asks if p < max(bot1_ask_candidates)]
            if inner_asks:
                bot2_ask_eligible += 1
                if any(p in expected_b2_ask and 10 <= v <= 15 for p, v in inner_asks):
                    bot2_ask_match_when_known += 1

    mean_vols = {k: sum(v) / len(v) for k, v in vol_at_each_level.items() if v}

    return {
        'total_ticks': total,
        'bid_level_histogram': dict(bid_level_count),
        'ask_level_histogram': dict(ask_level_count),
        'mean_vol_by_level': mean_vols,
        'bot2_bid_match_rate_given_bot1_visible': (bot2_bid_match_when_known / bot2_bid_eligible) if bot2_bid_eligible else None,
        'bot2_ask_match_rate_given_bot1_visible': (bot2_ask_match_when_known / bot2_ask_eligible) if bot2_ask_eligible else None,
        'bot2_bid_eligible_ticks': bot2_bid_eligible,
        'bot2_ask_eligible_ticks': bot2_ask_eligible,
    }


def summarize_trades(trades: list[dict]) -> dict:
    own_buy_qty = sum(t['quantity'] for t in trades if t.get('buyer') == 'SUBMISSION')
    own_sell_qty = sum(t['quantity'] for t in trades if t.get('seller') == 'SUBMISSION')
    market_only = sum(t['quantity'] for t in trades if t.get('buyer') != 'SUBMISSION' and t.get('seller') != 'SUBMISSION')
    by_product = Counter(t['symbol'] for t in trades)
    own_trades_per_product = Counter(
        t['symbol'] for t in trades
        if t.get('buyer') == 'SUBMISSION' or t.get('seller') == 'SUBMISSION'
    )
    return {
        'total_trades': len(trades),
        'own_buy_qty': own_buy_qty,
        'own_sell_qty': own_sell_qty,
        'market_only_qty': market_only,
        'trades_by_product': dict(by_product),
        'own_trades_by_product': dict(own_trades_per_product),
    }


def compute_final_pnl(rows: list[dict]) -> dict:
    by_key = {}
    for r in rows:
        k = (r['day'], r['product'])
        t = int(r['timestamp'])
        pnl = float(r['profit_and_loss'])
        if k not in by_key or t > by_key[k][0]:
            by_key[k] = (t, pnl)
    per_prod = defaultdict(float)
    for (day, prod), (t, pnl) in by_key.items():
        per_prod[prod] += pnl
    return {'per_product': dict(per_prod), 'total': sum(per_prod.values())}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    log_path = Path(sys.argv[1])
    d = parse_log(log_path)
    rows = rows_from_activities(d['activitiesLog'])
    trades = d.get('tradeHistory', [])

    pepper = audit_pepper(rows)
    osmium = audit_osmium(rows)
    pnl = compute_final_pnl(rows)
    trade_summary = summarize_trades(trades)

    total_ticks = pepper['total_ticks']

    report = {
        'log': str(log_path),
        'total_ticks_per_product': total_ticks,
        'final_pnl': pnl,
        'trade_summary': trade_summary,
        'pepper': pepper,
        'osmium': osmium,
    }

    print('=' * 70)
    print('Portal log audit:', log_path.name)
    print('=' * 70)
    print(f'Total ticks (per product): {total_ticks}')
    print(f'Final PnL: total={pnl["total"]:.2f}')
    for p, v in pnl['per_product'].items():
        print(f'  {p}: {v:.2f}')
    day_scale = 10000 / total_ticks if total_ticks else 1.0
    print(f'\nExtrapolated to 10,000 ticks (1 real day): {pnl["total"] * day_scale:.0f}')

    print('\n--- TRADES ---')
    for k, v in trade_summary.items():
        print(f'  {k}: {v}')

    print('\n--- PEPPER ---')
    print(f'  drift per tick (observed): {pepper["mean_drift_per_tick"]:.5f} (calibrated: 0.10000)')
    print(f'  Bot1 bid presence: {pepper["bot1_bid_presence"]:.2%} (calibrated: 80.0%)')
    print(f'  Bot1 ask presence: {pepper["bot1_ask_presence"]:.2%} (calibrated: 80.0%)')
    print(f'  Bot2 bid presence: {pepper["bot2_bid_presence"]:.2%} (calibrated: 80.0%)')
    print(f'  Bot2 ask presence: {pepper["bot2_ask_presence"]:.2%} (calibrated: 80.0%)')
    print(f'  bid levels histogram: {pepper["bid_level_histogram"]}')
    print(f'  ask levels histogram: {pepper["ask_level_histogram"]}')
    if pepper['bot1_bid_miss_samples']:
        print(f'  First Bot1 bid misses:')
        for s in pepper['bot1_bid_miss_samples']:
            print(f'    tick={s["tick"]} FV={s["fv"]:.2f} expected={s["expected"]} observed={s["observed"]} offsets={s["offsets"]}')
    if pepper['bot2_bid_miss_samples']:
        print(f'  First Bot2 bid misses:')
        for s in pepper['bot2_bid_miss_samples']:
            print(f'    tick={s["tick"]} FV={s["fv"]:.2f} expected={s["expected"]} observed={s["observed"]} offsets={s["offsets"]}')

    print('\n--- OSMIUM ---')
    print(f'  bid levels histogram: {osmium["bid_level_histogram"]}')
    print(f'  ask levels histogram: {osmium["ask_level_histogram"]}')
    print(f'  mean vol by level: {osmium["mean_vol_by_level"]}')
    print(f'  Bot2 bid match rate (given Bot1 visible): {osmium["bot2_bid_match_rate_given_bot1_visible"]}')
    print(f'  Bot2 ask match rate (given Bot1 visible): {osmium["bot2_ask_match_rate_given_bot1_visible"]}')

    out_path = log_path.with_suffix('.audit.json')
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f'\nFull report saved: {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
