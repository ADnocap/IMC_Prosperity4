import { Alert, Group, Loader, NumberInput, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
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

export function RealizedVolPanel({ prepared, products }: Props): ReactNode {
  const [window, setWindow] = useState<number>(500);

  const task = useMemo<(TaskInput & { kind: 'realizedVol' }) | null>(() => {
    if (prepared === null) return null;
    const p = prepared.projection;
    return {
      kind: 'realizedVol',
      input: {
        productsAllowed: products.length > 0 ? products : null,
        products: p.products,
        times: p.times,
        mids: p.mids,
        window,
      },
    };
  }, [prepared, products, window]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Realized volatility">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Realized volatility">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = prepared.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({ value: b.cumulativeOffset, color: '#868e96', dashStyle: 'Dash', width: 1 }));

  const timeSeries: Highcharts.SeriesOptionsType[] = (data ?? []).map((s, i) => ({
    type: 'line',
    name: s.product,
    data: s.timeSeries,
    color: PALETTE[i % PALETTE.length],
    lineWidth: 1,
  }));

  const subtitle = (data ?? [])
    .map(s => `${s.product} μ=${formatNumber(s.mean, 3)} · P05/50/95=${formatNumber(s.p05, 3)}/${formatNumber(s.p50, 3)}/${formatNumber(s.p95, 3)}`)
    .join(' · ');

  return (
    <VisualizerCard title={`Realized volatility${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <NumberInput
            label="Window (rows)"
            value={window}
            onChange={v => setWindow(Math.max(10, Number(v) || 500))}
            min={10}
            max={10000}
            step={100}
            w={160}
          />
        </Group>
        <Text size="sm" c="dimmed">
          Rolling stdev of tick-to-tick <Text span ff="monospace">Δmid</Text> over the selected window. Higher values
          mark volatility bursts. Flat curves indicate regime stability; spikes flag regime breaks where MM width and
          take-thresholds should widen.
        </Text>
        {data !== null && data.length === 0 ? (
          <Alert color="yellow">Not enough return samples for the chosen window.</Alert>
        ) : (
          <SimpleChart
            title="σ(Δmid) over time"
            subtitle={subtitle}
            series={timeSeries}
            options={{
              xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
              yAxis: { title: { text: 'σ' } },
              tooltip: { shared: false, valueDecimals: 3 },
            }}
          />
        )}
        {data === null && loading && (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        )}
      </Stack>
    </VisualizerCard>
  );
}
