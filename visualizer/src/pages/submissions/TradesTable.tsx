import { MantineReactTable, MRT_ColumnDef, useMantineReactTable } from 'mantine-react-table';
import { ReactNode, useMemo } from 'react';
import { formatNumber } from '../../utils/format.ts';
import { SubmissionTrade } from './SubmissionsPage.tsx';

interface TradeRow extends SubmissionTrade {
  side: string;
  notional: number;
}

export function TradesTable({ trades }: { trades: SubmissionTrade[] }): ReactNode {
  const rows = useMemo<TradeRow[]>(
    () =>
      trades.map(t => ({
        ...t,
        side: t.buyer === 'SUBMISSION' ? 'BUY' : t.seller === 'SUBMISSION' ? 'SELL' : 'MARKET',
        notional: t.price * t.quantity,
      })),
    [trades],
  );

  const columns = useMemo<MRT_ColumnDef<TradeRow>[]>(
    () => [
      { accessorKey: 'timestamp', header: 'Time', size: 100 },
      { accessorKey: 'symbol', header: 'Symbol' },
      {
        accessorKey: 'side',
        header: 'Side',
        size: 80,
        Cell: ({ cell }) => {
          const side = cell.getValue<string>();
          const color = side === 'BUY' ? '#12b886' : side === 'SELL' ? '#fa5252' : '#868e96';
          return <span style={{ color, fontWeight: 600 }}>{side}</span>;
        },
      },
      {
        accessorKey: 'price',
        header: 'Price',
        size: 100,
        Cell: ({ cell }) => formatNumber(cell.getValue<number>(), 2),
      },
      { accessorKey: 'quantity', header: 'Qty', size: 80 },
      {
        accessorKey: 'notional',
        header: 'Notional',
        size: 120,
        Cell: ({ cell }) => formatNumber(cell.getValue<number>(), 2),
      },
      { accessorKey: 'buyer', header: 'Buyer' },
      { accessorKey: 'seller', header: 'Seller' },
    ],
    [],
  );

  const mrt = useMantineReactTable({
    data: rows,
    columns,
    enableColumnFilters: true,
    enableGlobalFilter: true,
    enableSorting: true,
    enableDensityToggle: true,
    enableRowVirtualization: rows.length > 200,
    initialState: { density: 'xs', pagination: { pageIndex: 0, pageSize: 25 } },
    mantineTableProps: { striped: true, withTableBorder: true, withColumnBorders: true },
    mantinePaperProps: { withBorder: false, shadow: 'none' },
  });

  return <MantineReactTable table={mrt} />;
}
