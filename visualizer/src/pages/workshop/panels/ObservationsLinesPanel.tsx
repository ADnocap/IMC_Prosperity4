import { Alert, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ConcatenatedTable } from '../concat.ts';
import { numericValue } from '../schema.ts';

interface Props {
  table: ConcatenatedTable | null;
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

export function ObservationsLinesPanel({ table }: Props): ReactNode {
  const panels = useMemo(() => {
    if (table === null) return [];
    const timeKey = table.cumulativeKey;
    const numericCols = table.shape.columns
      .filter(col => col.kind === 'numeric')
      .map(col => col.name)
      .filter(name => name !== timeKey);
    return numericCols.map((name, idx) => {
      const color = PALETTE[idx % PALETTE.length];
      const data: [number, number][] = [];
      for (const row of table.rows) {
        const t = Number(row[timeKey]);
        const v = numericValue(row, name);
        if (!Number.isFinite(t) || v === null) continue;
        data.push([t, v]);
      }
      return { name, color, data };
    });
  }, [table]);

  if (table === null) {
    return (
      <VisualizerCard title="Observation time series">
        <Text c="dimmed" size="sm">Load an observations file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (panels.length === 0) {
    return (
      <VisualizerCard title="Observation time series">
        <Alert color="yellow">No numeric columns detected.</Alert>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Observation time series · ${panels.length} columns`}>
      <Stack gap="sm">
        {panels.map(p => {
          const series: Highcharts.SeriesOptionsType[] = [
            { type: 'line', name: p.name, data: p.data, color: p.color, lineWidth: 1 },
          ];
          return (
            <SimpleChart
              key={p.name}
              title={p.name}
              series={series}
              options={{
                chart: { height: 260 },
                xAxis: { title: { text: 'Cumulative tick' } },
                yAxis: { title: { text: p.name } },
              }}
            />
          );
        })}
      </Stack>
    </VisualizerCard>
  );
}
