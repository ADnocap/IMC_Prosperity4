// Stage 6 — trade bot model.
//
// Reads trade records from the extended fv_and_book.json (merged via
// `extract_fv_and_book.py --trades-csv`). Fits:
//   - Poisson on per-tick trade counts with χ² GoF against observed histogram
//   - Quantity distribution: χ² vs U(min,max); empirical PMF also reported
//   - Counterparty distribution (if CSV has named buyer/seller; otherwise empty)
//
// The trade bot's per-tick rate is low (~0.04 for OSMIUM, ~0.03 for PEPPER) so
// Poisson with a single λ is a decent first-order model. Asymmetric or bursty
// tape would flag via the χ² GoF.

import { Chi2Out, ensureWasmReady, wasm } from '../wasm';
import { FvAndBook } from '../types';

export interface TradeStats {
  n_trades: number;
  n_ticks: number;
  rate_per_tick: number;        // λ̂ = n_trades / n_ticks
  /// Observed count distribution at 0, 1, 2, ... trades per tick.
  count_hist: Array<{ k: number; observed: number; expected_poisson: number }>;
  /// χ² GoF against Poisson(λ̂) on the count histogram (binned).
  poisson_gof: Chi2Out | null;
  /// Empirical quantity histogram (value → count).
  qty_hist: Array<{ qty: number; count: number }>;
  qty_min: number;
  qty_max: number;
  qty_mean: number;
  qty_uniform_gof: Chi2Out | null;
  /// Per-counterparty tallies when the CSV has named buyers/sellers.
  counterparties: Array<{ name: string; buys: number; sells: number; mean_qty: number }>;
}

export interface Stage6Result {
  available: boolean;
  reason: string | null;
  stats: TradeStats | null;
}

function poissonPmf(k: number, lambda: number): number {
  if (lambda < 0) return 0;
  if (lambda === 0) return k === 0 ? 1 : 0;
  let logP = -lambda + k * Math.log(lambda);
  for (let i = 2; i <= k; i++) logP -= Math.log(i);
  return Math.exp(logP);
}

export async function runStage6(data: FvAndBook): Promise<Stage6Result> {
  if (!data.trades || data.trades.length === 0) {
    return { available: false, reason: 'No trades in fv_and_book.json. Re-run extractor with --trades-csv.', stats: null };
  }
  await ensureWasmReady();

  const nTicks = data.rows.filter(r => r.fv !== null).length;
  const trades = data.trades;

  // Per-tick trade count → counts histogram (bucketed at the tick resolution
  // used in the price feed, assumed 100 ticks-per-second).
  const perTick = new Map<number, number>();
  for (const t of trades) {
    const bucket = Math.floor(t.ts / 100) * 100;
    perTick.set(bucket, (perTick.get(bucket) ?? 0) + 1);
  }
  // Build count distribution histogram (k → how many ticks saw exactly k trades).
  const maxK = [...perTick.values()].reduce((a, b) => Math.max(a, b), 0);
  const dist = new Array(maxK + 1).fill(0);
  // A tick with 0 trades doesn't appear in perTick, so compute implicit zeros:
  const nonZeroTicks = perTick.size;
  dist[0] = Math.max(0, nTicks - nonZeroTicks);
  for (const c of perTick.values()) dist[c] += 1;

  const lambda = trades.length / Math.max(1, nTicks);
  const observedCounts = new Float64Array(dist);
  const expectedProbs = new Float64Array(dist.length);
  let tail = 1;
  for (let k = 0; k < dist.length - 1; k++) { expectedProbs[k] = poissonPmf(k, lambda); tail -= expectedProbs[k]; }
  expectedProbs[dist.length - 1] = Math.max(0, tail);
  const gof = wasm.chi2Gof(observedCounts, expectedProbs) as Chi2Out;

  // Quantity histogram + χ² uniform fit
  const qtys = trades.map(t => t.quantity);
  const qMin = qtys.length > 0 ? Math.min(...qtys) : 0;
  const qMax = qtys.length > 0 ? Math.max(...qtys) : 0;
  const qMean = qtys.length > 0 ? qtys.reduce((a, b) => a + b, 0) / qtys.length : 0;
  const qMap = new Map<number, number>();
  for (const q of qtys) qMap.set(q, (qMap.get(q) ?? 0) + 1);
  const qHist = [...qMap.entries()].sort((a, b) => a[0] - b[0]).map(([qty, count]) => ({ qty, count }));
  const qUniform = (qtys.length >= 30 && qMax > qMin)
    ? (wasm.chi2Uniform(new Float64Array(qtys), qMin, qMax) as Chi2Out)
    : null;

  // Counterparties (named only — tutorial data has empty strings)
  const cpMap = new Map<string, { buys: number; sells: number; qty_sum: number; qty_n: number }>();
  for (const t of trades) {
    for (const role of [['buyer', t.buyer], ['seller', t.seller]] as const) {
      const [label, name] = role;
      if (!name) continue;
      const entry = cpMap.get(name) ?? { buys: 0, sells: 0, qty_sum: 0, qty_n: 0 };
      if (label === 'buyer') entry.buys += 1;
      else entry.sells += 1;
      entry.qty_sum += t.quantity;
      entry.qty_n += 1;
      cpMap.set(name, entry);
    }
  }
  const counterparties = [...cpMap.entries()]
    .sort((a, b) => (b[1].buys + b[1].sells) - (a[1].buys + a[1].sells))
    .map(([name, v]) => ({ name, buys: v.buys, sells: v.sells, mean_qty: v.qty_n > 0 ? v.qty_sum / v.qty_n : 0 }));

  return {
    available: true,
    reason: null,
    stats: {
      n_trades: trades.length,
      n_ticks: nTicks,
      rate_per_tick: lambda,
      count_hist: dist.map((observed, k) => ({ k, observed, expected_poisson: expectedProbs[k] * nTicks })),
      poisson_gof: gof,
      qty_hist: qHist,
      qty_min: qMin, qty_max: qMax, qty_mean: qMean,
      qty_uniform_gof: qUniform,
      counterparties,
    },
  };
}
