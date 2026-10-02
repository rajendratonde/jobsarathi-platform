import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { mockApi, permissions, token } from '../../test-utils';
import { ADMIN_NAV, visibleNav } from './nav';

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

const signedIn = (perms: Record<string, string>) => ({
  'POST /v1/auth/refresh': () => ({ body: token() }),
  'GET /v1/me/permissions': () => ({ body: permissions(perms) }),
});

describe('navigation is data-driven', () => {
  it('shows exactly the entries whose permission is held', () => {
    const held = new Set(['ROLE.VIEW']);
    expect(visibleNav((p) => held.has(p)).map((n) => n.label)).toEqual(['Roles', 'Permissions', 'Permission matrix']);
    expect(visibleNav(() => false)).toEqual([]);
  });

  it('names permissions, never roles', () => {
    for (const item of ADMIN_NAV) expect(item.permission).toMatch(/^[A-Z_]+\.[A-Z_]+$/);
  });
});

describe('permission matrix', () => {
  it('renders resources x actions from the API', async () => {
    mockApi({
      ...signedIn({ 'ROLE.VIEW': 'ALL' }),
      'GET /v1/roles': () => ({ body: { items: [{ id: 'r1', name: 'Recruiting lead', role_code: 'RL', status: 'ACTIVE', is_system: false, version: 1 }], page: 1, size: 100, total: 1 } }),
      'GET /v1/rbac/matrix': () => ({ body: {
        role: { id: 'r1', name: 'Recruiting lead', role_code: 'RL', version: 1, status: 'ACTIVE', is_system: false },
        columns: [{ action_id: 'a1', action_code: 'VIEW', name: 'View' }, { action_id: 'a2', action_code: 'EDIT', name: 'Edit' }],
        rows: [{ module_code: 'M', module_name: 'Identity & Access', resource_id: 'res1', resource_code: 'USER', resource_name: 'Users', is_active: true,
                 cells: [{ permission_id: 'p1', permission_code: 'USER.VIEW', is_active: true, is_enforced: true, granted: true }, null] }],
      } }),
    });
    window.history.pushState({}, '', '/admin/matrix');
    render(<App />);
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'View' })).toBeInTheDocument();
    expect(within(table).getByRole('rowheader', { name: /Users/ })).toBeInTheDocument();
  });
});

describe('approvals', () => {
  const approval = (overrides: Record<string, unknown>) => ({
    id: 'q1', request_number: 'APR-I-000001', entity_type: 'ROLE', entity_id: 'r1', entity_version: 3, action_type: 'CREATE',
    organization_id: null, subject_user_id: null, change_summary: 'Create role Recruiting lead', maker_user_id: 'u9',
    submitted_at: '2026-10-02T10:00:00Z', status: 'PENDING', decision_reason: null, proposed_changes: null,
    actions: [], can_decide: false, can_withdraw: false, ...overrides,
  });

  it('offers approve/reject only when the server says this person may decide', async () => {
    const { calls } = mockApi({
      ...signedIn({ 'MAKER_CHECKER.VIEW': 'ALL' }),
      'GET /v1/approvals': () => ({ body: { items: [approval({})], page: 1, size: 50, total: 1 } }),
      'GET /v1/approvals/q1': () => ({ body: approval({ can_decide: true }) }),
      'POST /v1/approvals/q1/approve': () => ({ body: approval({ status: 'APPROVED' }) }),
    });
    window.history.pushState({}, '', '/admin/approvals');
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'APR-I-000001' }));
    const reject = await screen.findByRole('button', { name: 'Reject' });
    expect(reject).toBeDisabled(); // needs a reason of 5+ characters
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Request approved.')).toBeInTheDocument();
    expect(calls.find((c) => c.key === 'POST /v1/approvals/q1/approve')?.body).toEqual({ reviewed_version: 3 });
  });

  it('shows no decision buttons to the maker', async () => {
    mockApi({
      ...signedIn({ 'MAKER_CHECKER.VIEW': 'ALL' }),
      'GET /v1/approvals': () => ({ body: { items: [approval({})], page: 1, size: 50, total: 1 } }),
      'GET /v1/approvals/q1': () => ({ body: approval({ can_withdraw: true }) }),
    });
    window.history.pushState({}, '', '/admin/approvals');
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'APR-I-000001' }));
    expect(await screen.findByRole('button', { name: 'Withdraw my request' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });
});

describe('users', () => {
  it('shows the temporary password once after creating a user', async () => {
    mockApi({
      ...signedIn({ 'USER.VIEW': 'ORGANIZATION', 'USER.CREATE': 'ORGANIZATION' }),
      'GET /v1/users': () => ({ body: { items: [], page: 1, size: 20, total: 0 } }),
      'POST /v1/users': () => ({ status: 201, body: { user: { id: 'u5', display_name: 'Ravi', status: 'ACTIVE' }, membership_id: 'm5', temporary_password: 'Tmp9xYz12345ab' } }),
    });
    window.history.pushState({}, '', '/admin/users');
    render(<App />);
    fireEvent.click(await screen.findByText('Add a user'));
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Ravi Kumar' } });
    fireEvent.change(screen.getByLabelText('Email', { selector: 'input[type=email]' }), { target: { value: 'ravi@example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }));
    expect(await screen.findByText('Tmp9xYz12345ab')).toBeInTheDocument();
  });
});
