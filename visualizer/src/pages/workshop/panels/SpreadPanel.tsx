import { Alert, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { mean, standardDeviation, quantile } from 'simple-statistics';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ConcatenatedTable } from '../concat.ts';
import { numericValue, stringValue } from '../schema.ts';
import { formatNumber } from '../../../utils/format.ts';

interface Props {
  table: ConcatenatedTable | null;
  products: string[];
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

interface SpreadStats {
  product: string;
  count: number;
  mean: number;
  std: number;
  p05: number;
  p50: number;
  p95: number;
  series: [number, number][];
  histogram: Highcharts.SeriesOptionsType;
  timeSeries: Highcharts.SeriesOptionsType;
}

function binCounts(values: number[], bins: number): { binEdges: number[]; counts: number[] } {
  if (values.length === 0) return { binEdges: [], counts: [] };
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo === hi) return { binEdges: [lo, lo + 1], counts: [values.length] };
  const width = (hi - lo) / bins;
  const edges = Array.from({ length: bins + 1 }, (_, i) => lo + i * width);
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    let idx = Math.floor((v - lo) / width);
    if (idx === bins) idx = bins - 1;
    counts[idx] += 1;
  }
  return { binEdges: edges, counts };
}

export function SpreadPanel({ table, products }: Props): ReactNode {
  const stats = useMemo<SpreadStats[]>(() => {
    if (table === null) return [];
    const productCol = table.shape.productColumn;
    const bid1 = table.shape.ladderLevels[0]?.bidPrice ?? null;
    const ask1 = table.shape.ladderLevels[0]?.askPrice ?? null;
    if (productCol === null || bid1 === null || ask1 === null) return [];
    const timeKey = table.cumulativeKey;

    const byProduct = new Map<string, { values: number[]; series: [number, number][] }>();
    for (const row of table.rows) {
      const product = stringValue(row, productCol);
      if (product === null) continue;
      if (products.length > 0 && !products.includes(product)) continue;
      const bp = numericValue(row, bid1);
      const ap = numericValue(row, ask1);
      const t = Number(row[timeKey]);
      if (bp === null || ap === null || !Number.isFinite(t)) continue;
      const spread = ap - bp;
      if (!Number.isFinite(spread)) continue;
      let slot = byProduct.get(product);
      if (slot === undefined) {
        slot = { values: [], series: [] };
        byProduct.set(product, slot);
      }
      slot.values.push(spread);
      slot.series.push([t, spread]);
    }
    const out: SpreadStats[] = [];
    let idx = 0;
    for (const [product, { values, series }] of [...byProduct.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      if (values.length === 0) continue;
      const color = PALETTE[idx % PALETTE.length];
      idx += 1;
      const { binEdges, counts } = binCounts(values, Math.min(30, Math.max(10, Math.floor(Math.sqrt(values.length)))));
      const histData = counts.map((c, i) => [(binEdges[i] + binEdges[i + 1]) / 2, c] as [number, number]);
      out.push({
        product,
        count: values.length,
        mean: mean(values),
        std: standardDeviation(values),
        p05: quantile(values, 0.05),
        p50: quantile(values, 0.5),
        p95: quantile(values, 0.95),
        series,
        histogram: {
          type: 'column',
          name: product,
          data: histData,
          color,
          pointPadding: 0,
          groupPadding: 0,
        },
        timeSeries: {
          type: 'line',
          name: product,
          data: series,
          color,
          lineWidth: 1,
        },
      });
    }
    return out;
  }, [table, products]);

  if (table === null) {
    return (
      <VisualizerCard title="Spread">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }

  if (stats.length === 0) {
    return (
      <VisualizerCard title="Spread">
        <Alert color="yellow">No bid/ask ladder detected — spread cannot be computed.</Alert>
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
    }));

  const subtitle = stats
    .map(s =>
      `${s.product} μ=${formatNumber(s.mean, 2)} σ=${formatNumber(s.std, 2)} · P05/50/95=${formatNumber(s.p05, 1)}/${formatNumber(s.p50, 1)}/${formatNumber(s.p95, 1)}`,
    )
    .join(' · ');

  return (
    <VisualizerCard title="Bid-Ask Spread">
      <SimpleChart
        title="Spread over time"
        subtitle={subtitle}
        series={stats.map(s => s.timeSeries)}
        options={{
          xAxis: { title: { text: 'Cumulative tick' }, plotLines: dayMarkers },
          yAxis: { title: { text: 'ask1 − bid1' } },
          tooltip: { shared: false, valueDecimals: 2 },
        }}
      />
      <SimpleChart
        title="Spread distribution"
        series={stats.map(s => s.histogram)}
        options={{
          xAxis: { title: { text: 'Spread' } },
          yAxis: { title: { text: 'Count' } },
          plotOptions: { column: { grouping: false } },
        }}
      />
    </VisualizerCard>
  );
}
