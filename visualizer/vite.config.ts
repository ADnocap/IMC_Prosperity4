import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    // Bind to IPv4 explicitly. Node prefers IPv6 for "localhost" on Windows 10+,
    // which makes `127.0.0.1:5555` probes (netstat, curl, PS scripts) fail even
    // though the dev server is reachable from a browser via `localhost`.
    host: '127.0.0.1',
    port: 5555,
    proxy: {
      '/dashboard.json': 'http://127.0.0.1:8001',
      '/__prosperity4mcbt__': 'http://127.0.0.1:8001',
      '/run_summary.csv': 'http://127.0.0.1:8001',
      '/session_summary.csv': 'http://127.0.0.1:8001',
      '/sample_paths': 'http://127.0.0.1:8001',
      '/sessions': 'http://127.0.0.1:8001',
      '/static_charts': 'http://127.0.0.1:8001',
    },
  },
  build: {
    minify: true,
    sourcemap: false,
  },
  resolve: {
    alias: {
      '@tabler/icons-react': '@tabler/icons-react/dist/esm/icons/index.mjs',
    },
  },
  optimizeDeps: {
    include: [
      'papaparse',
      'hyparquet',
      'arquero',
      'simple-statistics',
      'mantine-react-table',
      '@mantine/dates',
      '@tanstack/react-table',
      'dayjs',
    ],
  },
});
