import { Alert, Group, Loader, Stack, Text } from '@mantine/core';
import { ReactNode, useMemo } from 'react';
import { SimpleChart } from '../../montecarlo/MonteCarloComponents.tsx';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { formatNumber } from '../../../utils/format.ts';
import { PreparedPrices } from '../compute/project.ts';
import { useCompute } from '../compute/useCompute.ts';
import { TaskInput } from '../compute/types.ts';

interface Props {
  prepared: PreparedPrices | null;
  products: string[];
}

const PALETTE = ['#4c6ef5', '#12b886', '#fd7e14', '#7950f2', '#fa5252', '#15aabf', '#e67700', '#2f9e44'];

export function OfiPanel({ prepared, products }: Props): ReactNode {
  const task = useMemo<(TaskInput & { kind: 'ofi' }) | null>(() => {
    if (prepared === null || !prepared.hasLadder) return null;
    const projection = prepared.projection;
    return {
      kind: 'ofi',
      input: {
        productsAllowed: products.length > 0 ? products : null,
        products: projection.products,
        times: projection.times,
        mids: projection.mids,
        bid1: projection.bid1,
        bidVol1: projection.bidVol1,
        ask1: projection.ask1,
        askVol1: projection.askVol1,
        maxScatter: 1500,
      },
    };
  }, [prepared, products]);

  const { data, loading, error } = useCompute(task);

  if (prepared === null) {
    return (
      <VisualizerCard title="Order flow imbalance → next-tick return">
        <Text c="dimmed" size="sm">Load a prices file to see this panel.</Text>
      </VisualizerCard>
    );
  }
  if (error !== null) {
    return (
      <VisualizerCard title="Order flow imbalance → next-tick return">
        <Alert color="red">{error.message}</Alert>
      </VisualizerCard>
    );
  }
  if (data === null || data.length === 0) {
    return (
      <VisualizerCard title="Order flow imbalance → next-tick return">
        {loading ? (
          <Group><Loader size="sm" /><Text>Computing…</Text></Group>
        ) : (
          <Alert color="yellow">Need top-of-book bid/ask prices + volumes + mid.</Alert>
        )}
      </VisualizerCard>
    );
  }

  return (
    <VisualizerCard title={`Order flow imbalance (Cont-Kukanov) → next-tick return${loading ? ' · computing…' : ''}`}>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          OFI = signed size change at top of book (bid events positive, ask events negative).
          The regression slope is Kyle-style price impact per unit of signed flow.
        </Text>
        {data.map((s, i) => (
          <SimpleChart
            key={`ofi-${s.product}`}
            title={`${s.product}  ·  corr=${formatNumber(s.correlation, 3)}  ·  λ=${formatNumber(s.slope, 5)}  ·  n=${s.n}`}
            series={[
              {
                type: 'scatter',
                name: 'ticks',
                color: PALETTE[i % PALETTE.length],
                data: s.scatter,
                marker: { radius: 1.5, symbol: 'circle', fillOpacity: 0.35 },
                opacity: 0.5,
                enableMouseTracking: false,
                boostThreshold: 1,
                states: { hover: { enabled: false } },
              },
              {
                type: 'line',
                name: 'OLS fit',
                color: '#fa5252',
                lineWidth: 2,
                data: [[s.xMin, s.slope * s.xMin + s.intercept], [s.xMax, s.slope * s.xMax + s.intercept]],
                marker: { enabled: false },
              },
            ]}
            options={{
              xAxis: { title: { text: 'OFI_t' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              yAxis: { title: { text: 'Δmid_{t+1}' }, plotLines: [{ value: 0, color: '#868e96', width: 1 }] },
              tooltip: { valueDecimals: 3 },
            }}
          />
        ))}
      </Stack>
    </VisualizerCard>
  );
}
