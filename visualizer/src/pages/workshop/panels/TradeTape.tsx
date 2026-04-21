import { Alert, Text } from '@mantine/core';
import { MantineReactTable, MRT_ColumnDef, useMantineReactTable } from 'mantine-react-table';
import { ReactNode, useMemo } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ConcatenatedTable } from '../concat.ts';
import { Row } from '../types.ts';

interface Props {
  table: ConcatenatedTable | null;
  products: string[];
}

function useTradeRows(
  table: ConcatenatedTable | null,
  products: string[],
): { rows: Row[]; columns: MRT_ColumnDef<Row>[] } {
  return useMemo(() => {
    if (table === null) return { rows: [], columns: [] };
    const productCol = table.shape.productColumn;
    const filtered = productCol === null || products.length === 0
      ? table.rows
      : table.rows.filter(r => products.includes(String(r[productCol] ?? '')));

    // Show all columns the file actually has, in order, so this adapts to any
    // future shape (extra fields, missing fields, etc.)
    const columnSpecs = table.shape.columns;
    const columns: MRT_ColumnDef<Row>[] = columnSpecs.map(spec => ({
      accessorKey: spec.name,
      header: spec.name,
      size: spec.kind === 'time' ? 90 : undefined,
      Cell: ({ cell }) => {
        const value = cell.getValue<string | number | null | undefined>();
        if (value === null || value === undefined || value === '') return '—';
        return String(value);
      },
    }));
    return { rows: filtered, columns };
  }, [table, products]);
}

export function TradeTape({ table, products }: Props): ReactNode {
  const { rows, columns } = useTradeRows(table, products);
  const mrt = useMantineReactTable({
    data: rows,
    columns,
    enableColumnFilters: true,
    enableGlobalFilter: true,
    enableSorting: true,
    enableDensityToggle: true,
    enableRowVirtualization: true,
    initialState: { density: 'xs' },
    mantineTableProps: { striped: true, withTableBorder: true, withColumnBorders: true },
    mantinePaperProps: { withBorder: false, shadow: 'none' },
  });

  if (table === null) {
    return (
      <VisualizerCard title="Trade tape">
        <Text c="dimmed" size="sm">Load a trades file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (rows.length === 0) {
    return (
      <VisualizerCard title="Trade tape">
        <Alert color="yellow">No trades match the current product filter.</Alert>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Trade tape · ${rows.length} rows`}>
      <MantineReactTable table={mrt} />
    </VisualizerCard>
  );
}
