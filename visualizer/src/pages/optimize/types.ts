// Typed view of the payloads served by the optimizer endpoints.
//
// The backend reads `tmp/optimizer/<name>/results.parquet` and converts it
// to a list of dict rows. Column names match Optuna's conventions, plus a
// few Phase 2 additions from our study layer:
//   - `params_<NAME>`         — the sampled value of param <NAME>
//   - `user_attrs_<path>`     — metrics/PnL moments attached by _build_objective
//   - `test_score`, `test_pnl_mean`, `test_pnl_std` — merged from retest.json

export interface StudyListItem {
  name: string;
  hasParquet: boolean;
  hasValidators: boolean;
  hasRetest: boolean;
  hasTopCsv: boolean;
  mtimeMs: number;
  dbSizeBytes: number;
  nTrials: number | null;
  bestValue: number | null;
  bestTestScore: number | null;
}

// One row of the trials table. Keys are dynamic (`params_*`, `user_attrs_*`)
// so this type is intentionally loose — panels mine specific keys.
export type TrialRow = Record<string, unknown> & {
  number?: number;
  value?: number | null;
  state?: string;
  test_score?: number | null;
  test_pnl_mean?: number | null;
  test_pnl_std?: number | null;
};

export interface DsrBlock {
  sharpe?: number;
  probability?: number;
  expected_max_sr_under_null?: number;
  n_trials?: number;
  n_sessions?: number;
  skew?: number;
  kurt_excess?: number;
  reasoning?: string;
  skipped?: string;
}

export interface PboBlock {
  pbo?: number;
  n_trials?: number;
  n_sessions?: number;
  n_partitions_used?: number;
  reasoning?: string;
  skipped?: string;
}

export interface ClusterBlock {
  top_k?: number;
  median_top_dist?: number;
  median_random_dist?: number;
  ratio?: number;
  reasoning?: string;
  numeric_params?: string[];
  skipped?: string;
}

export interface ImportanceBlock {
  importances?: Record<string, number>;
  reasoning?: string;
}

export interface Validators {
  n_completed_trials?: number;
  n_trials_with_pnl_matrix?: number;
  best_trial?: { number: number; value: number | null; params: Record<string, unknown> };
  dsr?: DsrBlock;
  pbo?: PboBlock;
  cluster?: ClusterBlock;
  importance?: ImportanceBlock;
  skipped?: string;
}

export interface RetestEntry {
  score: number;
  n_sessions: number;
  pnl_mean: number;
  pnl_std: number;
  parts?: Record<string, number>;
  symbol_means?: Record<string, number>;
}

export interface Retest {
  test_seed: number;
  test_sessions: number;
  results: Record<string, RetestEntry>;
}

export interface StudyDetail {
  name: string;
  trials: TrialRow[];
  paramNames: string[];
  validators: Validators | null;
  retest: Retest | null;
}
