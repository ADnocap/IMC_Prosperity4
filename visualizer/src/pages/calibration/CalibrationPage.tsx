import {
  Alert,
  Badge,
  Box,
  Button,
  Container,
  Divider,
  Grid,
  Group,
  Loader,
  NavLink,
  Select,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { IconCheck, IconAlertTriangle, IconX, IconCircleDashed, IconRefresh } from '@tabler/icons-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { fetchAssets, fetchData, fetchParams } from './loader';
import { ExportPanel } from './panels/ExportPanel';
import { FormulaDiscoveryPanel } from './panels/FormulaDiscoveryPanel';
import { FvProcessPanel } from './panels/FvProcessPanel';
import { LayerDetectionPanel } from './panels/LayerDetectionPanel';
import { NoiseLayerPanel } from './panels/NoiseLayerPanel';
import { PresenceModelPanel } from './panels/PresenceModelPanel';
import { StagePlaceholder } from './panels/StagePlaceholder';
import { TradeBotPanel } from './panels/TradeBotPanel';
import { ValidationPanel } from './panels/ValidationPanel';
import { VolumeModelPanel } from './panels/VolumeModelPanel';
import { Stage2Result } from './stages/formula_discovery';
import { FvFitResult } from './stages/fv_process';
import { Stage1Result } from './stages/layer_detection';
import { Stage5Result } from './stages/noise_layer';
import { Stage4Result } from './stages/presence_model';
import { Stage6Result } from './stages/trade_bot';
import { Stage7Result } from './stages/validation';
import { Stage3Result } from './stages/volume_model';
import { useStagesStore } from './store';
import {
  CalibrationAsset,
  CalibrationParams,
  FvAndBook,
  STAGES,
  StageId,
  StageStatus,
} from './types';

function statusColor(s: StageStatus): string {
  return s === 'pass' ? 'green' : s === 'warn' ? 'yellow' : s === 'fail' ? 'red' : s === 'running' ? 'blue' : 'gray';
}

function statusIcon(s: StageStatus): ReactNode {
  const size = 14;
  if (s === 'pass') return <IconCheck size={size} />;
  if (s === 'warn') return <IconAlertTriangle size={size} />;
  if (s === 'fail') return <IconX size={size} />;
  if (s === 'running') return <Loader size={size} />;
  return <IconCircleDashed size={size} />;
}

export function CalibrationPage(): ReactNode {
  const [assets, setAssets] = useState<CalibrationAsset[]>([]);
  const [assetsError, setAssetsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [data, setData] = useState<FvAndBook | null>(null);
  const [params, setParams] = useState<CalibrationParams | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [activeStage, setActiveStage] = useState<StageId>('fv_process');
  const { stages, update, resetFrom, reset } = useStagesStore();

  // ── Load asset list once ──
  useEffect(() => {
    let cancelled = false;
    fetchAssets()
      .then(list => {
        if (cancelled) return;
        setAssets(list);
        if (list.length > 0 && selected === null) {
          setSelected(list[0].asset);
        }
      })
      .catch(err => { if (!cancelled) setAssetsError(String(err?.message ?? err)); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Load data + params when asset changes ──
  useEffect(() => {
    if (!selected) { setData(null); setParams(null); return; }
    let cancelled = false;
    setLoadingData(true);
    setLoadError(null);
    Promise.all([fetchData(selected), fetchParams(selected)])
      .then(([d, p]) => {
        if (cancelled) return;
        setData(d); setParams(p);
        reset();  // new asset → fresh pipeline state
        setActiveStage('fv_process');
      })
      .catch(err => { if (!cancelled) setLoadError(String(err?.message ?? err)); })
      .finally(() => { if (!cancelled) setLoadingData(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const selectedAsset = useMemo(() => assets.find(a => a.asset === selected) ?? null, [assets, selected]);
  const fvRows = data?.rows.filter(r => r.fv !== null) ?? [];
  const nTrades = data?.trades?.length ?? 0;

  const assetOptions = assets.map(a => ({
    value: a.asset,
    label: `${a.asset}${a.hasData ? '' : ' (no hold-1 data)'}`,
    disabled: !a.hasData,
  }));

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-end">
          <Stack gap={2}>
            <Title order={2}>Calibration</Title>
            <Text size="sm" c="dimmed">
              Discover and validate market-maker bot models from hold-1 submission data.
              Assets discovered from <code>rust_simulator/src/assets/*.rs</code>.
            </Text>
          </Stack>
          <Group gap="xs">
            <Select
              data={assetOptions}
              value={selected}
              onChange={setSelected}
              placeholder="Select asset"
              w={320}
              disabled={assets.length === 0}
            />
            <Button
              variant="light"
              leftSection={<IconRefresh size={14} />}
              onClick={() => setSelected(selected)}
              disabled={!selected || loadingData}
            >
              Reload
            </Button>
          </Group>
        </Group>

        {assetsError && <Alert color="red" title="Failed to load assets">{assetsError}</Alert>}
        {loadError && <Alert color="red" title="Failed to load data">{loadError}</Alert>}

        {selectedAsset && (
          <Group gap="sm">
            <Badge color={selectedAsset.hasData ? 'green' : 'gray'}>
              {selectedAsset.hasData ? `${fvRows.length} ticks` : 'no hold-1 data'}
            </Badge>
            <Badge color={nTrades > 0 ? 'green' : 'gray'}>
              {nTrades > 0 ? `${nTrades} trades` : 'no trades'}
            </Badge>
            <Badge color={selectedAsset.hasParams ? 'blue' : 'gray'}>
              {selectedAsset.hasParams ? 'params.json' : 'no params'}
            </Badge>
            {params && (
              <Badge variant="outline">
                {params.fv_process.type} · {params.bots.length} bots
              </Badge>
            )}
          </Group>
        )}

        <Divider />

        {loadingData && (
          <Group><Loader size="sm" /><Text size="sm">Loading hold-1 data...</Text></Group>
        )}

        {!loadingData && selected && !data && (
          <Alert color="yellow" title="No hold-1 data for this asset">
            <Text size="sm">
              Submit <code>traders/trader_hold1.py</code> to the portal for this product, download
              the submission, and run{' '}
              <code>py -3.13 calibration/extract_fv_and_book.py &lt;submission_id&gt; {selected}</code>.
              Add <code>--trades-csv</code> to include trade-bot input.
            </Text>
          </Alert>
        )}

        {!loadingData && selected && data && (
          <Grid gutter="md">
            {/* Stepper rail */}
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Stack gap={2}>
                {STAGES.map((stage, idx) => {
                  const state = stages[stage.id];
                  return (
                    <NavLink
                      key={stage.id}
                      active={activeStage === stage.id}
                      label={<Group justify="space-between" wrap="nowrap">
                        <Text size="sm" span>{stage.label}</Text>
                        <Badge
                          color={statusColor(state.status)}
                          variant={state.status === 'pending' ? 'light' : 'filled'}
                          size="xs"
                          leftSection={statusIcon(state.status)}
                        >
                          {state.status}
                        </Badge>
                      </Group>}
                      description={stage.short}
                      onClick={() => {
                        if (activeStage !== stage.id) {
                          // Clicking an earlier stage after running later ones invalidates downstream.
                          const curIdx = STAGES.findIndex(s => s.id === activeStage);
                          if (idx < curIdx) resetFrom(stage.id);
                          setActiveStage(stage.id);
                        }
                      }}
                    />
                  );
                })}
              </Stack>
            </Grid.Col>

            {/* Active stage panel */}
            <Grid.Col span={{ base: 12, md: 9 }}>
              <Box>
                {renderActiveStage({
                  id: activeStage,
                  asset: selected!,
                  data,
                  existingParams: params,
                  fvProcessResult: stages.fv_process.result as FvFitResult | null | undefined,
                  layerResult: stages.layer_detection.result as Stage1Result | null | undefined,
                  formulaResult: stages.formula_discovery.result as Stage2Result | null | undefined,
                  volumeResult: stages.volume_model.result as Stage3Result | null | undefined,
                  presenceResult: stages.presence_model.result as Stage4Result | null | undefined,
                  noiseResult: stages.noise_layer.result as Stage5Result | null | undefined,
                  tradeResult: stages.trade_bot.result as Stage6Result | null | undefined,
                  validationResult: stages.validation.result as Stage7Result | null | undefined,
                  onFvProcessRun: (r) => {
                    const status: 'pass' | 'warn' | 'fail' =
                      r.diagnostics.residualLjung.p < 0.01 ? 'warn' : 'pass';
                    update('fv_process', { status, result: r, summaryP: r.diagnostics.residualLjung.p });
                  },
                  onLayerRun: (r) => {
                    const status = r.layers.length > 0 ? 'pass' : 'warn';
                    update('layer_detection', { status, result: r });
                  },
                  onFormulaRun: (r) => {
                    const allGood = r.bots.every(b =>
                      b.winner_bid.cv_match_rate >= 0.95 && b.winner_ask.cv_match_rate >= 0.95);
                    update('formula_discovery', { status: allGood ? 'pass' : 'warn', result: r });
                  },
                  onVolumeRun: (r) => {
                    const allUniform = r.layers.every(L =>
                      L.bid.uniform.p_value > 0.01 && L.ask.uniform.p_value > 0.01);
                    update('volume_model', { status: allUniform ? 'pass' : 'warn', result: r });
                  },
                  onPresenceRun: (r) => {
                    const allIid = r.layers.every(L =>
                      L.bid.ljung.p_value > 0.01 && L.ask.ljung.p_value > 0.01);
                    update('presence_model', { status: allIid ? 'pass' : 'warn', result: r });
                  },
                  onNoiseRun: (r) => {
                    update('noise_layer', { status: r.stats.n_events > 0 ? 'pass' : 'warn', result: r });
                  },
                  onTradeRun: (r) => {
                    if (!r.available) {
                      update('trade_bot', { status: 'warn', result: r });
                    } else {
                      const passes = r.stats?.poisson_gof?.p_value ?? 1;
                      update('trade_bot', { status: passes > 0.01 ? 'pass' : 'warn', result: r });
                    }
                  },
                  onValidationRun: (r) => {
                    const s = r.verdict === 'pass' ? 'pass' : r.verdict === 'warn' ? 'warn' : 'fail';
                    update('validation', { status: s, result: r });
                  },
                  onExportWritten: () => {
                    update('export', { status: 'pass' });
                    setSelected(selected);  // trigger reload to pick up the new params.json
                  },
                  onAcceptAndAdvance: () => {
                    const idx = STAGES.findIndex(s => s.id === activeStage);
                    if (idx < STAGES.length - 1) setActiveStage(STAGES[idx + 1].id);
                  },
                })}
              </Box>
            </Grid.Col>
          </Grid>
        )}

        {!loadingData && !selected && assets.length === 0 && (
          <Alert color="gray" title="No assets registered">
            <Text size="sm">
              No <code>*.rs</code> files under <code>rust_simulator/src/assets/</code>.
              Add an asset module there to make it available here.
            </Text>
          </Alert>
        )}
      </Stack>
    </Container>
  );
}

interface StageRenderCtx {
  id: StageId;
  asset: string;
  data: FvAndBook;
  existingParams: import('./types').CalibrationParams | null;
  fvProcessResult: FvFitResult | null | undefined;
  layerResult: Stage1Result | null | undefined;
  formulaResult: Stage2Result | null | undefined;
  volumeResult: Stage3Result | null | undefined;
  presenceResult: Stage4Result | null | undefined;
  noiseResult: Stage5Result | null | undefined;
  tradeResult: Stage6Result | null | undefined;
  validationResult: Stage7Result | null | undefined;
  onFvProcessRun: (r: FvFitResult) => void;
  onLayerRun: (r: Stage1Result) => void;
  onFormulaRun: (r: Stage2Result) => void;
  onVolumeRun: (r: Stage3Result) => void;
  onPresenceRun: (r: Stage4Result) => void;
  onNoiseRun: (r: Stage5Result) => void;
  onTradeRun: (r: Stage6Result) => void;
  onValidationRun: (r: Stage7Result) => void;
  onExportWritten: () => void;
  onAcceptAndAdvance: () => void;
}

function renderActiveStage(ctx: StageRenderCtx): ReactNode {
  const stage = STAGES.find(s => s.id === ctx.id)!;
  const description = STAGE_DESCRIPTIONS[ctx.id];
  switch (ctx.id) {
    case 'fv_process':
      return <FvProcessPanel data={ctx.data} result={ctx.fvProcessResult ?? null} onRun={ctx.onFvProcessRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'layer_detection':
      return <LayerDetectionPanel data={ctx.data} result={ctx.layerResult ?? null} onRun={ctx.onLayerRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'formula_discovery':
      return <FormulaDiscoveryPanel stage1={ctx.layerResult ?? null} result={ctx.formulaResult ?? null} onRun={ctx.onFormulaRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'volume_model':
      return <VolumeModelPanel data={ctx.data} stage1={ctx.layerResult ?? null} result={ctx.volumeResult ?? null} onRun={ctx.onVolumeRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'presence_model':
      return <PresenceModelPanel data={ctx.data} stage1={ctx.layerResult ?? null} result={ctx.presenceResult ?? null} onRun={ctx.onPresenceRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'noise_layer':
      return <NoiseLayerPanel data={ctx.data} stage1={ctx.layerResult ?? null} result={ctx.noiseResult ?? null} onRun={ctx.onNoiseRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'trade_bot':
      return <TradeBotPanel data={ctx.data} result={ctx.tradeResult ?? null} onRun={ctx.onTradeRun} onAccept={ctx.onAcceptAndAdvance} />;
    case 'validation':
      return <ValidationPanel
        fv={ctx.fvProcessResult ?? null}
        stage2={ctx.formulaResult ?? null}
        stage3={ctx.volumeResult ?? null}
        stage4={ctx.presenceResult ?? null}
        result={ctx.validationResult ?? null}
        onRun={ctx.onValidationRun}
        onAccept={ctx.onAcceptAndAdvance}
      />;
    case 'export':
      return <ExportPanel
        asset={ctx.asset}
        fv={ctx.fvProcessResult ?? null}
        s1={ctx.layerResult ?? null}
        s2={ctx.formulaResult ?? null}
        s3={ctx.volumeResult ?? null}
        s4={ctx.presenceResult ?? null}
        existingParams={ctx.existingParams}
        onWritten={ctx.onExportWritten}
      />;
    default:
      return <StagePlaceholder stageId={ctx.id} label={stage.label} description={description} />;
  }
}

const STAGE_DESCRIPTIONS: Record<StageId, string> = {
  fv_process:        'Fit constant / linear drift / random walk / AR(1). Select by BIC. Diagnostics: residual Q-Q, Shapiro, Ljung-Box.',
  layer_detection:   'KDE on offset-from-FV per side. Peak-detect bot layers. Regress offset ~ FV to classify fixed vs proportional.',
  formula_discovery: 'Brute-force fixed + proportional formulas per bot/side. Cross-validated. FV-decile match rate heatmap.',
  volume_model:      'χ² goodness-of-fit for U(lo,hi). Side-tie test. Conditional checks on vol | offset and vol | FV-range.',
  presence_model:    'iid-Bernoulli tests: Ljung-Box, runs, Geometric run-length KS. Per-bot bid∥ask χ² 2×2. Cross-bot N×N χ².',
  noise_layer:       'Residual quotes outside main clusters: offset distribution, crossing vs passive, volume | crossing split.',
  trade_bot:         'Poisson rate fit + χ² GoF on trade counts. Quantity distribution (uniform / bimodal / empirical).',
  validation:        'Re-run all tests on held-out 20%. 2-sample KS vs synthetic marginals. Fisher combined p + BH-FDR correction.',
  export:            'Write calibration/<asset>/params.json and generate a starter rust_simulator/src/assets/<asset>.rs scaffold.',
};
