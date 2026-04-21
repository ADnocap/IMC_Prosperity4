import { Alert, Group, Loader, Table, Text } from '@mantine/core';
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

// Horizon for realized spread (10 ticks on the Prosperity grid).
const REALIZED_HORIZON_TS = 1000;

export function EffRealizedPanel({ prices, trades, products }: Props): ReactNode {
  const task = useMemo<(TaskInput & { kind: 'effRealized' }) | null>(() => {
    if (prices === null || trades === null) return null;
    return {
      kind: 'effRealized',
      input: {
        tradeTimes: trades.projection.times,
        tradeProducts: trades.projection.products,
        tradePrices: trades.projection.prices,
        priceTimes: prices.projection.times,
        priceProducts: prices.projection.products,
        priceMids: prices.projection.mids,
        horizonTimestamp: REALIZED_HORIZON_TS,
        productsAllowed: products.length > 0 ? products : null,
      },
    };
  }, [prices, trades, products]);

  const { data, loading, error } = useCompute(task);

  if (prices === null || trades === null) {
    return (
      <VisualizerCard title="Effective vs realized spread">
        <Text c="dimmed" size="sm">Load prices + trades to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Effective vs realized spread">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Effective vs realized spread">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">
            Couldn't classify any trades via Lee-Ready (need trades at prices ≠ mid).
          </Alert>
        )}
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Effective vs realized spread${loading ? ' · refreshing…' : ''}`}>
      <Text size="sm" c="dimmed" mb="xs">
        <Text span ff="monospace">effective = 2·|price − mid_t|</Text> (taker round-trip cost).
        <Text span ff="monospace"> realized = 2·sign·(price − mid_{`{t+10}`})</Text> (maker gross edge, Lee-Ready classified).
        <Text span ff="monospace"> adverse selection = effective − realized</Text> (what the maker lost to informed flow).
        Positive mean-sign ⇒ buyer-initiated tape.
      </Text>
      <Table striped withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Product</Table.Th>
            <Table.Th>Classified trades</Table.Th>
            <Table.Th>Mean effective</Table.Th>
            <Table.Th>Mean realized</Table.Th>
            <Table.Th>Adverse selection</Table.Th>
            <Table.Th>Mean sign</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.map(row => (
            <Table.Tr key={row.product}>
              <Table.Td>{row.product}</Table.Td>
              <Table.Td>{row.n}</Table.Td>
              <Table.Td>{formatNumber(row.meanEffective, 3)}</Table.Td>
              <Table.Td>{formatNumber(row.meanRealized, 3)}</Table.Td>
              <Table.Td>{formatNumber(row.adverseSelection, 3)}</Table.Td>
              <Table.Td>{formatNumber(row.meanSign, 2)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </VisualizerCard>
  );
}
