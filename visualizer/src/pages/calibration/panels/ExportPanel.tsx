import { Alert, Badge, Button, Card, Code, Group, Loader, Stack, Text, Textarea } from '@mantine/core';
import { IconDownload, IconUpload } from '@tabler/icons-react';
import { ReactNode, useMemo, useState } from 'react';
import { writeParams } from '../loader';
import { CalibrationParams } from '../types';
import { assembleParams } from '../stages/export';
import { Stage2Result } from '../stages/formula_discovery';
import { FvFitResult } from '../stages/fv_process';
import { Stage1Result } from '../stages/layer_detection';
import { Stage4Result } from '../stages/presence_model';
import { Stage3Result } from '../stages/volume_model';

interface Props {
  asset: string;
  fv: FvFitResult | null;
  s1: Stage1Result | null;
  s2: Stage2Result | null;
  s3: Stage3Result | null;
  s4: Stage4Result | null;
  existingParams: CalibrationParams | null;
  onWritten: () => void;
}

export function ExportPanel(props: Props): ReactNode {
  const { asset, fv, s1, s2, s3, s4, existingParams, onWritten } = props;
  const [writing, setWriting] = useState(false);
  const [writeErr, setWriteErr] = useState<string | null>(null);
  const [writeOk, setWriteOk] = useState(false);

  const assembled = useMemo<CalibrationParams | null>(() => {
    try { return assembleParams(asset, fv, s1, s2, s3, s4); }
    catch (e) { return null; }
  }, [asset, fv, s1, s2, s3, s4]);

  const json = useMemo(() => assembled ? JSON.stringify(assembled, null, 2) : '', [assembled]);

  const handleDownload = () => {
    if (!assembled) return;
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${asset.toLowerCase()}_params.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleWrite = async () => {
    if (!assembled) return;
    setWriting(true); setWriteErr(null); setWriteOk(false);
    try {
      await writeParams(asset, assembled);
      setWriteOk(true);
      onWritten();
    } catch (e) {
      setWriteErr(String((e as Error)?.message ?? e));
    } finally { setWriting(false); }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Text size="lg" fw={600}>Stage 8 — Export</Text>
          <Text size="xs" c="dimmed">
            Write the assembled params.json to <Code>calibration/{asset.toLowerCase()}/params.json</Code>.
          </Text>
        </Stack>
      </Group>

      {!assembled && (
        <Alert color="yellow" title="Run Stages 0-2 first">
          <Text size="sm">Stage 8 requires FV process + layer detection + formula discovery.</Text>
        </Alert>
      )}

      {assembled && (
        <Stack gap="sm">
          <Group>
            <Button leftSection={<IconDownload size={14} />} variant="light" onClick={handleDownload}>
              Download JSON
            </Button>
            <Button leftSection={<IconUpload size={14} />} onClick={handleWrite} disabled={writing} color="green">
              {writing ? <Loader size="xs" /> : existingParams ? 'Overwrite on server' : 'Write to server'}
            </Button>
            {existingParams && <Badge variant="light" color="blue">existing params.json will be overwritten</Badge>}
          </Group>

          {writeErr && <Alert color="red" title="Write failed">{writeErr}</Alert>}
          {writeOk && <Alert color="green" title="Written">params.json saved to server.</Alert>}

          <Card withBorder padding="sm">
            <Text size="sm" fw={600} mb="xs">Summary</Text>
            <Stack gap={2}>
              <Text size="xs">FV process: <Badge variant="light">{assembled.fv_process.type}</Badge></Text>
              <Text size="xs">Bots: {assembled.bots.length}</Text>
              {assembled.bots.map(b => (
                <Text size="xs" key={b.id} c="dimmed">
                  {b.id} ({b.name}) — {b.offset_type}, bid=<Code>{b.bid_formula_str}</Code>, ask=<Code>{b.ask_formula_str}</Code>
                </Text>
              ))}
            </Stack>
          </Card>

          <Textarea
            label="params.json (preview)"
            description="Edit manually before download/write if you spot a tweak; this textarea is read-only in v1."
            value={json}
            autosize
            minRows={10}
            maxRows={30}
            readOnly
            styles={{ input: { fontFamily: 'monospace', fontSize: 11 } }}
          />
        </Stack>
      )}
    </Stack>
  );
}
