// Top-K ranked trials table.
//
// Ranking column: `test_score` if the study has retest data, else the raw
// training `value`. All `params_*` columns are shown side-by-side so the
// user can eyeball which knobs moved for the winners. Train/val/test PnL
// means come next — the train-val delta is a quick overfit-watching diagnostic.

import { Alert, Badge } from '@mantine/core';
import { MantineReactTable, MRT_ColumnDef, useMantineReactTable } from 'mantine-react-table';
import { ReactNode, useMemo } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { TrialRow } from '../types.ts';

interface Props {
  trials: TrialRow[];
  paramNames: string[];
}

interface DisplayRow {
  number: number;
  rank: number;
  score: number | null;
  value: number | null;
  testScore: number | null;
  trainMean: number | null;
  valMean: number | null;
  testMean: number | null;
  trainValDelta: number | null;
  state: string;
  params: Record<string, number | string | null>;
}

export function TopKPanel({ trials, paramNames }: Props): ReactNode {
  const rows = useMemo<DisplayRow[]>(() => {
    const completed = trials.filter(t => (t.state ?? '') === 'COMPLETE');
    const keyFor = (t: TrialRow): number => numericOrNeg(t.test_score) ?? numericOrNeg(t.value) ?? -Infinity;
    const sorted = [...completed].sort((a, b) => keyFor(b) - keyFor(a));
    return sorted.slice(0, 25).map((t, idx) => ({
      rank: idx + 1,
      number: Number(t.number ?? -1),
      score: numericOrNeg(t.value) ?? null,
      value: numericOrNeg(t.value) ?? null,
      testScore: numericOrNeg(t.test_score) ?? null,
      trainMean: numericOrNeg(t['user_attrs_train/pnl_mean']) ?? null,
      valMean: numericOrNeg(t['user_attrs_val/pnl_mean']) ?? null,
      testMean: numericOrNeg(t.test_pnl_mean) ?? null,
      trainValDelta: numericOrNeg(t.user_attrs_train_val_delta) ?? null,
      state: String(t.state ?? ''),
      params: buildParamDict(t, paramNames),
    }));
  }, [trials, paramNames]);

  const hasTest = useMemo(() => rows.some(r => r.testScore !== null), [rows]);

  const columns = useMemo<MRT_ColumnDef<DisplayRow>[]>(() => {
    const base: MRT_ColumnDef<DisplayRow>[] = [
      {
        accessorKey: 'rank',
        header: '#',
        size: 50,
        Cell: ({ cell }) => <Badge variant="light" color={cell.getValue<number>() === 1 ? 'teal' : 'gray'}>
          {cell.getValue<number>()}
        </Badge>,
      },
      { accessorKey: 'number', header: 'Trial', size: 70 },
      { accessorKey: 'value', header: 'Train score', size: 110, Cell: cellNum },
    ];
    if (hasTest) {
      base.push({ accessorKey: 'testScore', header: 'Test score', size: 110, Cell: cellNum });
    }
    base.push(
      { accessorKey: 'trainMean', header: 'Train PnL mean', size: 130, Cell: cellNum },
      { accessorKey: 'valMean', header: 'Val PnL mean', size: 130, Cell: cellNum },
    );
    if (hasTest) {
      base.push({ accessorKey: 'testMean', header: 'Test PnL mean', size: 130, Cell: cellNum });
    }
    base.push({ accessorKey: 'trainValDelta', header: 'Train-Val Δ', size: 100, Cell: cellNum });
    for (const name of paramNames) {
      base.push({
        accessorKey: `params.${name}`,
        header: name,
        accessorFn: row => row.params[name] ?? null,
        Cell: ({ cell }) => cellParam(cell.getValue()),
      });
    }
    return base;
  }, [paramNames, hasTest]);

  const table = useMantineReactTable({
    data: rows,
    columns,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    enableSorting: true,
    enableDensityToggle: false,
    initialState: { density: 'xs' },
  });

  if (trials.length === 0) {
    return (
      <VisualizerCard title="Top trials">
        <Alert color="yellow">No trials in this study yet.</Alert>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Top ${rows.length} trials — ranked by ${hasTest ? 'test score' : 'training value'}`}>
      <MantineReactTable table={table} />
    </VisualizerCard>
  );
}

function cellNum({ cell }: { cell: { getValue: () => unknown } }): ReactNode {
  const v = cell.getValue();
  if (typeof v !== 'number' || !isFinite(v)) return '—';
  return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function cellParam(v: unknown): ReactNode {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(v);
}

function numericOrNeg(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  if (!isFinite(n)) return null;
  return n;
}

function buildParamDict(t: TrialRow, paramNames: string[]): Record<string, number | string | null> {
  const out: Record<string, number | string | null> = {};
  for (const name of paramNames) {
    const raw = t[`params_${name}`];
    if (raw === null || raw === undefined) {
      out[name] = null;
    } else if (typeof raw === 'number') {
      out[name] = raw;
    } else {
      out[name] = String(raw);
    }
  }
  return out;
}
