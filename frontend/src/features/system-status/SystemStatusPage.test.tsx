import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { SystemStatusPage } from './SystemStatusPage';

afterEach(() => vi.restoreAllMocks());

it('shows each service as ready or not ready', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes('/job/')) {
      return new Response(JSON.stringify({ type: 't', status: 503, code: 'DEPENDENCY_UNAVAILABLE', message: 'x', errors: [], details: {}, correlation_id: null, timestamp: '' }), { status: 503 });
    }
    return new Response(
      JSON.stringify({ status: 'ok', service: 's', version: '0.1.0', checks: { database: { status: 'ok' }, migrations: { status: 'ok', current: '0001_platform_tables' } } }),
      { status: 200 },
    );
  });
  render(<SystemStatusPage />);
  await waitFor(() => expect(screen.getAllByText('Ready')).toHaveLength(7));
  expect(screen.getByText('Not ready')).toBeInTheDocument();
  expect(screen.getAllByText('0001_platform_tables')).toHaveLength(7);
});
