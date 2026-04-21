import { inferShape } from './schema.ts';
import { ParsedTable, Row } from './types.ts';

export interface DayBoundary {
  day: number;
  cumulativeOffset: number;
}

export interface ConcatenatedTable {
  tables: ParsedTable[];
  rows: Row[];
  shape: ParsedTable['shape'];
  dayBoundaries: DayBoundary[];
  cumulativeKey: string;
}

const CUMULATIVE_KEY = '__cumulativeTime';

/**
 * Concatenate N day-tables into one contiguous series. Adds a synthetic
 * `__cumulativeTime` column so charts can plot across day boundaries without
 * timestamp overlap; also returns boundary offsets for reference lines.
 *
 * Tables are expected to share a schema (same `role` and columns); the shape of
 * the first table is used as the canonical shape.
 */
export function concatTables(tables: ParsedTable[]): ConcatenatedTable | null {
  if (tables.length === 0) return null;
  const sorted = [...tables].sort((a, b) => {
    const dayA = a.entry.day ?? 0;
    const dayB = b.entry.day ?? 0;
    return dayA - dayB;
  });
  const timeCol = sorted[0].shape.timeColumn;
  const combinedRows: Row[] = [];
  const boundaries: DayBoundary[] = [];
  let runningOffset = 0;

  for (const table of sorted) {
    let maxTick = 0;
    const day = table.entry.day ?? 0;
    boundaries.push({ day, cumulativeOffset: runningOffset });
    for (const row of table.rows) {
      const cloned = { ...row };
      if (timeCol !== null) {
        const raw = Number(row[timeCol]);
        const tick = Number.isFinite(raw) ? raw : 0;
        cloned[CUMULATIVE_KEY] = runningOffset + tick;
        if (tick > maxTick) maxTick = tick;
      } else {
        cloned[CUMULATIVE_KEY] = runningOffset + combinedRows.length;
      }
      combinedRows.push(cloned);
    }
    // Advance offset; 100-tick grid → next day starts at maxTick + 100, but
    // fall back to maxTick + 1 for non-standard grids.
    const stride = maxTick > 0 ? maxTick + 100 : combinedRows.length + 1;
    runningOffset += stride;
  }

  const shape = inferShape(combinedRows);
  return {
    tables: sorted,
    rows: combinedRows,
    shape,
    dayBoundaries: boundaries,
    cumulativeKey: CUMULATIVE_KEY,
  };
}
