import { Alert, Group, Loader, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import HighchartsHeatmap from 'highcharts/modules/heatmap';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

// Register the heatmap module at module load. Doing this in useEffect runs
// AFTER the first render, so the first chart mounts with the heatmap type
// unregistered and falls back silently (cells take the plot background).
HighchartsHeatmap(Highcharts);

interface Props {
  prices: PreparedPrices | null;
  products: string[];
}

export function CorrMatrixPanel({ prices, products }: Props): ReactNode {

  const task = useMemo<(TaskInput & { kind: 'corrMatrix' }) | null>(() => {
    if (prices === null) return null;
    return {
      kind: 'corrMatrix',
      input: {
        products: prices.projection.products,
        times: prices.projection.times,
        mids: prices.projection.mids,
        productsAllowed: products.length > 0 ? products : null,
        returnHorizon: 1,
      },
    };
  }, [prices, products]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Return correlation matrix">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Return correlation matrix">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null || data.labels.length < 2) {
    return (
      <VisualizerCard title="Return correlation matrix">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing correlations…</Text></Group>
        ) : (
          <Alert color="yellow">Need at least 2 products.</Alert>
        )}
      </VisualizerCard>
    );
  }

  const n = data.labels.length;
  const points: Array<{ x: number; y: number; value: number | null; n: number }> = [];
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const raw = data.matrix[i * n + j];
      const sampleN = data.n[i * n + j] ?? 0;
      const value = Number.isFinite(raw) && sampleN > 0 ? raw : null;
      points.push({ x: i, y: j, value, n: sampleN });
    }
  }

  const series: Highcharts.SeriesOptionsType[] = [
    {
      type: 'heatmap',
      name: 'corr',
      data: points,
      nullColor: '#343a40',
      borderColor: '#1a1b1e',
      borderWidth: 1,
      // Heatmap cells are drawn as rects by Highcharts, but the shared
      // SimpleChart default `plotOptions.series.marker.enabled: false` also
      // suppresses the per-cell "point" rendering that heatmaps inherit.
      // Explicitly re-enable and opt out of the hover-only inactive dimming.
      marker: { enabled: true },
      states: {
        inactive: { enabled: false, opacity: 1 },
        hover: { brightness: 0.15 },
      },
      opacity: 1,
      dataLabels: {
        enabled: n <= 12,
        color: '#000',
        formatter: function () {
          const v = this.point.value;
          if (v === null || v === undefined) return '';
          return formatNumber(Number(v), 2);
        },
      },
    },
  ];

  return (
    <VisualizerCard title={`Return correlation matrix${loading ? ' · refreshing…' : ''}`}>
      <Text size="sm" c="dimmed" mb="xs">
        Per-timestamp tick-to-tick return correlation. Red = positively correlated (co-move),
        blue = negatively correlated (diverge). Useful for stat-arb scoping.
      </Text>
      <SimpleChart
        title=""
        series={series}
        options={{
          chart: { type: 'heatmap', height: Math.max(420, 60 + n * 28) },
          boost: { enabled: false },
          plotOptions: {
            series: {
              // SimpleChart's global defaults disable markers and dim inactive
              // series for scatter/line. Undo those here so heatmap cells paint
              // on first render, not only on hover.
              marker: { enabled: true },
              states: { inactive: { enabled: false, opacity: 1 } },
              boostThreshold: 0,
            },
            heatmap: {
              borderColor: '#1a1b1e',
              borderWidth: 1,
              states: {
                inactive: { enabled: false, opacity: 1 },
                hover: { brightness: 0.15 },
              },
            },
          },
          xAxis: {
            categories: data.labels,
            title: { text: null },
            // SimpleChart's default axis label formatter coerces via Number(),
            // which produces "NaN" for category strings. Passthrough here.
            labels: {
              formatter: function () { return String(this.value); },
              rotation: -45,
              style: { fontSize: '11px' },
            },
          },
          yAxis: {
            categories: data.labels,
            title: { text: null },
            reversed: true,
            labels: {
              formatter: function () { return String(this.value); },
              style: { fontSize: '11px' },
            },
          },
          colorAxis: {
            min: -1, max: 1,
            stops: [
              [0, '#1c7ed6'],
              [0.5, '#f8f9fa'],
              [1, '#fa5252'],
            ],
          },
          legend: { align: 'right', layout: 'vertical', verticalAlign: 'middle' },
          tooltip: {
            formatter: function () {
              const p = this.point as unknown as { x: number; y: number; value: number | null; n: number };
              const xLabel = data.labels[p.x] ?? p.x;
              const yLabel = data.labels[p.y] ?? p.y;
              const corr = p.value === null ? 'no overlap' : formatNumber(Number(p.value), 3);
              return `<b>${xLabel} × ${yLabel}</b><br/>corr: ${corr}<br/>n: ${p.n}`;
            },
            useHTML: true,
          },
        }}
      />
    </VisualizerCard>
  );
}
