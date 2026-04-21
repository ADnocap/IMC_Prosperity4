import { ColumnKind, ColumnSpec, LadderLevel, Row, TableShape } from './types.ts';

const BID_PRICE_RE = /^bid[_-]?price[_-]?(\d+)$/i;
const BID_VOLUME_RE = /^bid[_-]?volume[_-]?(\d+)$/i;
const ASK_PRICE_RE = /^ask[_-]?price[_-]?(\d+)$/i;
const ASK_VOLUME_RE = /^ask[_-]?volume[_-]?(\d+)$/i;

const TIME_NAMES = new Set(['timestamp', 'time', 't', 'ts']);
const DAY_NAMES = new Set(['day']);
const PRODUCT_NAMES = new Set(['product', 'symbol', 'asset']);
const BUYER_NAMES = new Set(['buyer']);
const SELLER_NAMES = new Set(['seller']);
const PRICE_NAMES = new Set(['price']);
const QUANTITY_NAMES = new Set(['quantity', 'qty', 'size']);
const MID_NAMES = new Set(['mid_price', 'mid', 'midprice']);

function looksNumeric(value: string | number | null): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'number') return Number.isFinite(value);
  const trimmed = value.trim();
  if (trimmed === '') return false;
  return Number.isFinite(Number(trimmed));
}

function classifyColumn(name: string, samples: Array<string | number | null>): ColumnKind {
  const lower = name.toLowerCase();
  if (TIME_NAMES.has(lower)) return 'time';
  if (DAY_NAMES.has(lower)) return 'day';
  if (PRODUCT_NAMES.has(lower)) return 'product';
  if (BUYER_NAMES.has(lower) || SELLER_NAMES.has(lower)) return 'counterparty';

  const nonNull = samples.filter(v => v !== null && v !== undefined && v !== '');
  if (nonNull.length === 0) return 'unknown';
  const numericShare = nonNull.filter(looksNumeric).length / nonNull.length;
  if (numericShare >= 0.9) return 'numeric';
  return 'categorical';
}

function detectLadder(columnNames: string[]): LadderLevel[] {
  const byLevel = new Map<number, LadderLevel>();
  const ensure = (level: number): LadderLevel => {
    let slot = byLevel.get(level);
    if (slot === undefined) {
      slot = {};
      byLevel.set(level, slot);
    }
    return slot;
  };
  for (const name of columnNames) {
    let m = BID_PRICE_RE.exec(name);
    if (m) { ensure(Number(m[1])).bidPrice = name; continue; }
    m = BID_VOLUME_RE.exec(name);
    if (m) { ensure(Number(m[1])).bidVolume = name; continue; }
    m = ASK_PRICE_RE.exec(name);
    if (m) { ensure(Number(m[1])).askPrice = name; continue; }
    m = ASK_VOLUME_RE.exec(name);
    if (m) { ensure(Number(m[1])).askVolume = name; continue; }
  }
  return [...byLevel.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, slot]) => slot);
}

export function inferShape(rows: Row[]): TableShape {
  const columnNames = rows.length === 0 ? [] : Object.keys(rows[0]);
  const sampleSize = Math.min(rows.length, 200);
  const columns: ColumnSpec[] = columnNames.map(name => {
    const samples = rows.slice(0, sampleSize).map(r => r[name] ?? null);
    const kind = classifyColumn(name, samples);
    const firstValue = samples.find(v => v !== null && v !== '');
    return {
      name,
      kind,
      sample: firstValue === undefined ? null : firstValue,
    };
  });
  const columnByName = Object.fromEntries(columns.map(col => [col.name, col]));

  const ladderLevels = detectLadder(columnNames);
  const hasLadder = ladderLevels.some(l => l.bidPrice !== undefined || l.askPrice !== undefined);

  const findBy = (predicate: (col: ColumnSpec) => boolean): string | null =>
    columns.find(predicate)?.name ?? null;

  const midColumn = findBy(col => MID_NAMES.has(col.name.toLowerCase()));
  const timeColumn = findBy(col => col.kind === 'time');
  const dayColumn = findBy(col => col.kind === 'day');
  const productColumn = findBy(col => col.kind === 'product');
  const buyerColumn = findBy(col => BUYER_NAMES.has(col.name.toLowerCase()));
  const sellerColumn = findBy(col => SELLER_NAMES.has(col.name.toLowerCase()));
  const priceColumn = findBy(col => PRICE_NAMES.has(col.name.toLowerCase()));
  const quantityColumn = findBy(col => QUANTITY_NAMES.has(col.name.toLowerCase()));

  const products = productColumn
    ? [...new Set(rows.map(r => String(r[productColumn] ?? '')).filter(Boolean))].sort()
    : [];

  const counterpartyNames = new Set<string>();
  if (buyerColumn) {
    for (const r of rows) {
      const v = r[buyerColumn];
      if (v !== null && v !== undefined && v !== '') counterpartyNames.add(String(v));
    }
  }
  if (sellerColumn) {
    for (const r of rows) {
      const v = r[sellerColumn];
      if (v !== null && v !== undefined && v !== '') counterpartyNames.add(String(v));
    }
  }

  return {
    rowCount: rows.length,
    columns,
    columnByName,
    products,
    counterparties: [...counterpartyNames].sort(),
    hasLadder,
    ladderLevels,
    midColumn,
    timeColumn,
    dayColumn,
    productColumn,
    buyerColumn,
    sellerColumn,
    priceColumn,
    quantityColumn,
  };
}

export function numericValue(row: Row, col: string | null): number | null {
  if (col === null) return null;
  const v = row[col];
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function stringValue(row: Row, col: string | null): string | null {
  if (col === null) return null;
  const v = row[col];
  if (v === null || v === undefined || v === '') return null;
  return String(v);
}
