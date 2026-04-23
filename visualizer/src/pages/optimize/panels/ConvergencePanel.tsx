// Convergence chart — "best-so-far" objective value as trials accumulate.
//
// X axis: trial number (order the sampler saw them — important for Bayesian
// samplers like TPE, which warm up on random startups before exploiting).
// Y axis: value (objective). We plot both the raw per-trial score and the
// running maximum so you can see when the sampler latched onto the best
// basin. If `test_score` is available, we overlay it on the top-K; this
// makes OOS gaps visible at a glance.

import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { TrialRow } from '../types.ts';

interface Props {
  trials: TrialRow[];
}

export function ConvergencePanel({ trials }: Props): ReactNode {
  const series = useMemo(() => {
    // Sort trials by trial number so running-max is chronological.
    const ordered = [...trials]
      .filter(t => typeof t.number === 'number' && typeof t.value === 'number' && isFinite(Number(t.value)))
      .sort((a, b) => Number(a.number) - Number(b.number));

    const valuePoints: [number, number][] = [];
    const bestPoints: [number, number][] = [];
    const testPoints: [number, number][] = [];
    let running = -Infinity;
    for (const t of ordered) {
      const n = Number(t.number);
      const v = Number(t.value);
      if (v > running) running = v;
      valuePoints.push([n, v]);
      bestPoints.push([n, running]);
      const test = Number(t.test_score);
      if (isFinite(test)) testPoints.push([n, test]);
    }

    const built: Highcharts.SeriesOptionsType[] = [
      {
        type: 'scatter',
        name: 'Trial score',
        data: valuePoints,
        marker: { radius: 3, symbol: 'circle' },
        color: '#868e96',
        opacity: 0.65,
      },
      {
        type: 'line',
        name: 'Best so far',
        data: bestPoints,
        color: '#4c6ef5',
        lineWidth: 2,
      },
    ];
    if (testPoints.length > 0) {
      built.push({
        type: 'scatter',
        name: 'Test score (OOS)',
        data: testPoints,
        marker: { radius: 5, symbol: 'diamond' },
        color: '#12b886',
      });
    }
    return built;
  }, [trials]);

  return (
    <SimpleChart
      title="Convergence"
      subtitle="Trial score (grey) + best-so-far (blue) + OOS test score on top-K (green)"
      series={series}
      options={{
        chart: { height: 360 },
        xAxis: { title: { text: 'Trial number' } },
        yAxis: { title: { text: 'Objective' } },
        legend: { enabled: true },
      }}
    />
  );
}
