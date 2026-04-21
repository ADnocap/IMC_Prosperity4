import { Alert, Group, Loader, SegmentedControl, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prepared: PreparedPrices | null;
  products: string[];
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

export function MidPricePanel({ prepared, products }: Props): ReactNode {
  const [mode, setMode] = useState<'mid' | 'microprice' | 'both'>('both');

  const task = useMemo<(TaskInput & { kind: 'mid' }) | null>(() => {
    if (prepared === null) return null;
    const projection = prepared.projection;
    return {
      kind: 'mid',
      input: {
        productsAllowed: products.length > 0 ? products : null,
        products: projection.products,
        times: projection.times,
        mids: projection.mids,
        bid1: projection.bid1,
        ask1: projection.ask1,
        bidVol1: projection.bidVol1,
        askVol1: projection.askVol1,
      },
    };
  }, [prepared, products]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Mid / Microprice">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }

  if (error !== null) {
    return (
      <VisualizerCard title="Mid / Microprice">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Mid / Microprice">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">No mid-price data found for the selected products.</Alert>
        )}
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = prepared.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({
      value: b.cumulativeOffset,
      color: '#868e96',
      dashStyle: 'Dash',
      width: 1,
      label: { text: `day ${b.day}`, style: { color: '#868e96', fontSize: '10px' } },
    }));

  const series: Highcharts.SeriesOptionsType[] = [];
  data.forEach((s, idx) => {
    const color = PALETTE[idx % PALETTE.length];
    if (mode !== 'microprice') {
      series.push({ type: 'line', name: `${s.product} mid`, data: s.midPoints, color, lineWidth: 1.5 });
    }
    if (mode !== 'mid' && s.microPoints.length > 0) {
      series.push({
        type: 'line',
        name: `${s.product} microprice`,
        data: s.microPoints,
        color,
        lineWidth: 1,
        dashStyle: 'ShortDash',
      });
    }
  });

  return (
    <VisualizerCard title={`Mid / Microprice${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group justify="flex-end">
          <SegmentedControl
            size="xs"
            value={mode}
            onChange={value => setMode(value as 'mid' | 'microprice' | 'both')}
            data={[
              { label: 'Mid', value: 'mid' },
              { label: 'Micro', value: 'microprice' },
              { label: 'Both', value: 'both' },
            ]}
          />
        </Group>
        <SimpleChart
          title=""
          subtitle="Microprice = (bid × askVol + ask × bidVol) / (bidVol + askVol). Dashed line."
          series={series}
          options={{
            xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
            yAxis: { title: { text: 'Price' } },
            tooltip: { shared: true, valueDecimals: 2 },
          }}
        />
      </Stack>
    </VisualizerCard>
  );
}
