// Lightweight main-thread WASM client for the Calibration tab.
//
// The Workshop tab runs WASM in a Web Worker to keep the UI responsive across
// its big P3 datasets (580k rows). Calibration runs on ≤ 30k-tick hold-1
// extracts and the kernels are O(N) — cheap enough to run on the main thread.
// Pulling in the worker machinery would be overkill here.

import init, {
  calibBhAdjust,
  calibChi2Gof,
  calibChi2Uniform,
  calibDescribe,
  calibFisherCombined,
  calibFormulaSearch,
  calibIndep2x2,
  calibKdePeaks,
  calibKs2,
  calibLjungBox,
  calibOls,
  calibRunLengthGeom,
  calibRunsTest,
  calibWilson,
} from '../../../wasm_compute/wasm_compute.js';

let ready: Promise<void> | null = null;

export function ensureWasmReady(): Promise<void> {
  if (ready === null) ready = init().then(() => undefined);
  return ready;
}

// Re-export under shorter names for panel code.
export const wasm = {
  describe: calibDescribe,
  chi2Uniform: calibChi2Uniform,
  chi2Gof: calibChi2Gof,
  indep2x2: calibIndep2x2,
  ljungBox: calibLjungBox,
  runsTest: calibRunsTest,
  runLengthGeom: calibRunLengthGeom,
  ks2: calibKs2,
  ols: calibOls,
  kdePeaks: calibKdePeaks,
  fisher: calibFisherCombined,
  bhAdjust: calibBhAdjust,
  wilson: calibWilson,
  formulaSearch: calibFormulaSearch,
};

// ── Shared shapes returned by the kernels (aligned with calibration.rs) ──

export interface WilsonOut { phat: number; lo: number; hi: number; z: number; p_value: number; }
export interface Chi2Out { chi2: number; df: number; p_value: number; n: number; observed: number[]; expected: number[]; }
export interface OlsOut { alpha: number; beta: number; se_alpha: number; se_beta: number; t_beta: number; p_beta: number; r_squared: number; residual_std: number; n: number; }
export interface LjungOut { q: number; df: number; p_value: number; autocorr: number[]; }
export interface RunsOut { runs: number; n1: number; n2: number; expected: number; variance: number; z: number; p_value: number; }
export interface RunLenOut { run_lengths: number[]; empirical_pmf: number[]; fitted_pmf: number[]; ks_stat: number; ks_p: number; mean_length: number; n_runs: number; }
export interface Ks2Out { d: number; p_value: number; n1: number; n2: number; }
export interface KdeOut { grid: number[]; density: number[]; peaks: number[]; bandwidth: number; }
export interface Indep2x2Out { observed: number[][]; expected: number[][]; chi2: number; p_value: number; phi: number; }
export interface FixedCandidate { round_fn: string; shift: number; constant: number; match_rate: number; cv_match_rate: number; ci_lo: number; ci_hi: number; n: number; residual_hist: number[]; fv_decile_match: number[]; }
export interface PropCandidate { round_fn: string; k: number; match_rate: number; cv_match_rate: number; ci_lo: number; ci_hi: number; n: number; residual_hist: number[]; fv_decile_match: number[]; }
export interface FormulaSearchOut { fixed_top: FixedCandidate[]; proportional_top: PropCandidate[]; winner: string; winner_index: number; }
export interface FisherResult { chi2: number; df: number; p_value: number; }
