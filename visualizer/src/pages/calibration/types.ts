// Shared types for the Calibration tab.

export type FvProcessType = 'random_walk' | 'linear_drift' | 'constant' | 'ar1';
export type OffsetType = 'fixed' | 'proportional';
export type RoundFn = 'floor' | 'ceil' | 'round' | 'banker';

export interface CalibrationAsset {
  asset: string;           // uppercase product symbol
  assetLower: string;
  rustFile: string;
  hasData: boolean;
  hasParams: boolean;
  dataPath: string | null;
  paramsPath: string | null;
  dataMtimeMs: number | null;
  paramsMtimeMs: number | null;
}

export interface FvAndBookRow {
  ts: number;
  fv: number | null;
  bids: number[];
  asks: number[];
  bid_vols: Record<string, number>;
  ask_vols: Record<string, number>;
  mid_price: number;
}

export interface TradeRow {
  ts: number;
  buyer: string | null;
  seller: string | null;
  price: number;
  quantity: number;
  currency: string | null;
  source: string;
}

export interface FvAndBook {
  product: string;
  buy_price: number;
  rows: FvAndBookRow[];
  trades?: TradeRow[];
}

export interface FormulaSpecSide {
  round_fn: RoundFn;
  shift: number;
  constant: number;
  K: number | null;
}

export interface BotSpec {
  id: string;
  name: string;
  offset_type: OffsetType;
  bid_formula_str: string;
  ask_formula_str: string;
  formula_spec: { bid: FormulaSpecSide; ask: FormulaSpecSide };
  volume: {
    distribution: 'uniform' | 'discrete_normal' | 'poisson' | 'empirical';
    low: number;
    high: number;
    mean?: number | null;
    std?: number | null;
    lambda?: number | null;
    pmf?: Record<string, number> | null;
    sides_tied: boolean;
  };
  presence: {
    rate: number;
    iid: boolean;
    bid_ask_independent: boolean;
  };
  offset_band: { bid: [number, number]; ask: [number, number] };
  diagnostics?: Record<string, unknown>;
}

export interface CalibrationParams {
  asset: string;
  position_limit: number;
  fv_process: {
    type: FvProcessType;
    params: Record<string, number>;
    diagnostics?: Record<string, unknown>;
  };
  bots: BotSpec[];
  noise_layer?: unknown;
  trade_bot?: unknown;
  metadata?: Record<string, unknown>;
}

// Pipeline stages. Index matches the stepper order.
export const STAGES = [
  { id: 'fv_process',       label: 'FV Process',        short: 'Stage 0' },
  { id: 'layer_detection',  label: 'Layer Detection',   short: 'Stage 1' },
  { id: 'formula_discovery',label: 'Formula Discovery', short: 'Stage 2' },
  { id: 'volume_model',     label: 'Volume Model',      short: 'Stage 3' },
  { id: 'presence_model',   label: 'Presence Model',    short: 'Stage 4' },
  { id: 'noise_layer',      label: 'Noise Layer',       short: 'Stage 5' },
  { id: 'trade_bot',        label: 'Trade Bot',         short: 'Stage 6' },
  { id: 'validation',       label: 'Held-out Validation', short: 'Stage 7' },
  { id: 'export',           label: 'Export',            short: 'Stage 8' },
] as const;

export type StageId = typeof STAGES[number]['id'];
export type StageStatus = 'pending' | 'running' | 'pass' | 'warn' | 'fail';

export interface StageState {
  status: StageStatus;
  // Free-form result payload owned by the stage panel.
  result?: unknown;
  error?: string;
  // Fisher-combined p-value for the stage's tests, if any.
  summaryP?: number;
}
