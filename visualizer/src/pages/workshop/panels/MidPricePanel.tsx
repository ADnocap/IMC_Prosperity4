import { Alert, Group, SegmentedControl, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ConcatenatedTable } from '../concat.ts';
import { numericValue, stringValue } from '../schema.ts';

interface Props {
  table: ConcatenatedTable | null;
  products: string[];
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

interface ProductSeries {
  product: string;
  midPoints: [number, number][];
  microPoints: [number, number][];
}

export function MidPricePanel({ table, products }: Props): ReactNode {
  const [mode, setMode] = useState<'mid' | 'microprice' | 'both'>('both');

  const series = useMemo<ProductSeries[]>(() => {
    if (table === null || table.shape.productColumn === null) return [];
    const bid1 = table.shape.ladderLevels[0]?.bidPrice ?? null;
    const ask1 = table.shape.ladderLevels[0]?.askPrice ?? null;
    const bid1v = table.shape.ladderLevels[0]?.bidVolume ?? null;
    const ask1v = table.shape.ladderLevels[0]?.askVolume ?? null;
    const midCol = table.shape.midColumn;
    const timeKey = table.cumulativeKey;
    const productCol = table.shape.productColumn;

    const byProduct = new Map<string, ProductSeries>();
    for (const row of table.rows) {
      const product = stringValue(row, productCol);
      if (product === null) continue;
      if (products.length > 0 && !products.includes(product)) continue;
      let slot = byProduct.get(product);
      if (slot === undefined) {
        slot = { product, midPoints: [], microPoints: [] };
        byProduct.set(product, slot);
      }
      const t = Number(row[timeKey]);
      if (!Number.isFinite(t)) continue;
      const mid = numericValue(row, midCol);
      if (mid !== null) slot.midPoints.push([t, mid]);

      if (bid1 !== null && ask1 !== null && bid1v !== null && ask1v !== null) {
        const bp = numericValue(row, bid1);
        const ap = numericValue(row, ask1);
        const bv = numericValue(row, bid1v);
        const av = numericValue(row, ask1v);
        if (bp !== null && ap !== null && bv !== null && av !== null && bv + av > 0) {
          const microprice = (bp * av + ap * bv) / (bv + av);
          slot.microPoints.push([t, microprice]);
        }
      }
    }
    return [...byProduct.values()].sort((a, b) => a.product.localeCompare(b.product));
  }, [table, products]);

  if (table === null) {
    return (
      <VisualizerCard title="Mid / Microprice">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }

  if (series.length === 0) {
    return (
      <VisualizerCard title="Mid / Microprice">
        <Alert color="yellow">No mid-price data found for the selected products.</Alert>
      </VisualizerCard>
    );
  }

  const dayMarkers: Highcharts.XAxisPlotLinesOptions[] = table.dayBoundaries
    .filter((_, i) => i > 0)
    .map(b => ({
      value: b.cumulativeOffset,
      color: '#868e96',
      dashStyle: 'Dash',
      width: 1,
      label: { text: `day ${b.day}`, style: { color: '#868e96', fontSize: '10px' } },
    }));

  const chartSeries: Highcharts.SeriesOptionsType[] = [];
  series.forEach((s, idx) => {
    const color = PALETTE[idx % PALETTE.length];
    if (mode !== 'microprice') {
      chartSeries.push({
        type: 'line',
        name: `${s.product} mid`,
        data: s.midPoints,
        color,
        lineWidth: 1.5,
      });
    }
    if (mode !== 'mid' && s.microPoints.length > 0) {
      chartSeries.push({
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
    <VisualizerCard title="Mid / Microprice">
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
          series={chartSeries}
          options={{
            xAxis: {
              title: { text: 'Cumulative tick' },
              plotLines: dayMarkers,
            },
            yAxis: { title: { text: 'Price' } },
            tooltip: { shared: true, valueDecimals: 2 },
          }}
        />
      </Stack>
    </VisualizerCard>
  );
}
