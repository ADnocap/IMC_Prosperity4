import { Alert, Group, Loader, SegmentedControl, Stack, Table, Text } from '@mantine/core';
import { ReactNode, useMemo, useState } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { ConcatenatedTable } from '../concat.ts';
import { numericValue } from '../schema.ts';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prices: PreparedPrices | null;
  observations: ConcatenatedTable | null;
  products: string[];
}

const LAGS = [100, 500, 1000, 5000];

export function ObsBetaPanel({ prices, observations, products }: Props): ReactNode {
  const [lag, setLag] = useState<number>(500);

  const obsProjection = useMemo(() => {
    if (observations === null) return null;
    const timeKey = observations.cumulativeKey;
    const numericCols = observations.shape.columns
      .filter(col => col.kind === 'numeric' && col.name !== timeKey);
    if (numericCols.length === 0) return null;
    const n = observations.rows.length;
    const times = new Float64Array(n);
    const columns = numericCols.map(col => ({ name: col.name, values: new Float64Array(n) }));
    for (let i = 0; i < n; i += 1) {
      const t = Number(observations.rows[i][timeKey]);
      times[i] = Number.isFinite(t) ? t : Number.NaN;
      columns.forEach((c, j) => {
        const v = numericValue(observations.rows[i], numericCols[j].name);
        c.values[i] = v === null ? Number.NaN : v;
      });
    }
    return { times, columns };
  }, [observations]);

  const task = useMemo<(TaskInput & { kind: 'obsBeta' }) | null>(() => {
    if (prices === null || obsProjection === null) return null;
    return {
      kind: 'obsBeta',
      input: {
        obsTimes: obsProjection.times,
        obsColumns: obsProjection.columns,
        priceTimes: prices.projection.times,
        priceProducts: prices.projection.products,
        priceMids: prices.projection.mids,
        lagTimestamp: lag,
        productsAllowed: products.length > 0 ? products : null,
      },
    };
  }, [prices, obsProjection, products, lag]);

  const { data, loading, error } = useCompute(task);

  if (prices === null) {
    return (
      <VisualizerCard title="Observation → product return β">
        <Text c="dimmed" size="sm">Load prices to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (obsProjection === null) {
    return (
      <VisualizerCard title="Observation → product return β">
        <Alert color="yellow">No numeric observation columns found for this round.</Alert>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Observation → product return β">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null) {
    return (
      <VisualizerCard title="Observation → product return β">
        <Group><Loader size="sm" /><Text>Computing βs…</Text></Group>
      </VisualizerCard>
    );
  }
  if (data.length === 0) {
    return (
      <VisualizerCard title="Observation → product return β">
        <Alert color="yellow">No overlapping observation × price samples at this lag.</Alert>
      </VisualizerCard>
    );
  }

  const sorted = [...data].sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation));

  return (
    <VisualizerCard title={`Observation → product return β${loading ? ' · refreshing…' : ''}`}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            OLS <Text span ff="monospace">Δmid_{`{t+lag}`} = α + β · obs_t</Text> per (observation × product). Sorted by |corr|.
            Large |β| with high R² = exogenous driver you can trade on.
          </Text>
          <SegmentedControl
            size="xs"
            value={String(lag)}
            onChange={v => setLag(Number(v))}
            data={LAGS.map(l => ({ label: `lag ${l / 100}t`, value: String(l) }))}
          />
        </Group>
        <Table striped withTableBorder withColumnBorders stickyHeader>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Observation</Table.Th>
              <Table.Th>Product</Table.Th>
              <Table.Th>n</Table.Th>
              <Table.Th>β</Table.Th>
              <Table.Th>corr</Table.Th>
              <Table.Th>R²</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sorted.map(row => (
              <Table.Tr key={`${row.observation}-${row.product}`}>
                <Table.Td>{row.observation}</Table.Td>
                <Table.Td>{row.product}</Table.Td>
                <Table.Td>{row.n}</Table.Td>
                <Table.Td>{formatNumber(row.beta, 5)}</Table.Td>
                <Table.Td>{formatNumber(row.correlation, 3)}</Table.Td>
                <Table.Td>{formatNumber(row.r2, 3)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </VisualizerCard>
  );
}
