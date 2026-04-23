// Stage 2 — formula discovery per (bot, side).
//
// Consumes Stage 1's detected layers + the raw quotes, runs the WASM
// formula-search kernel (brute force over fixed and proportional families
// with 2-fold CV), and returns a winning formula per bot side.
//
// Key output fields:
//   - top-N candidates with CV match rate + Wilson CI + FV-decile match
//   - residual histogram (spikes at ±1 reveal rounding-mode bugs)
//   - FV-decile match heatmap (flat row = good, sloped row = wrong offset type)
//
// The "PEPPER discriminator": on a wide-FV-range dataset, the winning fixed
// formula's FV-decile match rate decays with FV range. If we see that and a
// proportional candidate has a flat row, the Stage picks proportional.

import { BotSpec, FormulaSpecSide } from '../types';
import { DetectedLayer, Quote } from './layer_detection';
import { ensureWasmReady, FixedCandidate, FormulaSearchOut, PropCandidate, wasm } from '../wasm';

export interface BotFormulaResult {
  layer_id: string;
  layer_name: string;
  bid: FormulaSearchOut;
  ask: FormulaSearchOut;
  winner_bid: FixedCandidate | PropCandidate;
  winner_ask: FixedCandidate | PropCandidate;
  winner_bid_family: 'fixed' | 'proportional';
  winner_ask_family: 'fixed' | 'proportional';
}

export interface Stage2Result {
  bots: BotFormulaResult[];
}

function quotesForLayer(quotes: Quote[], layer: DetectedLayer, side: 'bid' | 'ask'): Quote[] {
  const band = side === 'bid' ? layer.offset_band.bid : layer.offset_band.ask;
  return quotes.filter(q => q.side === side && q.offset >= band[0] && q.offset <= band[1]);
}

async function searchSide(qs: Quote[], sideSign: -1 | 1, kGuess: number, useWide: boolean): Promise<FormulaSearchOut> {
  const fv = new Float64Array(qs.map(q => q.fv));
  const price = new Float64Array(qs.map(q => q.price));
  // Constant search range: enough to cover OSMIUM ±10 and PEPPER ±(K·FV) at narrow
  // range; we tune it to the sign of the side.
  const constLo = sideSign < 0 ? -15 : 1;
  const constHi = sideSign < 0 ? -1 : 15;
  // Proportional K grid: fine around the kGuess from Stage 1 if we have one, else
  // a wide default that spans both OSMIUM-scale (~1e-3) and PEPPER-scale (~7e-4).
  let kMin = 0, kMax = 2e-3, kSteps = 200;
  if (kGuess > 0 && !useWide) {
    const spread = Math.max(kGuess * 0.25, 1e-4);
    kMin = Math.max(0, kGuess - spread);
    kMax = kGuess + spread;
    kSteps = 400;
  }
  const res = wasm.formulaSearch(fv, price, sideSign, constLo, constHi, kMin, kMax, kSteps, 5) as FormulaSearchOut;
  return res;
}

function pickWinner(result: FormulaSearchOut): { cand: FixedCandidate | PropCandidate; family: 'fixed' | 'proportional' } {
  const fixedBest = result.fixed_top[0];
  const propBest = result.proportional_top[0];
  const spread = (arr: number[]) => {
    if (!arr || arr.length === 0) return 1;
    const m = Math.max(...arr);
    const mn = Math.min(...arr);
    return m - mn;
  };
  if (!fixedBest && !propBest) throw new Error('formula search returned no candidates');
  if (!fixedBest) return { cand: propBest, family: 'proportional' };
  if (!propBest)  return { cand: fixedBest, family: 'fixed' };
  // Follow the same rule as in the kernel — prefer proportional only when it
  // genuinely beats fixed by > 0.5% CV AND has flatter FV-decile match.
  const fixedSpread = spread(fixedBest.fv_decile_match);
  const propSpread  = spread(propBest.fv_decile_match);
  const preferProp = propBest.cv_match_rate > fixedBest.cv_match_rate + 0.005
    && propSpread < fixedSpread;
  return preferProp
    ? { cand: propBest, family: 'proportional' }
    : { cand: fixedBest, family: 'fixed' };
}

export async function runStage2(layers: DetectedLayer[], quotes: Quote[]): Promise<Stage2Result> {
  await ensureWasmReady();
  const out: BotFormulaResult[] = [];
  for (const L of layers) {
    const bidQs = quotesForLayer(quotes, L, 'bid');
    const askQs = quotesForLayer(quotes, L, 'ask');
    if (bidQs.length < 20 || askQs.length < 20) continue;
    const kGuess = L.offset_type === 'proportional' ? L.k_estimate : 0;
    const [bidRes, askRes] = await Promise.all([
      searchSide(bidQs, -1, kGuess, L.offset_type === 'fixed'),
      searchSide(askQs, 1, kGuess, L.offset_type === 'fixed'),
    ]);
    const wBid = pickWinner(bidRes);
    const wAsk = pickWinner(askRes);
    out.push({
      layer_id: L.id, layer_name: L.name,
      bid: bidRes, ask: askRes,
      winner_bid: wBid.cand, winner_ask: wAsk.cand,
      winner_bid_family: wBid.family, winner_ask_family: wAsk.family,
    });
  }
  return { bots: out };
}

/// Convert a Stage 2 winner into the params.json `formula_spec` shape.
export function winnerToFormulaSpec(cand: FixedCandidate | PropCandidate, family: 'fixed' | 'proportional'): FormulaSpecSide {
  if (family === 'fixed') {
    const c = cand as FixedCandidate;
    return { round_fn: c.round_fn as FormulaSpecSide['round_fn'], shift: c.shift, constant: c.constant, K: null };
  }
  const p = cand as PropCandidate;
  return { round_fn: p.round_fn as FormulaSpecSide['round_fn'], shift: 0, constant: 0, K: p.k };
}

/// Render a formula into a human-readable string.
export function formulaString(spec: FormulaSpecSide, side: 'bid' | 'ask'): string {
  if (spec.K === null) {
    const shift = spec.shift === 0 ? 'fv' : `fv ${spec.shift >= 0 ? '+' : '-'} ${Math.abs(spec.shift)}`;
    const c = spec.constant === 0 ? '' : ` ${spec.constant >= 0 ? '+' : '-'} ${Math.abs(spec.constant)}`;
    return `${spec.round_fn}(${shift})${c}`;
  }
  const sign = side === 'bid' ? '-' : '+';
  return `${spec.round_fn}(fv * (1 ${sign} ${spec.K.toExponential(4)}))`;
}

/// Suggest the BotSpec[] entry for a Stage 8 export.
export function layersToBotSpecs(
  layers: DetectedLayer[],
  stage2: Stage2Result,
): BotSpec[] {
  return stage2.bots.map(b => {
    const L = layers.find(l => l.id === b.layer_id)!;
    const bidSpec = winnerToFormulaSpec(b.winner_bid, b.winner_bid_family);
    const askSpec = winnerToFormulaSpec(b.winner_ask, b.winner_ask_family);
    const offsetType = b.winner_bid_family === 'proportional' || b.winner_ask_family === 'proportional'
      ? 'proportional' : 'fixed';
    return {
      id: b.layer_id,
      name: L.name,
      offset_type: offsetType,
      bid_formula_str: formulaString(bidSpec, 'bid'),
      ask_formula_str: formulaString(askSpec, 'ask'),
      formula_spec: { bid: bidSpec, ask: askSpec },
      volume: { distribution: 'uniform', low: 0, high: 0, sides_tied: true },  // Stage 3 fills
      presence: { rate: 0.8, iid: true, bid_ask_independent: true },             // Stage 4 fills
      offset_band: L.offset_band,
    };
  });
}
