import { Alert, Group, Loader, SegmentedControl, Stack, Text } from '@mantine/core';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prepared: PreparedPrices | null;
  products: string[];
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];
const HORIZONS = [1, 5, 10, 50];

export function QueueImbalancePanel({ prepared, products }: Props): ReactNode {
  const [horizon, setHorizon] = useState<number>(5);

  const task = useMemo<(TaskInput & { kind: 'queueImbalance' }) | null>(() => {
    if (prepared === null || !prepared.hasLadder) return null;
    const projection = prepared.projection;
    return {
      kind: 'queueImbalance',
      input: {
        productsAllowed: products.length > 0 ? products : null,
        products: projection.products,
        times: projection.times,
        mids: projection.mids,
        bidVol1: projection.bidVol1,
        askVol1: projection.askVol1,
        horizon,
        maxScatter: 1500,
        bins: 20,
      },
    };
  }, [prepared, products, horizon]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Queue imbalance → next-k-tick return">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Queue imbalance → next-k-tick return">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Queue imbalance → next-k-tick return">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">Need a bid/ask ladder, mid, and enough rows per product.</Alert>
        )}
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Queue imbalance → next-k-tick return${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            <Text span ff="monospace">I = (bidVol − askVol) / (bidVol + askVol)</Text> at top-of-book.
            Binned curve = conditional mean mid-change; the shape is the tradable signal.
          </Text>
          <SegmentedControl
            size="xs"
            value={String(horizon)}
            onChange={value => setHorizon(Number(value))}
            data={HORIZONS.map(h => ({ label: `${h} tick${h === 1 ? '' : 's'}`, value: String(h) }))}
          />
        </Group>
        {data.map((s, i) => (
          <SimpleChart
            key={`qi-${s.product}`}
            title={`${s.product}  ·  corr=${formatNumber(s.correlation, 3)}  ·  n=${s.n}`}
            series={[
              {
                type: 'scatter',
                name: 'ticks',
                color: PALETTE[i % PALETTE.length],
                data: s.scatter,
                marker: { radius: 1.5, symbol: 'circle', fillOpacity: 0.35 },
                opacity: 0.5,
                enableMouseTracking: false,
                boostThreshold: 1,
                states: { hover: { enabled: false } },
              },
              {
                type: 'line',
                name: 'E[Δmid | I]',
                color: '#fa5252',
                lineWidth: 2,
                data: s.binned,
                marker: { enabled: true, radius: 3 },
              },
            ]}
            options={{
              xAxis: { title: { text: 'Queue imbalance I' }, min: -1, max: 1 },
              yAxis: { title: { text: `Δmid over next ${horizon} ticks` } },
              tooltip: { valueDecimals: 3 },
            }}
          />
        ))}
      </Stack>
    </VisualizerCard>
  );
}
