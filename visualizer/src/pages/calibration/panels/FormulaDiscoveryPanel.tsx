import { Alert, Badge, Button, Card, Grid, Group, Loader, Stack, Table, Text, Tooltip } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { formulaString, runStage2, Stage2Result, winnerToFormulaSpec, BotFormulaResult } from '../stages/formula_discovery';
import { Stage1Result } from '../stages/layer_detection';
import { FixedCandidate, PropCandidate } from '../wasm';

interface Props {
  stage1: Stage1Result | null;
  result: Stage2Result | null;
  onRun: (r: Stage2Result) => void;
  onAccept: () => void;
}

export function FormulaDiscoveryPanel({ stage1, result, onRun, onAccept }: Props): ReactNode {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!stage1) {
    return <Alert color="yellow" title="Run Stage 1 first">Layer detection output is required for formula discovery.</Alert>;
  }

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await runStage2(stage1.layers, stage1.quotes);
      onRun(r);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 2 — Formula Discovery</Text>
          <Text size="xs" c="dimmed">
            Brute-force fixed + proportional formula search per layer, 2-fold CV, Wilson CI, FV-decile match heatmap.
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
      {!result && !busy && (
        <Alert color="gray" title="Ready">
          <Text size="sm">Runs ~{stage1.layers.length * 2} searches (bid + ask per detected layer). Takes a few seconds on 30k ticks.</Text>
        </Alert>
      )}
      {busy && (
        <Alert color="blue" icon={<Loader size="xs" />} title="Running formula search...">
          <Text size="sm">WASM kernel sweeping {3 * 7 * 8 + 3 * 200} formulas per side × {stage1.layers.length * 2} sides.</Text>
        </Alert>
      )}

      {result && result.bots.map(b => <BotFormulaCard key={b.layer_id} bot={b} />)}
    </Stack>
  );
}

function BotFormulaCard({ bot }: { bot: BotFormulaResult }): ReactNode {
  const { layer_name, winner_bid, winner_ask, winner_bid_family, winner_ask_family, bid, ask } = bot;
  const bidSpec = winnerToFormulaSpec(winner_bid, winner_bid_family);
  const askSpec = winnerToFormulaSpec(winner_ask, winner_ask_family);

  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group gap="md">
          <Text fw={600}>{layer_name}</Text>
          <Badge color={winner_bid_family === 'proportional' ? 'grape' : 'blue'}>
            bid: {winner_bid_family}
          </Badge>
          <Badge color={winner_ask_family === 'proportional' ? 'grape' : 'blue'}>
            ask: {winner_ask_family}
          </Badge>
        </Group>

        <Group gap="xl">
          <Stack gap={2}>
            <Text size="xs" c="dimmed">Bid formula</Text>
            <Text size="sm" ff="monospace">{formulaString(bidSpec, 'bid')}</Text>
            <Group gap="xs">
              <Tooltip label={`95% CI [${(winner_bid.ci_lo * 100).toFixed(1)}%, ${(winner_bid.ci_hi * 100).toFixed(1)}%] · n=${winner_bid.n}`}>
                <Badge variant="light">
                  match {(winner_bid.match_rate * 100).toFixed(2)}% · CV {(winner_bid.cv_match_rate * 100).toFixed(2)}%
                </Badge>
              </Tooltip>
            </Group>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">Ask formula</Text>
            <Text size="sm" ff="monospace">{formulaString(askSpec, 'ask')}</Text>
            <Group gap="xs">
              <Tooltip label={`95% CI [${(winner_ask.ci_lo * 100).toFixed(1)}%, ${(winner_ask.ci_hi * 100).toFixed(1)}%] · n=${winner_ask.n}`}>
                <Badge variant="light">
                  match {(winner_ask.match_rate * 100).toFixed(2)}% · CV {(winner_ask.cv_match_rate * 100).toFixed(2)}%
                </Badge>
              </Tooltip>
            </Group>
          </Stack>
        </Group>

        <Grid gutter="md">
          <Grid.Col span={6}>
            <TopCandidatesTable side="bid" fixed={bid.fixed_top} proportional={bid.proportional_top} winnerFamily={winner_bid_family} />
          </Grid.Col>
          <Grid.Col span={6}>
            <TopCandidatesTable side="ask" fixed={ask.fixed_top} proportional={ask.proportional_top} winnerFamily={winner_ask_family} />
          </Grid.Col>
          <Grid.Col span={6}>
            <ResidualChart title="Bid residuals (observed − predicted)" hist={winner_bid.residual_hist} />
          </Grid.Col>
          <Grid.Col span={6}>
            <ResidualChart title="Ask residuals" hist={winner_ask.residual_hist} />
          </Grid.Col>
          <Grid.Col span={6}>
            <DecileChart title="Bid: FV-decile match rate" deciles={winner_bid.fv_decile_match} />
          </Grid.Col>
          <Grid.Col span={6}>
            <DecileChart title="Ask: FV-decile match rate" deciles={winner_ask.fv_decile_match} />
          </Grid.Col>
        </Grid>
      </Stack>
    </Card>
  );
}

function TopCandidatesTable({
  side, fixed, proportional, winnerFamily,
}: {
  side: 'bid' | 'ask';
  fixed: FixedCandidate[];
  proportional: PropCandidate[];
  winnerFamily: 'fixed' | 'proportional';
}): ReactNode {
  return (
    <Stack gap="xs">
      <Text size="xs" fw={600}>Top fixed ({side})</Text>
      <Table fz="xs" striped withTableBorder>
        <Table.Thead>
          <Table.Tr><Table.Th>formula</Table.Th><Table.Th>CV%</Table.Th><Table.Th>match%</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {fixed.slice(0, 3).map((c, i) => (
            <Table.Tr key={i} bg={i === 0 && winnerFamily === 'fixed' ? 'var(--mantine-color-green-light)' : undefined}>
              <Table.Td ff="monospace">{c.round_fn}(fv {c.shift >= 0 ? '+' : '−'} {Math.abs(c.shift)}) {c.constant >= 0 ? '+' : '−'} {Math.abs(c.constant)}</Table.Td>
              <Table.Td>{(c.cv_match_rate * 100).toFixed(2)}</Table.Td>
              <Table.Td>{(c.match_rate * 100).toFixed(2)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Text size="xs" fw={600}>Top proportional ({side})</Text>
      <Table fz="xs" striped withTableBorder>
        <Table.Thead>
          <Table.Tr><Table.Th>round</Table.Th><Table.Th>K</Table.Th><Table.Th>CV%</Table.Th><Table.Th>match%</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {proportional.slice(0, 3).map((c, i) => (
            <Table.Tr key={i} bg={i === 0 && winnerFamily === 'proportional' ? 'var(--mantine-color-green-light)' : undefined}>
              <Table.Td ff="monospace">{c.round_fn}</Table.Td>
              <Table.Td ff="monospace">{c.k.toExponential(3)}</Table.Td>
              <Table.Td>{(c.cv_match_rate * 100).toFixed(2)}</Table.Td>
              <Table.Td>{(c.match_rate * 100).toFixed(2)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function ResidualChart({ title, hist }: { title: string; hist: number[] }): ReactNode {
  const series = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    // hist indexes -5..=5
    const data: [number, number][] = hist.map((v, i) => [i - 5, v]);
    return [{ type: 'column', name: 'count', data, color: '#4c6ef5' }];
  }, [hist]);
  return (
    <SimpleChart
      title={title}
      series={series}
      options={{
        chart: { height: 220 },
        xAxis: { title: { text: 'residual' }, tickInterval: 1 },
        yAxis: { title: { text: 'count' }, type: 'logarithmic' },
        legend: { enabled: false },
      }}
    />
  );
}

function DecileChart({ title, deciles }: { title: string; deciles: number[] }): ReactNode {
  const series = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const data: [number, number][] = deciles.map((v, i) => [i + 1, v * 100]);
    return [{ type: 'column', name: 'match %', data, color: '#12b886' }];
  }, [deciles]);
  return (
    <SimpleChart
      title={title}
      series={series}
      options={{
        chart: { height: 220 },
        xAxis: { title: { text: 'FV decile (1 = lowest)' }, tickInterval: 1 },
        yAxis: { title: { text: 'match %' }, min: 0, max: 101 },
        legend: { enabled: false },
        subtitle: { text: 'Flat row ⇒ formula holds across FV range. Sloped ⇒ wrong offset type.' },
      }}
    />
  );
}
