import { Badge, Container, Grid, Group, Select, Table, Text, Title } from '@mantine/core';
import axios from 'axios';
import Highcharts from 'highcharts';
import { ReactNode, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { MonteCarloDashboard } from '../../models.ts';
import { useStore } from '../../store.ts';
import { parseVisualizerInput } from '../../utils/algorithm.tsx';
import { formatNumber } from '../../utils/format.ts';
import { VisualizerCard } from '../visualizer/VisualizerCard.tsx';
import {
  buildBandChartSeries,
  distributionLineSeries,
  EmptyMonteCarloView,
  ErrorMonteCarloView,
  formatSlope,
  histogramSeries,
  lineSeries,
  LoadingMonteCarloView,
  normalFitSeries,
  SessionRankingTable,
  SimpleChart,
  SummaryTable,
} from './MonteCarloComponents.tsx';

function basename(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  return normalized.split('/').filter(Boolean).pop() ?? path;
}

function withVersion(url: string, version: string | null): string {
  if (version === null || version.length === 0) {
    return url;
  }

  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}v=${encodeURIComponent(version)}`;
}

type LocalDashboardStatus = {
  dashboardExists: boolean;
  dashboardMtimeMs: number | null;
  dashboardSizeBytes: number | null;
  root: string;
  currentRunId?: string | null;
  runs?: Array<{
    id: string;
    label: string;
    mtimeMs: number;
    dashboardUrl: string;
  }>;
};

export function MonteCarloPage(): ReactNode {
  const storedDashboard = useStore(state => state.monteCarlo);
  const { search } = useLocation();
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [status, setStatus] = useState('Loading Monte Carlo dashboard');
  const [localDashboard, setLocalDashboard] = useState<MonteCarloDashboard | null>(null);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [dashboardVersion, setDashboardVersion] = useState<string | null>(null);
  const [availableRuns, setAvailableRuns] = useState<
    Array<{
      id: string;
      label: string;
      mtimeMs: number;
      dashboardUrl: string;
    }>
  >([]);
  const [selectedRunId, setSelectedRunId] = useState<string>('latest');
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [dashboardExists, setDashboardExists] = useState(false);
  const [bandProduct, setBandProduct] = useState<string>('');
  const searchParams = new URLSearchParams(search);
  const explicitOpenUrl = searchParams.get('open');
  const localMode = typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const latestRun = availableRuns[0] ?? null;
  const selectedRun =
    selectedRunId === 'latest'
      ? latestRun
      : availableRuns.find(run => run.id === selectedRunId) ?? latestRun;
  const localHasAnyDashboard = dashboardExists || availableRuns.length > 0;
  const localFallbackOpenUrl = localMode
    ? selectedRun?.dashboardUrl ?? (localHasAnyDashboard ? '/dashboard.json' : null)
    : null;
  const localStatusUrl = localMode ? '/__prosperity4mcbt__/status.json' : null;
  const openUrl = explicitOpenUrl ?? localFallbackOpenUrl;
  const effectiveOpenUrl = openUrl;
  const dashboard = effectiveOpenUrl === null ? storedDashboard : loadedUrl === effectiveOpenUrl ? localDashboard : null;

  useEffect(() => {
    if (localStatusUrl === null || explicitOpenUrl !== null) {
      return;
    }

    let cancelled = false;
    let previousVersion: string | null = null;

    const poll = async (): Promise<void> => {
      try {
        const response = await axios.get<LocalDashboardStatus>(localStatusUrl, {
          headers: {
            'Cache-Control': 'no-cache',
            Pragma: 'no-cache',
          },
        });

        if (cancelled) {
          return;
        }

        const runs = response.data.runs ?? [];
        setAvailableRuns(runs);
        setDashboardExists(response.data.dashboardExists);
        setStatusLoaded(true);

        if (runs.length === 0) {
          setSelectedRunId('latest');
        } else {
          setSelectedRunId(previous => {
            if (previous === 'latest') {
              return 'latest';
            }
            return runs.some(run => run.id === previous) ? previous : 'latest';
          });
        }

        if (!response.data.dashboardExists || response.data.dashboardMtimeMs === null) {
          return;
        }

        const currentRun =
          response.data.currentRunId === undefined || response.data.currentRunId === null
            ? runs[0]
            : runs.find(run => run.id === response.data.currentRunId) ?? runs[0];
        const selectedForVersion = selectedRunId === 'latest' ? currentRun : runs.find(run => run.id === selectedRunId) ?? currentRun;
        const nextVersion = selectedForVersion === undefined ? String(response.data.dashboardMtimeMs) : String(selectedForVersion.mtimeMs);
        if (previousVersion !== nextVersion) {
          previousVersion = nextVersion;
          setDashboardVersion(nextVersion);
        }
      } catch {
        if (!cancelled) {
          setStatus('Waiting for local dashboard');
        }
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 1500);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [explicitOpenUrl, localStatusUrl, selectedRunId]);

  useEffect(() => {
    if (effectiveOpenUrl === null) {
      setLoadError(null);
      setStatus('Loading Monte Carlo dashboard');
      setLocalDashboard(null);
      setLoadedUrl(null);
      return;
    }

    if (effectiveOpenUrl.trim().length === 0) {
      return;
    }

    let cancelled = false;
    setLoadError(null);
    setStatus('Fetching dashboard');
    setLocalDashboard(null);
    setLoadedUrl(null);
    const load = async (): Promise<void> => {
      try {
        const response = await axios.get(effectiveOpenUrl, {
          headers: {
            'Cache-Control': 'no-cache',
            Pragma: 'no-cache',
          },
        });
        const parsed = parseVisualizerInput(response.data);

        if (cancelled) {
          return;
        }

        if (parsed.kind === 'monteCarlo') {
          setLocalDashboard(parsed.monteCarlo);
          setLoadedUrl(effectiveOpenUrl);
          setStatus('Dashboard loaded');
          return;
        }

        setLoadError(new Error('This visualizer build only supports Monte Carlo dashboard bundles.'));
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLoadError(error as Error);
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, [effectiveOpenUrl]);

  useEffect(() => {
    if (dashboard?.bandSeries === undefined) {
      return;
    }
    if (dashboard.bandSeries[bandProduct] !== undefined) {
      return;
    }
    const fallback = Object.keys(dashboard.bandSeries)[0];
    if (fallback !== undefined) {
      setBandProduct(fallback);
    }
  }, [bandProduct, dashboard]);

  if (dashboard === null) {
    if (loadError !== null) {
      return <ErrorMonteCarloView error={loadError} />;
    }

    if (localMode && explicitOpenUrl === null && statusLoaded && !localHasAnyDashboard) {
      return <EmptyMonteCarloView />;
    }

    return <LoadingMonteCarloView status={status} />;
  }

  const strategyName = basename(dashboard.meta.algorithmPath);
  const assets = (dashboard.meta.activeAssets ?? Object.keys(dashboard.products ?? {})).filter(
    asset => dashboard.products?.[asset] !== undefined,
  );
  const assetPalette = ['#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];
  const colorForAsset = (asset: string): string => assetPalette[assets.indexOf(asset) % assetPalette.length] ?? '#868e96';
  const TOTAL_COLOR = '#4c6ef5';

  const totalTrend = dashboard.trendFits.TOTAL;
  const scatterFit = dashboard.scatterFit;
  const selectedBandSeries = dashboard.bandSeries?.[bandProduct];
  const bandOptions = Object.keys(dashboard.bandSeries ?? {}).map(product => ({ value: product, label: product }));

  const totalHistogramSeries: Highcharts.SeriesOptionsType[] = [
    histogramSeries(dashboard.histograms.totalPnl, 'Total PnL', TOTAL_COLOR),
    normalFitSeries(dashboard.normalFits.totalPnl),
  ];

  const profitabilitySeries: Highcharts.SeriesOptionsType[] = [
    distributionLineSeries(dashboard.histograms.totalProfitability, 'Total', TOTAL_COLOR),
    ...assets
      .filter(asset => dashboard.histograms[`${asset}_profitability`] !== undefined)
      .map(asset => distributionLineSeries(dashboard.histograms[`${asset}_profitability`], asset, colorForAsset(asset))),
  ];
  const stabilitySeries: Highcharts.SeriesOptionsType[] = [
    distributionLineSeries(dashboard.histograms.totalStability, 'Total', TOTAL_COLOR),
    ...assets
      .filter(asset => dashboard.histograms[`${asset}_stability`] !== undefined)
      .map(asset => distributionLineSeries(dashboard.histograms[`${asset}_stability`], asset, colorForAsset(asset))),
  ];

  const scatterAssets = scatterFit !== undefined && assets.length === 2 ? (assets as [string, string]) : null;
  const scatterSeries: Highcharts.SeriesOptionsType[] | null = scatterAssets && scatterFit
    ? [
        {
          type: 'scatter',
          name: 'Sessions',
          color: TOTAL_COLOR,
          data: dashboard.sessions.map(row => [
            row.perAsset?.[scatterAssets[0]]?.pnl ?? 0,
            row.perAsset?.[scatterAssets[1]]?.pnl ?? 0,
          ]),
        },
        {
          type: 'line',
          name: 'Linear fit',
          color: '#fa5252',
          lineWidth: 2,
          data: scatterFit.line,
        },
      ]
    : null;

  return (
    <Container fluid py="md">
      <Grid>
        <Grid.Col span={12}>
          <VisualizerCard>
            <Group justify="space-between" align="flex-start">
              <div>
                <Title order={2}>Monte Carlo Results</Title>
                <Text c="dimmed">{strategyName}</Text>
              </div>
              <Group gap="xs" align="flex-start">
                {explicitOpenUrl === null && localMode && availableRuns.length > 0 && (
                  <Select
                    w={260}
                    label="Run"
                    value={selectedRunId}
                    onChange={value => setSelectedRunId(value ?? 'latest')}
                    allowDeselect={false}
                    data={[
                      {
                        value: 'latest',
                        label: `Latest (${latestRun?.label ?? 'none'})`,
                      },
                      ...availableRuns.map(run => ({
                        value: run.id,
                        label: run.label,
                      })),
                    ]}
                  />
                )}
                <Badge variant="light">{dashboard.meta.sessionCount} sessions</Badge>
                <Badge variant="light">{dashboard.meta.bandSessionCount ?? dashboard.meta.sampleSessions} path traces</Badge>
                <Badge variant="light">{dashboard.meta.fvMode}</Badge>
                <Badge variant="light">{dashboard.meta.tradeMode}</Badge>
              </Group>
            </Group>
          </VisualizerCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 6 }}>
          <VisualizerCard title="Mean Total PnL">
            <Title order={2}>{formatNumber(dashboard.overall.totalPnl.mean)}</Title>
            <Text c="dimmed" size="sm">
              95% mean CI {formatNumber(dashboard.overall.totalPnl.meanConfidenceLow95)} to{' '}
              {formatNumber(dashboard.overall.totalPnl.meanConfidenceHigh95)}
            </Text>
          </VisualizerCard>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <VisualizerCard title="Total PnL 1σ">
            <Title order={2}>{formatNumber(dashboard.overall.totalPnl.std)}</Title>
            <Text c="dimmed" size="sm">
              P05 {formatNumber(dashboard.overall.totalPnl.p05)} · P95 {formatNumber(dashboard.overall.totalPnl.p95)}
            </Text>
          </VisualizerCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 8 }}>
          <VisualizerCard title="Profitability And Statistics">
            <Table striped withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Metric</Table.Th>
                  <Table.Th>Meaning</Table.Th>
                  <Table.Th>Total</Table.Th>
                  {assets.map(asset => (
                    <Table.Th key={`stats-head-${asset}`}>{asset}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Td>Profitability</Table.Td>
                  <Table.Td>Mean fitted MTM slope in dollars per step.</Table.Td>
                  <Table.Td>{formatSlope(totalTrend.profitability.mean)}</Table.Td>
                  {assets.map(asset => (
                    <Table.Td key={`stats-prof-mean-${asset}`}>
                      {formatSlope(dashboard.trendFits[asset]?.profitability.mean ?? 0)}
                    </Table.Td>
                  ))}
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Stability</Table.Td>
                  <Table.Td>Mean linear-fit R². Higher means steadier PnL paths.</Table.Td>
                  <Table.Td>{formatNumber(totalTrend.stability.mean, 3)}</Table.Td>
                  {assets.map(asset => (
                    <Table.Td key={`stats-stab-mean-${asset}`}>
                      {formatNumber(dashboard.trendFits[asset]?.stability.mean ?? 0, 3)}
                    </Table.Td>
                  ))}
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Profitability 1σ</Table.Td>
                  <Table.Td>Cross-session spread of profitability.</Table.Td>
                  <Table.Td>{formatSlope(totalTrend.profitability.std)}</Table.Td>
                  {assets.map(asset => (
                    <Table.Td key={`stats-prof-std-${asset}`}>
                      {formatSlope(dashboard.trendFits[asset]?.profitability.std ?? 0)}
                    </Table.Td>
                  ))}
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Stability 1σ</Table.Td>
                  <Table.Td>Cross-session spread of stability.</Table.Td>
                  <Table.Td>{formatNumber(totalTrend.stability.std, 3)}</Table.Td>
                  {assets.map(asset => (
                    <Table.Td key={`stats-stab-std-${asset}`}>
                      {formatNumber(dashboard.trendFits[asset]?.stability.std ?? 0, 3)}
                    </Table.Td>
                  ))}
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </VisualizerCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 4 }}>
          <VisualizerCard title="Fair Value Models">
            {Object.keys(dashboard.generatorModel ?? {}).length === 0 ? (
              <Text c="dimmed" size="sm">No generator-model metadata in this dashboard.</Text>
            ) : (
              <Table withTableBorder withColumnBorders>
                <Table.Tbody>
                  {Object.entries(dashboard.generatorModel).map(([asset, model]) => (
                    <Table.Tr key={`gen-${asset}`}>
                      <Table.Td>{asset}</Table.Td>
                      <Table.Td>
                        <Text fw={500}>{model.formula}</Text>
                        {model.notes[0] !== undefined && (
                          <Text size="sm" c="dimmed">
                            {model.notes[0]}
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </VisualizerCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: Math.max(3, Math.floor(12 / (assets.length + 1))) }}>
          <SummaryTable title="Total PnL Summary" stats={dashboard.overall.totalPnl} />
        </Grid.Col>
        {assets.map(asset => {
          const stats = dashboard.products[asset]?.pnl;
          if (stats === undefined) return null;
          return (
            <Grid.Col
              key={`summary-${asset}`}
              span={{ base: 12, md: Math.max(3, Math.floor(12 / (assets.length + 1))) }}
            >
              <SummaryTable title={`${asset} PnL Summary`} stats={stats} />
            </Grid.Col>
          );
        })}

        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Total PnL Distribution"
            subtitle={`Normal fit μ ${formatNumber(dashboard.normalFits.totalPnl.mean)} · σ ${formatNumber(dashboard.normalFits.totalPnl.std)} · R² ${formatNumber(dashboard.normalFits.totalPnl.r2, 3)}`}
            series={totalHistogramSeries}
            options={{
              xAxis: { title: { text: 'Final total pnl' } },
              yAxis: { title: { text: 'Session count' } },
            }}
          />
        </Grid.Col>
        {scatterSeries && scatterAssets && scatterFit && (
          <Grid.Col span={{ base: 12, md: 6 }}>
            <SimpleChart
              title="Cross Product Scatter"
              subtitle={`corr ${formatNumber(scatterFit.correlation, 3)} · fit R² ${formatNumber(scatterFit.r2, 3)} · ${scatterFit.diagnosis}`}
              series={scatterSeries}
              options={{
                xAxis: { title: { text: `${scatterAssets[0]} pnl` } },
                yAxis: { title: { text: `${scatterAssets[1]} pnl` } },
              }}
            />
          </Grid.Col>
        )}
        {assets.map(asset => {
          const hist = dashboard.histograms[`${asset}_pnl`];
          const fit = dashboard.normalFits[`${asset}_pnl`];
          if (hist === undefined || fit === undefined) return null;
          return (
            <Grid.Col key={`hist-${asset}`} span={{ base: 12, md: 6 }}>
              <SimpleChart
                title={`${asset} PnL Distribution`}
                subtitle={`Normal fit μ ${formatNumber(fit.mean)} · σ ${formatNumber(fit.std)} · R² ${formatNumber(fit.r2, 3)}`}
                series={[
                  histogramSeries(hist, `${asset} PnL`, colorForAsset(asset)),
                  normalFitSeries(fit),
                ]}
                options={{
                  xAxis: { title: { text: `${asset} final pnl` } },
                  yAxis: { title: { text: 'Session count' } },
                }}
              />
            </Grid.Col>
          );
        })}

        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Profitability Distribution"
            subtitle="Per-session fitted MTM slope in dollars per step"
            series={profitabilitySeries}
            options={{
              xAxis: {
                title: { text: '$ / step' },
                labels: {
                  formatter(this: Highcharts.AxisLabelsFormatterContextObject) {
                    return formatNumber(Number(this.value), 4);
                  },
                },
              },
              yAxis: { title: { text: 'Density proxy' } },
            }}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SimpleChart
            title="Stability Distribution"
            subtitle="Per-session linear-fit R²"
            series={stabilitySeries}
            options={{
              xAxis: {
                title: { text: 'R²' },
                labels: {
                  formatter(this: Highcharts.AxisLabelsFormatterContextObject) {
                    return formatNumber(Number(this.value), 3);
                  },
                },
              },
              yAxis: { title: { text: 'Density proxy' } },
            }}
          />
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 6 }}>
          <SessionRankingTable title="Best Sessions" rows={dashboard.topSessions} assets={assets} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <SessionRankingTable title="Worst Sessions" rows={dashboard.bottomSessions} assets={assets} />
        </Grid.Col>

        {selectedBandSeries && (
          <>
            <Grid.Col span={12}>
              <VisualizerCard title="Path Boards">
                <Group justify="space-between" align="center">
                  <Text c="dimmed" size="sm">
                    Mean path with ±1σ and ±3σ bands across {dashboard.meta.bandSessionCount ?? dashboard.meta.sampleSessions} sessions.
                  </Text>
                  <Select
                    w={220}
                    data={bandOptions}
                    value={bandProduct}
                    onChange={value => {
                      if (value !== null) setBandProduct(value);
                    }}
                    allowDeselect={false}
                  />
                </Group>
              </VisualizerCard>
            </Grid.Col>
            <Grid.Col span={12}>
              <SimpleChart
                title={`${bandProduct} Fair Value`}
                series={buildBandChartSeries(selectedBandSeries.fair, colorForAsset(bandProduct))}
                options={{
                  xAxis: {
                    title: { text: 'Step' },
                  },
                  yAxis: { title: { text: 'Fair value' } },
                }}
              />
            </Grid.Col>
            <Grid.Col span={12}>
              <SimpleChart
                title={`${bandProduct} MTM PnL`}
                series={[
                  ...buildBandChartSeries(selectedBandSeries.mtmPnl, colorForAsset(bandProduct)),
                  lineSeries('Zero', '#868e96', selectedBandSeries.mtmPnl.timestamps, selectedBandSeries.mtmPnl.timestamps.map(() => 0), 'ShortDash'),
                ]}
                options={{
                  xAxis: {
                    title: { text: 'Step' },
                  },
                  yAxis: { title: { text: 'MTM pnl' } },
                }}
              />
            </Grid.Col>
            <Grid.Col span={12}>
              <SimpleChart
                title={`${bandProduct} Position`}
                series={[
                  ...buildBandChartSeries(selectedBandSeries.position, colorForAsset(bandProduct)),
                  lineSeries('Zero', '#868e96', selectedBandSeries.position.timestamps, selectedBandSeries.position.timestamps.map(() => 0), 'ShortDash'),
                ]}
                options={{
                  xAxis: {
                    title: { text: 'Step' },
                  },
                  yAxis: { title: { text: 'Position' } },
                }}
              />
            </Grid.Col>
          </>
        )}
      </Grid>
    </Container>
  );
}
