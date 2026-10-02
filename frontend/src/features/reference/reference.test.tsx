import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { mockApi, permissions, token } from '../../test-utils';

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

const signedIn = (perms: Record<string, string>) => ({
  'POST /v1/auth/refresh': () => ({ body: token() }),
  'GET /v1/me/permissions': () => ({ body: permissions(perms) }),
});

const LISTS = [
  { list: 'states', label: 'States', requires_approval: false, active: 36, total: 36, searchable: false, fields: [] },
  { list: 'cities', label: 'Cities', requires_approval: true, active: 2, total: 3, searchable: false,
    fields: [{ name: 'state_code', label: 'State', kind: 'parent', required: true, immutable: false, parent_list: 'states' }] },
];

const value = (overrides: Record<string, unknown>) => ({
  id: 'v1', code: 'PUNE', name: 'Pune', name_hi: null, sort_order: 10, is_active: true, version: 111,
  updated_at: '', pending_request: null, state_code: 'MH', ...overrides,
});

function openReference(extra: Record<string, (body: unknown) => { status?: number; body?: unknown }> = {}) {
  const api = mockApi({
    ...signedIn({ 'REFERENCE.EDIT': 'ALL' }),
    'GET /v1/admin/reference': () => ({ body: LISTS }),
    'GET /v1/admin/reference/states': () => ({ body: { items: [value({ id: 's1', code: 'MH', name: 'Maharashtra' })], page: 1, size: 20, total: 1 } }),
    'GET /v1/admin/reference/cities': () => ({ body: { items: [
      value({}), value({ id: 'v2', code: 'NAGPUR', name: 'Nagpur', pending_request: { id: 'r1', request_number: 'APR-R-000004', action_type: 'UPDATE', summary: 'Edit NAGPUR' } }),
      value({ id: 'v3', code: 'OLD', name: 'Old town', is_active: false }),
    ], page: 1, size: 20, total: 3 } }),
    'GET /v1/reference/states': () => ({ body: { items: [{ code: 'MH', name: 'Maharashtra', name_hi: null }] } }),
    ...extra,
  });
  window.history.pushState({}, '', '/admin/reference');
  render(<App />);
  return api;
}

describe('reference data administration', () => {
  it('renders any list from server metadata and marks pending and inactive values', async () => {
    openReference();
    await screen.findByRole('option', { name: /Cities/ });
    fireEvent.change(screen.getByLabelText('List'), { target: { value: 'cities' } });
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'State' })).toBeInTheDocument(); // extra field from metadata
    expect(within(table).getByText('Pending approval · APR-R-000004')).toBeInTheDocument();
    expect(within(table).getByText('Inactive')).toBeInTheDocument();
    expect(screen.getByText(/Changes to this list need approval/)).toBeInTheDocument();
    const nagpur = within(table).getByText('Nagpur').closest('tr')!;
    expect(within(nagpur).queryByRole('button', { name: 'Edit' })).toBeNull(); // locked while pending
  });

  it('submits a new value for approval and says so', async () => {
    const { calls } = openReference({
      'POST /v1/admin/reference/cities': () => ({ status: 201, body: { status: 'PENDING_APPROVAL', entity_id: 'n1', value: null,
        approval_request: { id: 'r9', request_number: 'APR-R-000009', status: 'PENDING' } } }),
    });
    await screen.findByRole('option', { name: /Cities/ });
    fireEvent.change(screen.getByLabelText('List'), { target: { value: 'cities' } });
    fireEvent.click(await screen.findByText('Add a value'));
    const form = screen.getByRole('form', { name: 'Add to Cities' });
    fireEvent.change(within(form).getByLabelText('Code'), { target: { value: 'NASHIK_ROAD' } });
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Nashik Road' } });
    fireEvent.change(await within(form).findByLabelText('State'), { target: { value: 'MH' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Add value' }));
    expect(await screen.findByText(/Submitted for approval \(APR-R-000009\)/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === 'POST /v1/admin/reference/cities')?.body).toEqual(
      { name: 'Nashik Road', name_hi: null, sort_order: 0, state_code: 'MH', code: 'NASHIK_ROAD' });
  });

  it('shows field errors from the server next to the field', async () => {
    openReference({
      'POST /v1/admin/reference/states': () => ({ status: 422, body: { type: 't', status: 422, code: 'VALIDATION_FAILED',
        message: 'Some fields need attention.', errors: [{ field: 'code', code: 'INVALID_CODE', message: 'Use capital letters, digits and underscores (max 50).' }],
        details: {}, correlation_id: 'c1', timestamp: '' } }),
    });
    fireEvent.click(await screen.findByText('Add a value'));
    const form = screen.getByRole('form', { name: 'Add to States' });
    fireEvent.change(within(form).getByLabelText('Code'), { target: { value: 'bad code' } });
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'X' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Add value' }));
    expect(await within(form).findByText('Use capital letters, digits and underscores (max 50).', { selector: '.field-error' }))
      .toBeInTheDocument();
    expect(within(form).getByLabelText('Code')).toHaveAttribute('aria-invalid', 'true');
  });

  it('edits with the version it read and deactivates instead of deleting', async () => {
    const { calls } = openReference({
      'PUT /v1/admin/reference/cities/v1': () => ({ body: { status: 'APPLIED', entity_id: 'v1', approval_request: null } }),
      'PATCH /v1/admin/reference/cities/v1/status': () => ({ body: { status: 'APPLIED', entity_id: 'v1', approval_request: null } }),
    });
    await screen.findByRole('option', { name: /Cities/ });
    fireEvent.change(screen.getByLabelText('List'), { target: { value: 'cities' } });
    const row = (await screen.findByText('Pune')).closest('tr')!;
    expect(within(row).queryByRole('button', { name: /delete/i })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Edit' }));
    const form = screen.getByRole('form', { name: 'Edit PUNE' });
    expect(within(form).queryByLabelText('Code')).toBeNull(); // codes never change
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Pune City' } });
    fireEvent.submit(form); // the real-browser click is covered by the Playwright run
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(calls.find((c) => c.key === 'PUT /v1/admin/reference/cities/v1')?.body).toMatchObject({ name: 'Pune City', version: 111 });
    fireEvent.click(within((await screen.findByText('Pune')).closest('tr')!).getByRole('button', { name: 'Deactivate' }));
    await screen.findAllByText('Saved.');
    expect(calls.find((c) => c.key === 'PATCH /v1/admin/reference/cities/v1/status')?.body).toEqual({ is_active: false, version: 111 });
  });

  it('is closed without REFERENCE.EDIT', async () => {
    mockApi(signedIn({ 'USER.VIEW': 'ALL' }));
    window.history.pushState({}, '', '/admin/reference');
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to open this page.');
    expect(screen.getByRole('navigation', { name: 'Administration' })).not.toHaveTextContent('Reference data');
  });
});

describe('approvals across services', () => {
  it('switches between access-control and reference-data queues and labels stale requests', async () => {
    const { calls } = mockApi({
      ...signedIn({ 'MAKER_CHECKER.VIEW': 'ALL' }),
      'GET /v1/approvals': () => ({ body: { items: [], page: 1, size: 50, total: 0 } }),
    });
    window.history.pushState({}, '', '/admin/approvals');
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Area'), { target: { value: 'reference' } });
    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'SUPERSEDED' } });
    expect(screen.getByRole('option', { name: 'Stale (record changed)' })).toBeInTheDocument();
    await screen.findAllByText('Nothing here.');
    const services = calls.filter((c) => c.key === 'GET /v1/approvals').map((c) => c.service);
    expect(services[0]).toBe('identity');
    expect(services.at(-1)).toBe('reference');
  });
});
