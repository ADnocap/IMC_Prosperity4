import { Alert, Badge, Group, Loader, NumberInput, Select, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prices: PreparedPrices | null;
  products: string[];
}

export function RollingBetaPanel({ prices, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prices?.availableProducts ?? []),
    [products, prices],
  );
  const [productA, setProductA] = useState<string | null>(null);
  const [productB, setProductB] = useState<string | null>(null);
  const [window, setWindow] = useState<number>(500);

  useEffect(() => {
    if (candidates.length < 2) { setProductA(null); setProductB(null); return; }
    if (productA === null || !candidates.includes(productA)) setProductA(candidates[0]);
    if (productB === null || !candidates.includes(productB) || productB === productA) {
      setProductB(candidates.find(p => p !== (productA ?? candidates[0])) ?? candidates[1] ?? null);
    }
  }, [candidates, productA, productB]);

  const task = useMemo<(TaskInput & { kind: 'rollingBeta' }) | null>(() => {
    if (prices === null || productA === null || productB === null) return null;
    return {
      kind: 'rollingBeta',
      input: {
        products: prices.projection.products,
        times: prices.projection.times,
        mids: prices.projection.mids,
        productA,
        productB,
        window,
      },
    };
  }, [prices, productA, productB, window]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Rolling β">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (candidates.length < 2) {
    return (
      <VisualizerCard title="Rolling β">
        <Alert color="yellow">Need at least 2 products.</Alert>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Rolling β">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = prices.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({ value: b.cumulativeOffset, color: '#868e96', dashStyle: 'Dash', width: 1 }));

  const betaSeries: Highcharts.SeriesOptionsType[] = data
    ? [{ type: 'line', name: 'β', data: data.betaSeries, color: '#4c6ef5', lineWidth: 1 }]
    : [];
  const r2Series: Highcharts.SeriesOptionsType[] = data
    ? [{ type: 'line', name: 'R²', data: data.r2Series, color: '#12b886', lineWidth: 1 }]
    : [];

  return (
    <VisualizerCard title={`Rolling β${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <Select label="A" data={candidates} value={productA} onChange={setProductA} w={200} allowDeselect={false} />
          <Select label="B" data={candidates} value={productB} onChange={setProductB} w={200} allowDeselect={false} />
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
          Rolling OLS slope of <Text span ff="monospace">returnsA = β · returnsB</Text> over the window,
          plus rolling R². Stable β ⇒ persistent hedge ratio. β drift flags regime change or structural shift.
          R² measures co-movement strength inside the window.
        </Text>
        {data !== null && (
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">full-sample β = {formatNumber(data.fullBeta, 4)}</Badge>
            <Badge variant="light" color={data.fullR2 > 0.5 ? 'teal' : 'gray'}>
              full-sample R² = {formatNumber(data.fullR2, 3)}
            </Badge>
            <Badge variant="light">n returns = {data.n.toLocaleString()}</Badge>
          </Group>
        )}
        {data === null ? (
          loading ? <Group><Loader size="sm" /><Text>Computing…</Text></Group> : null
        ) : data.betaSeries.length === 0 ? (
          <Alert color="yellow">Not enough aligned timestamps for the chosen window.</Alert>
        ) : (
          <>
            <SimpleChart
              title="β over time"
              series={betaSeries}
              options={{
                xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
                yAxis: { title: { text: 'β' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
                tooltip: { shared: false, valueDecimals: 4 },
              }}
            />
            <SimpleChart
              title="Rolling R²"
              series={r2Series}
              options={{
                xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
                yAxis: { title: { text: 'R²' }, min: 0, max: 1 },
                tooltip: { shared: false, valueDecimals: 3 },
              }}
            />
          </>
        )}
      </Stack>
    </VisualizerCard>
  );
}
