import { Alert, Table, Text } from '@mantine/core';
import { ReactNode, useMemo } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { ConcatenatedTable } from '../concat.ts';

interface Props {
  table: ConcatenatedTable | null;
  products: string[];
}

interface AggregateRow {
  counterparty: string;
  side: 'buyer' | 'seller';
  trades: number;
  quantity: number;
  notional: number;
  vwap: number;
  avgPrice: number;
}

interface Accumulator {
  trades: number;
  quantity: number;
  notional: number;
  priceSum: number;
}

function emptyAcc(): Accumulator {
  return { trades: 0, quantity: 0, notional: 0, priceSum: 0 };
}

function buildRows(table: ConcatenatedTable | null, products: string[]): AggregateRow[] {
  if (table === null) return [];
  const { buyerColumn, sellerColumn, quantityColumn, priceColumn, productColumn } = table.shape;
  if (quantityColumn === null || priceColumn === null) return [];
  if (buyerColumn === null && sellerColumn === null) return [];

  const productFilter = productColumn !== null && products.length > 0 ? new Set(products) : null;

  const buyerMap = new Map<string, Accumulator>();
  const sellerMap = new Map<string, Accumulator>();

  for (const row of table.rows) {
    if (productFilter !== null && productColumn !== null) {
      const product = row[productColumn];
      if (product === null || product === undefined || !productFilter.has(String(product))) continue;
    }
    const rawPrice = Number(row[priceColumn] ?? 0);
    const rawQty = Math.abs(Number(row[quantityColumn] ?? 0));
    const price = Number.isFinite(rawPrice) ? rawPrice : 0;
    const qty = Number.isFinite(rawQty) ? rawQty : 0;
    const notional = price * qty;

    if (buyerColumn !== null) {
      const buyer = row[buyerColumn];
      if (buyer !== null && buyer !== undefined && buyer !== '') {
        const key = String(buyer);
        let slot = buyerMap.get(key);
        if (slot === undefined) {
          slot = emptyAcc();
          buyerMap.set(key, slot);
        }
        slot.trades += 1;
        slot.quantity += qty;
        slot.notional += notional;
        slot.priceSum += price;
      }
    }

    if (sellerColumn !== null) {
      const seller = row[sellerColumn];
      if (seller !== null && seller !== undefined && seller !== '') {
        const key = String(seller);
        let slot = sellerMap.get(key);
        if (slot === undefined) {
          slot = emptyAcc();
          sellerMap.set(key, slot);
        }
        slot.trades += 1;
        slot.quantity += qty;
        slot.notional += notional;
        slot.priceSum += price;
      }
    }
  }

  const rows: AggregateRow[] = [];
  const push = (side: 'buyer' | 'seller', map: Map<string, Accumulator>): void => {
    for (const [counterparty, acc] of map) {
      rows.push({
        counterparty,
        side,
        trades: acc.trades,
        quantity: acc.quantity,
        notional: acc.notional,
        vwap: acc.quantity === 0 ? 0 : acc.notional / acc.quantity,
        avgPrice: acc.trades === 0 ? 0 : acc.priceSum / acc.trades,
      });
    }
  };
  push('buyer', buyerMap);
  push('seller', sellerMap);
  rows.sort((a, b) => b.trades - a.trades);
  return rows;
}

export function CounterpartyPivot({ table, products }: Props): ReactNode {
  const rows = useMemo(() => buildRows(table, products), [table, products]);

  if (table === null) {
    return (
      <VisualizerCard title="Counterparty pivot">
        <Text c="dimmed" size="sm">Load a trades file to see this panel.</Text>
      </VisualizerCard>
    );
  }

  if (rows.length === 0) {
    return (
      <VisualizerCard title="Counterparty pivot">
        <Alert color="yellow">
          No buyer/seller data available (either the tape has no counterparty IDs or none of the selected products have trades).
        </Alert>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Counterparty pivot · ${rows.length} rows`}>
      <Table striped withTableBorder withColumnBorders stickyHeader>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Counterparty</Table.Th>
            <Table.Th>Side</Table.Th>
            <Table.Th>Trades</Table.Th>
            <Table.Th>Qty</Table.Th>
            <Table.Th>Notional</Table.Th>
            <Table.Th>VWAP</Table.Th>
            <Table.Th>Avg px</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map(row => (
            <Table.Tr key={`${row.counterparty}-${row.side}`}>
              <Table.Td>{row.counterparty || '—'}</Table.Td>
              <Table.Td>{row.side}</Table.Td>
              <Table.Td>{row.trades}</Table.Td>
              <Table.Td>{formatNumber(row.quantity, 0)}</Table.Td>
              <Table.Td>{formatNumber(row.notional, 0)}</Table.Td>
              <Table.Td>{formatNumber(row.vwap, 2)}</Table.Td>
              <Table.Td>{formatNumber(row.avgPrice, 2)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </VisualizerCard>
  );
}
