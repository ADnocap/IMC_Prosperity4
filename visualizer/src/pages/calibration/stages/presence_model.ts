// Stage 4 — per-bot presence model.
//
// For each (bot, side) we build a binary per-tick indicator series (1 if the
// bot posted a quote on that side at that tick, else 0) and run:
//   - Wilson 95% CI on presence rate (optional z-test vs 0.80 baseline)
//   - Ljung-Box Q on the indicator (iid ⇒ fail to reject)
//   - Runs test (same)
//   - Geometric run-length KS on off-run lengths (iid Bernoulli ⇒ Geometric(1-p))
//   - Per-bot bid ∥ ask χ² 2×2 (same-layer sides independent?)
//   - Cross-bot pairwise χ² 2×2 (Bot1 ⊥ Bot2?)

import { FvAndBook } from '../types';
import { DetectedLayer } from './layer_detection';
import {
  ensureWasmReady, Indep2x2Out, LjungOut, RunLenOut, RunsOut, WilsonOut, wasm,
} from '../wasm';

export interface PresenceSide {
  rate: number;
  ci: WilsonOut;
  ljung: LjungOut;
  runs: RunsOut;
  runLength: RunLenOut;
  n_ticks: number;
  n_present: number;
}

export interface LayerPresence {
  layer_id: string;
  layer_name: string;
  bid: PresenceSide;
  ask: PresenceSide;
  // Per-bot bid ∥ ask 2×2 χ²
  bid_ask_indep: Indep2x2Out;
}

export interface CrossBotRow {
  a_id: string;
  b_id: string;
  side_a: 'bid' | 'ask';
  side_b: 'bid' | 'ask';
  indep: Indep2x2Out;
}

export interface Stage4Result {
  layers: LayerPresence[];
  cross_bot: CrossBotRow[];
}

function buildIndicatorSeries(
  data: FvAndBook,
  layer: DetectedLayer,
  side: 'bid' | 'ask',
): Float64Array {
  const band = side === 'bid' ? layer.offset_band.bid : layer.offset_band.ask;
  const arr = new Float64Array(data.rows.length);
  for (let i = 0; i < data.rows.length; i++) {
    const r = data.rows[i];
    if (r.fv === null) { arr[i] = 0; continue; }
    const prices = side === 'bid' ? r.bids : r.asks;
    let present = 0;
    for (const p of prices) {
      const off = p - r.fv;
      if (off >= band[0] && off <= band[1]) { present = 1; break; }
    }
    arr[i] = present;
  }
  return arr;
}

function summarizeSide(indicator: Float64Array): PresenceSide {
  const n = indicator.length;
  let k = 0; for (let i = 0; i < n; i++) k += indicator[i];
  const rate = n > 0 ? k / n : 0;
  const ci = wasm.wilson(k, n, 0.80, 0.05) as WilsonOut;
  const lj = wasm.ljungBox(indicator, 10) as LjungOut;
  const runs = wasm.runsTest(indicator) as RunsOut;
  const rl = wasm.runLengthGeom(indicator) as RunLenOut;
  return { rate, ci, ljung: lj, runs, runLength: rl, n_ticks: n, n_present: k };
}

function indepFromIndicators(a: Float64Array, b: Float64Array): Indep2x2Out {
  let both = 0, aOnly = 0, bOnly = 0, neither = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const ax = a[i] > 0.5, bx = b[i] > 0.5;
    if (ax && bx) both++;
    else if (ax) aOnly++;
    else if (bx) bOnly++;
    else neither++;
  }
  return wasm.indep2x2(both, aOnly, bOnly, neither) as Indep2x2Out;
}

export async function runStage4(data: FvAndBook, layers: DetectedLayer[]): Promise<Stage4Result> {
  await ensureWasmReady();
  const bidIndicators = new Map<string, Float64Array>();
  const askIndicators = new Map<string, Float64Array>();
  const out: LayerPresence[] = [];
  for (const L of layers) {
    const bid = buildIndicatorSeries(data, L, 'bid');
    const ask = buildIndicatorSeries(data, L, 'ask');
    bidIndicators.set(L.id, bid);
    askIndicators.set(L.id, ask);
    out.push({
      layer_id: L.id, layer_name: L.name,
      bid: summarizeSide(bid),
      ask: summarizeSide(ask),
      bid_ask_indep: indepFromIndicators(bid, ask),
    });
  }
  const cross: CrossBotRow[] = [];
  const ids = layers.map(L => L.id);
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = ids[i], b = ids[j];
      for (const sideA of ['bid', 'ask'] as const) {
        for (const sideB of ['bid', 'ask'] as const) {
          const arrA = (sideA === 'bid' ? bidIndicators : askIndicators).get(a)!;
          const arrB = (sideB === 'bid' ? bidIndicators : askIndicators).get(b)!;
          cross.push({ a_id: a, b_id: b, side_a: sideA, side_b: sideB, indep: indepFromIndicators(arrA, arrB) });
        }
      }
    }
  }
  return { layers: out, cross_bot: cross };
}
