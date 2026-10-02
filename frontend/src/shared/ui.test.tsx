import { renderHook, waitFor } from '@testing-library/react';
import { expect, it } from 'vitest';

import { useLoad } from './ui';

it('keeps the newest result when an older request finishes last', async () => {
  const resolvers: Record<string, (value: string) => void> = {};
  const fetchFor = (key: string) => new Promise<string>((resolve) => { resolvers[key] = resolve; });
  const { result, rerender } = renderHook(({ key }) => useLoad(() => fetchFor(key), [key]), {
    initialProps: { key: 'identity' },
  });
  rerender({ key: 'reference' });
  await waitFor(() => expect(resolvers.reference).toBeDefined());
  resolvers.reference('reference list');
  await waitFor(() => expect(result.current.data).toBe('reference list'));
  resolvers.identity('identity list'); // the slow, older request
  await new Promise((r) => setTimeout(r, 20));
  expect(result.current.data).toBe('reference list');
});
