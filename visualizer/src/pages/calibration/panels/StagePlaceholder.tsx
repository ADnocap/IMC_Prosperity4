import { Alert, Code, Stack, Text } from '@mantine/core';
import { ReactNode } from 'react';

interface Props {
  stageId: string;
  label: string;
  description?: string;
}

/**
 * Render-until-implemented stub. Each stage panel will replace this progressively.
 */
export function StagePlaceholder({ stageId, label, description }: Props): ReactNode {
  return (
    <Stack gap="sm">
      <Text size="lg" fw={600}>{label}</Text>
      <Alert color="gray" title="Stage not implemented yet">
        <Text size="sm">
          This stage will be wired up in a later commit. Its compute kernels are {' '}
          <Code>wasm_compute/src/calibration.rs</Code> and {' '}
          <Code>wasm_compute/src/formula_search.rs</Code>.
        </Text>
        {description && <Text size="sm" mt="xs">{description}</Text>}
        <Text size="xs" c="dimmed" mt="xs">stageId: {stageId}</Text>
      </Alert>
    </Stack>
  );
}
