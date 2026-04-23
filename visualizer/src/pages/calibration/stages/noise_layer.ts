// Stage 5 — noise-layer model.
//
// Consumes the `noise_quotes` from Stage 1 (quotes that didn't fall into any
// main cluster). Summarises:
//   - Presence rate + single-sided fraction
//   - Offset distribution (counts at integer offsets from round(FV))
//   - Crossing (price inside FV) vs passive split
//   - Volume conditional on crossing — χ² uniform fit per side
//   - Run-length distribution (how bursty noise activity is)

import { FvAndBook } from '../types';
import { ensureWasmReady, Chi2Out, RunLenOut, wasm } from '../wasm';
import { Quote, Stage1Result } from './layer_detection';

export interface NoiseStats {
  n_events: number;
  presence_rate: number;          // P(≥1 noise quote on a tick)
  single_sided_rate: number;      // of events, fraction that are single-sided
  offset_hist: Array<{ offset: number; count: number }>;
  crossing_frac: number;
  crossing_n: number;
  passive_n: number;
  crossing_vol: Chi2Out | null;   // χ² vs U(observed min,max) — null if n < 10
  passive_vol: Chi2Out | null;
  crossing_vol_mean: number;
  passive_vol_mean: number;
  run_length: RunLenOut;
}

export interface Stage5Result {
  stats: NoiseStats;
  quotes: Quote[];
}

function presenceSeries(data: FvAndBook, noiseTimes: Set<number>): Float64Array {
  const arr = new Float64Array(data.rows.length);
  for (let i = 0; i < data.rows.length; i++) arr[i] = noiseTimes.has(data.rows[i].ts) ? 1 : 0;
  return arr;
}

export async function runStage5(data: FvAndBook, stage1: Stage1Result): Promise<Stage5Result> {
  await ensureWasmReady();
  const quotes = stage1.noise_quotes;
  const nData = data.rows.filter(r => r.fv !== null).length;

  // Group noise quotes by tick to compute single-sided %
  const byTick = new Map<number, Quote[]>();
  for (const q of quotes) {
    const arr = byTick.get(q.ts); if (arr) arr.push(q); else byTick.set(q.ts, [q]);
  }
  const n_events = byTick.size;
  let singleSided = 0;
  for (const [, arr] of byTick) {
    const hasBid = arr.some(q => q.side === 'bid');
    const hasAsk = arr.some(q => q.side === 'ask');
    if (hasBid !== hasAsk) singleSided += 1;
  }
  const single_sided_rate = n_events > 0 ? singleSided / n_events : 0;

  // Offset histogram — offset from round(FV), integer buckets
  const offCount = new Map<number, number>();
  for (const q of quotes) {
    const key = Math.round(q.price - Math.round(q.fv));
    offCount.set(key, (offCount.get(key) ?? 0) + 1);
  }
  const offset_hist = [...offCount.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([offset, count]) => ({ offset, count }));

  // Crossing vs passive
  const crossing: number[] = [];
  const passive: number[] = [];
  for (const q of quotes) {
    const isCrossing = (q.side === 'bid' && q.price > q.fv) || (q.side === 'ask' && q.price < q.fv);
    (isCrossing ? crossing : passive).push(q.volume);
  }
  const cvStats = (vs: number[]): Chi2Out | null => {
    if (vs.length < 10) return null;
    const lo = Math.min(...vs), hi = Math.max(...vs);
    if (hi === lo) return null;
    return wasm.chi2Uniform(new Float64Array(vs), lo, hi) as Chi2Out;
  };
  const crossing_vol = cvStats(crossing);
  const passive_vol  = cvStats(passive);
  const mean = (vs: number[]) => vs.length > 0 ? vs.reduce((a, b) => a + b, 0) / vs.length : 0;

  // Run-length on presence indicator
  const runLen = wasm.runLengthGeom(presenceSeries(data, new Set(byTick.keys()))) as RunLenOut;

  return {
    stats: {
      n_events,
      presence_rate: nData > 0 ? n_events / nData : 0,
      single_sided_rate,
      offset_hist,
      crossing_frac: quotes.length > 0 ? crossing.length / quotes.length : 0,
      crossing_n: crossing.length,
      passive_n: passive.length,
      crossing_vol,
      passive_vol,
      crossing_vol_mean: mean(crossing),
      passive_vol_mean: mean(passive),
      run_length: runLen,
    },
    quotes,
  };
}
