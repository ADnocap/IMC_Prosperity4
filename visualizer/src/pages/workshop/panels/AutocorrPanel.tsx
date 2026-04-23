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

export function AutocorrPanel({ prepared, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prepared?.availableProducts ?? []),
    [products, prepared],
  );
  const [product, setProduct] = useState<string | null>(null);
  const [maxLag, setMaxLag] = useState<number>(20);

  useEffect(() => {
    if (candidates.length === 0) { setProduct(null); return; }
    if (product === null || !candidates.includes(product)) setProduct(candidates[0]);
  }, [candidates, product]);

  const task = useMemo<(TaskInput & { kind: 'autocorr' }) | null>(() => {
    if (prepared === null || product === null) return null;
    const p = prepared.projection;
    return {
      kind: 'autocorr',
      input: {
        productsAllowed: [product],
        products: p.products,
        times: p.times,
        mids: p.mids,
        maxLag,
      },
    };
  }, [prepared, product, maxLag]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Return autocorrelation (Ljung-Box)">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Return autocorrelation (Ljung-Box)">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }

  const row = (data ?? []).find(r => r.product === product) ?? null;
  const barSeries: Highcharts.SeriesOptionsType[] = row
    ? [{
      type: 'column',
      name: 'ACF',
      data: row.lags.map((k, i) => [k, row.acf[i]] as [number, number]),
      color: '#4c6ef5',
      pointPadding: 0.15,
      groupPadding: 0.05,
    }]
    : [];

  const ciPlotLines: Highcharts.YAxisPlotLinesOptions[] = row
    ? [
      { value: row.ciUpper, color: '#fa5252', dashStyle: 'Dash', width: 1 },
      { value: row.ciLower, color: '#fa5252', dashStyle: 'Dash', width: 1 },
      { value: 0, color: '#868e96', width: 1 },
    ]
    : [{ value: 0, color: '#868e96', width: 1 }];

  const reject = row !== null && row.ljungBoxP < 0.05;

  return (
    <VisualizerCard title={`Return autocorrelation${loading ? ' · computing…' : ''}`}>
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
            label="Max lag"
            value={maxLag}
            onChange={v => setMaxLag(Math.max(1, Number(v) || 20))}
            min={1}
            max={200}
            w={120}
          />
        </Group>
        <Text size="sm" c="dimmed">
          ACF of tick returns <Text span ff="monospace">r_t = Δmid</Text> with Bartlett 95% band
          <Text span ff="monospace"> ±1.96/√n</Text>. Ljung-Box Q tests the joint null
          "no autocorrelation at any lag ≤ max_lag" (χ² under the null).
          Reject ⇒ returns carry serial structure an MR/momentum signal may exploit.
        </Text>
        {row !== null && (
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">n = {row.n.toLocaleString()}</Badge>
            <Badge variant="light">Q = {formatNumber(row.ljungBoxQ, 2)}</Badge>
            <Badge variant="light" color={reject ? 'teal' : 'gray'}>
              p = {row.ljungBoxP < 1e-4 ? row.ljungBoxP.toExponential(2) : formatNumber(row.ljungBoxP, 4)}
            </Badge>
            <Badge variant="light" color={reject ? 'teal' : 'gray'}>
              {reject ? 'reject iid' : 'cannot reject iid'}
            </Badge>
          </Group>
        )}
        {data === null ? (
          loading ? <Group><Loader size="sm" /><Text>Computing…</Text></Group> : null
        ) : row === null ? (
          <Alert color="yellow">Not enough samples to compute ACF.</Alert>
        ) : (
          <SimpleChart
            title="ACF by lag"
            series={barSeries}
            options={{
              xAxis: { title: { text: 'Lag k' }, allowDecimals: false },
              yAxis: { title: { text: 'ρ(k)' }, plotLines: ciPlotLines },
              tooltip: { shared: false, valueDecimals: 4 },
            }}
          />
        )}
      </Stack>
    </VisualizerCard>
  );
}
