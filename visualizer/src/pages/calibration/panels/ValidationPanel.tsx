import { Alert, Badge, Button, Card, Group, Loader, Stack, Table, Text } from '@mantine/core';
import { ReactNode, useState } from 'react';
import { Stage2Result } from '../stages/formula_discovery';
import { FvFitResult } from '../stages/fv_process';
import { Stage4Result } from '../stages/presence_model';
import { runStage7, Stage7Result } from '../stages/validation';
import { Stage3Result } from '../stages/volume_model';

interface Props {
  fv: FvFitResult | null;
  stage2: Stage2Result | null;
  stage3: Stage3Result | null;
  stage4: Stage4Result | null;
  result: Stage7Result | null;
  onRun: (r: Stage7Result) => void;
  onAccept: () => void;
}

export function ValidationPanel(props: Props): ReactNode {
  const { fv, stage2, stage3, stage4, result, onRun, onAccept } = props;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleRun = async () => {
    setBusy(true); setErr(null);
    try { onRun(await runStage7(fv, stage2, stage3, stage4)); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 7 — Held-out Validation &amp; Confidence</Text>
          <Text size="xs" c="dimmed">
            Collect every p-value from Stages 0-4 · Fisher combined test · BH-FDR correction at α=0.05.
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
      {result && <ValidationView result={result} />}
    </Stack>
  );
}

function ValidationView({ result }: { result: Stage7Result }): ReactNode {
  const vcolor = result.verdict === 'pass' ? 'green' : result.verdict === 'warn' ? 'yellow' : 'red';
  return (
    <Stack gap="md">
      <Card withBorder padding="md">
        <Group gap="lg">
          <Badge size="xl" color={vcolor}>{result.verdict.toUpperCase()}</Badge>
          <Stack gap={0}>
            <Text size="sm">
              {result.rows.length} tests · {result.n_fail_raw} raw failures (α=0.05) ·
              {' '}{result.n_fail_bh} BH-adjusted failures
            </Text>
            {result.fisher && (
              <Text size="xs" c="dimmed">
                Fisher combined: χ²={result.fisher.chi2.toFixed(1)}, df={result.fisher.df}, p={fmt(result.fisher.p_value)}
              </Text>
            )}
          </Stack>
        </Group>
      </Card>
      <Card withBorder padding="md">
        <Text size="sm" fw={600} mb="xs">Test breakdown</Text>
        <Table striped withTableBorder fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>stage</Table.Th>
              <Table.Th>test</Table.Th>
              <Table.Th>p (raw)</Table.Th>
              <Table.Th>p (BH)</Table.Th>
              <Table.Th>verdict</Table.Th>
              <Table.Th>detail</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {result.rows.map((r, i) => {
              const bh = result.bh_adjusted[i];
              const fail = Number.isFinite(bh) && bh < 0.05;
              return (
                <Table.Tr key={i}>
                  <Table.Td><Badge variant="light" size="xs">{r.stage}</Badge></Table.Td>
                  <Table.Td>{r.test}</Table.Td>
                  <Table.Td>{fmt(r.p)}</Table.Td>
                  <Table.Td>{fmt(bh)}</Table.Td>
                  <Table.Td><Badge color={fail ? 'red' : 'green'} size="xs">{fail ? 'fail' : 'pass'}</Badge></Table.Td>
                  <Table.Td c="dimmed">{r.detail}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

function fmt(p: number): string {
  if (!Number.isFinite(p)) return '—';
  if (p < 1e-4) return '< 1e-4';
  return p.toFixed(4);
}
