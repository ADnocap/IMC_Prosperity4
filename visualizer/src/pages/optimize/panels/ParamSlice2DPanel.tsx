// 2D param slice — scatter over (x, y) param pair, coloured by objective.
//
// When a study has 3+ params, marginal 1D scatters can hide interaction
// effects (param A only matters when param B is low, etc.). A 2D slice lets
// you inspect any chosen pair at a glance: hotspots = basins, gradient
// direction = which way to push in future studies.
//
// We use a colour scale tied to the score range (blue = low, red = high)
// and reduce every point to just (x, y, score). If there are more than two
// numeric params, the view conditions on "all trials" rather than holding
// the others fixed — we rely on enough trial coverage for the visual to
// still be informative.

import { Group, Select, Stack, Text } from '@mantine/core';
import { ReactNode, useMemo, useState } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { TrialRow } from '../types.ts';

interface Props {
  trials: TrialRow[];
  paramNames: string[];
}

export function ParamSlice2DPanel({ trials, paramNames }: Props): ReactNode {
  const completed = useMemo(
    () => trials.filter(t => (t.state ?? '') === 'COMPLETE'),
    [trials],
  );

  const numericParams = useMemo(() => {
    return paramNames.filter(name => completed.some(t => typeof t[`params_${name}`] === 'number'));
  }, [paramNames, completed]);

  const [xParam, setXParam] = useState<string | null>(numericParams[0] ?? null);
  const [yParam, setYParam] = useState<string | null>(numericParams[1] ?? null);

  const useTest = useMemo(
    () => completed.some(t => typeof t.test_score === 'number' && isFinite(Number(t.test_score))),
    [completed],
  );

  const { seriesData, scoreRange } = useMemo(() => {
    if (xParam === null || yParam === null) {
      return { seriesData: [], scoreRange: [0, 1] as [number, number] };
    }
    const pts: Array<{ x: number; y: number; z: number }> = [];
    let lo = Infinity;
    let hi = -Infinity;
    for (const t of completed) {
      const x = Number(t[`params_${xParam}`]);
      const y = Number(t[`params_${yParam}`]);
      const v = Number(useTest ? t.test_score : t.value);
      if (!isFinite(x) || !isFinite(y) || !isFinite(v)) continue;
      pts.push({ x, y, z: v });
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    return { seriesData: pts, scoreRange: [lo, hi] as [number, number] };
  }, [completed, xParam, yParam, useTest]);

  if (numericParams.length < 2) {
    return (
      <VisualizerCard title="2D slice">
        <Text size="sm" c="dimmed">Need at least two numeric params for a 2D slice. This study has {numericParams.length}.</Text>
      </VisualizerCard>
    );
  }

  const paramOptions = numericParams.map(p => ({ value: p, label: p }));
  const [lo, hi] = scoreRange;
  const span = Math.max(hi - lo, 1e-9);

  // Pre-compute color per point based on score percentile.
  const colored = seriesData.map(pt => ({
    x: pt.x,
    y: pt.y,
    color: scoreColor((pt.z - lo) / span),
    z: pt.z,  // preserved for tooltip
  }));

  return (
    <VisualizerCard title={`2D slice — ${useTest ? 'OOS test score' : 'value'} across (x, y) params`}>
      <Stack gap="md">
        <Group>
          <Select label="X param" data={paramOptions} value={xParam} onChange={setXParam} />
          <Select label="Y param" data={paramOptions} value={yParam} onChange={setYParam} />
          <Text size="xs" c="dimmed" style={{ alignSelf: 'end', marginBottom: 8 }}>
            Blue → Red = score low → high ({lo.toFixed(0)} → {hi.toFixed(0)})
          </Text>
        </Group>
        <SimpleChart
          title={`${xParam ?? ''} × ${yParam ?? ''}`}
          series={[{
            type: 'scatter',
            name: useTest ? 'test score' : 'value',
            data: colored as unknown as Highcharts.PointOptionsObject[],
            marker: { radius: 7, symbol: 'circle' },
          }]}
          options={{
            chart: { height: 360 },
            xAxis: { title: { text: xParam ?? '' } },
            yAxis: { title: { text: yParam ?? '' } },
            legend: { enabled: false },
            tooltip: {
              formatter: function () {
                const p = this.point as unknown as { x: number; y: number; z: number };
                return `<b>${xParam}</b> = ${p.x}<br/><b>${yParam}</b> = ${p.y}<br/>score = ${p.z.toFixed(1)}`;
              },
            },
          }}
        />
      </Stack>
    </VisualizerCard>
  );
}

// Linear interpolation from blue (low) through grey to red (high).
function scoreColor(t: number): string {
  const s = Math.max(0, Math.min(1, t));
  if (s <= 0.5) {
    const k = s / 0.5;
    return blend('#4c6ef5', '#adb5bd', k);
  }
  const k = (s - 0.5) / 0.5;
  return blend('#adb5bd', '#fa5252', k);
}

function blend(a: string, b: string, t: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function parseHex(h: string): [number, number, number] {
  const m = h.replace('#', '');
  return [
    parseInt(m.slice(0, 2), 16),
    parseInt(m.slice(2, 4), 16),
    parseInt(m.slice(4, 6), 16),
  ];
}
