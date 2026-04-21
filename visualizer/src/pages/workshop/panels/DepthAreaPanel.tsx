import { Alert, Group, Loader, Select, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prepared: PreparedPrices | null;
  products: string[];
}

const BID_COLORS = ['#1c7ed6', '#339af0', '#74c0fc'];
const ASK_COLORS = ['#e03131', '#ff6b6b', '#ffa8a8'];

export function DepthAreaPanel({ prepared, products }: Props): ReactNode {
  const candidates = useMemo(
    () => (products.length > 0 ? products : prepared?.availableProducts ?? []),
    [products, prepared],
  );
  const [product, setProduct] = useState<string | null>(null);

  useEffect(() => {
    if (candidates.length === 0) {
      if (product !== null) setProduct(null);
      return;
    }
    if (product === null || !candidates.includes(product)) {
      setProduct(candidates[0]);
    }
  }, [candidates, product]);

  const task = useMemo<(TaskInput & { kind: 'depth' }) | null>(() => {
    if (product === null || prepared === null || !prepared.hasLadder) return null;
    const projection = prepared.projection;
    return {
      kind: 'depth',
      input: {
        productFilter: product,
        products: projection.products,
        times: projection.times,
        ladder: projection.ladder,
        maxPoints: 3000,
      },
    };
  }, [prepared, product]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Book depth (stacked)">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (!prepared.hasLadder) {
    return (
      <VisualizerCard title="Book depth (stacked)">
        <Alert color="yellow">No bid/ask ladder detected in this file.</Alert>
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = prepared.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({ value: b.cumulativeOffset, color: '#868e96', dashStyle: 'Dash', width: 1 }));

  // Render deeper levels first so L1 sits on top of the stack.
  const series: Highcharts.SeriesOptionsType[] = [];
  if (data !== null) {
    const levels = [...data].sort((a, b) => b.level - a.level);
    for (const level of levels) {
      const bidColor = BID_COLORS[level.level - 1] ?? BID_COLORS[BID_COLORS.length - 1];
      const askColor = ASK_COLORS[level.level - 1] ?? ASK_COLORS[ASK_COLORS.length - 1];
      if (level.bidPoints.length > 0) {
        series.push({
          type: 'areaspline',
          name: `bid L${level.level}`,
          data: level.bidPoints,
          color: bidColor,
          fillOpacity: 0.5,
          lineWidth: 0.5,
          stack: 'bid',
        });
      }
      if (level.askPoints.length > 0) {
        series.push({
          type: 'areaspline',
          name: `ask L${level.level}`,
          data: level.askPoints,
          color: askColor,
          fillOpacity: 0.5,
          lineWidth: 0.5,
          stack: 'ask',
        });
      }
    }
  }

  return (
    <VisualizerCard title={`Book depth (stacked)${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Select
          w={260}
          label="Product"
          data={candidates}
          value={product}
          onChange={setProduct}
          allowDeselect={false}
        />
        {error !== null ? (
          <Alert color="red">{error.message}</Alert>
        ) : series.length === 0 ? (
          loading ? (
            <Group><Loader size="sm" /><Text>Computing…</Text></Group>
          ) : (
            <Alert color="yellow">No volume data for {product}.</Alert>
          )
        ) : (
          <SimpleChart
            title=""
            subtitle="Bid levels below zero (blue), ask levels above (red). Shade depth = level (dark = L1)."
            series={series}
            options={{
              chart: { type: 'areaspline' },
              plotOptions: { areaspline: { stacking: 'normal', marker: { enabled: false } } },
              xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
              yAxis: { title: { text: 'Signed volume' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              tooltip: { shared: false, valueDecimals: 0 },
            }}
          />
        )}
      </Stack>
    </VisualizerCard>
  );
}
