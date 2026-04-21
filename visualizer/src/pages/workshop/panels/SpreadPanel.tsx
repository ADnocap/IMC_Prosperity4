import { Alert, Group, Loader, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo } from 'react';
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

export function SpreadPanel({ prepared, products }: Props): ReactNode {
  const task = useMemo<(TaskInput & { kind: 'spread' }) | null>(() => {
    if (prepared === null) return null;
    const projection = prepared.projection;
    return {
      kind: 'spread',
      input: {
        productsAllowed: products.length > 0 ? products : null,
        products: projection.products,
        times: projection.times,
        bid1: projection.bid1,
        ask1: projection.ask1,
      },
    };
  }, [prepared, products]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Spread">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }

  if (error !== null) {
    return (
      <VisualizerCard title="Spread">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Spread">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">No bid/ask ladder detected — spread cannot be computed.</Alert>
        )}
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = prepared.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({ value: b.cumulativeOffset, color: '#868e96', dashStyle: 'Dash', width: 1 }));

  const subtitle = data
    .map(s =>
      `${s.product} μ=${formatNumber(s.mean, 2)} σ=${formatNumber(s.std, 2)} · P05/50/95=${formatNumber(s.p05, 1)}/${formatNumber(s.p50, 1)}/${formatNumber(s.p95, 1)}`,
    )
    .join(' · ');

  const timeSeries: Highcharts.SeriesOptionsType[] = data.map((s, i) => ({
    type: 'line',
    name: s.product,
    data: s.timeSeries,
    color: PALETTE[i % PALETTE.length],
    lineWidth: 1,
  }));

  const histSeries: Highcharts.SeriesOptionsType[] = data.map((s, i) => ({
    type: 'column',
    name: s.product,
    data: s.histogram.centers.map((c, idx) => [c, s.histogram.counts[idx]] as [number, number]),
    color: PALETTE[i % PALETTE.length],
    pointPadding: 0,
    groupPadding: 0,
  }));

  return (
    <VisualizerCard title={`Bid-Ask Spread${loading ? ' · computing…' : ''}`}>
      <SimpleChart
        title="Spread over time"
        subtitle={subtitle}
        series={timeSeries}
        options={{
          xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
          yAxis: { title: { text: 'ask1 − bid1' } },
          tooltip: { shared: false, valueDecimals: 2 },
        }}
      />
      <SimpleChart
        title="Spread distribution"
        series={histSeries}
        options={{
          xAxis: { title: { text: 'Spread' } },
          yAxis: { title: { text: 'Count' } },
          plotOptions: { column: { grouping: false } },
        }}
      />
    </VisualizerCard>
  );
}
