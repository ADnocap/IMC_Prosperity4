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
  prepared: PreparedPrices | null;
  products: string[];
}

// Mark k's where we reject the RW null at 5% (M2, two-sided) so the VR line
// draws with colored points and the test-stat chart highlights its crossings.
function classify(m2p: number): 'reject' | 'keep' {
  return m2p < 0.05 ? 'reject' : 'keep';
}

export function VarianceRatioPanel({ prepared, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prepared?.availableProducts ?? []),
    [products, prepared],
  );
  const [product, setProduct] = useState<string | null>(null);
  const [maxK, setMaxK] = useState<number>(32);

  useEffect(() => {
    if (candidates.length === 0) { setProduct(null); return; }
    if (product === null || !candidates.includes(product)) setProduct(candidates[0]);
  }, [candidates, product]);

  const task = useMemo<(TaskInput & { kind: 'varianceRatio' }) | null>(() => {
    if (prepared === null || product === null) return null;
    const p = prepared.projection;
    return {
      kind: 'varianceRatio',
      input: {
        productsAllowed: [product],
        products: p.products,
        times: p.times,
        mids: p.mids,
        maxK,
      },
    };
  }, [prepared, product, maxK]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Variance-ratio (Lo-MacKinlay)">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Variance-ratio (Lo-MacKinlay)">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  const row = (data ?? []).find(r => r.product === product) ?? null;

  // Split VR points into rejected (colored) and not-rejected (gray) so the
  // chart legend doubles as a verdict at a glance.
  const vrRejected: [number, number][] = [];
  const vrKept: [number, number][] = [];
  if (row) {
    for (let i = 0; i < row.ks.length; i += 1) {
      const point: [number, number] = [row.ks[i], row.vrs[i]];
      if (classify(row.m2Pvalues[i]) === 'reject') vrRejected.push(point);
      else vrKept.push(point);
    }
  }

  const vrSeries: Highcharts.SeriesOptionsType[] = row
    ? [
      {
        type: 'line',
        name: 'VR(k)',
        data: row.ks.map((k, i) => [k, row.vrs[i]] as [number, number]),
        color: '#4c6ef5',
        lineWidth: 1,
        marker: { enabled: false },
        enableMouseTracking: true,
      },
      {
        type: 'scatter',
        name: 'reject RW (M2 p<0.05)',
        data: vrRejected,
        color: '#fa5252',
        marker: { radius: 4, symbol: 'circle' },
      },
      {
        type: 'scatter',
        name: 'cannot reject RW',
        data: vrKept,
        color: '#adb5bd',
        marker: { radius: 3, symbol: 'circle' },
      },
    ]
    : [];

  const m2Series: Highcharts.SeriesOptionsType[] = row
    ? [{
      type: 'column',
      name: 'M2',
      data: row.ks.map((k, i) => [k, row.m2s[i]] as [number, number]),
      color: '#7950f2',
      pointPadding: 0.1,
      groupPadding: 0.05,
    }]
    : [];

  // Summary verdict: take a few representative k's (power-of-2-ish) and
  // report the most significant result.
  const highlightKs = row ? [2, 4, 8, 16, 32].filter(k => row.ks.includes(k)) : [];
  const highlightBadges = row
    ? highlightKs.map(k => {
      const i = row.ks.indexOf(k);
      const vr = row.vrs[i];
      const p = row.m2Pvalues[i];
      const sig = p < 0.05;
      const direction = vr < 1 ? 'MR' : vr > 1 ? 'MO' : '·';
      return (
        <Badge key={k} variant="light" color={sig ? (vr < 1 ? 'grape' : 'orange') : 'gray'}>
          k={k} VR={formatNumber(vr, 3)} {sig ? `(${direction}, p=${p < 1e-4 ? p.toExponential(1) : formatNumber(p, 3)})` : '(RW)'}
        </Badge>
      );
    })
    : [];

  return (
    <VisualizerCard title={`Variance-ratio test${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Group>
          <Select
            label="Product"
            data={candidates}
            value={product}
            onChange={setProduct}
            w={220}
            allowDeselect={false}
            disabled={candidates.length === 0}
          />
          <NumberInput
            label="Max k"
            value={maxK}
            onChange={v => setMaxK(Math.max(2, Math.min(128, Number(v) || 32)))}
            min={2}
            max={128}
            step={2}
            w={120}
          />
        </Group>
        <Text size="sm" c="dimmed">
          <Text span ff="monospace">VR(k) = σ²_k / (k·σ²_1)</Text> compares the k-period return variance
          to k copies of the 1-period variance.{' '}
          <Text span fw={500}>VR &lt; 1</Text> ⇒ mean-reverting (MR),{' '}
          <Text span fw={500}>VR &gt; 1</Text> ⇒ momentum (MO),{' '}
          <Text span fw={500}>VR ≈ 1</Text> ⇒ random walk. M2 is the heteroskedasticity-robust
          test statistic (standard-normal under H0).
        </Text>
        {row !== null && (
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">n = {row.n.toLocaleString()}</Badge>
            {highlightBadges}
          </Group>
        )}
        {data === null ? (
          loading ? <Group><Loader size="sm" /><Text>Computing…</Text></Group> : null
        ) : row === null ? (
          <Alert color="yellow">Not enough return samples for the selected max k.</Alert>
        ) : (
          <>
            <SimpleChart
              title="VR(k) — ref line at 1 (random walk)"
              series={vrSeries}
              options={{
                xAxis: { title: { text: 'k (periods)' }, allowDecimals: false },
                yAxis: {
                  title: { text: 'VR(k)' },
                  plotLines: [{ value: 1, color: '#868e96', dashStyle: 'Dash', width: 1 }],
                },
                tooltip: { shared: false, valueDecimals: 4 },
              }}
            />
            <SimpleChart
              title="M2 statistic — ±1.96 = 5% two-sided"
              series={m2Series}
              options={{
                xAxis: { title: { text: 'k (periods)' }, allowDecimals: false },
                yAxis: {
                  title: { text: 'M2' },
                  plotLines: [
                    { value: 0, color: '#868e96', width: 1 },
                    { value: 1.96, color: '#fa5252', dashStyle: 'Dash', width: 1 },
                    { value: -1.96, color: '#fa5252', dashStyle: 'Dash', width: 1 },
                  ],
                },
                tooltip: { shared: false, valueDecimals: 3 },
              }}
            />
          </>
        )}
      </Stack>
    </VisualizerCard>
  );
}
