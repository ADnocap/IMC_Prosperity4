import { Alert, Group, Loader, NumberInput, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prices: PreparedPrices | null;
  products: string[];
}

const DEFAULT_BUCKETS = 20;
const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

export function SeasonalityPanel({ prices, products }: Props): ReactNode {
  // Prosperity day = 2000 ticks × 100 timestamp stride = 200 000.
  const [dayPeriod, setDayPeriod] = useState<number>(200_000);

  const task = useMemo<(TaskInput & { kind: 'seasonality' }) | null>(() => {
    if (prices === null) return null;
    return {
      kind: 'seasonality',
      input: {
        products: prices.projection.products,
        times: prices.projection.times,
        mids: prices.projection.mids,
        bid1: prices.projection.bid1,
        ask1: prices.projection.ask1,
        dayPeriod,
        buckets: DEFAULT_BUCKETS,
        productsAllowed: products.length > 0 ? products : null,
      },
    };
  }, [prices, products, dayPeriod]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Intraday seasonality">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Intraday seasonality">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Intraday seasonality">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">No data bucketed (check day period).</Alert>
        )}
      </VisualizerCard>
    );
  }

  const spreadSeries: Highcharts.SeriesOptionsType[] = data.map((p, i) => ({
    type: 'line',
    name: p.product,
    data: p.bucketCenters.map((c, idx) => [c, p.meanSpread[idx]] as [number, number]),
    color: PALETTE[i % PALETTE.length],
    lineWidth: 1.5,
  }));
  const volSeries: Highcharts.SeriesOptionsType[] = data.map((p, i) => ({
    type: 'line',
    name: p.product,
    data: p.bucketCenters.map((c, idx) => [c, p.returnVol[idx]] as [number, number]),
    color: PALETTE[i % PALETTE.length],
    lineWidth: 1.5,
  }));

  return (
    <VisualizerCard title={`Intraday seasonality${loading ? ' · refreshing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <NumberInput
            label="Day period (timestamp units)"
            value={dayPeriod}
            onChange={v => setDayPeriod(Number(v) || 200_000)}
            min={1000}
            w={220}
          />
          <Text size="sm" c="dimmed" maw={520}>
            Buckets 0..1 map to fractional position within the day. Ticks are wrapped via{' '}
            <Text span ff="monospace">timestamp mod period</Text>.
          </Text>
        </Group>
        <SimpleChart
          title="Mean bid-ask spread by intraday bucket"
          series={spreadSeries}
          options={{
            xAxis: { title: { text: 'Timestamp within day' } },
            yAxis: { title: { text: 'Mean spread' } },
          }}
        />
        <SimpleChart
          title="Return volatility by intraday bucket"
          series={volSeries}
          options={{
            xAxis: { title: { text: 'Timestamp within day' } },
            yAxis: { title: { text: 'RMS Δmid' } },
          }}
        />
      </Stack>
    </VisualizerCard>
  );
}
