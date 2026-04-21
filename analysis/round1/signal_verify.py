"""Verify Bot1 asymmetry signal and quantify trading opportunities."""
import csv
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "prosperity4", "round1")

def load_aco_ticks(day_suffix):
    """Load ACO ticks from price CSV. Returns list of dicts."""
    path = os.path.join(DATA_DIR, f"prices_round_1_day_{day_suffix}.csv")
    ticks = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] != 'ASH_COATED_OSMIUM':
                continue
            tick = {
                'ts': int(row['timestamp']),
                'bid1': int(row['bid_price_1']) if row['bid_price_1'] else None,
                'bv1': int(row['bid_volume_1']) if row['bid_volume_1'] else None,
                'bid2': int(row['bid_price_2']) if row['bid_price_2'] else None,
                'bv2': int(row['bid_volume_2']) if row['bid_volume_2'] else None,
                'bid3': int(row['bid_price_3']) if row['bid_price_3'] else None,
                'bv3': int(row['bid_volume_3']) if row['bid_volume_3'] else None,
                'ask1': int(row['ask_price_1']) if row['ask_price_1'] else None,
                'av1': int(row['ask_volume_1']) if row['ask_volume_1'] else None,
                'ask2': int(row['ask_price_2']) if row['ask_price_2'] else None,
                'av2': int(row['ask_volume_2']) if row['ask_volume_2'] else None,
                'ask3': int(row['ask_price_3']) if row['ask_price_3'] else None,
                'av3': int(row['ask_volume_3']) if row['ask_volume_3'] else None,
                'mid': float(row['mid_price']) if row['mid_price'] else None,
            }
            ticks.append(tick)
    return ticks


def extract_fv_and_signals(ticks):
    """Extract FV series and Bot1 asymmetry signal."""
    results = []
    last_fv = None

    for t in ticks:
        fv = None
        bot1_asym = None

        # FV extraction: symmetric ticks with spread=16, both L1 vol 10-15
        if (t['bid1'] is not None and t['ask1'] is not None):
            spread = t['ask1'] - t['bid1']
            if spread == 16 and t['bv1'] and t['av1']:
                if 10 <= t['bv1'] <= 15 and 10 <= t['av1'] <= 15:
                    fv = (t['bid1'] + t['ask1']) / 2

        if fv is None:
            fv = last_fv  # carry forward

        # Bot1 asymmetry: L2 with vol >= 20
        if (fv is not None and t['bid2'] is not None and t['ask2'] is not None
            and t['bv2'] is not None and t['av2'] is not None):
            if t['bv2'] >= 20 and t['av2'] >= 20:
                bid_offset = fv - t['bid2']
                ask_offset = t['ask2'] - fv
                bot1_asym = ask_offset - bid_offset

        # Also check L1 for Bot1 when one side has been hit
        # (Bot1 becomes L1 when Bot2 is consumed)

        results.append({
            'ts': t['ts'],
            'fv': fv,
            'bot1_asym': bot1_asym,
            'bid1': t['bid1'], 'bv1': t['bv1'],
            'bid2': t['bid2'], 'bv2': t['bv2'],
            'bid3': t['bid3'], 'bv3': t['bv3'],
            'ask1': t['ask1'], 'av1': t['av1'],
            'ask2': t['ask2'], 'av2': t['av2'],
            'ask3': t['ask3'], 'av3': t['av3'],
        })

        if fv is not None:
            last_fv = fv

    return results


def analyze_day(day_suffix):
    print(f"\n{'='*70}")
    print(f"  DAY {day_suffix}")
    print(f"{'='*70}")

    ticks = load_aco_ticks(day_suffix)
    results = extract_fv_and_signals(ticks)

    # --- 1. FV extraction stats ---
    fv_series = [(r['ts'], r['fv']) for r in results if r['fv'] is not None]
    print(f"\nTotal ACO ticks: {len(ticks)}")
    print(f"Ticks with FV: {len(fv_series)}")
    if fv_series:
        fvs = [f for _, f in fv_series]
        print(f"FV range: {min(fvs):.0f} - {max(fvs):.0f}")

    # --- 2. Bot1 asymmetry signal ---
    asym_ticks = [(r['ts'], r['bot1_asym'], r['fv']) for r in results
                  if r['bot1_asym'] is not None and r['fv'] is not None]
    print(f"\nBot1 asymmetry ticks: {len(asym_ticks)} / {len(ticks)} ({100*len(asym_ticks)/len(ticks):.1f}%)")

    asym_vals = defaultdict(int)
    for _, asym, _ in asym_ticks:
        asym_vals[asym] += 1
    print(f"Asymmetry distribution: {dict(sorted(asym_vals.items()))}")

    # --- 3. Signal vs next FV change ---
    # Build FV change series
    fv_changes = []
    prev_fv = None
    for r in results:
        if r['fv'] is not None:
            if prev_fv is not None and r['fv'] != prev_fv:
                fv_changes.append((r['ts'], r['fv'] - prev_fv))
            prev_fv = r['fv']

    print(f"\nFV changes: {len(fv_changes)}")

    # For each asymmetry signal, find the next FV change
    correct = 0
    wrong = 0
    no_move = 0

    # Build ts -> fv map for quick lookup
    ts_fv = {r['ts']: r['fv'] for r in results if r['fv'] is not None}
    ts_asym = {r['ts']: r['bot1_asym'] for r in results if r['bot1_asym'] is not None}

    all_ts = sorted(ts_fv.keys())
    ts_idx = {ts: i for i, ts in enumerate(all_ts)}

    # For each tick with asymmetry signal, look at FV change over next N ticks
    for horizon in [1, 3, 5, 10]:
        gains = []
        for ts, asym, fv in asym_ticks:
            if ts not in ts_idx:
                continue
            idx = ts_idx[ts]
            if idx + horizon >= len(all_ts):
                continue
            future_ts = all_ts[idx + horizon]
            future_fv = ts_fv.get(future_ts)
            if future_fv is None:
                continue
            if asym > 0:
                gains.append(future_fv - fv)
            elif asym < 0:
                gains.append(fv - future_fv)

        if gains:
            avg = sum(gains) / len(gains)
            wins = sum(1 for g in gains if g > 0)
            flat = sum(1 for g in gains if g == 0)
            losses = sum(1 for g in gains if g < 0)
            print(f"  Horizon {horizon}: avg={avg:.3f}, win={wins}, flat={flat}, loss={losses}, "
                  f"accuracy={wins/(wins+losses)*100:.1f}% (excl flat), n={len(gains)}")

    # --- 4. Bot3 analysis ---
    print(f"\n--- Bot3 Orders (vol 1-9, close to FV) ---")
    bot3_bids = defaultdict(int)
    bot3_asks = defaultdict(int)
    bot3_bid_details = []
    bot3_ask_details = []

    for r in results:
        if r['fv'] is None:
            continue
        fv = r['fv']

        # Check all levels for small-volume orders close to FV
        for level, vol_key in [('bid1', 'bv1'), ('bid2', 'bv2'), ('bid3', 'bv3')]:
            p = r[level]
            v = r[vol_key]
            if p is not None and v is not None and 1 <= v <= 9:
                offset = fv - p
                if 0 <= offset <= 5:
                    bot3_bids[offset] += 1
                    bot3_bid_details.append((r['ts'], p, v, fv, offset))

        for level, vol_key in [('ask1', 'av1'), ('ask2', 'av2'), ('ask3', 'av3')]:
            p = r[level]
            v = r[vol_key]
            if p is not None and v is not None and 1 <= v <= 9:
                offset = p - fv
                if 0 <= offset <= 5:
                    bot3_asks[offset] += 1
                    bot3_ask_details.append((r['ts'], p, v, fv, offset))

    print(f"  Bot3 bids (FV - offset): {dict(sorted(bot3_bids.items()))}")
    print(f"  Bot3 asks (FV + offset): {dict(sorted(bot3_asks.items()))}")
    print(f"  Total Bot3 bids: {sum(bot3_bids.values())}, asks: {sum(bot3_asks.values())}")

    # --- 5. Book state distribution ---
    print(f"\n--- Book States ---")
    states = defaultdict(int)
    for t in ticks:
        has_b1 = t['bid1'] is not None
        has_b2 = t['bid2'] is not None
        has_a1 = t['ask1'] is not None
        has_a2 = t['ask2'] is not None
        n_bid = sum(1 for x in [t['bid1'], t['bid2'], t['bid3']] if x is not None)
        n_ask = sum(1 for x in [t['ask1'], t['ask2'], t['ask3']] if x is not None)
        spread = (t['ask1'] - t['bid1']) if (t['bid1'] and t['ask1']) else None
        key = f"bids={n_bid} asks={n_ask} spread={spread}"
        states[key] += 1

    for k, v in sorted(states.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k}: {v} ({100*v/len(ticks):.1f}%)")

    # --- 6. Runtime-detectable signal ---
    print(f"\n--- Runtime Signal Detection ---")
    # At runtime we see the book but don't know FV a priori
    # Can we detect Bot1 asymmetry from raw book state?
    #
    # When we have 2+ levels on each side:
    #   L1 vol 10-15 = Bot2 -> FV = bid1 + 8 = ask1 - 8
    #   L2 vol >= 20 = Bot1 -> check offsets from FV

    runtime_detectable = 0
    runtime_correct_fv = 0

    for r in results:
        if r['fv'] is None:
            continue
        # Check if we can detect at runtime
        if (r['bid1'] and r['ask1'] and r['bid2'] and r['ask2']
            and r['bv1'] and r['av1'] and r['bv2'] and r['av2']):
            if (10 <= r['bv1'] <= 15 and 10 <= r['av1'] <= 15
                and r['bv2'] >= 20 and r['av2'] >= 20):
                # We can compute FV from L1
                est_fv_bid = r['bid1'] + 8
                est_fv_ask = r['ask1'] - 8
                if est_fv_bid == est_fv_ask:
                    runtime_detectable += 1
                    if est_fv_bid == r['fv']:
                        runtime_correct_fv += 1

    print(f"  Clean signal ticks (L1=Bot2, L2=Bot1, both sides): {runtime_detectable}")
    print(f"  FV estimation correct: {runtime_correct_fv} / {runtime_detectable}")

    # --- 7. What fills would we get with asymmetric quoting? ---
    print(f"\n--- Asymmetric Quoting Simulation ---")
    # When Bot1 asym > 0 (bullish): bid at FV-5, ask at FV+9
    # When Bot1 asym < 0 (bearish): bid at FV-9, ask at FV+5
    # When no signal: bid at FV-7, ask at FV+7

    # Look at what prices appear in the book that could fill us
    # A bid at price P gets filled if someone sells at P (ask <= P appears)
    # An ask at price P gets filled if someone buys at P (bid >= P appears)

    # Count how often asks appear at or below various FV offsets
    ask_at_offset = defaultdict(int)
    bid_at_offset = defaultdict(int)

    for r in results:
        if r['fv'] is None:
            continue
        fv = r['fv']
        for level in ['ask1', 'ask2', 'ask3']:
            p = r[level]
            if p is not None:
                off = p - fv
                if -3 <= off <= 12:
                    ask_at_offset[off] += 1
        for level in ['bid1', 'bid2', 'bid3']:
            p = r[level]
            if p is not None:
                off = fv - p
                if -3 <= off <= 12:
                    bid_at_offset[off] += 1

    print(f"  Ask prices relative to FV (FV + offset):")
    for off in sorted(ask_at_offset.keys()):
        print(f"    FV+{off}: {ask_at_offset[off]} ticks")
    print(f"  Bid prices relative to FV (FV - offset):")
    for off in sorted(bid_at_offset.keys()):
        print(f"    FV-{off}: {bid_at_offset[off]} ticks")

    return results


def main():
    for day in ['-2', '-1', '0']:
        analyze_day(day)


if __name__ == '__main__':
    main()
