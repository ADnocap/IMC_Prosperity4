// Stage 3 — per-bot volume model.
//
// For each detected layer we fit a uniform U(lo, hi) and run these tests:
//   - χ² goodness-of-fit vs uniform (marginal)
//   - Same-tick bid-vol == ask-vol rate (binomial vs null) — catches the
//     "sides tied by one random draw" structural feature observed on OSMIUM/PEPPER.
//   - vol | offset χ² per distinct offset (catches hidden sub-layers — the
//     ANALYSIS_PHILOSOPHY.md cardinal rule made automatic).
//
// The panel renders each test with a clear pass/fail verdict and its p-value.

import { FvAndBook } from '../types';
import { DetectedLayer, Quote } from './layer_detection';
import { Chi2Out, ensureWasmReady, wasm } from '../wasm';

export interface VolumeSideModel {
  // Observed range
  min: number;
  max: number;
  mean: number;
  n: number;
  // χ² fit to U(lo, hi) where lo = observed min, hi = observed max
  uniform: Chi2Out;
  // Per-offset volume conditional (offset → {count, chi2_p of uniform on that row})
  byOffset: Array<{ offset: number; n: number; mean: number; p_uniform: number }>;
}

export interface VolumeLayerModel {
  layer_id: string;
  layer_name: string;
  bid: VolumeSideModel;
  ask: VolumeSideModel;
  /// Fraction of ticks where the bot is active on BOTH sides AND volumes match.
  /// Under "one random draw per tick" this approaches 1.0.
  sides_tied_rate: number;
  sides_tied_n: number;
  sides_tied_p: number;   // binomial p vs null (independent U(lo,hi) draws)
}

export interface Stage3Result {
  layers: VolumeLayerModel[];
}

function quotesByTick(quotes: Quote[]): Map<number, Quote[]> {
  const m = new Map<number, Quote[]>();
  for (const q of quotes) {
    const arr = m.get(q.ts);
    if (arr) arr.push(q);
    else m.set(q.ts, [q]);
  }
  return m;
}

function sideQuotes(quotes: Quote[], layer: DetectedLayer, side: 'bid' | 'ask'): Quote[] {
  const band = side === 'bid' ? layer.offset_band.bid : layer.offset_band.ask;
  return quotes.filter(q => q.side === side && q.offset >= band[0] && q.offset <= band[1]);
}

function fitSideUniform(qs: Quote[]): VolumeSideModel {
  const vols = qs.map(q => q.volume).filter(v => Number.isFinite(v));
  if (vols.length === 0) {
    return {
      min: 0, max: 0, mean: 0, n: 0,
      uniform: { chi2: 0, df: 0, p_value: 1, n: 0, observed: [], expected: [] },
      byOffset: [],
    };
  }
  const lo = Math.min(...vols);
  const hi = Math.max(...vols);
  const arr = new Float64Array(vols);
  const uni = wasm.chi2Uniform(arr, lo, hi) as Chi2Out;

  // vol | offset conditional
  const byRound = new Map<number, number[]>();
  for (const q of qs) {
    const key = Math.round(q.offset);   // bucket to integer offsets
    const bucket = byRound.get(key);
    if (bucket) bucket.push(q.volume);
    else byRound.set(key, [q.volume]);
  }
  const byOffset: VolumeSideModel['byOffset'] = [];
  for (const [off, vs] of [...byRound.entries()].sort((a, b) => a[0] - b[0])) {
    let p = NaN;
    if (vs.length >= 20 && lo < hi) {
      const res = wasm.chi2Uniform(new Float64Array(vs), lo, hi) as Chi2Out;
      p = res.p_value;
    }
    const mean = vs.reduce((a, b) => a + b, 0) / vs.length;
    byOffset.push({ offset: off, n: vs.length, mean, p_uniform: p });
  }

  return {
    min: lo, max: hi, n: vols.length,
    mean: vols.reduce((a, b) => a + b, 0) / vols.length,
    uniform: uni, byOffset,
  };
}

export async function runStage3(data: FvAndBook, layers: DetectedLayer[]): Promise<Stage3Result> {
  await ensureWasmReady();
  // Extract all quotes from the fv_and_book rows (same extraction as Stage 1 —
  // duplicated here so Stage 3 can be re-run independently).
  const quotes: Quote[] = [];
  for (const r of data.rows) {
    if (r.fv === null) continue;
    for (const bp of r.bids) {
      const v = r.bid_vols[String(bp)] ?? r.bid_vols[bp as unknown as string] ?? 0;
      quotes.push({ side: 'bid', price: bp, volume: v, fv: r.fv, offset: bp - r.fv, ts: r.ts });
    }
    for (const ap of r.asks) {
      const v = r.ask_vols[String(ap)] ?? r.ask_vols[ap as unknown as string] ?? 0;
      quotes.push({ side: 'ask', price: ap, volume: v, fv: r.fv, offset: ap - r.fv, ts: r.ts });
    }
  }
  const tickMap = quotesByTick(quotes);

  const out: VolumeLayerModel[] = [];
  for (const L of layers) {
    const bidQ = sideQuotes(quotes, L, 'bid');
    const askQ = sideQuotes(quotes, L, 'ask');
    const bid = fitSideUniform(bidQ);
    const ask = fitSideUniform(askQ);

    // side-tie analysis: pick per tick the Bot's bid & ask and check vol match
    let bothN = 0;
    let sameN = 0;
    for (const [, arr] of tickMap) {
      const bSide = arr.find(q => q.side === 'bid' && q.offset >= L.offset_band.bid[0] && q.offset <= L.offset_band.bid[1]);
      const aSide = arr.find(q => q.side === 'ask' && q.offset >= L.offset_band.ask[0] && q.offset <= L.offset_band.ask[1]);
      if (bSide && aSide) {
        bothN += 1;
        if (bSide.volume === aSide.volume) sameN += 1;
      }
    }
    const rate = bothN > 0 ? sameN / bothN : 0;
    // Null: independent draws from U(lo, hi); P(vol_a == vol_b) = 1/(hi-lo+1)
    const lo = Math.min(bid.min, ask.min);
    const hi = Math.max(bid.max, ask.max);
    const pNull = hi >= lo ? 1 / (hi - lo + 1) : 1 / 10;
    // Binomial z-test vs p0 = pNull
    const se = bothN > 0 ? Math.sqrt(pNull * (1 - pNull) / bothN) : 1;
    const z = se > 0 ? (rate - pNull) / se : 0;
    const p = 2 * (1 - normalCdf(Math.abs(z)));

    out.push({
      layer_id: L.id, layer_name: L.name,
      bid, ask,
      sides_tied_rate: rate, sides_tied_n: bothN, sides_tied_p: p,
    });
  }
  return { layers: out };
}

// Local normal CDF (single-file; rest of the file uses WASM stats where possible).
function normalCdf(z: number): number {
  const sign = z < 0 ? -1 : 1;
  const x = Math.abs(z);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return 0.5 * (1 + sign * y);
}
