import { Alert, Badge, Group, Loader, Table, Text } from '@mantine/core';
import { ReactNode, useMemo } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { PreparedPrices, PreparedTrades } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prices: PreparedPrices | null;
  trades: PreparedTrades | null;
  products: string[];
}

const DEFAULT_HORIZONS = [100, 500, 1000, 5000]; // 1, 5, 10, 50 ticks on the Prosperity grid

export function MarkoutPanel({ prices, trades, products }: Props): ReactNode {
  const task = useMemo<(TaskInput & { kind: 'markout' }) | null>(() => {
    if (prices === null || trades === null) return null;
    if (!trades.hasCounterparties) return null;
    return {
      kind: 'markout',
      input: {
        tradeTimes: trades.projection.times,
        tradeProducts: trades.projection.products,
        tradePrices: trades.projection.prices,
        tradeQuantities: trades.projection.quantities,
        tradeBuyers: trades.projection.buyers,
        tradeSellers: trades.projection.sellers,
        priceTimes: prices.projection.times,
        priceProducts: prices.projection.products,
        priceMids: prices.projection.mids,
        horizonTimestamps: Uint32Array.from(DEFAULT_HORIZONS),
        productsAllowed: products.length > 0 ? products : null,
        counterpartiesAllowed: null,
      },
    };
  }, [prices, trades, products]);

  const { data, loading, error } = useCompute(task);

  if (prices === null || trades === null) {
    return (
      <VisualizerCard title="Mark-out by counterparty">
        <Text c="dimmed" size="sm">Load prices + trades to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (!trades.hasCounterparties) {
    return (
      <VisualizerCard title="Mark-out by counterparty">
        <Alert color="yellow">Trades have no buyer/seller IDs — can't attribute post-trade drift.</Alert>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Mark-out by counterparty">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null) {
    return (
      <VisualizerCard title="Mark-out by counterparty">
        <Group><Loader size="sm" /><Text>Computing mark-outs…</Text></Group>
      </VisualizerCard>
    );
  }

  // Big-picture signals: positive mark-out ⇒ they profited ⇒ informed flow ⇒ toxic.
  // Negative ⇒ their direction was wrong ⇒ dumb flow ⇒ we want to trade them.
  const signalClass = (v: number): { label: string; color: string } => {
    if (v > 0.3) return { label: 'INFORMED', color: 'red' };
    if (v > 0.05) return { label: 'toxic', color: 'orange' };
    if (v < -0.3) return { label: 'DUMB', color: 'teal' };
    if (v < -0.05) return { label: 'dumb', color: 'green' };
    return { label: 'neutral', color: 'gray' };
  };

  return (
    <VisualizerCard title={`Mark-out by counterparty${loading ? ' · refreshing…' : ''}`}>
      <Text size="sm" c="dimmed" mb="xs">
        Average <Text span ff="monospace">mid(t+Δ) − price</Text> for buyers, <Text span ff="monospace">price − mid(t+Δ)</Text> for sellers.
        <Text span fw={600}> Positive = informed</Text> (they profited → toxic flow, avoid quoting into it).
        <Text span fw={600}> Negative = dumb</Text> (they lost → exactly who we want to trade).
        Sorted by |50-tick mark-out| — most-informative counterparties at the top.
      </Text>
      <Table striped withTableBorder withColumnBorders stickyHeader>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Counterparty</Table.Th>
            <Table.Th>Side</Table.Th>
            <Table.Th>Trades</Table.Th>
            <Table.Th>Δ=1</Table.Th>
            <Table.Th>Δ=5</Table.Th>
            <Table.Th>Δ=10</Table.Th>
            <Table.Th>Δ=50</Table.Th>
            <Table.Th>Signal</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.map(row => {
            const last = row.markoutMeans[row.markoutMeans.length - 1] ?? 0;
            const signal = signalClass(last);
            return (
              <Table.Tr key={`${row.counterparty}-${row.side}`}>
                <Table.Td>{row.counterparty || '—'}</Table.Td>
                <Table.Td>{row.side}</Table.Td>
                <Table.Td>{row.trades}</Table.Td>
                {row.markoutMeans.map((v, i) => (
                  <Table.Td key={i}>{formatNumber(v, 3)}</Table.Td>
                ))}
                <Table.Td>
                  <Badge color={signal.color} variant="light" size="sm">{signal.label}</Badge>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </VisualizerCard>
  );
}
