import {
  Alert,
  Badge,
  Box,
  Container,
  Grid,
  Group,
  Loader,
  MultiSelect,
  Select,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core';
import axios from 'axios';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { VisualizerCard } from '../visualizer/VisualizerCard.tsx';
import { concatTables, ConcatenatedTable } from './concat.ts';
import { preparePrices, prepareTrades } from './compute/project.ts';
import { fetchTree, loadTable } from './loader.ts';
import { CorrMatrixPanel } from './panels/CorrMatrixPanel.tsx';
import { CounterpartyPivot } from './panels/CounterpartyPivot.tsx';
import { DepthAreaPanel } from './panels/DepthAreaPanel.tsx';
import { EffRealizedPanel } from './panels/EffRealizedPanel.tsx';
import { LeadLagPanel } from './panels/LeadLagPanel.tsx';
import { MarkoutPanel } from './panels/MarkoutPanel.tsx';
import { MidPricePanel } from './panels/MidPricePanel.tsx';
import { ObsBetaPanel } from './panels/ObsBetaPanel.tsx';
import { ObservationsLinesPanel } from './panels/ObservationsLinesPanel.tsx';
import { OffsetFromMidPanel } from './panels/OffsetFromMidPanel.tsx';
import { OfiPanel } from './panels/OfiPanel.tsx';
import { PairSpreadPanel } from './panels/PairSpreadPanel.tsx';
import { QueueImbalancePanel } from './panels/QueueImbalancePanel.tsx';
import { SchemaCard } from './panels/SchemaCard.tsx';
import { SeasonalityPanel } from './panels/SeasonalityPanel.tsx';
import { SpreadPanel } from './panels/SpreadPanel.tsx';
import { TradeTape } from './panels/TradeTape.tsx';
import { ParsedTable, TreeEntry } from './types.ts';

const ALL_DAYS = '__all__';

function uniqSorted<T>(values: Iterable<T>, compare?: (a: T, b: T) => number): T[] {
  const out = [...new Set(values)];
  if (compare) out.sort(compare);
  else out.sort();
  return out;
}

export function WorkshopPage(): ReactNode {
  const [tree, setTree] = useState<TreeEntry[] | null>(null);
  const [treeError, setTreeError] = useState<Error | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [round, setRound] = useState<string | null>(null);
  const [daySelection, setDaySelection] = useState<string>(ALL_DAYS);
  const [products, setProducts] = useState<string[]>([]);
  const [pricesTable, setPricesTable] = useState<ConcatenatedTable | null>(null);
  const [tradesTable, setTradesTable] = useState<ConcatenatedTable | null>(null);
  const [observationsTable, setObservationsTable] = useState<ConcatenatedTable | null>(null);
  const [otherTables, setOtherTables] = useState<ParsedTable[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<Error | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const files = await fetchTree();
        setTree(files);
      } catch (err) {
        setTreeError(err as Error);
      }
    })();
  }, []);

  const versions = useMemo(
    () => uniqSorted(tree?.map(e => e.version) ?? []),
    [tree],
  );
  const rounds = useMemo(
    () => uniqSorted((tree ?? []).filter(e => e.version === version).map(e => e.round)),
    [tree, version],
  );
  const dayEntries = useMemo(
    () => (tree ?? []).filter(e => e.version === version && e.round === round),
    [tree, version, round],
  );
  const days = useMemo(
    () => uniqSorted(
      dayEntries.filter(e => e.day !== null).map(e => e.day as number),
      (a, b) => a - b,
    ),
    [dayEntries],
  );

  // Default selections when data arrives
  useEffect(() => {
    if (version === null && versions.length > 0) {
      const preferred = versions.find(v => v === 'prosperity4') ?? versions[versions.length - 1];
      setVersion(preferred);
    }
  }, [version, versions]);

  useEffect(() => {
    if (round === null || !rounds.includes(round)) {
      setRound(rounds[rounds.length - 1] ?? null);
    }
  }, [rounds, round]);

  useEffect(() => {
    setDaySelection(ALL_DAYS);
  }, [version, round]);

  // Load data for the current selection
  useEffect(() => {
    if (tree === null || version === null || round === null) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setPricesTable(null);
    setTradesTable(null);
    setObservationsTable(null);
    setOtherTables([]);

    const candidates = dayEntries.filter(entry => {
      if (daySelection === ALL_DAYS) return true;
      return String(entry.day) === daySelection;
    });

    const byRole: Record<string, TreeEntry[]> = { prices: [], trades: [], observations: [], other: [] };
    for (const entry of candidates) byRole[entry.role].push(entry);

    (async () => {
      try {
        const [prices, trades, observations, others] = await Promise.all([
          Promise.all(byRole.prices.map(loadTable)),
          Promise.all(byRole.trades.map(loadTable)),
          Promise.all(byRole.observations.map(loadTable)),
          Promise.all(byRole.other.map(loadTable)),
        ]);
        if (cancelled) return;
        setPricesTable(concatTables(prices));
        setTradesTable(concatTables(trades));
        setObservationsTable(concatTables(observations));
        setOtherTables(others);
      } catch (err) {
        if (cancelled) return;
        if (axios.isAxiosError(err)) {
          setLoadError(new Error(`Failed to load CSVs: ${err.message}`));
        } else {
          setLoadError(err as Error);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [tree, version, round, daySelection, dayEntries]);

  const preparedPrices = useMemo(() => preparePrices(pricesTable), [pricesTable]);
  const preparedTrades = useMemo(() => prepareTrades(tradesTable), [tradesTable]);

  const availableProducts = useMemo(() => {
    const fromPrices = pricesTable?.shape.products ?? [];
    const fromTrades = tradesTable?.shape.products ?? [];
    return uniqSorted([...fromPrices, ...fromTrades]);
  }, [pricesTable, tradesTable]);

  // Keep the product multi-select in bounds; default to all products
  useEffect(() => {
    if (availableProducts.length === 0) {
      if (products.length !== 0) setProducts([]);
      return;
    }
    const filtered = products.filter(p => availableProducts.includes(p));
    if (filtered.length === 0) {
      setProducts(availableProducts);
    } else if (filtered.length !== products.length) {
      setProducts(filtered);
    }
  }, [availableProducts, products]);

  const activeProducts = products.length > 0 ? products : availableProducts;

  if (treeError !== null) {
    return (
      <Container size="md" py="xl">
        <Alert color="red" title="Failed to load data tree">
          {treeError.message}
        </Alert>
      </Container>
    );
  }

  if (tree === null) {
    return (
      <Container size="md" py="xl">
        <Group>
          <Loader size="sm" />
          <Text>Scanning data/ directory…</Text>
        </Group>
      </Container>
    );
  }

  if (versions.length === 0) {
    return (
      <Container size="md" py="xl">
        <Alert color="yellow" title="No data found">
          Nothing under <Text span ff="monospace">data/</Text>. Drop CSVs into{' '}
          <Text span ff="monospace">data/prosperity4/round&lt;N&gt;/</Text> and reload.
        </Alert>
      </Container>
    );
  }

  return (
    <Container fluid py="md">
      <Grid>
        <Grid.Col span={{ base: 12, lg: 3 }}>
          <VisualizerCard title="Data Source">
            <Stack gap="sm">
              <Select
                label="Version"
                data={versions.map(v => ({ value: v, label: v }))}
                value={version}
                onChange={setVersion}
                allowDeselect={false}
              />
              <Select
                label="Round"
                data={rounds.map(r => ({ value: r, label: r }))}
                value={round}
                onChange={setRound}
                allowDeselect={false}
                disabled={rounds.length === 0}
              />
              <Select
                label="Day"
                data={[
                  { value: ALL_DAYS, label: `All days (${days.length})` },
                  ...days.map(d => ({ value: String(d), label: `Day ${d}` })),
                ]}
                value={daySelection}
                onChange={value => setDaySelection(value ?? ALL_DAYS)}
                allowDeselect={false}
                disabled={days.length === 0}
              />
              <MultiSelect
                label="Products"
                data={availableProducts}
                value={products}
                onChange={setProducts}
                searchable
                clearable
                placeholder={availableProducts.length === 0 ? 'No products detected' : 'All products'}
                disabled={availableProducts.length === 0}
              />
              <Group gap="xs">
                <Badge variant="light" color="gray">
                  {pricesTable?.rows.length ?? 0} price rows
                </Badge>
                <Badge variant="light" color="gray">
                  {tradesTable?.rows.length ?? 0} trade rows
                </Badge>
                {observationsTable !== null && (
                  <Badge variant="light" color="gray">
                    {observationsTable.rows.length} obs rows
                  </Badge>
                )}
              </Group>
            </Stack>
          </VisualizerCard>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 9 }}>
          {loading && (
            <Box mb="sm">
              <Group>
                <Loader size="sm" />
                <Text>Loading CSVs…</Text>
              </Group>
            </Box>
          )}
          {loadError !== null && (
            <Alert color="red" title="Load error" mb="sm">
              {loadError.message}
            </Alert>
          )}

          <Tabs defaultValue="overview" keepMounted={true}>
            <Tabs.List>
              <Tabs.Tab value="overview">Overview</Tabs.Tab>
              <Tabs.Tab value="lob" disabled={preparedPrices === null || !preparedPrices.hasLadder}>
                LOB
              </Tabs.Tab>
              <Tabs.Tab
                value="mmalpha"
                disabled={preparedPrices === null || preparedTrades === null || !preparedTrades.hasCounterparties}
              >
                MM Alpha
              </Tabs.Tab>
              <Tabs.Tab value="cross" disabled={preparedPrices === null || availableProducts.length < 2}>
                Cross-Asset
              </Tabs.Tab>
              <Tabs.Tab value="exogenous" disabled={preparedPrices === null || observationsTable === null}>
                Exogenous
              </Tabs.Tab>
              <Tabs.Tab value="seasonality" disabled={preparedPrices === null}>
                Seasonality
              </Tabs.Tab>
              <Tabs.Tab value="trades" disabled={tradesTable === null}>
                Trades
              </Tabs.Tab>
              <Tabs.Tab value="counterparty" disabled={tradesTable === null}>
                Counterparty
              </Tabs.Tab>
              <Tabs.Tab value="schema">Schema</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="overview" pt="sm">
              <Grid>
                <Grid.Col span={12}>
                  <VisualizerCard>
                    <Group justify="space-between" align="center">
                      <div>
                        <Title order={3}>Workshop</Title>
                        <Text c="dimmed" size="sm">
                          {version} · {round} · {daySelection === ALL_DAYS ? 'all days' : `day ${daySelection}`} ·{' '}
                          {activeProducts.length} products
                        </Text>
                      </div>
                    </Group>
                  </VisualizerCard>
                </Grid.Col>
                <Grid.Col span={12}>
                  <MidPricePanel prepared={preparedPrices} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <SpreadPanel prepared={preparedPrices} products={activeProducts} />
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="lob" pt="sm">
              <Grid>
                <Grid.Col span={12}>
                  <DepthAreaPanel prepared={preparedPrices} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <QueueImbalancePanel prepared={preparedPrices} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <OfiPanel prepared={preparedPrices} products={activeProducts} />
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="mmalpha" pt="sm">
              <Grid>
                <Grid.Col span={12}>
                  <MarkoutPanel prices={preparedPrices} trades={preparedTrades} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <EffRealizedPanel prices={preparedPrices} trades={preparedTrades} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <OffsetFromMidPanel prices={preparedPrices} trades={preparedTrades} products={activeProducts} />
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="cross" pt="sm">
              <Grid>
                <Grid.Col span={12}>
                  <CorrMatrixPanel prices={preparedPrices} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <LeadLagPanel prices={preparedPrices} products={activeProducts} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <PairSpreadPanel prices={preparedPrices} products={activeProducts} />
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="exogenous" pt="sm">
              <Grid>
                <Grid.Col span={12}>
                  <ObservationsLinesPanel table={observationsTable} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <ObsBetaPanel prices={preparedPrices} observations={observationsTable} products={activeProducts} />
                </Grid.Col>
              </Grid>
            </Tabs.Panel>

            <Tabs.Panel value="seasonality" pt="sm">
              <SeasonalityPanel prices={preparedPrices} products={activeProducts} />
            </Tabs.Panel>

            <Tabs.Panel value="trades" pt="sm">
              <TradeTape table={tradesTable} products={activeProducts} />
            </Tabs.Panel>

            <Tabs.Panel value="counterparty" pt="sm">
              <CounterpartyPivot table={tradesTable} products={activeProducts} />
            </Tabs.Panel>

            <Tabs.Panel value="schema" pt="sm">
              <SchemaCard
                prices={pricesTable}
                trades={tradesTable}
                observations={observationsTable}
                others={otherTables}
              />
            </Tabs.Panel>
          </Tabs>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
