// Stage 1 — bot-layer detection.
//
// Goal: discover how many market-maker layers exist in the book without being
// told N up front, and classify each as fixed-offset or proportional.
//
// Method:
//   1. For every visible quote (bid & ask, all levels), compute offset = price - FV.
//   2. KDE the offset distribution per side; peak-detect → candidate bot layers.
//   3. For each detected peak, collect quotes within a bandwidth window around it
//      and regress `offset ~ FV` (OLS). A significant slope (|t| > 3) means the
//      offset scales with FV → proportional. Else fixed.
//   4. For a proportional layer, K̂ = mean(offset) / mean(FV) gives the coefficient.
//
// The hard part we learned from PEPPER: fixed offsets in narrow-FV data look
// identical to proportional with small K. The slope test is the discriminator.

import { FvAndBook, OffsetType } from '../types';
import { ensureWasmReady, wasm, KdeOut, OlsOut } from '../wasm';

export interface Quote {
  side: 'bid' | 'ask';
  price: number;
  volume: number;
  fv: number;
  offset: number;   // price - fv (signed; negative on bid side by construction)
  ts: number;
}

export interface DetectedLayer {
  id: string;
  name: string;            // auto-named: "Layer 1 (outer)", "Layer 2 (inner)", etc.
  /// Canonical offset magnitude (positive) — ranks layers from outer to inner.
  offset_mag: number;
  offset_type: OffsetType;
  /// Proportional K estimate (only meaningful when offset_type === 'proportional').
  k_estimate: number;
  /// Per-side peak data (peak mode of `offset` in price units).
  bid_peak_offset: number;
  ask_peak_offset: number;
  /// Classification band used for Stage 2 (in units of price - FV).
  offset_band: { bid: [number, number]; ask: [number, number] };
  /// n of quotes that fell into this layer.
  n_bid: number;
  n_ask: number;
  /// OLS results (one per side — slope tests fixed-vs-proportional).
  bid_ols: OlsOut | null;
  ask_ols: OlsOut | null;
}

export interface Stage1Result {
  quotes: Quote[];
  bid_kde: KdeOut;
  ask_kde: KdeOut;
  layers: DetectedLayer[];
  /// Quotes that didn't fall into any layer (candidate noise).
  noise_quotes: Quote[];
}

function extractQuotes(data: FvAndBook): Quote[] {
  const out: Quote[] = [];
  for (const r of data.rows) {
    if (r.fv === null) continue;
    for (const bp of r.bids) {
      const v = r.bid_vols[String(bp)] ?? r.bid_vols[bp as unknown as string] ?? 0;
      out.push({ side: 'bid', price: bp, volume: v, fv: r.fv, offset: bp - r.fv, ts: r.ts });
    }
    for (const ap of r.asks) {
      const v = r.ask_vols[String(ap)] ?? r.ask_vols[ap as unknown as string] ?? 0;
      out.push({ side: 'ask', price: ap, volume: v, fv: r.fv, offset: ap - r.fv, ts: r.ts });
    }
  }
  return out;
}

/// Map a KDE peak index into a ±(bandwidth × multiplier) band on the offset axis.
function peakToBand(kde: KdeOut, peakIdx: number, bandwidthMultiplier = 1.5): [number, number] {
  const center = kde.grid[peakIdx];
  const halfWidth = kde.bandwidth * bandwidthMultiplier;
  return [center - halfWidth, center + halfWidth];
}

function quotesInBand(quotes: Quote[], band: [number, number]): Quote[] {
  return quotes.filter(q => q.offset >= band[0] && q.offset <= band[1]);
}

/// Pair bid peaks with ask peaks by matching offset magnitudes (outermost first).
function pairPeaks(bidPeaks: { band: [number, number]; mag: number }[], askPeaks: { band: [number, number]; mag: number }[])
  : Array<{ bid: { band: [number, number]; mag: number } | null; ask: { band: [number, number]; mag: number } | null }>
{
  const bids = bidPeaks.slice().sort((a, b) => b.mag - a.mag); // outer first
  const asks = askPeaks.slice().sort((a, b) => b.mag - a.mag);
  const paired: Array<{ bid: { band: [number, number]; mag: number } | null; ask: { band: [number, number]; mag: number } | null }> = [];
  const usedAsks = new Set<number>();
  for (const b of bids) {
    // nearest-magnitude unmatched ask
    let bestIdx = -1; let bestDiff = Infinity;
    for (let i = 0; i < asks.length; i++) {
      if (usedAsks.has(i)) continue;
      const diff = Math.abs(asks[i].mag - b.mag);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    }
    if (bestIdx >= 0) {
      paired.push({ bid: b, ask: asks[bestIdx] });
      usedAsks.add(bestIdx);
    } else {
      paired.push({ bid: b, ask: null });
    }
  }
  for (let i = 0; i < asks.length; i++) {
    if (!usedAsks.has(i)) paired.push({ bid: null, ask: asks[i] });
  }
  return paired;
}

/**
 * Classify a layer as fixed or proportional by regressing `offset ~ FV` over
 * all quotes that fell inside the peak band. Under a fixed-offset bot, slope ≈ 0;
 * under proportional with coefficient K, slope ≈ K (with sign matching the side).
 *
 * Returns OLS plus a boolean flag that's true when slope is significantly non-zero.
 */
async function classifyLayer(quotes: Quote[]): Promise<{ ols: OlsOut | null; proportional: boolean; k: number }> {
  if (quotes.length < 20) return { ols: null, proportional: false, k: 0 };
  const fvs = new Float64Array(quotes.map(q => q.fv));
  const offs = new Float64Array(quotes.map(q => q.offset));
  try {
    const ols = wasm.ols(fvs, offs) as OlsOut;
    // significance cutoff: |t| > 3 (conservative — we want to *not* call it
    // proportional just because of narrow-range noise; PEPPER had |t| > 100)
    const proportional = Math.abs(ols.t_beta) > 3 && Math.abs(ols.beta) > 1e-5;
    // K̂ such that offset ≈ K × FV (signed by side). For a proportional bot,
    // price = floor(fv * (1 ± K)) → offset = ±K × fv + (rounding wiggle).
    const k = proportional ? Math.abs(ols.beta) : 0;
    return { ols, proportional, k };
  } catch (e) {
    return { ols: null, proportional: false, k: 0 };
  }
}

export async function runStage1(data: FvAndBook, bandwidth = 0): Promise<Stage1Result> {
  await ensureWasmReady();
  const quotes = extractQuotes(data);
  const bidOffsets = new Float64Array(quotes.filter(q => q.side === 'bid').map(q => q.offset));
  const askOffsets = new Float64Array(quotes.filter(q => q.side === 'ask').map(q => q.offset));

  const bidKde = wasm.kdePeaks(bidOffsets, 400, bandwidth) as KdeOut;
  const askKde = wasm.kdePeaks(askOffsets, 400, bandwidth) as KdeOut;

  // Build peak objects with a ±1.5·bandwidth band and the magnitude for pairing.
  const bidPeakObjs = bidKde.peaks.slice(0, 6).map(idx => {
    const band = peakToBand(bidKde, idx);
    return { band, mag: Math.abs(bidKde.grid[idx]) };
  });
  const askPeakObjs = askKde.peaks.slice(0, 6).map(idx => {
    const band = peakToBand(askKde, idx);
    return { band, mag: Math.abs(askKde.grid[idx]) };
  });
  const paired = pairPeaks(bidPeakObjs, askPeakObjs);

  const bidQuotes = quotes.filter(q => q.side === 'bid');
  const askQuotes = quotes.filter(q => q.side === 'ask');

  // For each paired peak → classify each side independently (they should agree).
  const layers: DetectedLayer[] = [];
  for (let i = 0; i < paired.length; i++) {
    const { bid, ask } = paired[i];
    const bidBand = bid?.band ?? [0, 0];
    const askBand = ask?.band ?? [0, 0];
    const bidQs = bid ? quotesInBand(bidQuotes, bidBand) : [];
    const askQs = ask ? quotesInBand(askQuotes, askBand) : [];

    const [bidClass, askClass] = await Promise.all([classifyLayer(bidQs), classifyLayer(askQs)]);
    const proportional = bidClass.proportional || askClass.proportional;
    // Pool K estimate across sides when both fire proportional.
    const kPool: number[] = [];
    if (bidClass.proportional) kPool.push(bidClass.k);
    if (askClass.proportional) kPool.push(askClass.k);
    const k = kPool.length ? kPool.reduce((a, b) => a + b, 0) / kPool.length : 0;

    const mag = (bid?.mag ?? 0 + (ask?.mag ?? 0)) / ((bid ? 1 : 0) + (ask ? 1 : 0) || 1);
    layers.push({
      id: `layer${i + 1}`,
      name: `Layer ${i + 1} (${mag > 8 ? 'outer' : mag > 4 ? 'inner' : 'near-FV'})`,
      offset_mag: mag,
      offset_type: proportional ? 'proportional' : 'fixed',
      k_estimate: k,
      bid_peak_offset: bid ? bidKde.grid[bidKde.peaks[0]] : 0,
      ask_peak_offset: ask ? askKde.grid[askKde.peaks[0]] : 0,
      offset_band: { bid: bidBand, ask: askBand },
      n_bid: bidQs.length, n_ask: askQs.length,
      bid_ols: bidClass.ols, ask_ols: askClass.ols,
    });
  }
  // Order by outer-first (larger offset magnitude).
  layers.sort((a, b) => b.offset_mag - a.offset_mag);
  // Re-id after sort.
  for (let i = 0; i < layers.length; i++) layers[i].id = `layer${i + 1}`;

  // Noise = quotes not in any detected layer band.
  const noiseQuotes = quotes.filter(q => {
    return !layers.some(L => {
      const band = q.side === 'bid' ? L.offset_band.bid : L.offset_band.ask;
      return q.offset >= band[0] && q.offset <= band[1];
    });
  });

  return { quotes, bid_kde: bidKde, ask_kde: askKde, layers, noise_quotes: noiseQuotes };
}
