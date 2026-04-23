import { Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { Stage1Result } from '../stages/layer_detection';
import { runStage5, Stage5Result } from '../stages/noise_layer';

interface Props {
  data: FvAndBook;
  stage1: Stage1Result | null;
  result: Stage5Result | null;
  onRun: (r: Stage5Result) => void;
  onAccept: () => void;
}

export function NoiseLayerPanel({ data, stage1, result, onRun, onAccept }: Props): ReactNode {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!stage1) return <Alert color="yellow" title="Run Stage 1 first">Layer detection output is required.</Alert>;

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try { onRun(await runStage5(data, stage1)); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 5 — Noise Layer</Text>
          <Text size="xs" c="dimmed">
            Characterise quotes that fell outside the detected main clusters. Offsets, crossing/passive split, vol conditional, run-length.
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
      {result && <NoiseView result={result} />}
    </Stack>
  );
}

function NoiseView({ result }: { result: Stage5Result }): ReactNode {
  const s = result.stats;

  const offsetSeriesClean = useMemo<Highcharts.SeriesOptionsType[]>(
    () => [{ type: 'column', name: 'count', data: s.offset_hist.map(r => [r.offset, r.count] as [number, number]), color: '#fd7e14' }],
    [s.offset_hist],
  );

  const volSeries = (vs: typeof s.crossing_vol, color: string): Highcharts.SeriesOptionsType[] => {
    if (!vs) return [];
    return [
      { type: 'column', name: 'observed', data: vs.observed.map((c, i) => [i, c] as [number, number]), color },
      { type: 'line',   name: 'expected', data: vs.expected.map((e, i) => [i, e] as [number, number]), color: '#adb5bd', dashStyle: 'Dash' as Highcharts.DashStyleValue },
    ];
  };

  return (
    <Stack gap="md">
      <Card withBorder padding="sm">
        <Group gap="md">
          <Badge size="lg" color="orange" variant="light">
            {s.n_events} events ({(s.presence_rate * 100).toFixed(1)}% of ticks)
          </Badge>
          <Badge variant="light">single-sided {(s.single_sided_rate * 100).toFixed(1)}%</Badge>
          <Badge variant="light">crossing {(s.crossing_frac * 100).toFixed(1)}% · n={s.crossing_n}</Badge>
          <Badge variant="light">passive {((1 - s.crossing_frac) * 100).toFixed(1)}% · n={s.passive_n}</Badge>
        </Group>
      </Card>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Noise offset from round(FV)"
            series={offsetSeriesClean}
            options={{
              xAxis: { title: { text: 'offset' }, tickInterval: 1 },
              yAxis: { title: { text: 'count' } },
              legend: { enabled: false },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <RunLengthCard title="Run-length (consecutive noise ticks)" rl={s.run_length} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="xs">
            <Group gap="xs">
              <Text size="sm" fw={600}>Crossing volumes (aggressive)</Text>
              {s.crossing_vol && (
                <Badge size="sm" color={s.crossing_vol.p_value > 0.05 ? 'green' : 'red'}>
                  χ² U p={fmt(s.crossing_vol.p_value)}
                </Badge>
              )}
              <Text size="xs" c="dimmed">mean={s.crossing_vol_mean.toFixed(1)}</Text>
            </Group>
            {s.crossing_vol && (
              <SimpleChart
                title="Crossing volume histogram"
                series={volSeries(s.crossing_vol, '#fa5252')}
                options={{
                  chart: { height: 180 },
                  xAxis: { title: { text: 'bin' }, tickInterval: 1 },
                  yAxis: { title: { text: 'count' } },
                  legend: { enabled: false },
                }}
              />
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Stack gap="xs">
            <Group gap="xs">
              <Text size="sm" fw={600}>Passive volumes (inside-spread)</Text>
              {s.passive_vol && (
                <Badge size="sm" color={s.passive_vol.p_value > 0.05 ? 'green' : 'red'}>
                  χ² U p={fmt(s.passive_vol.p_value)}
                </Badge>
              )}
              <Text size="xs" c="dimmed">mean={s.passive_vol_mean.toFixed(1)}</Text>
            </Group>
            {s.passive_vol && (
              <SimpleChart
                title="Passive volume histogram"
                series={volSeries(s.passive_vol, '#4c6ef5')}
                options={{
                  chart: { height: 180 },
                  xAxis: { title: { text: 'bin' }, tickInterval: 1 },
                  yAxis: { title: { text: 'count' } },
                  legend: { enabled: false },
                }}
              />
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

function RunLengthCard({ title, rl }: { title: string; rl: import('../wasm').RunLenOut }): ReactNode {
  const series = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const emp: [number, number][] = rl.empirical_pmf.map((p, i) => [i + 1, p]);
    const fit: [number, number][] = rl.fitted_pmf.map((p, i) => [i + 1, p]);
    return [
      { type: 'column', name: 'empirical', data: emp, color: '#12b886' },
      { type: 'line', name: 'Geometric(1-p̂)', data: fit, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, marker: { enabled: false } },
    ];
  }, [rl]);
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text size="sm" fw={600}>{title}</Text>
        <Badge size="sm" color={rl.ks_p > 0.05 ? 'green' : 'red'}>KS p={fmt(rl.ks_p)}</Badge>
        <Text size="xs" c="dimmed">n_runs={rl.n_runs}, mean={rl.mean_length.toFixed(2)}</Text>
      </Group>
      <SimpleChart
        title="PMF"
        series={series}
        options={{
          chart: { height: 180 },
          xAxis: { title: { text: 'length' } },
          yAxis: { title: { text: 'P' } },
          legend: { enabled: true, itemStyle: { fontSize: '9px' } },
        }}
      />
    </Stack>
  );
}

function fmt(p: number): string {
  if (!Number.isFinite(p)) return '—';
  if (p < 1e-4) return '< 1e-4';
  return p.toFixed(4);
}
