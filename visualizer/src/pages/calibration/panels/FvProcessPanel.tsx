import { Alert, Badge, Button, Card, Grid, Group, Stack, Table, Text } from '@mantine/core';
import Highcharts from 'highcharts';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents';
import { FvAndBook } from '../types';
import { runStage0, FvFitResult } from '../stages/fv_process';

interface Props {
  data: FvAndBook;
  result: FvFitResult | null;
  onRun: (result: FvFitResult) => void;
  onAccept: () => void;
}

function pctOrP(p: number): string {
  if (!isFinite(p)) return '—';
  if (p < 0.0001) return '< 1e-4';
  return p.toFixed(4);
}

function passFail(p: number, alpha = 0.05): { color: string; label: string } {
  if (!isFinite(p)) return { color: 'gray', label: 'n/a' };
  return p > alpha ? { color: 'green', label: 'pass' } : { color: 'red', label: 'fail' };
}

export function FvProcessPanel({ data, result, onRun, onAccept }: Props): ReactNode {
  const fvRows = useMemo(
    () => data.rows.filter(r => r.fv !== null).map(r => ({ ts: r.ts, fv: r.fv as number })),
    [data],
  );

  const handleRun = () => {
    try {
      const r = runStage0({ rows: fvRows });
      onRun(r);
    } catch (e) {
      console.error(e);
    }
  };

  if (fvRows.length < 3) {
    return <Alert color="red" title="Not enough data">Need ≥ 3 ticks with FV.</Alert>;
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 0 — FV Process</Text>
          <Text size="xs" c="dimmed">{fvRows.length} ticks · buy price {data.buy_price}</Text>
        </Stack>
        <Group>
          <Button onClick={handleRun} variant={result ? 'light' : 'filled'}>
            {result ? 'Re-run' : 'Run'}
          </Button>
          {result && <Button onClick={onAccept} color="green">Accept & continue</Button>}
        </Group>
      </Group>

      {!result && (
        <Alert color="gray" title="Ready to run">
          <Text size="sm">
            Hierarchy: constant (low variance) → linear drift (significant β) → AR(1) (significant ΔFV lag-1) → random walk.
          </Text>
        </Alert>
      )}

      {result && <FvResultView result={result} />}
    </Stack>
  );
}

function FvResultView({ result }: { result: FvFitResult }): ReactNode {
  const d = result.diagnostics;

  const fvLineSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const obs: [number, number][] = result.fvSeries.map(r => [r.ts, r.fv]);
    const fit: [number, number][] = result.fvSeries.map((r, i) => [r.ts, result.fitted[i]]);
    return [
      { type: 'line', name: 'Observed FV', data: obs, color: '#4c6ef5', lineWidth: 1.5, enableMouseTracking: false },
      { type: 'line', name: `Fitted (${result.pickedType})`, data: fit, color: '#fa5252', lineWidth: 1.2, dashStyle: 'ShortDash' as Highcharts.DashStyleValue },
    ];
  }, [result]);

  const stepHist = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const steps = result.deltaFv;
    if (steps.length === 0) return [];
    const mu = d.meanStep;
    const sd = d.stdStep;
    const lo = mu - 4 * sd;
    const hi = mu + 4 * sd;
    const nBins = 40;
    const binW = (hi - lo) / nBins;
    const counts = new Array(nBins).fill(0);
    for (const s of steps) {
      const idx = Math.floor((s - lo) / binW);
      if (idx >= 0 && idx < nBins) counts[idx] += 1;
    }
    const xs: number[] = new Array(nBins);
    for (let i = 0; i < nBins; i++) xs[i] = lo + (i + 0.5) * binW;
    const areaNorm = steps.length * binW;
    const pdf = xs.map(x => {
      const y = (1 / (sd * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mu) / sd) ** 2);
      return y * areaNorm;
    });
    return [
      { type: 'column', name: 'ΔFV histogram', data: xs.map((x, i) => [x, counts[i]]) as [number, number][], color: '#868e96' },
      { type: 'line', name: 'N(μ, σ²) fit', data: xs.map((x, i) => [x, pdf[i]]) as [number, number][], color: '#e64980', lineWidth: 2, enableMouseTracking: false },
    ];
  }, [result, d]);

  // Q-Q plot of residuals vs standard normal
  const qqSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const rs = result.residuals.slice().sort((a, b) => a - b);
    const n = rs.length;
    const mu = rs.reduce((a, b) => a + b, 0) / n;
    const sd = Math.sqrt(rs.reduce((a, b) => a + (b - mu) ** 2, 0) / Math.max(1, n - 1)) || 1;
    const pts: [number, number][] = rs.map((r, i) => {
      const p = (i + 0.5) / n;
      const z = invNorm(p);
      return [z, (r - mu) / sd];
    });
    const lineZ: [number, number][] = [[-3, -3], [3, 3]];
    return [
      { type: 'scatter', name: 'Residual z', data: pts, color: '#4c6ef5', marker: { radius: 2 }, enableMouseTracking: false },
      { type: 'line', name: 'y = x', data: lineZ, color: '#fa5252', lineWidth: 1, dashStyle: 'Dash' as Highcharts.DashStyleValue, enableMouseTracking: false },
    ];
  }, [result]);

  // ACF bar chart on residuals
  const acfSeries = useMemo<Highcharts.SeriesOptionsType[]>(() => {
    const data = d.residualLjung.ac.map((r, i) => [i + 1, r] as [number, number]);
    return [{ type: 'column', name: 'AC(k)', data, color: '#12b886', pointWidth: 14 }];
  }, [d]);
  const acfBand = 1.96 / Math.sqrt(Math.max(1, result.residuals.length));

  const tests = [
    { name: 'Mean step = 0',      z: d.meanStepZ,   p: d.meanStepP, expected: 'pass under RW / AR(1)' },
    { name: 'Residual Ljung-Box', z: NaN,           p: d.residualLjung.p, expected: `df=${d.residualLjung.df}, Q=${d.residualLjung.q.toFixed(2)}` },
    { name: 'Residual skewness',  z: d.skewZ,       p: d.skewP, expected: 'normal ⇒ z ≈ 0' },
    { name: 'Residual kurtosis',  z: d.kurtZ,       p: d.kurtP, expected: 'normal ⇒ z ≈ 0' },
    { name: 'ΔFV AC(1) = 0',      z: d.deltaAc1Z,   p: d.deltaAc1P, expected: 'RW ⇒ pass; AR(1) ⇒ fail' },
  ];

  return (
    <Stack gap="md">
      <Card withBorder padding="sm">
        <Group gap="md">
          <Badge size="lg" color="blue">{result.pickedType}</Badge>
          <Text size="sm" c="dimmed">
            n={d.nTicks} · μ_step={d.meanStep.toExponential(2)} · σ_step={d.stdStep.toFixed(4)} ·
            quantization={d.quantization.grid} (min |Δ|={d.quantization.minAbs.toExponential(2)})
          </Text>
          {result.pickedType === 'linear_drift' && (
            <Text size="sm">
              β̂={d.linearFit.beta.toFixed(5)} ± {d.linearFit.seBeta.toExponential(2)} ·
              R²={d.linearFit.rSquared.toFixed(4)}
            </Text>
          )}
        </Group>
      </Card>

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <SimpleChart
            title="FV + fitted model"
            series={fvLineSeries}
            options={{
              xAxis: { title: { text: 'timestamp' } },
              yAxis: { title: { text: 'FV' } },
              legend: { enabled: true },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <SimpleChart
            title="ΔFV histogram vs normal fit"
            series={stepHist}
            options={{
              xAxis: { title: { text: 'ΔFV' } },
              yAxis: { title: { text: 'count' } },
              legend: { enabled: true },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Residual Q-Q vs N(0,1)"
            series={qqSeries}
            options={{
              xAxis: { title: { text: 'theoretical z' }, min: -4, max: 4 },
              yAxis: { title: { text: 'sample z' } },
              legend: { enabled: false },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Residual autocorrelation"
            series={acfSeries}
            options={{
              xAxis: { title: { text: 'lag' } },
              yAxis: {
                title: { text: 'AC(k)' },
                plotLines: [
                  { value: acfBand, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, width: 1, zIndex: 1 },
                  { value: -acfBand, color: '#fa5252', dashStyle: 'Dash' as Highcharts.DashStyleValue, width: 1, zIndex: 1 },
                  { value: 0, color: '#868e96', width: 1 },
                ],
              },
              legend: { enabled: false },
            }}
          />
        </Grid.Col>
      </Grid>

      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb="xs">Statistical tests</Text>
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Test</Table.Th>
              <Table.Th>z</Table.Th>
              <Table.Th>p-value</Table.Th>
              <Table.Th>result</Table.Th>
              <Table.Th>interpretation</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {tests.map(t => {
              const r = passFail(t.p);
              return (
                <Table.Tr key={t.name}>
                  <Table.Td>{t.name}</Table.Td>
                  <Table.Td>{isNaN(t.z) ? '—' : t.z.toFixed(2)}</Table.Td>
                  <Table.Td>{pctOrP(t.p)}</Table.Td>
                  <Table.Td><Badge color={r.color} size="sm">{r.label}</Badge></Table.Td>
                  <Table.Td c="dimmed">{t.expected}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

// Acklam's inverse-normal approximation, single-file copy for Q-Q.
function invNorm(p: number): number {
  const pp = Math.min(Math.max(p, 1e-12), 1 - 1e-12);
  const A = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const B = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const C = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const D = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const plow = 0.02425, phigh = 1 - plow;
  if (pp < plow) {
    const q = Math.sqrt(-2 * Math.log(pp));
    return (((((C[0]*q+C[1])*q+C[2])*q+C[3])*q+C[4])*q+C[5]) / ((((D[0]*q+D[1])*q+D[2])*q+D[3])*q+1);
  }
  if (pp <= phigh) {
    const q = pp - 0.5;
    const r = q*q;
    return (((((A[0]*r+A[1])*r+A[2])*r+A[3])*r+A[4])*r+A[5])*q / (((((B[0]*r+B[1])*r+B[2])*r+B[3])*r+B[4])*r+1);
  }
  const q = Math.sqrt(-2 * Math.log(1 - pp));
  return -(((((C[0]*q+C[1])*q+C[2])*q+C[3])*q+C[4])*q+C[5]) / ((((D[0]*q+D[1])*q+D[2])*q+D[3])*q+1);
}
