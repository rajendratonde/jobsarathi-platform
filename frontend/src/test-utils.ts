import { vi } from 'vitest';

// Route-based fetch mock for component tests: "METHOD /path" -> handler.

export type Handler = (body: unknown, init: RequestInit) => { status?: number; body?: unknown };

export function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

export function apiError(status: number, code: string, message = code) {
  return { status, body: { type: 't', status, code, message, errors: [], details: {}, correlation_id: 'corr1234', timestamp: '' } };
}

export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown; headers: Record<string, string> }[] = [];
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init = {}) => {
    const url = new URL(String(input), 'http://localhost');
    const path = url.pathname.replace(/^\/svc\/[a-z]+/, '');
    const key = `${init.method ?? 'GET'} ${path}`;
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ key, body, headers: (init.headers ?? {}) as Record<string, string> });
    const handler = routes[key];
    if (!handler) return json(404, apiError(404, 'NOT_FOUND').body);
    const result = handler(body, init);
    return json(result.status ?? 200, result.body);
  });
  return { calls, spy };
}

export const org = (id: string, name: string, platform = false) => ({
  organization: { id, organization_code: `ORG-${id}`, name, organization_type: platform ? 'PLATFORM' : 'EMPLOYER', is_platform: platform, status: 'ACTIVE' },
  membership_id: `m-${id}`, membership_status: 'ACTIVE', roles: [] as string[],
});

export function token(overrides: Record<string, unknown> = {}) {
  return {
    access_token: 'access-1', token_type: 'Bearer', expires_at: 0, password_change_required: false,
    user: { id: 'u1', display_name: 'Asha Rao', status: 'ACTIVE' }, active_organization_id: 'o1',
    organizations: [org('o1', 'JobSarathi', true)], ...overrides,
  };
}

export function permissions(map: Record<string, string>, organization_id: string | null = 'o1') {
  return { organization_id, authz_version: 1, roles: [], permissions: map };
}
