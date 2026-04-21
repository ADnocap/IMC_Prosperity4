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

const tableCache = new Map<string, Promise<ParsedTable>>();

export function loadTable(entry: TreeEntry): Promise<ParsedTable> {
  const cached = tableCache.get(entry.path);
  if (cached !== undefined) return cached;
  const promise = (async (): Promise<ParsedTable> => {
    const text = await fetchCsv(entry.path);
    const delimiter = detectDelimiter(text);
    const parsed = Papa.parse<Row>(text, {
      header: true,
      delimiter,
      dynamicTyping: false,
      skipEmptyLines: true,
      transformHeader: (h: string) => h.trim(),
    });
    const rows = parsed.data.filter(r => r && Object.keys(r).length > 0);
    const shape = inferShape(rows);
    return { entry, rows, shape };
  })();
  tableCache.set(entry.path, promise);
  return promise;
}

export function invalidateCache(): void {
  tableCache.clear();
}
