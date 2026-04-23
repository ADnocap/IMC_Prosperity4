import '@mantine/core/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/code-highlight/styles.css';
import '@mantine/dates/styles.css';
import 'mantine-react-table/styles.css';

import { createTheme, MantineProvider } from '@mantine/core';
import { ReactNode } from 'react';
import { createBrowserRouter, createRoutesFromElements, Navigate, Route, RouterProvider } from 'react-router-dom';
import { BasePage } from './pages/base/BasePage.tsx';
import { CalibrationPage } from './pages/calibration/CalibrationPage.tsx';
import { MonteCarloPage } from './pages/montecarlo/MonteCarloPage.tsx';
import { OptimizePage } from './pages/optimize/OptimizePage.tsx';
import { RunnerPage } from './pages/runner/RunnerPage.tsx';
import { SubmissionsPage } from './pages/submissions/SubmissionsPage.tsx';
import { WorkshopPage } from './pages/workshop/WorkshopPage.tsx';
import { useStore } from './store.ts';

const theme = createTheme({
  colors: {
    // Mantine 7.3.0 changes the dark colors to be more slightly lighter than they used to be
    // See https://mantine.dev/changelog/7-3-0/#improved-dark-color-scheme-colors for more information
    // The old dark colors offer better contrast between default text and background colors
    dark: [
      '#C1C2C5',
      '#A6A7AB',
      '#909296',
      '#5c5f66',
      '#373A40',
      '#2C2E33',
      '#25262b',
      '#1A1B1E',
      '#141517',
      '#101113',
    ],
  },
});

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      <Route path="/" element={<BasePage />}>
        <Route index element={<MonteCarloPage />} />
        <Route path="run" element={<RunnerPage />} />
        <Route path="workshop" element={<WorkshopPage />} />
        <Route path="calibration" element={<CalibrationPage />} />
        <Route path="optimize" element={<OptimizePage />} />
        <Route path="submissions" element={<SubmissionsPage />} />
      </Route>
      <Route path="prosperity4mcbt/*" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </>,
  ),
);

export function App(): ReactNode {
  const colorScheme = useStore(state => state.colorScheme);

  return (
    <MantineProvider theme={theme} defaultColorScheme={colorScheme}>
      <RouterProvider router={router} />
    </MantineProvider>
  );
}
