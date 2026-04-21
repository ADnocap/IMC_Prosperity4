/**
 * Pure compute kernels. No DOM, no React. Callable from the main thread OR the
 * Web Worker -- same module, same behavior. Each kernel runs in a single pass
 * over the column arrays, allocating plot-ready arrays only.
 */

import {
  DepthInput,
  DepthOutput,
  DepthOutputLevel,
  MidInput,
  MidOutput,
  OfiInput,
  OfiOutput,
  OfiOutputProduct,
  QueueImbalanceInput,
  QueueImbalanceOutput,
  QueueImbalanceOutputProduct,
  SpreadInput,
  SpreadOutput,
  SpreadOutputProduct,
} from './types.ts';

function inSet(allowed: string[] | null, product: string): boolean {
  return allowed === null ? true : allowed.includes(product);
}

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  let s = 0;
  for (const v of values) s += v;
  return s / values.length;
}

function stdev(values: number[], mu: number): number {
  if (values.length < 2) return 0;
  let ss = 0;
  for (const v of values) {
    const d = v - mu;
    ss += d * d;
  }
  return Math.sqrt(ss / (values.length - 1));
}

function quantileSorted(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
  return sorted[idx];
}

function sampleCorrelation(xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n < 2) return 0;
  let sx = 0;
  let sy = 0;
  for (let i = 0; i < n; i += 1) { sx += xs[i]; sy += ys[i]; }
  const mx = sx / n;
  const my = sy / n;
  let num = 0;
  let dx2 = 0;
  let dy2 = 0;
  for (let i = 0; i < n; i += 1) {
    const ax = xs[i] - mx;
    const ay = ys[i] - my;
    num += ax * ay;
    dx2 += ax * ax;
    dy2 += ay * ay;
  }
  const denom = Math.sqrt(dx2 * dy2);
  return denom === 0 ? 0 : num / denom;
}

function olsFit(xs: number[], ys: number[]): { slope: number; intercept: number } {
  const n = xs.length;
  if (n < 2) return { slope: 0, intercept: 0 };
  let sx = 0;
  let sy = 0;
  for (let i = 0; i < n; i += 1) { sx += xs[i]; sy += ys[i]; }
  const mx = sx / n;
  const my = sy / n;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i += 1) {
    const ax = xs[i] - mx;
    num += ax * (ys[i] - my);
    den += ax * ax;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = my - slope * mx;
  return { slope, intercept };
}

function decimate<T>(arr: T[], cap: number): T[] {
  if (arr.length <= cap) return arr;
  const step = Math.ceil(arr.length / cap);
  const out: T[] = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[i]);
  return out;
}

// ── Mid / microprice ────────────────────────────────────────────────

export function computeMid(input: MidInput): MidOutput {
  const { productsAllowed, products, times, mids, bid1, ask1, bidVol1, askVol1 } = input;
  const hasMicro = bid1 !== null && ask1 !== null && bidVol1 !== null && askVol1 !== null;
  const byProduct = new Map<string, { midPoints: [number, number][]; microPoints: [number, number][] }>();
  for (let i = 0; i < products.length; i += 1) {
    const product = products[i];
    if (!inSet(productsAllowed, product)) continue;
    let slot = byProduct.get(product);
    if (slot === undefined) {
      slot = { midPoints: [], microPoints: [] };
      byProduct.set(product, slot);
    }
    const t = times[i];
    const m = mids[i];
    if (Number.isFinite(t) && Number.isFinite(m)) slot.midPoints.push([t, m]);
    if (hasMicro && Number.isFinite(t)) {
      const bp = bid1![i]; const ap = ask1![i];
      const bv = bidVol1![i]; const av = askVol1![i];
      const denom = bv + av;
      if (Number.isFinite(bp) && Number.isFinite(ap) && Number.isFinite(denom) && denom > 0) {
        slot.microPoints.push([t, (bp * av + ap * bv) / denom]);
      }
    }
  }
  return [...byProduct.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([product, slot]) => ({ product, ...slot }));
}

// ── Spread ──────────────────────────────────────────────────────────

export function computeSpread(input: SpreadInput): SpreadOutput {
  const { productsAllowed, products, times, bid1, ask1 } = input;
  const byProduct = new Map<string, { values: number[]; series: [number, number][] }>();
  for (let i = 0; i < products.length; i += 1) {
    const product = products[i];
    if (!inSet(productsAllowed, product)) continue;
    const bp = bid1[i]; const ap = ask1[i]; const t = times[i];
    if (!Number.isFinite(bp) || !Number.isFinite(ap) || !Number.isFinite(t)) continue;
    const spread = ap - bp;
    if (!Number.isFinite(spread)) continue;
    let slot = byProduct.get(product);
    if (slot === undefined) {
      slot = { values: [], series: [] };
      byProduct.set(product, slot);
    }
    slot.values.push(spread);
    slot.series.push([t, spread]);
  }

  const out: SpreadOutputProduct[] = [];
  for (const [product, { values, series }] of [...byProduct.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    if (values.length === 0) continue;
    const mu = mean(values);
    const sd = stdev(values, mu);
    const sorted = [...values].sort((a, b) => a - b);
    const bins = Math.min(30, Math.max(10, Math.floor(Math.sqrt(values.length))));
    const lo = sorted[0];
    const hi = sorted[sorted.length - 1];
    const width = lo === hi ? 1 : (hi - lo) / bins;
    const centers = new Array<number>(bins).fill(0);
    const counts = new Array<number>(bins).fill(0);
    for (let i = 0; i < bins; i += 1) centers[i] = lo + width * (i + 0.5);
    for (const v of values) {
      let idx = Math.floor((v - lo) / width);
      if (idx < 0) idx = 0;
      if (idx >= bins) idx = bins - 1;
      counts[idx] += 1;
    }
    out.push({
      product,
      n: values.length,
      mean: mu,
      std: sd,
      p05: quantileSorted(sorted, 0.05),
      p50: quantileSorted(sorted, 0.5),
      p95: quantileSorted(sorted, 0.95),
      timeSeries: decimate(series, 5000),
      histogram: { centers, counts },
    });
  }
  return out;
}

// ── Depth (per product) ─────────────────────────────────────────────

export function computeDepth(input: DepthInput): DepthOutput {
  const { productFilter, products, times, ladder } = input;
  const levels: DepthOutputLevel[] = ladder.map((_, i) => ({
    level: i + 1,
    bidPoints: [],
    askPoints: [],
  }));
  for (let i = 0; i < products.length; i += 1) {
    if (products[i] !== productFilter) continue;
    const t = times[i];
    if (!Number.isFinite(t)) continue;
    for (let l = 0; l < ladder.length; l += 1) {
      const slice = ladder[l];
      if (slice.bidVolume !== null) {
        const bv = slice.bidVolume[i];
        if (Number.isFinite(bv)) levels[l].bidPoints.push([t, -bv]);
      }
      if (slice.askVolume !== null) {
        const av = slice.askVolume[i];
        if (Number.isFinite(av)) levels[l].askPoints.push([t, av]);
      }
    }
  }
  return levels;
}

// ── Queue imbalance ─────────────────────────────────────────────────

export function computeQueueImbalance(input: QueueImbalanceInput): QueueImbalanceOutput {
  const { productsAllowed, products, times, mids, bidVol1, askVol1, horizon, maxScatter, bins } = input;
  // Group by product with chronological order preserved (assumes input rows already
  // ordered by cumulative time, which `concatTables` guarantees).
  const byProduct = new Map<string, { I: number[]; mid: number[] }>();
  for (let i = 0; i < products.length; i += 1) {
    const product = products[i];
    if (!inSet(productsAllowed, product)) continue;
    const bv = bidVol1[i]; const av = askVol1[i]; const m = mids[i]; const t = times[i];
    if (!Number.isFinite(bv) || !Number.isFinite(av) || !Number.isFinite(m) || !Number.isFinite(t)) continue;
    const denom = bv + av;
    if (denom <= 0) continue;
    let slot = byProduct.get(product);
    if (slot === undefined) {
      slot = { I: [], mid: [] };
      byProduct.set(product, slot);
    }
    slot.I.push((bv - av) / denom);
    slot.mid.push(m);
  }

  const out: QueueImbalanceOutputProduct[] = [];
  for (const [product, { I, mid }] of [...byProduct.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const xs: number[] = [];
    const ys: number[] = [];
    const limit = mid.length - horizon;
    for (let i = 0; i < limit; i += 1) {
      xs.push(I[i]);
      ys.push(mid[i + horizon] - mid[i]);
    }
    if (xs.length < 10) continue;

    const buckets: number[][] = Array.from({ length: bins }, () => []);
    for (let i = 0; i < xs.length; i += 1) {
      let idx = Math.floor(((xs[i] + 1) / 2) * bins);
      if (idx < 0) idx = 0;
      if (idx >= bins) idx = bins - 1;
      buckets[idx].push(ys[i]);
    }
    const binned: [number, number][] = [];
    for (let b = 0; b < bins; b += 1) {
      if (buckets[b].length === 0) continue;
      const center = -1 + (2 * (b + 0.5)) / bins;
      binned.push([center, mean(buckets[b])]);
    }

    const step = xs.length > maxScatter ? Math.ceil(xs.length / maxScatter) : 1;
    const scatter: [number, number][] = [];
    for (let i = 0; i < xs.length; i += step) scatter.push([xs[i], ys[i]]);

    out.push({
      product,
      scatter,
      binned,
      correlation: sampleCorrelation(xs, ys),
      n: xs.length,
    });
  }
  return out;
}

// ── OFI (Cont-Kukanov) ──────────────────────────────────────────────

export function computeOfi(input: OfiInput): OfiOutput {
  const { productsAllowed, products, times, mids, bid1, bidVol1, ask1, askVol1, maxScatter } = input;
  const byProduct = new Map<string, {
    bp: number[]; bv: number[]; ap: number[]; av: number[]; mid: number[];
  }>();
  for (let i = 0; i < products.length; i += 1) {
    const product = products[i];
    if (!inSet(productsAllowed, product)) continue;
    const bp = bid1[i]; const bv = bidVol1[i]; const ap = ask1[i]; const av = askVol1[i]; const m = mids[i]; const t = times[i];
    if (!Number.isFinite(bp) || !Number.isFinite(bv) || !Number.isFinite(ap) || !Number.isFinite(av) || !Number.isFinite(m) || !Number.isFinite(t)) continue;
    let slot = byProduct.get(product);
    if (slot === undefined) {
      slot = { bp: [], bv: [], ap: [], av: [], mid: [] };
      byProduct.set(product, slot);
    }
    slot.bp.push(bp); slot.bv.push(bv); slot.ap.push(ap); slot.av.push(av); slot.mid.push(m);
  }

  const out: OfiOutputProduct[] = [];
  for (const [product, s] of [...byProduct.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const xs: number[] = [];
    const ys: number[] = [];
    for (let i = 1; i < s.mid.length; i += 1) {
      let eB: number;
      if (s.bp[i] > s.bp[i - 1]) eB = s.bv[i];
      else if (s.bp[i] < s.bp[i - 1]) eB = -s.bv[i - 1];
      else eB = s.bv[i] - s.bv[i - 1];
      let eA: number;
      if (s.ap[i] < s.ap[i - 1]) eA = -s.av[i];
      else if (s.ap[i] > s.ap[i - 1]) eA = s.av[i - 1];
      else eA = s.av[i] - s.av[i - 1];
      const ofi = eB + eA;
      const nextMid = i + 1 < s.mid.length ? s.mid[i + 1] : s.mid[i];
      xs.push(ofi);
      ys.push(nextMid - s.mid[i]);
    }
    if (xs.length < 10) continue;
    const { slope, intercept } = olsFit(xs, ys);
    const step = xs.length > maxScatter ? Math.ceil(xs.length / maxScatter) : 1;
    const scatter: [number, number][] = [];
    let xMin = Infinity;
    let xMax = -Infinity;
    for (let i = 0; i < xs.length; i += step) {
      scatter.push([xs[i], ys[i]]);
    }
    for (let i = 0; i < xs.length; i += 1) {
      if (xs[i] < xMin) xMin = xs[i];
      if (xs[i] > xMax) xMax = xs[i];
    }
    out.push({
      product,
      scatter,
      correlation: sampleCorrelation(xs, ys),
      slope,
      intercept,
      n: xs.length,
      xMin: Number.isFinite(xMin) ? xMin : 0,
      xMax: Number.isFinite(xMax) ? xMax : 0,
    });
  }
  return out;
}
