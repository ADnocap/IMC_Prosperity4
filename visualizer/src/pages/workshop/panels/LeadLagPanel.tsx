import { Alert, Group, Loader, Select, Stack, Text } from '@mantine/core';
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

const MAX_LAG_STEPS = 20;

export function LeadLagPanel({ prices, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prices?.availableProducts ?? []),
    [products, prices],
  );
  const [productA, setProductA] = useState<string | null>(null);
  const [productB, setProductB] = useState<string | null>(null);

  useEffect(() => {
    if (candidates.length < 2) { setProductA(null); setProductB(null); return; }
    if (productA === null || !candidates.includes(productA)) setProductA(candidates[0]);
    if (productB === null || !candidates.includes(productB) || productB === productA) {
      setProductB(candidates.find(p => p !== (productA ?? candidates[0])) ?? candidates[1] ?? null);
    }
  }, [candidates, productA, productB]);

  const task = useMemo<(TaskInput & { kind: 'leadLag' }) | null>(() => {
    if (prices === null || productA === null || productB === null) return null;
    return {
      kind: 'leadLag',
      input: {
        products: prices.projection.products,
        times: prices.projection.times,
        mids: prices.projection.mids,
        productA,
        productB,
        maxLagSteps: MAX_LAG_STEPS,
        stepTimestamp: 100,
      },
    };
  }, [prices, productA, productB]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Lead-lag cross-correlation">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (candidates.length < 2) {
    return (
      <VisualizerCard title="Lead-lag cross-correlation">
        <Alert color="yellow">Need at least 2 products.</Alert>
      </VisualizerCard>
    );
  }

  const series: Highcharts.SeriesOptionsType[] = data
    ? [
        {
          type: 'column',
          name: 'corr',
          data: data.lags.map((l, i) => [l, data.correlations[i]] as [number, number]),
          color: '#4c6ef5',
          pointPadding: 0,
          groupPadding: 0,
        },
      ]
    : [];

  return (
    <VisualizerCard title={`Lead-lag CCF${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <Select label="A" data={candidates} value={productA} onChange={setProductA} w={220} allowDeselect={false} />
          <Select label="B" data={candidates} value={productB} onChange={setProductB} w={220} allowDeselect={false} />
        </Group>
        <Text size="sm" c="dimmed">
          <Text span ff="monospace">corr(Δ{productA ?? 'A'}_t, Δ{productB ?? 'B'}_{`{t+lag}`})</Text> over the overlapping series.
          Positive lag on the x-axis ⇒ A leads B. The tallest bar is the most-useful lead/lag relationship.
          {data && (
            <> Best lag: <Text span fw={600}>{data.bestLag}</Text> steps · corr <Text span fw={600}>{formatNumber(data.bestCorr, 3)}</Text></>
          )}
        </Text>
        {error !== null && <Alert color="red">{error.message}</Alert>}
        {data === null ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <SimpleChart
            title=""
            series={series}
            options={{
              xAxis: {
                title: { text: 'lag (steps)' },
                plotLines: [{ value: 0, color: '#868e96', width: 1 }],
              },
              yAxis: {
                title: { text: 'correlation' },
                plotLines: [{ value: 0, color: '#868e96', width: 1 }],
              },
              plotOptions: { column: { grouping: false } },
            }}
          />
        )}
      </Stack>
    </VisualizerCard>
  );
}
