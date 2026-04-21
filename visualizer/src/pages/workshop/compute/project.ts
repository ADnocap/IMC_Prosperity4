import { ConcatenatedTable, DayBoundary } from '../concat.ts';
import { Row } from '../types.ts';
import { LadderSlice } from './types.ts';

function toFloat64(rows: Row[], column: string | null): Float64Array {
  if (column === null) {
    const out = new Float64Array(rows.length);
    out.fill(Number.NaN);
    return out;
  }
  const out = new Float64Array(rows.length);
  for (let i = 0; i < rows.length; i += 1) {
    const raw = rows[i][column];
    if (raw === null || raw === undefined || raw === '') { out[i] = Number.NaN; continue; }
    const n = Number(raw);
    out[i] = Number.isFinite(n) ? n : Number.NaN;
  }
  return out;
}

function toStringColumn(rows: Row[], column: string | null): string[] {
  if (column === null) return rows.map(() => '');
  const out = new Array<string>(rows.length);
  for (let i = 0; i < rows.length; i += 1) {
    const raw = rows[i][column];
    out[i] = raw === null || raw === undefined ? '' : String(raw);
  }
  return out;
}

export interface PricesProjection {
  products: string[];
  times: Float64Array;
  mids: Float64Array;
  bid1: Float64Array;
  ask1: Float64Array;
  bidVol1: Float64Array;
  askVol1: Float64Array;
  ladder: LadderSlice[];
  hasLadder: boolean;
  availableProducts: string[];
}

export function projectPrices(table: ConcatenatedTable | null): PricesProjection | null {
  if (table === null) return null;
  const shape = table.shape;
  const productCol = shape.productColumn;
  if (productCol === null) return null;
  const timeKey = table.cumulativeKey;
  const rows = table.rows;
  const products = toStringColumn(rows, productCol);
  const times = toFloat64(rows, timeKey);
  const mids = toFloat64(rows, shape.midColumn);
  const level1 = shape.ladderLevels[0];
  const bid1 = toFloat64(rows, level1?.bidPrice ?? null);
  const ask1 = toFloat64(rows, level1?.askPrice ?? null);
  const bidVol1 = toFloat64(rows, level1?.bidVolume ?? null);
  const askVol1 = toFloat64(rows, level1?.askVolume ?? null);

  const ladder: LadderSlice[] = shape.ladderLevels.map(level => ({
    bidPrice: level.bidPrice ? toFloat64(rows, level.bidPrice) : null,
    bidVolume: level.bidVolume ? toFloat64(rows, level.bidVolume) : null,
    askPrice: level.askPrice ? toFloat64(rows, level.askPrice) : null,
    askVolume: level.askVolume ? toFloat64(rows, level.askVolume) : null,
  }));

  return {
    products,
    times,
    mids,
    bid1,
    ask1,
    bidVol1,
    askVol1,
    ladder,
    hasLadder: shape.hasLadder,
    availableProducts: shape.products,
  };
}

/**
 * Everything a prices-panel needs. Computed once per table load at the
 * WorkshopPage level so each panel doesn't re-walk 60k rows.
 */
export interface PreparedPrices {
  projection: PricesProjection;
  dayBoundaries: DayBoundary[];
  hasLadder: boolean;
  availableProducts: string[];
}

export function preparePrices(table: ConcatenatedTable | null): PreparedPrices | null {
  if (table === null) return null;
  const projection = projectPrices(table);
  if (projection === null) return null;
  return {
    projection,
    dayBoundaries: table.dayBoundaries,
    hasLadder: projection.hasLadder,
    availableProducts: projection.availableProducts,
  };
}

export interface TradesProjection {
  times: Float64Array;
  products: string[];
  prices: Float64Array;
  quantities: Float64Array;
  buyers: string[];
  sellers: string[];
  availableProducts: string[];
  counterparties: string[];
}

export function projectTrades(table: ConcatenatedTable | null): TradesProjection | null {
  if (table === null) return null;
  const shape = table.shape;
  if (shape.priceColumn === null || shape.quantityColumn === null) return null;
  const rows = table.rows;
  return {
    times: toFloat64(rows, table.cumulativeKey),
    products: toStringColumn(rows, shape.productColumn),
    prices: toFloat64(rows, shape.priceColumn),
    quantities: toFloat64(rows, shape.quantityColumn),
    buyers: toStringColumn(rows, shape.buyerColumn),
    sellers: toStringColumn(rows, shape.sellerColumn),
    availableProducts: shape.products,
    counterparties: shape.counterparties,
  };
}

export interface PreparedTrades {
  projection: TradesProjection;
  dayBoundaries: DayBoundary[];
  availableProducts: string[];
  counterparties: string[];
  hasCounterparties: boolean;
}

export function prepareTrades(table: ConcatenatedTable | null): PreparedTrades | null {
  const projection = projectTrades(table);
  if (projection === null || table === null) return null;
  return {
    projection,
    dayBoundaries: table.dayBoundaries,
    availableProducts: projection.availableProducts,
    counterparties: projection.counterparties,
    hasCounterparties: projection.counterparties.length > 0,
  };
}
