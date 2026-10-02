import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Local development only: /svc/<service> is forwarded to that service's local port.
// This is a dev-server convenience, not the API Gateway (the gateway product is decision T2).
// In every shared environment React calls VITE_API_BASE_URL instead.
const SERVICES: Record<string, number> = {
  identity: 8001,
  candidate: 8002,
  employer: 8003,
  job: 8004,
  application: 8005,
  learning: 8006,
  engagement: 8007,
  reference: 8008,
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      Object.entries(SERVICES).map(([name, port]) => [
        `/svc/${name}`,
        { target: `http://127.0.0.1:${port}`, rewrite: (path: string) => path.replace(`/svc/${name}`, '') },
      ]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
