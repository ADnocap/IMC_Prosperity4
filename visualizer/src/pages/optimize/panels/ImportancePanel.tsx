// fANOVA importance bar chart — params ranked by variance-decomposition share.
//
// This is already shown as badges in the validators card, but a bar chart
// makes the relative magnitudes pop — especially when one param accounts for
// >90% of the variance (common; our R2 smoke study showed IPR_ASK_OFFSET_1
// at 0.96 and the others below 0.05). Params you could freeze in future
// studies become obvious visually.

import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { Validators } from '../types.ts';

interface Props {
  validators: Validators | null;
}

export function ImportancePanel({ validators }: Props): ReactNode {
  const { categories, data } = useMemo(() => {
    const importances = validators?.importance?.importances ?? {};
    const pairs = Object.entries(importances).sort((a, b) => b[1] - a[1]);
    return {
      categories: pairs.map(([name]) => name),
      data: pairs.map(([, value]) => value),
    };
  }, [validators]);

  if (categories.length === 0) {
    return (
      <SimpleChart
        title="Param importance (fANOVA)"
        subtitle="No importance data — validators.json missing or importance failed."
        series={[]}
      />
    );
  }

  return (
    <SimpleChart
      title="Param importance (fANOVA)"
      subtitle="Normalized to sum 1 — params with <0.05 barely move the objective."
      series={[{
        type: 'bar',
        name: 'Importance',
        data,
        color: '#7950f2',
      }]}
      options={{
        chart: { height: 360 },
        xAxis: { categories, title: { text: undefined } },
        yAxis: { title: { text: 'Importance share' }, max: 1, min: 0 },
        legend: { enabled: false },
        plotOptions: {
          bar: {
            dataLabels: { enabled: true, format: '{y:.3f}' },
          },
        },
      }}
    />
  );
}
