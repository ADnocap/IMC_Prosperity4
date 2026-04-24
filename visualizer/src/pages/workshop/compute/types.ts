/**
 * Inputs/outputs for every worker-backed compute task.
 *
 * All inputs are projected from the raw parsed table into column arrays so that
 * we only pay structured-clone cost for the columns a panel actually needs.
 * Outputs are plot-ready arrays (scatter pairs, line series) to keep the main
 * thread allocation-free during rendering.
 */

export interface MidInput {
  productsAllowed: string[] | null;
  products: string[];           // per-row product label
  times: Float64Array;
  mids: Float64Array;           // NaN where missing
  bid1: Float64Array | null;
  ask1: Float64Array | null;
  bidVol1: Float64Array | null;
  askVol1: Float64Array | null;
}

export interface MidOutputProduct {
  product: string;
  midPoints: [number, number][];
  microPoints: [number, number][];
}

export type MidOutput = MidOutputProduct[];

export interface SpreadInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  bid1: Float64Array;
  ask1: Float64Array;
}

export interface SpreadOutputProduct {
  product: string;
  n: number;
  mean: number;
  std: number;
  p05: number;
  p50: number;
  p95: number;
  timeSeries: [number, number][];
  histogram: { centers: number[]; counts: number[] };
}

export type SpreadOutput = SpreadOutputProduct[];

export interface LadderSlice {
  bidPrice: Float64Array | null;
  bidVolume: Float64Array | null;
  askPrice: Float64Array | null;
  askVolume: Float64Array | null;
}

export interface DepthInput {
  productFilter: string;
  products: string[];
  times: Float64Array;
  ladder: LadderSlice[];
  maxPoints: number;
}

export interface DepthOutputLevel {
  level: number;      // 1..N
  bidPoints: [number, number][];
  askPoints: [number, number][];
}

export type DepthOutput = DepthOutputLevel[];

export interface QueueImbalanceInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  bidVol1: Float64Array;
  askVol1: Float64Array;
  horizon: number;
  maxScatter: number;
  bins: number;
}

export interface QueueImbalanceOutputProduct {
  product: string;
  scatter: [number, number][];
  binned: [number, number][];
  correlation: number;
  n: number;
}

export type QueueImbalanceOutput = QueueImbalanceOutputProduct[];

export interface OfiInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  bid1: Float64Array;
  bidVol1: Float64Array;
  ask1: Float64Array;
  askVol1: Float64Array;
  maxScatter: number;
}

export interface OfiOutputProduct {
  product: string;
  scatter: [number, number][];
  correlation: number;
  slope: number;
  intercept: number;
  n: number;
  xMin: number;
  xMax: number;
}

export type OfiOutput = OfiOutputProduct[];

// ── MM alpha inputs ─────────────────────────────────────────────────
// All three take trades joined against the prices snapshot at trade time
// and trade-time + horizon.

export interface MarkoutInput {
  // Trades
  tradeTimes: Float64Array;
  tradeProducts: string[];
  tradePrices: Float64Array;
  tradeQuantities: Float64Array;
  tradeBuyers: string[];
  tradeSellers: string[];
  // Prices (for mid lookup)
  priceTimes: Float64Array;
  priceProducts: string[];
  priceMids: Float64Array;
  // Horizons in timestamp units (Prosperity grid is 100 per tick → 100/500/1000/5000).
  horizonTimestamps: Uint32Array;
  // Filters
  productsAllowed: string[] | null;
  counterpartiesAllowed: string[] | null;
}

export interface MarkoutRow {
  counterparty: string;
  side: 'buyer' | 'seller';
  trades: number;
  markoutMeans: number[];       // parallel to horizonTimestamps
  markoutCounts: number[];
}

export type MarkoutOutput = MarkoutRow[];

export interface OffsetInput {
  tradeTimes: Float64Array;
  tradeProducts: string[];
  tradePrices: Float64Array;
  tradeBuyers: string[];
  tradeSellers: string[];
  priceTimes: Float64Array;
  priceProducts: string[];
  priceMids: Float64Array;
  productsAllowed: string[] | null;
}

export interface OffsetCounterparty {
  counterparty: string;
  side: 'buyer' | 'seller';
  trades: number;
  mean: number;
  histogram: { centers: number[]; counts: number[] };
}

export type OffsetOutput = OffsetCounterparty[];

export interface EffRealizedInput {
  tradeTimes: Float64Array;
  tradeProducts: string[];
  tradePrices: Float64Array;
  priceTimes: Float64Array;
  priceProducts: string[];
  priceMids: Float64Array;
  horizonTimestamp: number;
  productsAllowed: string[] | null;
}

export interface EffRealizedProductOut {
  product: string;
  n: number;
  meanEffective: number;
  meanRealized: number;
  adverseSelection: number;
  meanSign: number;       // average aggressor sign (-1..+1). 0 ⇒ equally buy/sell initiated.
}

export type EffRealizedOutput = EffRealizedProductOut[];

// ── Cross-asset inputs ─────────────────────────────────────────────

export interface CorrMatrixInput {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  productsAllowed: string[] | null;
  returnHorizon: number;   // timestamp units
}

export interface CorrMatrixOutput {
  labels: string[];        // ordered products
  matrix: number[];        // row-major, labels.length^2
  n: number[];             // parallel; number of paired samples per cell
}

export interface LeadLagInput {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  productA: string;
  productB: string;
  maxLagSteps: number;     // +/- this many timestamp-grid steps
  stepTimestamp: number;   // grid stride (usually 100 for Prosperity)
}

export interface LeadLagOutput {
  lags: number[];          // in step units
  correlations: number[];
  n: number[];
  bestLag: number;
  bestCorr: number;
}

export interface PairSpreadInput {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  productA: string;
  productB: string;
  zWindow: number;         // in rows
}

export interface PairSpreadOutput {
  beta: number;
  alpha: number;
  r2: number;
  spread: [number, number][];
  zscore: [number, number][];
  meanReversionHalfLife: number | null;
}

// ── Exogenous (observations → product returns) ─────────────────────

export interface ObsBetaInput {
  // Observations (timestamp-aligned, no product axis)
  obsTimes: Float64Array;
  obsColumns: { name: string; values: Float64Array }[];
  // Prices
  priceTimes: Float64Array;
  priceProducts: string[];
  priceMids: Float64Array;
  lagTimestamp: number;    // evaluate product return over [t, t+lag]
  productsAllowed: string[] | null;
}

export interface ObsBetaCell {
  observation: string;
  product: string;
  n: number;
  beta: number;
  correlation: number;
  r2: number;
}

export type ObsBetaOutput = ObsBetaCell[];

// ── Realized vol / autocorrelation / rolling β ─────────────────────

export interface RealizedVolInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  window: number;           // rows
}

export interface RealizedVolProduct {
  product: string;
  n: number;
  mean: number;
  p05: number;
  p50: number;
  p95: number;
  timeSeries: [number, number][];
}

export type RealizedVolOutput = RealizedVolProduct[];

export interface AutocorrInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  maxLag: number;
}

export interface AutocorrProduct {
  product: string;
  n: number;
  lags: number[];
  acf: number[];
  ciUpper: number;          // ±1.96/√n Bartlett band
  ciLower: number;
  ljungBoxQ: number;
  ljungBoxP: number;        // upper-tail χ²(maxLag) p-value
}

export type AutocorrOutput = AutocorrProduct[];

export interface VarianceRatioInput {
  productsAllowed: string[] | null;
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  maxK: number;            // compute VR(k) for k in 2..=maxK
}

export interface VarianceRatioProduct {
  product: string;
  n: number;
  ks: number[];
  vrs: number[];
  m1s: number[];           // homoskedastic test statistics (~N(0,1))
  m1Pvalues: number[];     // two-sided
  m2s: number[];           // heteroskedasticity-robust
  m2Pvalues: number[];
}

export type VarianceRatioOutput = VarianceRatioProduct[];

export interface RollingBetaInput {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  productA: string;
  productB: string;
  window: number;           // rows of aligned returns
}

export interface RollingBetaOutput {
  betaSeries: [number, number][];
  r2Series: [number, number][];
  fullBeta: number;
  fullR2: number;
  n: number;
}

// ── Seasonality ────────────────────────────────────────────────────

export interface SeasonalityInput {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  bid1: Float64Array;
  ask1: Float64Array;
  dayPeriod: number;       // grid ticks per day (2000 * 100 = 200000 for Prosperity)
  buckets: number;
  productsAllowed: string[] | null;
}

export interface SeasonalityProduct {
  product: string;
  bucketCenters: number[];
  meanSpread: number[];
  returnVol: number[];
  n: number[];
}

export type SeasonalityOutput = SeasonalityProduct[];

export type TaskKind =
  | 'mid' | 'spread' | 'depth' | 'queueImbalance' | 'ofi'
  | 'markout' | 'offset' | 'effRealized'
  | 'corrMatrix' | 'leadLag' | 'pairSpread'
  | 'obsBeta' | 'seasonality'
  | 'realizedVol' | 'autocorr' | 'rollingBeta' | 'varianceRatio';

export type TaskInput =
  | { kind: 'mid'; input: MidInput }
  | { kind: 'spread'; input: SpreadInput }
  | { kind: 'depth'; input: DepthInput }
  | { kind: 'queueImbalance'; input: QueueImbalanceInput }
  | { kind: 'ofi'; input: OfiInput }
  | { kind: 'markout'; input: MarkoutInput }
  | { kind: 'offset'; input: OffsetInput }
  | { kind: 'effRealized'; input: EffRealizedInput }
  | { kind: 'corrMatrix'; input: CorrMatrixInput }
  | { kind: 'leadLag'; input: LeadLagInput }
  | { kind: 'pairSpread'; input: PairSpreadInput }
  | { kind: 'obsBeta'; input: ObsBetaInput }
  | { kind: 'seasonality'; input: SeasonalityInput }
  | { kind: 'realizedVol'; input: RealizedVolInput }
  | { kind: 'autocorr'; input: AutocorrInput }
  | { kind: 'rollingBeta'; input: RollingBetaInput }
  | { kind: 'varianceRatio'; input: VarianceRatioInput };

export type TaskOutput =
  | { kind: 'mid'; output: MidOutput }
  | { kind: 'spread'; output: SpreadOutput }
  | { kind: 'depth'; output: DepthOutput }
  | { kind: 'queueImbalance'; output: QueueImbalanceOutput }
  | { kind: 'ofi'; output: OfiOutput }
  | { kind: 'markout'; output: MarkoutOutput }
  | { kind: 'offset'; output: OffsetOutput }
  | { kind: 'effRealized'; output: EffRealizedOutput }
  | { kind: 'corrMatrix'; output: CorrMatrixOutput }
  | { kind: 'leadLag'; output: LeadLagOutput }
  | { kind: 'pairSpread'; output: PairSpreadOutput }
  | { kind: 'obsBeta'; output: ObsBetaOutput }
  | { kind: 'seasonality'; output: SeasonalityOutput }
  | { kind: 'realizedVol'; output: RealizedVolOutput }
  | { kind: 'autocorr'; output: AutocorrOutput }
  | { kind: 'rollingBeta'; output: RollingBetaOutput }
  | { kind: 'varianceRatio'; output: VarianceRatioOutput };

export interface WorkerRequest {
  id: number;
  task: TaskInput;
}

export type WorkerResponse =
  | { id: number; ok: true; result: TaskOutput }
  | { id: number; ok: false; error: string };
