import {
  Alert,
  Badge,
  Container,
  Grid,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import axios from 'axios';
import Highcharts from 'highcharts';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { ScrollableCodeHighlight } from '../../components/ScrollableCodeHighlight.tsx';
import { formatNumber } from '../../utils/format.ts';
import { SimpleChart } from '../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../visualizer/VisualizerCard.tsx';
import { TradesTable } from './TradesTable.tsx';

interface SubmissionListEntry {
  name: string;
  sizeBytes: number;
  mtimeMs: number;
  round: string | null;
  status: string | null;
  profit: number | null;
  submissionId: string | null;
  traderName: string | null;
}

interface ActivityRow {
  day: number;
  timestamp: number;
  product: string;
  bidPrices: number[];
  bidVolumes: number[];
  askPrices: number[];
  askVolumes: number[];
  midPrice: number | null;
  profitLoss: number | null;
}

export interface SubmissionTrade {
  timestamp: number;
  buyer: string;
  seller: string;
  symbol: string;
  currency: string;
  price: number;
  quantity: number;
}

interface SubmissionDetail {
  name: string;
  summary: {
    submissionId: string | null;
    round: string | null;
    status: string | null;
    profit: number | null;
    positions: Array<{ symbol: string; quantity: number }>;
    sizeBytes: number;
    mtimeMs: number;
  };
  activities: ActivityRow[];
  trades: SubmissionTrade[];
  pnlSeries: Array<{ timestamp: number; value: number }>;
  ticks: Array<{ sandboxLog: string; lambdaLog: string; timestamp: number }>;
  code: string;
}

const ASSET_PALETTE = ['#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

function colorForAsset(asset: string, assets: string[]): string {
  const idx = assets.indexOf(asset);
  return ASSET_PALETTE[idx >= 0 ? idx % ASSET_PALETTE.length : 0];
}

function uniqueProducts(activities: ActivityRow[]): string[] {
  const seen = new Set<string>();
  for (const r of activities) {
    if (r.product) seen.add(r.product);
  }
  return Array.from(seen).sort();
}

export function SubmissionsPage(): ReactNode {
  const [list, setList] = useState<SubmissionListEntry[]>([]);
  const [listError, setListError] = useState<Error | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [detailError, setDetailError] = useState<Error | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios
      .get<{ submissions: SubmissionListEntry[] }>('/__prosperity4mcbt__/submissions/list')
      .then(res => {
        if (cancelled) return;
        setList(res.data.submissions);
        if (res.data.submissions.length > 0 && selectedName === null) {
          setSelectedName(res.data.submissions[0].name);
        }
      })
      .catch(err => {
        if (!cancelled) setListError(err as Error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (selectedName === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    setDetailError(null);
    setDetail(null);
    axios
      .get<SubmissionDetail>('/__prosperity4mcbt__/submissions/file', {
        params: { name: selectedName },
      })
      .then(res => {
        if (!cancelled) setDetail(res.data);
      })
      .catch(err => {
        if (!cancelled) setDetailError(err as Error);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedName]);

  return (
    <Container fluid py="md">
      <Stack gap="md">
        <VisualizerCard>
          <Group justify="space-between" align="flex-end" wrap="wrap">
            <div>
              <Title order={2}>Portal Submissions</Title>
              <Text c="dimmed" size="sm">
                Drop portal-backtester zips into <code>submissions/</code> to view them here.
              </Text>
            </div>
            <Select
              w={420}
              label={`Submission (${list.length} available)`}
              placeholder={list.length === 0 ? 'No submissions found' : 'Select submission'}
              value={selectedName}
              onChange={value => setSelectedName(value)}
              disabled={list.length === 0}
              allowDeselect={false}
              data={list.map(entry => ({
                value: entry.name,
                label: formatListLabel(entry),
              }))}
            />
          </Group>
        </VisualizerCard>

        {listError && (
          <Alert color="red" title="Failed to list submissions">
            {listError.message}
          </Alert>
        )}

        {detailError && (
          <Alert color="red" title="Failed to load submission">
            {detailError.message}
          </Alert>
        )}

        {loadingDetail && (
          <Group>
            <Loader size="sm" />
            <Text c="dimmed">Loading submission…</Text>
          </Group>
        )}

        {detail && <SubmissionDetailView detail={detail} />}

        {!loadingDetail && detail === null && list.length === 0 && !listError && (
          <Alert color="blue" title="No submissions yet">
            Place portal-backtester zips (e.g. <code>209780.zip</code>) into the project's{' '}
            <code>submissions/</code> directory and refresh.
          </Alert>
        )}
      </Stack>
    </Container>
  );
}

function formatListLabel(entry: SubmissionListEntry): string {
  const profit = entry.profit === null ? 'n/a' : formatNumber(entry.profit);
  const round = entry.round === null ? '?' : `R${entry.round}`;
  return `${entry.name} · ${round} · PnL ${profit}`;
}

function SubmissionDetailView({ detail }: { detail: SubmissionDetail }): ReactNode {
  const products = useMemo(() => uniqueProducts(detail.activities), [detail.activities]);
  const [selectedProduct, setSelectedProduct] = useState<string>('');

  useEffect(() => {
    if (products.length > 0 && !products.includes(selectedProduct)) {
      setSelectedProduct(products[0]);
    }
  }, [products, selectedProduct]);

  const totalPnl = detail.summary.profit ?? 0;
  const finalPnl = detail.pnlSeries.length > 0 ? detail.pnlSeries[detail.pnlSeries.length - 1].value : 0;

  const pnlSeries: Highcharts.SeriesOptionsType[] = [
    {
      type: 'line',
      name: 'Total PnL',
      color: '#4c6ef5',
      lineWidth: 2,
      data: detail.pnlSeries.map(p => [p.timestamp, p.value]),
    },
  ];

  const productSeries = useMemo(() => {
    if (!selectedProduct) return [] as Highcharts.SeriesOptionsType[];
    const rows = detail.activities.filter(a => a.product === selectedProduct);
    const mid = rows.map(r => [r.timestamp, r.midPrice ?? null] as [number, number | null]);
    const bestBid = rows.map(r => [r.timestamp, r.bidPrices[0] ?? null] as [number, number | null]);
    const bestAsk = rows.map(r => [r.timestamp, r.askPrices[0] ?? null] as [number, number | null]);

    const buys = detail.trades
      .filter(t => t.symbol === selectedProduct && t.buyer === 'SUBMISSION')
      .map(t => [t.timestamp, t.price] as [number, number]);
    const sells = detail.trades
      .filter(t => t.symbol === selectedProduct && t.seller === 'SUBMISSION')
      .map(t => [t.timestamp, t.price] as [number, number]);

    return [
      { type: 'line', name: 'Mid', color: colorForAsset(selectedProduct, products), lineWidth: 1.5, data: mid },
      { type: 'line', name: 'Best bid', color: '#15aabf', dashStyle: 'ShortDash', lineWidth: 1, data: bestBid },
      { type: 'line', name: 'Best ask', color: '#fa5252', dashStyle: 'ShortDash', lineWidth: 1, data: bestAsk },
      {
        type: 'scatter',
        name: 'Our buys',
        color: '#12b886',
        marker: { symbol: 'triangle', radius: 4 },
        data: buys,
      },
      {
        type: 'scatter',
        name: 'Our sells',
        color: '#fa5252',
        marker: { symbol: 'triangle-down', radius: 4 },
        data: sells,
      },
    ] as Highcharts.SeriesOptionsType[];
  }, [detail.activities, detail.trades, selectedProduct, products]);

  const productPnlSeries = useMemo(() => {
    if (!selectedProduct) return [] as Highcharts.SeriesOptionsType[];
    const rows = detail.activities.filter(a => a.product === selectedProduct);
    return [
      {
        type: 'line',
        name: `${selectedProduct} P&L`,
        color: colorForAsset(selectedProduct, products),
        lineWidth: 1.5,
        data: rows.map(r => [r.timestamp, r.profitLoss ?? 0] as [number, number]),
      },
    ] as Highcharts.SeriesOptionsType[];
  }, [detail.activities, selectedProduct, products]);

  const tradeStats = useMemo(() => {
    const ours = detail.trades.filter(t => t.buyer === 'SUBMISSION' || t.seller === 'SUBMISSION');
    const buys = ours.filter(t => t.buyer === 'SUBMISSION');
    const sells = ours.filter(t => t.seller === 'SUBMISSION');
    const buyVol = buys.reduce((acc, t) => acc + t.quantity, 0);
    const sellVol = sells.reduce((acc, t) => acc + t.quantity, 0);
    const market = detail.trades.length - ours.length;
    return { ours: ours.length, buys: buys.length, sells: sells.length, buyVol, sellVol, market };
  }, [detail.trades]);

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 8 }}>
        <VisualizerCard>
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <div>
              <Title order={3}>Submission {detail.summary.submissionId?.slice(0, 8) ?? detail.name}</Title>
              <Text c="dimmed" size="sm">{detail.name}</Text>
            </div>
            <Group gap="xs">
              {detail.summary.round && <Badge variant="light">Round {detail.summary.round}</Badge>}
              {detail.summary.status && (
                <Badge color={detail.summary.status === 'FINISHED' ? 'green' : 'gray'} variant="light">
                  {detail.summary.status}
                </Badge>
              )}
              <Badge color={totalPnl >= 0 ? 'green' : 'red'} variant="filled" size="lg">
                PnL {formatNumber(totalPnl, 2)}
              </Badge>
            </Group>
          </Group>
        </VisualizerCard>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 4 }}>
        <VisualizerCard title="Trade summary">
          <Table>
            <Table.Tbody>
              <Table.Tr>
                <Table.Td>Our trades</Table.Td>
                <Table.Td ta="right">{tradeStats.ours}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Buys / sells</Table.Td>
                <Table.Td ta="right">
                  {tradeStats.buys} / {tradeStats.sells}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Buy / sell volume</Table.Td>
                <Table.Td ta="right">
                  {formatNumber(tradeStats.buyVol)} / {formatNumber(tradeStats.sellVol)}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Market trades observed</Table.Td>
                <Table.Td ta="right">{tradeStats.market}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Final tick PnL</Table.Td>
                <Table.Td ta="right">{formatNumber(finalPnl, 2)}</Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </VisualizerCard>
      </Grid.Col>

      <Grid.Col span={12}>
        <VisualizerCard title="Final positions">
          <Table withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Symbol</Table.Th>
                <Table.Th ta="right">Quantity</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {detail.summary.positions.map(p => (
                <Table.Tr key={p.symbol}>
                  <Table.Td>{p.symbol}</Table.Td>
                  <Table.Td ta="right">{formatNumber(p.quantity)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </VisualizerCard>
      </Grid.Col>

      <Grid.Col span={12}>
        <SimpleChart
          title="Total PnL over time"
          series={pnlSeries}
          options={{
            xAxis: { title: { text: 'Timestamp' } },
            yAxis: { title: { text: 'XIRECs' } },
          }}
        />
      </Grid.Col>

      {products.length > 0 && (
        <>
          <Grid.Col span={12}>
            <VisualizerCard>
              <Group justify="space-between">
                <Text fw={600}>Per-product view</Text>
                <Select
                  w={260}
                  data={products.map(p => ({ value: p, label: p }))}
                  value={selectedProduct}
                  onChange={value => value && setSelectedProduct(value)}
                  allowDeselect={false}
                />
              </Group>
            </VisualizerCard>
          </Grid.Col>
          <Grid.Col span={12}>
            <SimpleChart
              title={`${selectedProduct} prices and our fills`}
              series={productSeries}
              options={{
                xAxis: { title: { text: 'Timestamp' } },
                yAxis: { title: { text: 'Price' } },
              }}
            />
          </Grid.Col>
          <Grid.Col span={12}>
            <SimpleChart
              title={`${selectedProduct} per-product P&L (portal-reported)`}
              series={productPnlSeries}
              options={{
                xAxis: { title: { text: 'Timestamp' } },
                yAxis: { title: { text: 'XIRECs' } },
              }}
            />
          </Grid.Col>
        </>
      )}

      <Grid.Col span={12}>
        <VisualizerCard title={`Trades (${detail.trades.length})`}>
          <TradesTable trades={detail.trades} />
        </VisualizerCard>
      </Grid.Col>

      <Grid.Col span={12}>
        <VisualizerCard title={`Trader code (${detail.code.length.toLocaleString()} chars)`}>
          <ScrollableCodeHighlight code={detail.code} language="python" />
        </VisualizerCard>
      </Grid.Col>

      <Grid.Col span={12}>
        <VisualizerCard title={`Lambda log ticks (${detail.ticks.length})`}>
          <Text c="dimmed" size="sm" mb="xs">
            Sandbox + lambda log per tick from the portal. Pick a tick to see the raw payload.
          </Text>
          <TickInspector ticks={detail.ticks} />
        </VisualizerCard>
      </Grid.Col>
    </Grid>
  );
}

function TickInspector({ ticks }: { ticks: SubmissionDetail['ticks'] }): ReactNode {
  const [idx, setIdx] = useState<string | null>(null);

  useEffect(() => {
    if (ticks.length > 0 && idx === null) setIdx('0');
  }, [ticks, idx]);

  const current = idx === null ? null : ticks[Number(idx)];

  return (
    <Stack gap="xs">
      <Select
        w={260}
        label="Timestamp"
        data={ticks.map((t, i) => ({ value: String(i), label: `t=${t.timestamp}` }))}
        value={idx}
        onChange={value => setIdx(value)}
        searchable
        allowDeselect={false}
      />
      {current && (
        <Stack gap="xs">
          {current.sandboxLog && (
            <ScrollableCodeHighlight code={current.sandboxLog} language="json" />
          )}
          <ScrollableCodeHighlight code={current.lambdaLog || '(empty)'} language="json" />
        </Stack>
      )}
    </Stack>
  );
}
