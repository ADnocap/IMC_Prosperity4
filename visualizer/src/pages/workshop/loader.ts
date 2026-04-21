import axios from 'axios';
import Papa from 'papaparse';
import { inferShape } from './schema.ts';
import { ParsedTable, Row, TreeEntry } from './types.ts';

const TREE_URL = '/__prosperity4mcbt__/workshop/tree';
const FILE_URL = '/__prosperity4mcbt__/workshop/file';

function detectDelimiter(text: string): string {
  const firstLine = text.slice(0, text.indexOf('\n'));
  const commaCount = (firstLine.match(/,/g) ?? []).length;
  const semiCount = (firstLine.match(/;/g) ?? []).length;
  return semiCount >= commaCount ? ';' : ',';
}

export async function fetchTree(): Promise<TreeEntry[]> {
  const response = await axios.get<{ files: TreeEntry[] }>(TREE_URL);
  return response.data.files;
}

async function fetchCsv(path: string): Promise<string> {
  const response = await axios.get<string>(FILE_URL, {
    params: { path },
    responseType: 'text',
    transformResponse: [(raw: string) => raw],
  });
  return response.data;
}

function parseCsvInWorker(text: string, delimiter: string): Promise<Row[]> {
  return new Promise((resolve, reject) => {
    // PapaParse's `worker: true` spawns its own worker so parsing + row-object
    // allocation happens off the main thread -- the heaviest single step of
    // any load.
    Papa.parse<Row>(text, {
      worker: true,
      header: true,
      delimiter,
      dynamicTyping: false,
      skipEmptyLines: true,
      complete: results => {
        // Headers come through raw; trim whitespace lazily (cheap loop, on
        // main thread but dominated by N cols, not N rows).
        const rows = results.data.filter(r => r && Object.keys(r).length > 0);
        if (rows.length > 0) {
          const keys = Object.keys(rows[0]);
          const trimmed = keys.filter(k => k !== k.trim());
          if (trimmed.length > 0) {
            for (const row of rows) {
              for (const dirty of trimmed) {
                const clean = dirty.trim();
                if (clean !== dirty && row[dirty] !== undefined) {
                  row[clean] = row[dirty];
                  delete row[dirty];
                }
              }
            }
          }
        }
        resolve(rows);
      },
      error: (err: Error) => reject(err),
    });
  });
}

const tableCache = new Map<string, Promise<ParsedTable>>();

export function loadTable(entry: TreeEntry): Promise<ParsedTable> {
  const cached = tableCache.get(entry.path);
  if (cached !== undefined) return cached;
  const promise = (async (): Promise<ParsedTable> => {
    const text = await fetchCsv(entry.path);
    const delimiter = detectDelimiter(text);
    const rows = await parseCsvInWorker(text, delimiter);
    const shape = inferShape(rows);
    return { entry, rows, shape };
  })();
  tableCache.set(entry.path, promise);
  return promise;
}

export function invalidateCache(): void {
  tableCache.clear();
}
