"""Parameter sweep for IPR passive ask strategy at portal scale (1000 ticks)."""
import subprocess
import csv
import re
import sys
import os

TRADER_PATH = os.path.join(os.path.dirname(__file__), '..', 'traders', 'a.py')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'tmp', 'results')

def read_trader():
    with open(TRADER_PATH) as f:
        return f.read()

def write_trader(content):
    with open(TRADER_PATH, 'w') as f:
        f.write(content)

def set_params(original, ask_offset, threshold, ask_qty):
    code = original
    code = re.sub(r'IPR_ASK_OFFSET = \d+', f'IPR_ASK_OFFSET = {ask_offset}', code)
    code = re.sub(r'if position >= \d+:', f'if position >= {threshold}:', code)
    code = re.sub(r'ask_qty = min\(\d+,', f'ask_qty = min({ask_qty},', code)
    return code

def run_backtest(sessions=500, ticks=1000):
    out = os.path.join(RESULTS_DIR, 'sweep_tmp.json')
    result = subprocess.run(
        ['prosperity4mcbt', 'traders/a.py', '--sessions', str(sessions),
         '--out', out, '--ticks-per-day', str(ticks)],
        capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), '..')
    )
    # Parse per-product PnL
    summary_path = os.path.join(RESULTS_DIR, 'session_summary.csv')
    with open(summary_path) as f:
        rows = list(csv.DictReader(f))
    ipr = [float(r['ipr_pnl']) for r in rows]
    ash = [float(r['ash_pnl']) for r in rows]
    n = len(rows)
    return {
        'ipr_mean': sum(ipr)/n,
        'ash_mean': sum(ash)/n,
        'total_mean': (sum(ipr)+sum(ash))/n,
        'ipr_std': (sum((x-sum(ipr)/n)**2 for x in ipr)/n)**0.5,
    }

original = read_trader()

# First: baseline without passive ask
no_ask = original.replace(
    '        # Passive ask at FV+8: fills when Bot 2 absent (~20%), sells above rebuy cost\n'
    '        sell_room = LIMIT + position\n'
    '        if position >= 70:\n'
    '            our_ask = fv_r + self.IPR_ASK_OFFSET\n'
    '            ask_qty = min(15, sell_room)\n'
    '            if ask_qty > 0:\n'
    '                orders.append(Order(PEPPER, our_ask, -ask_qty))',
    '        pass  # No passive ask (baseline)'
)
write_trader(no_ask)
res = run_backtest()
print(f"{'NO ASK (baseline)':>30}  IPR={res['ipr_mean']:>7.1f} (std={res['ipr_std']:.1f})  Total={res['total_mean']:.1f}")

# Parameter sweep
results = []
for offset in [7, 8, 9]:
    for thresh in [50, 60, 70, 80]:
        for qty in [10, 15, 25]:
            code = set_params(original, offset, thresh, qty)
            write_trader(code)
            res = run_backtest()
            label = f"off={offset} thr={thresh} qty={qty}"
            results.append((res['ipr_mean'], label, res))
            print(f"{label:>30}  IPR={res['ipr_mean']:>7.1f} (std={res['ipr_std']:.1f})  Total={res['total_mean']:.1f}")

# Restore original
write_trader(original)

# Sort by IPR PnL
print("\n=== TOP 5 by IPR PnL ===")
results.sort(reverse=True)
for ipr_mean, label, res in results[:5]:
    print(f"  {label:>30}  IPR={ipr_mean:>7.1f}  Total={res['total_mean']:.1f}")
