import { Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Table, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { Stage1Result } from '../stages/layer_detection';
import { runStage3, Stage3Result, VolumeLayerModel, VolumeSideModel } from '../stages/volume_model';

interface Props {
  data: FvAndBook;
  stage1: Stage1Result | null;
  result: Stage3Result | null;
  onRun: (r: Stage3Result) => void;
  onAccept: () => void;
}

export function VolumeModelPanel({ data, stage1, result, onRun, onAccept }: Props): ReactNode {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!stage1) {
    return <Alert color="yellow" title="Run Stage 1 first">Layer bands are required for volume conditioning.</Alert>;
  }

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try { onRun(await runStage3(data, stage1.layers)); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 3 — Volume Model</Text>
          <Text size="xs" c="dimmed">
            χ² uniform fit per bot · side-tie binomial test · vol | offset conditional check.
          </Text>
        </Stack>
        <Group>
          <Button onClick={handleRun} variant={result ? 'light' : 'filled'} disabled={busy}>
            {busy ? <Loader size="xs" /> : result ? 'Re-run' : 'Run'}
          </Button>
          {result && <Button onClick={onAccept} color="green" disabled={busy}>Accept & continue</Button>}
        </Group>
      </Group>
      {err && <Alert color="red" title="Compute failed">{err}</Alert>}
      {result?.layers.map(L => <VolumeLayerCard key={L.layer_id} layer={L} />)}
    </Stack>
  );
}

function VolumeLayerCard({ layer }: { layer: VolumeLayerModel }): ReactNode {
  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group>
          <Text fw={600}>{layer.layer_name}</Text>
          <Badge color={layer.sides_tied_p < 0.01 ? 'grape' : 'gray'} variant="light">
            sides tied {(layer.sides_tied_rate * 100).toFixed(1)}% (z-test p={fmt(layer.sides_tied_p)})
          </Badge>
          <Text size="xs" c="dimmed">n both-sided = {layer.sides_tied_n}</Text>
        </Group>
        <Grid gutter="md">
          <Grid.Col span={6}>
            <VolumeSideCard title="Bid" model={layer.bid} />
          </Grid.Col>
          <Grid.Col span={6}>
            <VolumeSideCard title="Ask" model={layer.ask} />
          </Grid.Col>
        </Grid>
      </Stack>
    </Card>
  );
}

function VolumeSideCard({ title, model }: { title: string; model: VolumeSideModel }): ReactNode {
  const histSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const lo = model.min;
    const obs: [number, number][] = model.uniform.observed.map((c, i) => [lo + i, c]);
    const exp: [number, number][] = model.uniform.expected.map((e, i) => [lo + i, e]);
    return [
      { type: 'column', name: 'observed', data: obs, color: '#4c6ef5' },
      { type: 'line',   name: 'expected (uniform)', data: exp, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, lineWidth: 1.5, marker: { enabled: false } },
    ];
  }, [model]);

  const pass = model.uniform.p_value > 0.05;
  return (
    <Stack gap="xs">
      <Group gap="sm">
        <Text size="sm" fw={600}>{title}</Text>
        <Badge color={pass ? 'green' : 'red'}>
          χ² vs U({model.min},{model.max}) p={fmt(model.uniform.p_value)}
        </Badge>
        <Text size="xs" c="dimmed">n={model.n}, mean={model.mean.toFixed(2)}</Text>
      </Group>
      <SimpleChart
        title={`${title} volume histogram`}
        series={histSeries}
        options={{
          chart: { height: 200 },
          xAxis: { title: { text: 'volume' }, tickInterval: 1 },
          yAxis: { title: { text: 'count' } },
          legend: { enabled: true },
        }}
      />
      {model.byOffset.length > 1 && (
        <Table fz="xs" striped withTableBorder>
          <Table.Thead>
            <Table.Tr><Table.Th>offset</Table.Th><Table.Th>n</Table.Th><Table.Th>mean vol</Table.Th><Table.Th>vol|offset p</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {model.byOffset.map(row => (
              <Table.Tr key={row.offset}>
                <Table.Td>{row.offset >= 0 ? '+' : ''}{row.offset}</Table.Td>
                <Table.Td>{row.n}</Table.Td>
                <Table.Td>{row.mean.toFixed(2)}</Table.Td>
                <Table.Td>{Number.isFinite(row.p_uniform) ? (
                  <Badge size="xs" color={row.p_uniform > 0.05 ? 'green' : 'red'}>{fmt(row.p_uniform)}</Badge>
                ) : '—'}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function fmt(p: number): string {
  if (!Number.isFinite(p)) return '—';
  if (p < 1e-4) return '< 1e-4';
  return p.toFixed(4);
}
