import { Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Table, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { Stage1Result } from '../stages/layer_detection';
import { LayerPresence, PresenceSide, runStage4, Stage4Result } from '../stages/presence_model';

interface Props {
  data: FvAndBook;
  stage1: Stage1Result | null;
  result: Stage4Result | null;
  onRun: (r: Stage4Result) => void;
  onAccept: () => void;
}

export function PresenceModelPanel({ data, stage1, result, onRun, onAccept }: Props): ReactNode {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!stage1) return <Alert color="yellow" title="Run Stage 1 first">Layer bands required.</Alert>;

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try { onRun(await runStage4(data, stage1.layers)); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 4 — Presence Model</Text>
          <Text size="xs" c="dimmed">
            iid Bernoulli tests: Ljung-Box · runs · run-length KS vs Geometric · χ² independence.
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
      {result?.layers.map(L => <LayerPresenceCard key={L.layer_id} layer={L} />)}
      {result && result.cross_bot.length > 0 && <CrossBotTable rows={result.cross_bot} />}
    </Stack>
  );
}

function LayerPresenceCard({ layer }: { layer: LayerPresence }): ReactNode {
  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group>
          <Text fw={600}>{layer.layer_name}</Text>
          <Badge color={layer.bid_ask_indep.p_value > 0.05 ? 'green' : 'red'} variant="light">
            bid ⊥ ask χ² p={fmt(layer.bid_ask_indep.p_value)} (φ={layer.bid_ask_indep.phi.toFixed(3)})
          </Badge>
        </Group>
        <Grid gutter="md">
          <Grid.Col span={6}>
            <SideCard title="Bid" side={layer.bid} />
          </Grid.Col>
          <Grid.Col span={6}>
            <SideCard title="Ask" side={layer.ask} />
          </Grid.Col>
        </Grid>
      </Stack>
    </Card>
  );
}

function SideCard({ title, side }: { title: string; side: PresenceSide }): ReactNode {
  const acfSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const data = side.ljung.autocorr.map((r, i) => [i + 1, r] as [number, number]);
    return [{ type: 'column', name: 'AC(k)', data, color: '#12b886', pointWidth: 12 }];
  }, [side.ljung]);
  const acfBand = 1.96 / Math.sqrt(Math.max(1, side.n_ticks));

  const rlSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const emp: [number, number][] = side.runLength.empirical_pmf.map((p, i) => [i + 1, p]);
    const fit: [number, number][] = side.runLength.fitted_pmf.map((p, i) => [i + 1, p]);
    return [
      { type: 'column', name: 'empirical', data: emp, color: '#4c6ef5' },
      { type: 'line',   name: 'Geometric(1-p̂)', data: fit, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, marker: { enabled: false } },
    ];
  }, [side.runLength]);

  const tests = [
    { name: 'Rate vs 80%', p: side.ci.p_value,           aux: `φ̂ = ${(side.rate * 100).toFixed(1)}% (CI ${(side.ci.lo * 100).toFixed(1)}%-${(side.ci.hi * 100).toFixed(1)}%)` },
    { name: 'Ljung-Box Q', p: side.ljung.p_value,        aux: `Q=${side.ljung.q.toFixed(2)}, df=${side.ljung.df}` },
    { name: 'Runs test',   p: side.runs.p_value,         aux: `observed=${side.runs.runs}, expected=${side.runs.expected.toFixed(1)}` },
    { name: 'Run-length KS (Geom)', p: side.runLength.ks_p, aux: `D=${side.runLength.ks_stat.toFixed(3)}, n_runs=${side.runLength.n_runs}` },
  ];

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>{title} · n_present={side.n_present}/{side.n_ticks}</Text>
      <Table fz="xs" striped withTableBorder>
        <Table.Thead>
          <Table.Tr><Table.Th>test</Table.Th><Table.Th>p-value</Table.Th><Table.Th>verdict</Table.Th><Table.Th>detail</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {tests.map(t => (
            <Table.Tr key={t.name}>
              <Table.Td>{t.name}</Table.Td>
              <Table.Td>{fmt(t.p)}</Table.Td>
              <Table.Td><Badge color={t.p > 0.05 ? 'green' : 'red'} size="xs">{t.p > 0.05 ? 'pass' : 'fail'}</Badge></Table.Td>
              <Table.Td c="dimmed">{t.aux}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Grid gutter="xs">
        <Grid.Col span={6}>
          <SimpleChart
            title="Autocorrelation"
            series={acfSeries}
            options={{
              chart: { height: 160 },
              xAxis: { title: { text: 'lag' } },
              yAxis: {
                title: { text: 'AC(k)' },
                plotLines: [
                  { value: acfBand,  color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, width: 1 },
                  { value: -acfBand, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, width: 1 },
                  { value: 0,        color: '#868e96', width: 1 },
                ],
              },
              legend: { enabled: false },
            }}
          />
        </Grid.Col>
        <Grid.Col span={6}>
          <SimpleChart
            title="Run-length distribution"
            series={rlSeries}
            options={{
              chart: { height: 160 },
              xAxis: { title: { text: 'run length' } },
              yAxis: { title: { text: 'P' } },
              legend: { enabled: true, itemStyle: { fontSize: '9px' } },
            }}
          />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

function CrossBotTable({ rows }: { rows: Stage4Result['cross_bot'] }): ReactNode {
  return (
    <Card withBorder padding="sm">
      <Text size="sm" fw={600} mb="xs">Cross-bot independence</Text>
      <Table fz="xs" striped withTableBorder>
        <Table.Thead>
          <Table.Tr><Table.Th>A</Table.Th><Table.Th>B</Table.Th><Table.Th>χ²</Table.Th><Table.Th>p</Table.Th><Table.Th>φ</Table.Th><Table.Th>verdict</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r, i) => (
            <Table.Tr key={i}>
              <Table.Td>{r.a_id} {r.side_a}</Table.Td>
              <Table.Td>{r.b_id} {r.side_b}</Table.Td>
              <Table.Td>{r.indep.chi2.toFixed(2)}</Table.Td>
              <Table.Td>{fmt(r.indep.p_value)}</Table.Td>
              <Table.Td>{r.indep.phi.toFixed(3)}</Table.Td>
              <Table.Td><Badge color={r.indep.p_value > 0.05 ? 'green' : 'red'} size="xs">{r.indep.p_value > 0.05 ? 'indep' : 'coupled'}</Badge></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

function fmt(p: number): string {
  if (!Number.isFinite(p)) return '—';
  if (p < 1e-4) return '< 1e-4';
  return p.toFixed(4);
}
