import { Alert, Group, Loader, Select, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
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

export function OffsetFromMidPanel({ prices, trades, products }: Props): ReactNode {
  const task = useMemo<(TaskInput & { kind: 'offset' }) | null>(() => {
    if (prices === null || trades === null) return null;
    if (!trades.hasCounterparties) return null;
    return {
      kind: 'offset',
      input: {
        tradeTimes: trades.projection.times,
        tradeProducts: trades.projection.products,
        tradePrices: trades.projection.prices,
        tradeBuyers: trades.projection.buyers,
        tradeSellers: trades.projection.sellers,
        priceTimes: prices.projection.times,
        priceProducts: prices.projection.products,
        priceMids: prices.projection.mids,
        productsAllowed: products.length > 0 ? products : null,
      },
    };
  }, [prices, trades, products]);

  const { data, loading, error } = useCompute(task);

  const keys = useMemo(
    () => (data ?? []).map(row => `${row.counterparty} · ${row.side}`),
    [data],
  );
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (keys.length === 0) {
      if (selected !== null) setSelected(null);
      return;
    }
    if (selected === null || !keys.includes(selected)) setSelected(keys[0]);
  }, [keys, selected]);

  if (prices === null || trades === null) {
    return (
      <VisualizerCard title="Trade offset from mid, by counterparty">
        <Text c="dimmed" size="sm">Load prices + trades to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (!trades.hasCounterparties) {
    return (
      <VisualizerCard title="Trade offset from mid, by counterparty">
        <Alert color="yellow">Trades have no buyer/seller IDs.</Alert>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Trade offset from mid, by counterparty">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null) {
    return (
      <VisualizerCard title="Trade offset from mid, by counterparty">
        <Group><Loader size="sm" /><Text>Computing…</Text></Group>
      </VisualizerCard>
    );
  }

  const row = data.find(r => `${r.counterparty} · ${r.side}` === selected) ?? data[0];
  const histData = row.histogram.centers.map((c, i) => [c, row.histogram.counts[i]] as [number, number]);
  const series: Highcharts.SeriesOptionsType[] = [
    {
      type: 'column',
      name: `${row.counterparty} · ${row.side}`,
      data: histData,
      color: row.side === 'buyer' ? '#fa5252' : '#12b886',
      pointPadding: 0,
      groupPadding: 0,
    },
  ];

  return (
    <VisualizerCard title={`Trade offset from mid${loading ? ' · refreshing…' : ''}`}>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          For buyers: distance <Text span ff="monospace">price − mid</Text>. Positive = paid up (aggressive / informed), negative = lifted below mid (unusual).
          For sellers the sign is flipped so the semantics match: positive = hit above mid.
          Mean: <Text span fw={600}>{formatNumber(row.mean, 3)}</Text> · Trades: <Text span fw={600}>{row.trades}</Text>
        </Text>
        <Select
          label="Counterparty × side"
          data={keys}
          value={selected}
          onChange={setSelected}
          searchable
          allowDeselect={false}
          w={320}
        />
        <SimpleChart
          title=""
          series={series}
          options={{
            xAxis: { title: { text: 'price − mid' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
            yAxis: { title: { text: 'Trade count' } },
            plotOptions: { column: { grouping: false } },
          }}
        />
      </Stack>
    </VisualizerCard>
  );
}
