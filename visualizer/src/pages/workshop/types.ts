export type DataRole = 'prices' | 'trades' | 'observations' | 'other';

export interface TreeEntry {
  version: string;
  round: string;
  roundNumber: number | null;
  day: number | null;
  filename: string;
  path: string;
  role: DataRole;
  sizeBytes: number;
}

export type ColumnKind = 'time' | 'day' | 'product' | 'counterparty' | 'numeric' | 'categorical' | 'unknown';

export interface ColumnSpec {
  name: string;
  kind: ColumnKind;
  sample: string | number | null;
}

export interface LadderLevel {
  bidPrice?: string;
  bidVolume?: string;
  askPrice?: string;
  askVolume?: string;
}

export interface TableShape {
  rowCount: number;
  columns: ColumnSpec[];
  columnByName: Record<string, ColumnSpec>;
  products: string[];
  counterparties: string[];
  hasLadder: boolean;
  ladderLevels: LadderLevel[];
  midColumn: string | null;
  timeColumn: string | null;
  dayColumn: string | null;
  productColumn: string | null;
  buyerColumn: string | null;
  sellerColumn: string | null;
  priceColumn: string | null;
  quantityColumn: string | null;
}

export type Row = Record<string, string | number | null>;

export interface ParsedTable {
  entry: TreeEntry;
  rows: Row[];
  shape: TableShape;
}

export interface WorkshopSelection {
  version: string | null;
  round: string | null;
  days: number[];
  products: string[];
}
