// Marginal param-effect scatters.
//
// For each numeric param, plot (param value, objective) across all trials.
// Gives an immediate visual for where the good basin is — a clear upward or
// concave pattern means the param matters; a flat blob means it doesn't
// (and fANOVA should agree).
//
// The objective column used is `test_score` when available (honest OOS),
// else `value` (training). We also color points by whether the trial is in
// the top-K so the winners stand out in the cloud.

import { Group, Stack, Text } from '@mantine/core';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { TrialRow } from '../types.ts';

interface Props {
  trials: TrialRow[];
  paramNames: string[];
}

const TOP_K = 5;

export function ParamEffectPanel({ trials, paramNames }: Props): ReactNode {
  const { completed, useTest, topNumbers } = useMemo(() => {
    const comp = trials.filter(t => (t.state ?? '') === 'COMPLETE');
    const ut = comp.some(t => typeof t.test_score === 'number' && isFinite(Number(t.test_score)));
    const key = (t: TrialRow) => (ut ? Number(t.test_score) : Number(t.value));
    const sorted = [...comp].sort((a, b) => (key(b) ?? -Infinity) - (key(a) ?? -Infinity));
    const tops = new Set(sorted.slice(0, TOP_K).map(t => Number(t.number)));
    return { completed: comp, useTest: ut, topNumbers: tops };
  }, [trials]);

  const numericParams = useMemo(() => {
    return paramNames.filter(name => {
      return completed.some(t => typeof t[`params_${name}`] === 'number');
    });
  }, [paramNames, completed]);

  if (numericParams.length === 0) {
    return (
      <VisualizerCard title="Param effects">
        <Text size="sm" c="dimmed">No numeric params to plot.</Text>
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Param effects — ${useTest ? 'OOS test score' : 'training value'} vs each param`}>
      <Stack gap="md">
        <Text size="xs" c="dimmed">
          Each dot is a trial. Green diamonds are the top-{TOP_K} by the ranking metric. Look for
          clear monotonic or concave patterns — those are the params worth tuning further.
        </Text>
        <Group align="stretch" grow wrap="wrap">
          {numericParams.map(name => (
            <ParamEffectChart
              key={name}
              name={name}
              trials={completed}
              useTest={useTest}
              topNumbers={topNumbers}
            />
          ))}
        </Group>
      </Stack>
    </VisualizerCard>
  );
}

function ParamEffectChart({
  name, trials, useTest, topNumbers,
}: { name: string; trials: TrialRow[]; useTest: boolean; topNumbers: Set<number> }): ReactNode {
  const { allPoints, topPoints } = useMemo(() => {
    const all: [number, number][] = [];
    const top: [number, number][] = [];
    for (const t of trials) {
      const px = Number(t[`params_${name}`]);
      const py = Number(useTest ? t.test_score : t.value);
      if (!isFinite(px) || !isFinite(py)) continue;
      if (topNumbers.has(Number(t.number))) top.push([px, py]);
      else all.push([px, py]);
    }
    return { allPoints: all, topPoints: top };
  }, [trials, name, useTest, topNumbers]);

  return (
    <SimpleChart
      title={name}
      series={[
        {
          type: 'scatter',
          name: 'Trials',
          data: allPoints,
          color: '#adb5bd',
          marker: { radius: 3, symbol: 'circle' },
        },
        {
          type: 'scatter',
          name: `Top ${TOP_K}`,
          data: topPoints,
          color: '#12b886',
          marker: { radius: 6, symbol: 'diamond' },
        },
      ]}
      options={{
        chart: { height: 260 },
        xAxis: { title: { text: name } },
        yAxis: { title: { text: useTest ? 'test score' : 'value' } },
        legend: { enabled: false },
      }}
    />
  );
}
