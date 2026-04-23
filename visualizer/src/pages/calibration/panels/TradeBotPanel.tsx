import { Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Table, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { runStage6, Stage6Result, TradeStats } from '../stages/trade_bot';

interface Props {
  data: FvAndBook;
  result: Stage6Result | null;
  onRun: (r: Stage6Result) => void;
  onAccept: () => void;
}

export function TradeBotPanel({ data, result, onRun, onAccept }: Props): ReactNode {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hasTrades = !!data.trades && data.trades.length > 0;

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try { onRun(await runStage6(data)); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 6 — Trade Bot</Text>
          <Text size="xs" c="dimmed">
            Poisson rate + χ² GoF on per-tick trade counts · quantity distribution · counterparty tally.
          </Text>
        </Stack>
        <Group>
          <Button onClick={handleRun} variant={result?.available ? 'light' : 'filled'} disabled={busy || !hasTrades}>
            {busy ? <Loader size="xs" /> : result?.available ? 'Re-run' : 'Run'}
          </Button>
          {result?.available && <Button onClick={onAccept} color="green" disabled={busy}>Accept & continue</Button>}
        </Group>
      </Group>

      {err && <Alert color="red" title="Compute failed">{err}</Alert>}
      {!hasTrades && (
        <Alert color="yellow" title="No trades in the extracted data">
          <Text size="sm">
            Re-run the extractor with <code>--trades-csv data/prosperity4/roundN/trades_round_N_day_X.csv</code>
            (repeatable for multi-day sets) to populate trade data.
          </Text>
        </Alert>
      )}
      {result && !result.available && <Alert color="yellow" title="No trades available">{result.reason ?? ''}</Alert>}
      {result?.available && result.stats && <TradeStatsView stats={result.stats} />}
    </Stack>
  );
}

function TradeStatsView({ stats: s }: { stats: TradeStats }): ReactNode {
  const countSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const obs: [number, number][] = s.count_hist.map(r => [r.k, r.observed]);
    const exp: [number, number][] = s.count_hist.map(r => [r.k, r.expected_poisson]);
    return [
      { type: 'column', name: 'observed', data: obs, color: '#4c6ef5' },
      { type: 'line',   name: `Poisson(λ=${s.rate_per_tick.toFixed(4)})`, data: exp, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, marker: { enabled: false } },
    ];
  }, [s]);

  const qtySeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const obs: [number, number][] = s.qty_hist.map(r => [r.qty, r.count]);
    return [{ type: 'column', name: 'count', data: obs, color: '#12b886' }];
  }, [s]);

  return (
    <Stack gap="md">
      <Card withBorder padding="sm">
        <Group gap="md">
          <Badge size="lg" color="blue" variant="light">λ̂ = {s.rate_per_tick.toFixed(4)} trades/tick</Badge>
          <Text size="sm">{s.n_trades} trades over {s.n_ticks} ticks</Text>
          {s.poisson_gof && (
            <Badge color={s.poisson_gof.p_value > 0.05 ? 'green' : 'red'}>
              Poisson χ² p={fmt(s.poisson_gof.p_value)} (df={s.poisson_gof.df})
            </Badge>
          )}
          {s.qty_uniform_gof && (
            <Badge color={s.qty_uniform_gof.p_value > 0.05 ? 'green' : 'red'}>
              qty ~ U({s.qty_min},{s.qty_max}) p={fmt(s.qty_uniform_gof.p_value)}
            </Badge>
          )}
        </Group>
      </Card>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Trades per tick (observed vs Poisson)"
            series={countSeries}
            options={{
              xAxis: { title: { text: 'trades per tick' }, tickInterval: 1 },
              yAxis: { title: { text: 'count' }, type: 'logarithmic' },
              legend: { enabled: true },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Quantity distribution"
            series={qtySeries}
            options={{
              xAxis: { title: { text: 'quantity' }, tickInterval: 1 },
              yAxis: { title: { text: 'count' } },
              legend: { enabled: false },
              subtitle: { text: `mean=${s.qty_mean.toFixed(2)} · range [${s.qty_min}, ${s.qty_max}]` },
            }}
          />
        </Grid.Col>
      </Grid>

      {s.counterparties.length > 0 && (
        <Card withBorder padding="sm">
          <Text size="sm" fw={600} mb="xs">Counterparties</Text>
          <Table fz="xs" striped withTableBorder>
            <Table.Thead>
              <Table.Tr><Table.Th>name</Table.Th><Table.Th>buys</Table.Th><Table.Th>sells</Table.Th><Table.Th>mean qty</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {s.counterparties.map(cp => (
                <Table.Tr key={cp.name}>
                  <Table.Td>{cp.name}</Table.Td>
                  <Table.Td>{cp.buys}</Table.Td>
                  <Table.Td>{cp.sells}</Table.Td>
                  <Table.Td>{cp.mean_qty.toFixed(2)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
    </Stack>
  );
}

function fmt(p: number): string {
  if (!Number.isFinite(p)) return '—';
  if (p < 1e-4) return '< 1e-4';
  return p.toFixed(4);
}
