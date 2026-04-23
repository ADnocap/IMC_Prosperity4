import { Alert, Badge, Button, Card, Grid, Group, Loader, NumberInput, Stack, Table, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { DetectedLayer, runStage1, Stage1Result } from '../stages/layer_detection';

interface Props {
  data: FvAndBook;
  result: Stage1Result | null;
  onRun: (r: Stage1Result) => void;
  onAccept: () => void;
}

export function LayerDetectionPanel({ data, result, onRun, onAccept }: Props): ReactNode {
  const [bandwidth, setBandwidth] = useState<number>(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await runStage1(data, bandwidth);
      onRun(r);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 1 — Layer Detection</Text>
          <Text size="xs" c="dimmed">
            KDE-peak-detect bot layers. Regress <code>offset ~ FV</code> to classify fixed vs proportional.
          </Text>
        </Stack>
        <Group>
          <NumberInput
            label="KDE bandwidth"
            description="0 = Silverman auto"
            value={bandwidth}
            onChange={v => setBandwidth(Number(v) || 0)}
            step={0.1}
            min={0}
            max={5}
            w={140}
            disabled={busy}
          />
          <Button onClick={handleRun} variant={result ? 'light' : 'filled'} disabled={busy}>
            {busy ? <Loader size="xs" /> : result ? 'Re-run' : 'Run'}
          </Button>
          {result && <Button onClick={onAccept} color="green" disabled={busy}>Accept & continue</Button>}
        </Group>
      </Group>

      {err && <Alert color="red" title="Compute failed">{err}</Alert>}

      {!result && !busy && (
        <Alert color="gray" title="Click Run to start">
          <Text size="sm">
            The KDE will find modes in the bid/ask offset-from-FV distribution. A slope test per
            peak decides fixed vs proportional. Wide-FV-range data (PEPPER-style) produces visibly
            sloped clouds on proportional layers — that's the key discriminator.
          </Text>
        </Alert>
      )}

      {result && <LayerDetectionView result={result} />}
    </Stack>
  );
}

function LayerDetectionView({ result }: { result: Stage1Result }): ReactNode {
  const kdeSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const bidPts: [number, number][] = result.bid_kde.grid.map((g, i) => [g, result.bid_kde.density[i]]);
    const askPts: [number, number][] = result.ask_kde.grid.map((g, i) => [g, result.ask_kde.density[i]]);
    const bidPeakMarks: [number, number][] = result.bid_kde.peaks.map(i => [result.bid_kde.grid[i], result.bid_kde.density[i]]);
    const askPeakMarks: [number, number][] = result.ask_kde.peaks.map(i => [result.ask_kde.grid[i], result.ask_kde.density[i]]);
    return [
      { type: 'areaspline', name: 'Bid offset KDE', data: bidPts, color: '#4c6ef5', fillOpacity: 0.15, lineWidth: 1.5, enableMouseTracking: false },
      { type: 'areaspline', name: 'Ask offset KDE', data: askPts, color: '#fa5252', fillOpacity: 0.15, lineWidth: 1.5, enableMouseTracking: false },
      { type: 'scatter', name: 'Bid peaks', data: bidPeakMarks, color: '#1c3fa8', marker: { radius: 6, symbol: 'triangle-down' } },
      { type: 'scatter', name: 'Ask peaks', data: askPeakMarks, color: '#aa1919', marker: { radius: 6, symbol: 'triangle' } },
    ];
  }, [result]);

  const offsetScatter = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const colors = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf'];
    const seriesList: Highcharts.SeriesOptionsType[] = [];
    result.layers.forEach((L, i) => {
      const color = colors[i % colors.length];
      // Points in the bid band
      const bidPts: [number, number][] = result.quotes
        .filter(q => q.side === 'bid' && q.offset >= L.offset_band.bid[0] && q.offset <= L.offset_band.bid[1])
        .slice(0, 4000) // guard against giant datasets
        .map(q => [q.fv, q.offset]);
      const askPts: [number, number][] = result.quotes
        .filter(q => q.side === 'ask' && q.offset >= L.offset_band.ask[0] && q.offset <= L.offset_band.ask[1])
        .slice(0, 4000)
        .map(q => [q.fv, q.offset]);
      seriesList.push(
        { type: 'scatter', name: `${L.id} bid`, data: bidPts, color, marker: { radius: 1.5 }, enableMouseTracking: false },
        { type: 'scatter', name: `${L.id} ask`, data: askPts, color, marker: { radius: 1.5, symbol: 'triangle' }, enableMouseTracking: false },
      );
    });
    // Noise points in grey
    const noisePts: [number, number][] = result.noise_quotes
      .slice(0, 4000)
      .map(q => [q.fv, q.offset]);
    if (noisePts.length > 0) {
      seriesList.push({ type: 'scatter', name: 'noise', data: noisePts, color: '#adb5bd', marker: { radius: 1 }, enableMouseTracking: false });
    }
    return seriesList;
  }, [result]);

  return (
    <Stack gap="md">
      <Card withBorder padding="sm">
        <Group gap="md" wrap="wrap">
          <Text size="sm">Detected layers:</Text>
          {result.layers.map(L => (
            <Badge key={L.id} color={L.offset_type === 'proportional' ? 'grape' : 'blue'} size="lg" variant="light">
              {L.name} · {L.offset_type}{L.offset_type === 'proportional' ? ` (K≈${L.k_estimate.toExponential(3)})` : ` (offset≈${L.offset_mag.toFixed(1)})`}
            </Badge>
          ))}
          {result.layers.length === 0 && <Text size="sm" c="dimmed">No layers detected — try a smaller KDE bandwidth</Text>}
        </Group>
      </Card>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Offset-from-FV KDE (bid − ask)"
            series={kdeSeries}
            options={{
              xAxis: { title: { text: 'price - FV' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              yAxis: { title: { text: 'density' } },
              legend: { enabled: true },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Offset × FV (proportional layers show sloped clouds)"
            series={offsetScatter}
            options={{
              xAxis: { title: { text: 'FV' } },
              yAxis: { title: { text: 'offset = price - FV' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              legend: { enabled: true },
            }}
          />
        </Grid.Col>
      </Grid>

      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb="xs">Layer classification detail</Text>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Layer</Table.Th>
              <Table.Th>Offset type</Table.Th>
              <Table.Th>Offset mag</Table.Th>
              <Table.Th>K̂</Table.Th>
              <Table.Th>Bid band</Table.Th>
              <Table.Th>Ask band</Table.Th>
              <Table.Th>n bid / ask</Table.Th>
              <Table.Th>β bid (t, p)</Table.Th>
              <Table.Th>β ask (t, p)</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {result.layers.map(L => <LayerRow key={L.id} layer={L} />)}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed" mt="xs">
          Rule: |t| &gt; 3 on the β-slope of <code>offset ~ FV</code> ⇒ proportional. Below that we call it fixed
          (avoids misclassifying noise as proportional on narrow-FV data).
        </Text>
      </Card>
    </Stack>
  );
}

function LayerRow({ layer: L }: { layer: DetectedLayer }): ReactNode {
  const fmtBand = (b: [number, number]) => `[${b[0].toFixed(2)}, ${b[1].toFixed(2)}]`;
  const fmtOls = (ols: typeof L.bid_ols) =>
    ols ? `${ols.beta.toExponential(3)} (t=${ols.t_beta.toFixed(1)}, p=${ols.p_beta < 0.0001 ? '<1e-4' : ols.p_beta.toFixed(3)})` : '—';
  return (
    <Table.Tr>
      <Table.Td><Text size="sm" fw={500}>{L.name}</Text></Table.Td>
      <Table.Td>
        <Badge size="sm" color={L.offset_type === 'proportional' ? 'grape' : 'blue'}>{L.offset_type}</Badge>
      </Table.Td>
      <Table.Td>{L.offset_mag.toFixed(2)}</Table.Td>
      <Table.Td>{L.offset_type === 'proportional' ? L.k_estimate.toExponential(3) : '—'}</Table.Td>
      <Table.Td>{fmtBand(L.offset_band.bid)}</Table.Td>
      <Table.Td>{fmtBand(L.offset_band.ask)}</Table.Td>
      <Table.Td>{L.n_bid} / {L.n_ask}</Table.Td>
      <Table.Td>{fmtOls(L.bid_ols)}</Table.Td>
      <Table.Td>{fmtOls(L.ask_ols)}</Table.Td>
    </Table.Tr>
  );
}
