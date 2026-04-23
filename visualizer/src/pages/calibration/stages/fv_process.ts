// Stage 0 — FV process identification.
//
// Fit four candidate generating processes against the FV series extracted from
// a hold-1 submission (`FV = PnL + buy_price`). Pick a winner via a small
// decision hierarchy rather than across-model BIC — the likelihood targets
// differ (FV vs ΔFV) which makes BIC values non-comparable.
//
// Decision hierarchy:
//   1. If std(FV) is below the quantization grid spacing → "constant"
//   2. If OLS `FV ~ α + β t` gives a highly significant β → "linear_drift"
//   3. Else ΔFV series is the model. If AC(1) of ΔFV rejects iid → "ar1"
//                                   Otherwise                        → "random_walk"
//
// Diagnostics (same for all models): mean-step z-test (RW expects 0), Ljung-Box
// Q on residuals, skew/kurtosis z-scores, quantization detection, R² of linear
// fit, OU half-life if mean-reverting.

import { FvProcessType } from '../types';

// ── Math helpers ──────────────────────────────────────────────────

function mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  let s = 0;
  for (const x of xs) s += x;
  return s / xs.length;
}

function variance(xs: number[], mu: number): number {
  if (xs.length < 2) return 0;
  let ss = 0;
  for (const x of xs) { const d = x - mu; ss += d * d; }
  return ss / (xs.length - 1);
}

// Abramowitz-Stegun 7.1.26 — max abs err ~1.5e-7, plenty for p-values.
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const a = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * a);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
  return sign * y;
}

function normalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

function twoSidedP(z: number): number {
  return 2 * (1 - normalCdf(Math.abs(z)));
}

// Chi-squared CDF via Wilson-Hilferty (acceptable for df ≥ 3; tolerable df=1,2).
function chi2Cdf(chi2: number, df: number): number {
  if (df <= 0 || chi2 <= 0) return 0;
  const h = 2 / (9 * df);
  const z = (Math.cbrt(chi2 / df) - (1 - h)) / Math.sqrt(h);
  return normalCdf(z);
}

function chi2P(chi2: number, df: number): number {
  return 1 - chi2Cdf(chi2, df);
}

// ── Quantization detection ────────────────────────────────────────

const KNOWN_GRIDS = [
  { name: '1/1024', value: 1 / 1024 },
  { name: '1/100',  value: 1 / 100 },
  { name: '1/256',  value: 1 / 256 },
  { name: '1/500',  value: 1 / 500 },
  { name: '1/10000',value: 1 / 10000 },
];

function detectQuantization(steps: number[]): { grid: string; value: number; minAbs: number } {
  let minAbs = Infinity;
  for (const s of steps) {
    const a = Math.abs(s);
    if (a > 1e-12 && a < minAbs) minAbs = a;
  }
  if (!isFinite(minAbs)) minAbs = 0;
  let best = KNOWN_GRIDS[0];
  let bestErr = Infinity;
  for (const g of KNOWN_GRIDS) {
    const err = Math.abs(minAbs - g.value);
    if (err < bestErr) { bestErr = err; best = g; }
  }
  const tol = best.value * 0.05;
  return { grid: bestErr <= tol ? best.name : 'unknown', value: best.value, minAbs };
}

// ── Ljung-Box Q ───────────────────────────────────────────────────

function ljungBox(series: number[], maxLag: number): { q: number; df: number; p: number; ac: number[] } {
  const n = series.length;
  const mu = mean(series);
  let denom = 0;
  for (const x of series) { const d = x - mu; denom += d * d; }
  const ac: number[] = [];
  let qSum = 0;
  for (let k = 1; k <= maxLag && k < n; k++) {
    let num = 0;
    for (let i = k; i < n; i++) num += (series[i] - mu) * (series[i - k] - mu);
    const rk = denom > 0 ? num / denom : 0;
    ac.push(rk);
    qSum += (rk * rk) / (n - k);
  }
  const q = n * (n + 2) * qSum;
  const df = Math.min(maxLag, n - 1);
  return { q, df, p: chi2P(q, df), ac };
}

// ── OLS ───────────────────────────────────────────────────────────

interface OlsOut {
  alpha: number;
  beta: number;
  seBeta: number;
  tBeta: number;
  pBeta: number;
  rSquared: number;
  residualStd: number;
  residuals: number[];
}

function ols(xs: number[], ys: number[]): OlsOut {
  const n = xs.length;
  const mx = mean(xs);
  const my = mean(ys);
  let sxx = 0, syy = 0, sxy = 0;
  for (let i = 0; i < n; i++) {
    const dx = xs[i] - mx, dy = ys[i] - my;
    sxx += dx * dx; syy += dy * dy; sxy += dx * dy;
  }
  const beta = sxx > 0 ? sxy / sxx : 0;
  const alpha = my - beta * mx;
  let ssRes = 0;
  const residuals: number[] = new Array(n);
  for (let i = 0; i < n; i++) {
    const yh = alpha + beta * xs[i];
    const r = ys[i] - yh;
    residuals[i] = r;
    ssRes += r * r;
  }
  const dof = Math.max(1, n - 2);
  const sigma2 = ssRes / dof;
  const seBeta = sxx > 0 ? Math.sqrt(sigma2 / sxx) : 0;
  const tBeta = seBeta > 0 ? beta / seBeta : 0;
  const pBeta = twoSidedP(tBeta);
  const rSquared = syy > 0 ? 1 - ssRes / syy : 0;
  return { alpha, beta, seBeta, tBeta, pBeta, rSquared, residualStd: Math.sqrt(sigma2), residuals };
}

// ── Stage 0 main entry ────────────────────────────────────────────

export interface FvFitDiagnostics {
  // Descriptive
  nTicks: number;
  meanFv: number;
  stdFv: number;
  meanStep: number;
  stdStep: number;
  meanStepZ: number;
  meanStepP: number;

  // Linear drift fit
  linearFit: {
    alpha: number;
    beta: number;
    seBeta: number;
    tBeta: number;
    pBeta: number;
    rSquared: number;
    residualStd: number;
  };

  // Ljung-Box on the model's residuals
  residualLjung: { q: number; df: number; p: number; ac: number[] };

  // Normality of residuals (skew, kurtosis z-tests; normal ⇒ both ≈ 0)
  skewness: number;
  excessKurtosis: number;
  skewZ: number;
  skewP: number;
  kurtZ: number;
  kurtP: number;

  // Quantization grid
  quantization: { grid: string; value: number; minAbs: number };

  // AR(1) coefficient on ΔFV
  deltaAc1: number;
  deltaAc1Z: number;
  deltaAc1P: number;
}

export interface FvFitResult {
  pickedType: FvProcessType;
  diagnostics: FvFitDiagnostics;
  residuals: number[];
  fitted: number[];   // model predictions aligned with input fv series
  // Chart-ready data
  fvSeries: { ts: number; fv: number }[];
  deltaFv: number[];
}

export interface Stage0Input {
  rows: { ts: number; fv: number }[];
}

export function runStage0(input: Stage0Input): FvFitResult {
  const rows = input.rows.slice().sort((a, b) => a.ts - b.ts);
  const fvs = rows.map(r => r.fv);
  const n = fvs.length;
  if (n < 3) throw new Error('Stage 0: need ≥ 3 ticks with FV');

  const muFv = mean(fvs);
  const sFv  = Math.sqrt(variance(fvs, muFv));

  const steps: number[] = [];
  for (let i = 1; i < n; i++) steps.push(fvs[i] - fvs[i - 1]);
  const muStep = mean(steps);
  const sStep  = Math.sqrt(variance(steps, muStep));
  const seStep = sStep / Math.sqrt(steps.length);
  const zStep  = seStep > 0 ? muStep / seStep : 0;

  // Linear drift fit: FV ~ α + β·t (use tick index for numerical stability).
  const idx = new Array(n);
  for (let i = 0; i < n; i++) idx[i] = i;
  const lin = ols(idx, fvs);

  // AC(1) of ΔFV — tests for AR(1) structure
  const muSteps = muStep;
  let num = 0, den = 0;
  for (let i = 1; i < steps.length; i++) num += (steps[i] - muSteps) * (steps[i - 1] - muSteps);
  for (const s of steps) { const d = s - muSteps; den += d * d; }
  const ac1 = den > 0 ? num / den : 0;
  const ac1Se = 1 / Math.sqrt(steps.length);
  const ac1Z = ac1 / ac1Se;
  const ac1P = twoSidedP(ac1Z);

  // Choose process. Quantization gives us the minimum meaningful σ scale.
  const quant = detectQuantization(steps);
  const quantScale = quant.value > 0 ? quant.value : 1e-6;

  let pickedType: FvProcessType;
  let residuals: number[];
  let fitted: number[];

  if (sFv < quantScale * 3) {
    pickedType = 'constant';
    fitted = new Array(n).fill(muFv);
    residuals = fvs.map((v, i) => v - fitted[i]);
  } else if (lin.pBeta < 1e-3 && lin.rSquared > 0.9) {
    pickedType = 'linear_drift';
    fitted = idx.map(t => lin.alpha + lin.beta * t);
    residuals = lin.residuals;
  } else if (ac1P < 1e-3 && Math.abs(ac1) > 0.1) {
    pickedType = 'ar1';
    // For AR(1) on ΔFV, residuals are one-step-ahead prediction errors.
    // ε_t = ΔFV_t - φ̂·ΔFV_{t-1}
    residuals = [];
    for (let i = 1; i < steps.length; i++) residuals.push(steps[i] - ac1 * steps[i - 1]);
    // Fitted FV series: reconstruct from first tick + predicted steps.
    fitted = new Array(n).fill(0);
    fitted[0] = fvs[0];
    for (let i = 1; i < n; i++) {
      const predStep = i >= 2 ? ac1 * steps[i - 2] : muStep;
      fitted[i] = fitted[i - 1] + predStep;
    }
  } else {
    pickedType = 'random_walk';
    // For RW, model-implied residuals are the zero-mean step series.
    residuals = steps.map(s => s - muStep);
    fitted = new Array(n).fill(0);
    fitted[0] = fvs[0];
    for (let i = 1; i < n; i++) fitted[i] = fitted[i - 1] + muStep;
  }

  // Residual Ljung-Box (up to 10 lags or n/4, whichever smaller)
  const maxLag = Math.min(10, Math.max(2, Math.floor(residuals.length / 4)));
  const lb = ljungBox(residuals, maxLag);

  // Skew / kurt z-tests
  const rMu = mean(residuals);
  const rStd = Math.sqrt(variance(residuals, rMu));
  let m3 = 0, m4 = 0;
  for (const r of residuals) { const d = r - rMu; m3 += d*d*d; m4 += d*d*d*d; }
  const nR = residuals.length;
  const skew = rStd > 0 ? (m3 / nR) / Math.pow(rStd, 3) : 0;
  const ek   = rStd > 0 ? (m4 / nR) / Math.pow(rStd, 4) - 3 : 0;
  // Under normal, SE(skew) ≈ √(6/n), SE(ek) ≈ √(24/n)
  const seSkew = Math.sqrt(6 / nR);
  const seKurt = Math.sqrt(24 / nR);
  const skewZ = skew / seSkew;
  const kurtZ = ek / seKurt;

  const diagnostics: FvFitDiagnostics = {
    nTicks: n,
    meanFv: muFv,
    stdFv: sFv,
    meanStep: muStep,
    stdStep: sStep,
    meanStepZ: zStep,
    meanStepP: twoSidedP(zStep),
    linearFit: {
      alpha: lin.alpha, beta: lin.beta, seBeta: lin.seBeta,
      tBeta: lin.tBeta, pBeta: lin.pBeta,
      rSquared: lin.rSquared, residualStd: lin.residualStd,
    },
    residualLjung: lb,
    skewness: skew, excessKurtosis: ek,
    skewZ, skewP: twoSidedP(skewZ),
    kurtZ, kurtP: twoSidedP(kurtZ),
    quantization: quant,
    deltaAc1: ac1, deltaAc1Z: ac1Z, deltaAc1P: ac1P,
  };

  return {
    pickedType, diagnostics, residuals, fitted,
    fvSeries: rows.map(r => ({ ts: r.ts, fv: r.fv })),
    deltaFv: steps,
  };
}
