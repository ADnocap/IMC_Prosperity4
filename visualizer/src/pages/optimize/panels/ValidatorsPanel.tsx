// Validators card — render the four anti-overfitting diagnostics from
// validators.json. Each sub-card shows the verdict (PASS / FLAG / CAUTION /
// FAIL / SCATTERED / CLUSTERED) plus the headline numbers. The raw reasoning
// string is rendered as hint text so the user doesn't need to re-read the
// Phase 2 docs to interpret results.

import { Alert, Badge, Card, Grid, Group, Stack, Text } from '@mantine/core';
import { ReactNode } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ClusterBlock, DsrBlock, ImportanceBlock, PboBlock, Validators } from '../types.ts';

interface Props {
  validators: Validators | null;
}

export function ValidatorsPanel({ validators }: Props): ReactNode {
  // Catch both null (backend sent null) and undefined (field missing on payload).
  if (!validators) {
    return (
      <VisualizerCard title="Anti-overfitting diagnostics">
        <Text size="sm" c="dimmed">validators.json not found — this study finished before Phase 2 or was interrupted.</Text>
      </VisualizerCard>
    );
  }
  if (validators.skipped) {
    return (
      <VisualizerCard title="Anti-overfitting diagnostics">
        <Alert color="yellow">Skipped: {validators.skipped}</Alert>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title="Anti-overfitting diagnostics">
      <Grid gutter="md">
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <DsrCard dsr={validators.dsr} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <PboCard pbo={validators.pbo} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <ClusterCard cluster={validators.cluster} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <ImportanceCard importance={validators.importance} />
        </Grid.Col>
      </Grid>
    </VisualizerCard>
  );
}

function DsrCard({ dsr }: { dsr?: DsrBlock }): ReactNode {
  if (!dsr) return <Skipped title="Deflated Sharpe Ratio" reason="no data" />;
  if (dsr.skipped) return <Skipped title="Deflated Sharpe Ratio" reason={dsr.skipped} />;
  const p = dsr.probability ?? NaN;
  const verdict: Verdict = isFinite(p) && p >= 0.95 ? 'PASS' : 'FLAG';
  return (
    <StatCard title="Deflated Sharpe Ratio" verdict={verdict} reasoning={dsr.reasoning}>
      <Group gap="lg">
        <Stat label="P(true SR > 0)" value={fmt(p, 3)} />
        <Stat label="Sharpe" value={fmt(dsr.sharpe, 2)} />
        <Stat label="null-max SR" value={fmt(dsr.expected_max_sr_under_null, 2)} />
      </Group>
      <Text size="xs" c="dimmed">
        {dsr.n_trials} trials · n = {dsr.n_sessions} · skew = {fmt(dsr.skew, 2)} · kurt excess = {fmt(dsr.kurt_excess, 2)}
      </Text>
    </StatCard>
  );
}

function PboCard({ pbo }: { pbo?: PboBlock }): ReactNode {
  if (!pbo) return <Skipped title="Probability of Backtest Overfitting" reason="no data" />;
  if (pbo.skipped) return <Skipped title="Probability of Backtest Overfitting" reason={pbo.skipped} />;
  const p = pbo.pbo ?? NaN;
  const verdict: Verdict = !isFinite(p) ? 'FLAG' : p < 0.25 ? 'PASS' : p < 0.5 ? 'CAUTION' : 'FAIL';
  return (
    <StatCard title="Probability of Backtest Overfitting" verdict={verdict} reasoning={pbo.reasoning}>
      <Group gap="lg">
        <Stat label="PBO" value={fmt(p, 3)} />
        <Stat label="Partitions" value={String(pbo.n_partitions_used ?? '—')} />
        <Stat label="Sessions" value={String(pbo.n_sessions ?? '—')} />
      </Group>
    </StatCard>
  );
}

function ClusterCard({ cluster }: { cluster?: ClusterBlock }): ReactNode {
  if (!cluster) return <Skipped title="Cluster stability" reason="no data" />;
  if (cluster.skipped) return <Skipped title="Cluster stability" reason={cluster.skipped} />;
  const r = cluster.ratio ?? NaN;
  const verdict: Verdict = !isFinite(r) ? 'FLAG' : r < 1.0 ? 'CLUSTERED' : 'SCATTERED';
  return (
    <StatCard title="Cluster stability" verdict={verdict} reasoning={cluster.reasoning}>
      <Group gap="lg">
        <Stat label="Top/Random ratio" value={fmt(r, 2)} />
        <Stat label="Top dist" value={fmt(cluster.median_top_dist, 2)} />
        <Stat label="Random dist" value={fmt(cluster.median_random_dist, 2)} />
      </Group>
      {cluster.numeric_params && cluster.numeric_params.length > 0 && (
        <Text size="xs" c="dimmed">Params used: {cluster.numeric_params.join(', ')}</Text>
      )}
    </StatCard>
  );
}

function ImportanceCard({ importance }: { importance?: ImportanceBlock }): ReactNode {
  if (!importance || !importance.importances) {
    return <Skipped title="fANOVA importance" reason="no data" />;
  }
  const rows = Object.entries(importance.importances).sort((a, b) => b[1] - a[1]);
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb={6}>
        <Text fw={600}>fANOVA importance</Text>
      </Group>
      <Stack gap={4}>
        {rows.map(([name, value]) => (
          <Group key={name} justify="space-between" gap="xs">
            <Text size="sm">{name}</Text>
            <Badge variant="light" color={value >= 0.5 ? 'teal' : value >= 0.1 ? 'blue' : 'gray'}>
              {value.toFixed(3)}
            </Badge>
          </Group>
        ))}
      </Stack>
    </Card>
  );
}

// ────────────── helpers ──────────────

type Verdict = 'PASS' | 'FLAG' | 'CAUTION' | 'FAIL' | 'CLUSTERED' | 'SCATTERED';

const VERDICT_COLOR: Record<Verdict, string> = {
  PASS: 'teal',
  CLUSTERED: 'teal',
  FLAG: 'yellow',
  CAUTION: 'orange',
  SCATTERED: 'orange',
  FAIL: 'red',
};

function StatCard({
  title, verdict, reasoning, children,
}: { title: string; verdict: Verdict; reasoning?: string; children: ReactNode }): ReactNode {
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" mb={6}>
        <Text fw={600}>{title}</Text>
        <Badge color={VERDICT_COLOR[verdict]} variant="light">{verdict}</Badge>
      </Group>
      <Stack gap={4}>
        {children}
        {reasoning && <Text size="xs" c="dimmed">{reasoning}</Text>}
      </Stack>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="md" fw={600}>{value}</Text>
    </Stack>
  );
}

function Skipped({ title, reason }: { title: string; reason: string }): ReactNode {
  return (
    <Card withBorder padding="sm">
      <Text fw={600}>{title}</Text>
      <Text size="sm" c="dimmed">Skipped — {reason}</Text>
    </Card>
  );
}

function fmt(v: number | undefined, decimals: number): string {
  if (v === undefined || v === null || !isFinite(v)) return '—';
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
