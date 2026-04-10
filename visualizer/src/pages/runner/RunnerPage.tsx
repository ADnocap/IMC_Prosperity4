import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Grid,
  Group,
  NumberInput,
  Progress,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { IconAlertCircle, IconCheck, IconPlayerPlay, IconPlayerStop, IconExternalLink } from '@tabler/icons-react';
import axios from 'axios';
import { ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

interface Trader {
  name: string;
  path: string;
  sizeBytes: number;
  mtimeMs: number;
}

interface RunState {
  id: string;
  trader: string;
  sessions: number;
  sampleSessions: number;
  fvMode: string;
  tradeMode: string;
  seed: number;
  status: 'running' | 'complete' | 'failed';
  startTime: number;
  endTime: number | null;
  error: string | null;
  pid: number | null;
  outputDir: string;
  dashboardUrl: string | null;
  stdout: string | null;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function parseMeanPnl(stdout: string | null): string | null {
  if (!stdout) return null;
  const match = stdout.match(/Mean total PnL:\s*([-\d,.]+)/);
  return match ? match[1] : null;
}

export function RunnerPage(): ReactNode {
  const navigate = useNavigate();

  // Trader list
  const [traders, setTraders] = useState<Trader[]>([]);
  const [selectedTrader, setSelectedTrader] = useState<string | null>(null);

  // Config
  const [preset, setPreset] = useState('quick');
  const [customSessions, setCustomSessions] = useState<number>(500);
  const [customSampleSessions, setCustomSampleSessions] = useState<number>(50);
  const [fvMode, setFvMode] = useState('simulate');
  const [tradeMode, setTradeMode] = useState('simulate');
  const [seed, setSeed] = useState('20260401');
  const [ticksPerDay, setTicksPerDay] = useState<number>(2000);

  // Runner state
  const [runState, setRunState] = useState<RunState | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [launching, setLaunching] = useState(false);

  // Fetch trader list on mount
  useEffect(() => {
    axios.get('/__prosperity4mcbt__/runner/traders').then(res => {
      setTraders(res.data);
      if (res.data.length > 0 && !selectedTrader) {
        setSelectedTrader(res.data[0].name);
      }
    }).catch(() => {});
  }, []);

  // Poll runner status
  useEffect(() => {
    const poll = () => {
      axios.get('/__prosperity4mcbt__/runner/status').then(res => {
        setRunState(res.data.run);
      }).catch(() => {});
    };
    poll();
    const interval = setInterval(poll, 1500);
    return () => clearInterval(interval);
  }, []);

  // Elapsed time ticker
  useEffect(() => {
    if (!runState || runState.status !== 'running') return;
    const tick = () => setElapsed(Date.now() / 1000 - runState.startTime);
    tick();
    const interval = setInterval(tick, 500);
    return () => clearInterval(interval);
  }, [runState?.status, runState?.startTime]);

  const getSessionCount = () => {
    if (preset === 'quick') return { sessions: 100, sampleSessions: 10 };
    if (preset === 'heavy') return { sessions: 1000, sampleSessions: 100 };
    return { sessions: customSessions, sampleSessions: customSampleSessions };
  };

  const handleStart = async () => {
    if (!selectedTrader) return;
    setLaunching(true);
    const { sessions, sampleSessions } = getSessionCount();
    try {
      await axios.post('/__prosperity4mcbt__/runner/start', {
        trader: selectedTrader,
        sessions,
        sampleSessions,
        fvMode,
        tradeMode,
        seed: parseInt(seed) || 20260401,
        ticksPerDay,
      });
    } catch (err: any) {
      // handled by polling
    }
    setLaunching(false);
  };

  const handleCancel = async () => {
    try {
      await axios.post('/__prosperity4mcbt__/runner/cancel');
    } catch {}
  };

  const handleClear = async () => {
    try {
      await axios.post('/__prosperity4mcbt__/runner/clear');
      setRunState(null);
    } catch {}
  };

  const handleViewResults = () => {
    if (runState?.dashboardUrl) {
      navigate(`/?open=${encodeURIComponent(runState.dashboardUrl)}`);
    }
  };

  const isRunning = runState?.status === 'running';
  const isComplete = runState?.status === 'complete';
  const isFailed = runState?.status === 'failed';
  const duration = runState?.endTime && runState?.startTime
    ? formatElapsed(runState.endTime - runState.startTime)
    : null;

  return (
    <Container fluid p="md">
      <Stack gap="md">
        {/* ── Launch Panel ──────────────────────────────────────── */}
        <Card withBorder shadow="sm" padding="lg">
          <Text size="lg" fw={700} mb="md">Run Backtest</Text>
          <Grid>
            <Grid.Col span={4}>
              <Select
                label="Strategy"
                placeholder="Select trader"
                data={traders.map(t => ({ value: t.name, label: t.name }))}
                value={selectedTrader}
                onChange={setSelectedTrader}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={4}>
              <Text size="sm" fw={500} mb={4}>Preset</Text>
              <SegmentedControl
                fullWidth
                data={[
                  { label: 'Quick (100)', value: 'quick' },
                  { label: 'Heavy (1000)', value: 'heavy' },
                  { label: 'Custom', value: 'custom' },
                ]}
                value={preset}
                onChange={setPreset}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={4}>
              {preset === 'custom' && (
                <Group grow>
                  <NumberInput
                    label="Sessions"
                    value={customSessions}
                    onChange={v => setCustomSessions(Number(v) || 100)}
                    min={10}
                    max={10000}
                    disabled={isRunning}
                  />
                  <NumberInput
                    label="Sample paths"
                    value={customSampleSessions}
                    onChange={v => setCustomSampleSessions(Number(v) || 10)}
                    min={1}
                    max={10000}
                    disabled={isRunning}
                  />
                </Group>
              )}
            </Grid.Col>
          </Grid>

          {/* Advanced config */}
          <Grid mt="sm">
            <Grid.Col span={3}>
              <Select
                label="FV mode"
                data={[
                  { value: 'simulate', label: 'Simulate' },
                  { value: 'replay', label: 'Replay' },
                ]}
                value={fvMode}
                onChange={v => setFvMode(v || 'simulate')}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={3}>
              <Select
                label="Trade mode"
                data={[
                  { value: 'simulate', label: 'Simulate' },
                  { value: 'replay-times', label: 'Replay times' },
                ]}
                value={tradeMode}
                onChange={v => setTradeMode(v || 'simulate')}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={2}>
              <TextInput
                label="Seed"
                value={seed}
                onChange={e => setSeed(e.currentTarget.value)}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={2}>
              <NumberInput
                label="Ticks/day"
                value={ticksPerDay}
                onChange={v => setTicksPerDay(Number(v) || 2000)}
                min={100}
                max={100000}
                step={100}
                disabled={isRunning}
              />
            </Grid.Col>
            <Grid.Col span={2} style={{ display: 'flex', alignItems: 'flex-end' }}>
              {!isRunning ? (
                <Button
                  fullWidth
                  leftSection={<IconPlayerPlay size={16} />}
                  onClick={handleStart}
                  loading={launching}
                  disabled={!selectedTrader}
                >
                  Start
                </Button>
              ) : (
                <Button
                  fullWidth
                  color="red"
                  leftSection={<IconPlayerStop size={16} />}
                  onClick={handleCancel}
                >
                  Cancel
                </Button>
              )}
            </Grid.Col>
          </Grid>
        </Card>

        {/* ── Progress Panel ────────────────────────────────────── */}
        {runState && (
          <Card withBorder shadow="sm" padding="lg">
            <Group justify="space-between" mb="sm">
              <Text size="lg" fw={700}>
                {isRunning ? 'Running' : isComplete ? 'Complete' : 'Failed'}
              </Text>
              <Group gap="xs">
                <Badge color={isRunning ? 'blue' : isComplete ? 'green' : 'red'}>
                  {runState.trader}
                </Badge>
                <Badge variant="light">
                  {runState.sessions} sessions
                </Badge>
              </Group>
            </Group>

            {isRunning && (
              <>
                <Progress value={100} animated striped size="lg" mb="sm" />
                <Text size="sm" c="dimmed">
                  Elapsed: {formatElapsed(elapsed)} | Running {runState.trader} with {runState.sessions} sessions...
                </Text>
              </>
            )}

            {isComplete && (
              <>
                <Alert color="green" icon={<IconCheck size={16} />} mb="sm">
                  Completed in {duration}
                  {runState.stdout && parseMeanPnl(runState.stdout) && (
                    <> | Mean PnL: <strong>{parseMeanPnl(runState.stdout)}</strong></>
                  )}
                </Alert>
                <Group>
                  <Button
                    leftSection={<IconExternalLink size={16} />}
                    onClick={handleViewResults}
                  >
                    View Results
                  </Button>
                  <Button variant="subtle" onClick={handleClear}>Dismiss</Button>
                </Group>
              </>
            )}

            {isFailed && (
              <>
                <Alert color="red" icon={<IconAlertCircle size={16} />} title="Error" mb="sm">
                  {runState.error || 'Unknown error'}
                </Alert>
                <Button variant="subtle" onClick={handleClear}>Dismiss</Button>
              </>
            )}
          </Card>
        )}

        {/* ── Run History ───────────────────────────────────────── */}
        <RunHistory />
      </Stack>
    </Container>
  );
}

function RunHistory(): ReactNode {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<Array<{ id: string; label: string; mtimeMs: number; dashboardUrl: string }>>([]);

  useEffect(() => {
    const fetch = () => {
      axios.get('/__prosperity4mcbt__/status.json').then(res => {
        setRuns(res.data.runs || []);
      }).catch(() => {});
    };
    fetch();
    const interval = setInterval(fetch, 5000);
    return () => clearInterval(interval);
  }, []);

  if (runs.length === 0) return null;

  return (
    <Card withBorder shadow="sm" padding="lg">
      <Text size="lg" fw={700} mb="md">Run History</Text>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Run</Table.Th>
            <Table.Th>Date</Table.Th>
            <Table.Th></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.map(run => (
            <Table.Tr key={run.id}>
              <Table.Td>
                <Text fw={500}>{run.label}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {new Date(run.mtimeMs).toLocaleString()}
                </Text>
              </Table.Td>
              <Table.Td>
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => navigate(`/?open=${encodeURIComponent(run.dashboardUrl)}`)}
                >
                  View
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}
