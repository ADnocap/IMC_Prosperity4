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

export function PairSpreadPanel({ prices, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prices?.availableProducts ?? []),
    [products, prices],
  );
  const [productA, setProductA] = useState<string | null>(null);
  const [productB, setProductB] = useState<string | null>(null);
  const [zWindow, setZWindow] = useState<number>(200);

  useEffect(() => {
    if (candidates.length < 2) { setProductA(null); setProductB(null); return; }
    if (productA === null || !candidates.includes(productA)) setProductA(candidates[0]);
    if (productB === null || !candidates.includes(productB) || productB === productA) {
      setProductB(candidates.find(p => p !== (productA ?? candidates[0])) ?? candidates[1] ?? null);
    }
  }, [candidates, productA, productB]);

  const task = useMemo<(TaskInput & { kind: 'pairSpread' }) | null>(() => {
    if (prices === null || productA === null || productB === null) return null;
    return {
      kind: 'pairSpread',
      input: {
        products: prices.projection.products,
        times: prices.projection.times,
        mids: prices.projection.mids,
        productA,
        productB,
        zWindow,
      },
    };
  }, [prices, productA, productB, zWindow]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Pair spread + z-score">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (candidates.length < 2) {
    return (
      <VisualizerCard title="Pair spread + z-score">
        <Alert color="yellow">Need at least 2 products.</Alert>
      </VisualizerCard>
    );
  }

  const spreadSeries: Highcharts.SeriesOptionsType[] = data
    ? [{ type: 'line', name: 'residual', data: data.spread, color: '#4c6ef5', lineWidth: 1 }]
    : [];
  const zSeries: Highcharts.SeriesOptionsType[] = data
    ? [{ type: 'line', name: 'z', data: data.zscore, color: '#fd7e14', lineWidth: 1 }]
    : [];

  return (
    <VisualizerCard title={`Pair spread + z-score${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <Select label="A" data={candidates} value={productA} onChange={setProductA} w={200} allowDeselect={false} />
          <Select label="B" data={candidates} value={productB} onChange={setProductB} w={200} allowDeselect={false} />
          <NumberInput label="z window (rows)" value={zWindow} onChange={v => setZWindow(Number(v) || 200)} min={10} max={5000} w={140} />
        </Group>
        <Text size="sm" c="dimmed">
          Fit <Text span ff="monospace">mid_A ≈ α + β · mid_B</Text>, then plot the residual and its rolling z-score.
          Mean reversion = stat-arb opportunity. Finite half-life ⇒ actually reverting.
        </Text>
        {data && (
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">β = {formatNumber(data.beta, 4)}</Badge>
            <Badge variant="light">α = {formatNumber(data.alpha, 2)}</Badge>
            <Badge variant="light" color={data.r2 > 0.8 ? 'teal' : 'gray'}>R² = {formatNumber(data.r2, 3)}</Badge>
            <Badge variant="light" color={data.meanReversionHalfLife !== null ? 'teal' : 'gray'}>
              half-life = {data.meanReversionHalfLife === null ? 'no MR' : `${formatNumber(data.meanReversionHalfLife, 0)} rows`}
            </Badge>
          </Group>
        )}
        {error !== null && <Alert color="red">{error.message}</Alert>}
        {data === null ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <>
            <SimpleChart
              title="Residual (spread)"
              series={spreadSeries}
              options={{
                xAxis: { title: { text: 'Cumulative tick' } },
                yAxis: { title: { text: 'residual' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              }}
            />
            <SimpleChart
              title="Rolling z-score"
              series={zSeries}
              options={{
                xAxis: { title: { text: 'Cumulative tick' } },
                yAxis: {
                  title: { text: 'z' },
                  plotLines: [
                    { value: 0, color: '#868e96', width: 1 },
                    { value: 2, color: '#fa5252', dashStyle: 'Dash', width: 1 },
                    { value: -2, color: '#fa5252', dashStyle: 'Dash', width: 1 },
                  ],
                },
              }}
            />
          </>
        )}
      </Stack>
    </VisualizerCard>
  );
}
