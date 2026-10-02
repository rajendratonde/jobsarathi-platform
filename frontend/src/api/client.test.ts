import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiRequest } from './client';
import { ApiError } from './errors';

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

describe('apiRequest', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends a correlation ID and If-Match, and returns JSON', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(200, { ok: true }));
    const result = await apiRequest<{ ok: boolean }>('job', '/v1/jobs/1', { method: 'PUT', body: { title: 'x' }, version: 3 });
    expect(result).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/svc/job/v1/jobs/1');
    const headers = init?.headers as Record<string, string>;
    expect(headers['X-Correlation-Id']).toMatch(/^[0-9a-f]{32}$/);
    expect(headers['If-Match']).toBe('3');
  });

  it('turns the error model into an ApiError with field messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse(422, {
        type: 't', status: 422, code: 'VALIDATION_FAILED', message: 'Some fields need attention.',
        errors: [{ field: 'salary_max', code: 'LESS_THAN_MIN', message: 'Maximum must be at least the minimum.' }],
        details: {}, correlation_id: 'abc12345', timestamp: 'now',
      }),
    );
    const error = await apiRequest('job', '/v1/jobs', { method: 'POST', body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe('VALIDATION_FAILED');
    expect(apiError.forField('salary_max')).toBe('Maximum must be at least the minimum.');
    expect(apiError.correlationId).toBe('abc12345');
  });

  it('reports network failures plainly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(apiRequest('job', '/health/live')).rejects.toMatchObject({ code: 'NETWORK_ERROR', status: 0 });
  });

  it('handles non-JSON error pages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }));
    await expect(apiRequest('job', '/health/live')).rejects.toMatchObject({ code: 'HTTP_ERROR', status: 502 });
  });
});
