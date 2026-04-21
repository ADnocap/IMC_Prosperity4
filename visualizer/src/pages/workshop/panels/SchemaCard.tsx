import { Badge, Group, Stack, Table, Text } from '@mantine/core';
import { ReactNode } from 'react';
import { VisualizerCard } from '../../visualizer/VisualizerCard.tsx';
import { ConcatenatedTable } from '../concat.ts';
import { ParsedTable } from '../types.ts';

interface Props {
  prices: ConcatenatedTable | null;
  trades: ConcatenatedTable | null;
  observations: ConcatenatedTable | null;
  others: ParsedTable[];
}

function ShapeTable({
  title,
  table,
}: {
  title: string;
  table: ConcatenatedTable | ParsedTable | null;
}): ReactNode {
  if (table === null) {
    return (
      <VisualizerCard title={title}>
        <Text c="dimmed" size="sm">Not loaded for the current selection.</Text>
      </VisualizerCard>
    );
  }
  const shape = table.shape;
  const rowCount = 'rows' in table ? table.rows.length : shape.rowCount;
  return (
    <VisualizerCard title={title}>
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Badge variant="light">{rowCount} rows</Badge>
          <Badge variant="light">{shape.columns.length} cols</Badge>
          {shape.hasLadder && <Badge variant="light" color="blue">ladder ×{shape.ladderLevels.length}</Badge>}
          {shape.products.length > 0 && (
            <Badge variant="light" color="teal">{shape.products.length} products</Badge>
          )}
          {shape.counterparties.length > 0 && (
            <Badge variant="light" color="grape">{shape.counterparties.length} counterparties</Badge>
          )}
        </Group>
        <Table striped withTableBorder withColumnBorders>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Column</Table.Th>
              <Table.Th>Kind</Table.Th>
              <Table.Th>Sample</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shape.columns.map(col => (
              <Table.Tr key={col.name}>
                <Table.Td>
                  <Text ff="monospace" size="sm">{col.name}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge size="xs" variant="dot">{col.kind}</Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {col.sample === null ? '—' : String(col.sample)}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </VisualizerCard>
  );
}

export function SchemaCard({ prices, trades, observations, others }: Props): ReactNode {
  return (
    <Stack gap="md">
      <ShapeTable title="Prices" table={prices} />
      <ShapeTable title="Trades" table={trades} />
      <ShapeTable title="Observations" table={observations} />
      {others.map(o => (
        <ShapeTable key={o.entry.path} title={`Other · ${o.entry.filename}`} table={o} />
      ))}
    </Stack>
  );
}
