// Optimize tab — browse finished optimizer studies and inspect results.
//
// A study is one `prosperity4opt studies/*.yaml` run. Its artifacts live in
// `tmp/optimizer/<name>/` and are served by the `optimizer/*` endpoints
// defined in backtester/dashboard_server.py.
//
// Layout:
//   1. Study picker (studies sorted newest first).
//   2. Validators summary card — DSR, PBO, cluster, importance verdicts.
//   3. Convergence — best-so-far line chart.
//   4. Param importance — fANOVA bar chart.
//   5. Param effects — value-vs-each-param scatter (one per numeric param).
//   6. 2D slice — scatter over any (x, y) param pair, coloured by objective.
//   7. Top-K table — ranked by test score when available, else training value.

import { Alert, Badge, Container, Group, Loader, Select, Stack, Text, Title } from '@mantine/core';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { fetchStudyDetail, fetchStudyList } from './loader.ts';
import { StudyDetail, StudyListItem } from './types.ts';
import { ValidatorsPanel } from './panels/ValidatorsPanel.tsx';
import { ConvergencePanel } from './panels/ConvergencePanel.tsx';
import { ImportancePanel } from './panels/ImportancePanel.tsx';
import { TopKPanel } from './panels/TopKPanel.tsx';
import { ParamEffectPanel } from './panels/ParamEffectPanel.tsx';
import { ParamSlice2DPanel } from './panels/ParamSlice2DPanel.tsx';

export function OptimizePage(): ReactNode {
  const [studies, setStudies] = useState<StudyListItem[] | null>(null);
  const [studiesError, setStudiesError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStudyList()
      .then(list => {
        if (cancelled) return;
        setStudies(list);
        if (list.length > 0 && selected === null) {
          setSelected(list[0].name);
        }
      })
      .catch(err => {
        if (!cancelled) setStudiesError(String(err?.message ?? err));
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    setLoadingDetail(true);
    setDetailError(null);
    fetchStudyDetail(selected)
      .then(data => { if (!cancelled) setDetail(data); })
      .catch(err => { if (!cancelled) setDetailError(String(err?.message ?? err)); })
      .finally(() => { if (!cancelled) setLoadingDetail(false); });
    return () => { cancelled = true; };
  }, [selected]);

  const studyOptions = useMemo(() => {
    if (studies === null) return [];
    return studies.map(s => ({
      value: s.name,
      label: formatStudyLabel(s),
    }));
  }, [studies]);

  const currentSummary = useMemo(() => {
    if (studies === null || selected === null) return null;
    return studies.find(s => s.name === selected) ?? null;
  }, [studies, selected]);

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Group justify="space-between" align="end">
          <Stack gap={0}>
            <Title order={2}>Parameter optimization</Title>
            <Text c="dimmed" size="sm">
              Browse finished studies from <code>tmp/optimizer/</code>. Run new ones with <code>prosperity4opt studies/&lt;file&gt;.yaml</code>.
            </Text>
          </Stack>
          {currentSummary !== null && <StudyBadges summary={currentSummary} />}
        </Group>

        {studiesError !== null && (
          <Alert color="red" title="Failed to list studies">{studiesError}</Alert>
        )}

        {studies === null && studiesError === null && (
          <Group><Loader size="sm" /><Text>Loading studies…</Text></Group>
        )}

        {studies !== null && studies.length === 0 && (
          <Alert color="yellow" title="No studies yet">
            Run <code>prosperity4opt studies/demo_osmium.yaml --fresh</code> or any study under <code>studies/</code>,
            then refresh.
          </Alert>
        )}

        {studies !== null && studies.length > 0 && (
          <Select
            label="Study"
            data={studyOptions}
            value={selected}
            onChange={setSelected}
            searchable
            maxDropdownHeight={400}
          />
        )}

        {detailError !== null && (
          <Alert color="red" title="Failed to load study">{detailError}</Alert>
        )}

        {loadingDetail && (
          <Group><Loader size="sm" /><Text>Loading study detail…</Text></Group>
        )}

        {detail !== null && !loadingDetail && (
          <Stack gap="md">
            <ValidatorsPanel validators={detail.validators} />
            <Group align="stretch" grow wrap="wrap">
              <ConvergencePanel trials={detail.trials} />
              <ImportancePanel validators={detail.validators} />
            </Group>
            <ParamEffectPanel trials={detail.trials} paramNames={detail.paramNames} />
            <ParamSlice2DPanel trials={detail.trials} paramNames={detail.paramNames} />
            <TopKPanel trials={detail.trials} paramNames={detail.paramNames} />
          </Stack>
        )}
      </Stack>
    </Container>
  );
}

function StudyBadges({ summary }: { summary: StudyListItem }): ReactNode {
  const best = summary.bestTestScore ?? summary.bestValue;
  return (
    <Group gap="xs">
      {summary.nTrials !== null && <Badge variant="light">{summary.nTrials} trials</Badge>}
      {best !== null && best !== undefined && (
        <Badge color="teal" variant="light">
          best = {formatSigned(best)}{summary.bestTestScore !== null ? ' (test)' : ''}
        </Badge>
      )}
      {summary.hasValidators && <Badge color="violet" variant="light">validators</Badge>}
      {summary.hasRetest && <Badge color="blue" variant="light">retest</Badge>}
    </Group>
  );
}

function formatStudyLabel(s: StudyListItem): string {
  const parts: string[] = [s.name];
  if (s.nTrials !== null) parts.push(`${s.nTrials} trials`);
  const best = s.bestTestScore ?? s.bestValue;
  if (best !== null && best !== undefined) parts.push(`best=${Math.round(best).toLocaleString()}`);
  return parts.join(' · ');
}

function formatSigned(v: number): string {
  const sign = v >= 0 ? '' : '-';
  return sign + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
}
