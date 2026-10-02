import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { apiError, mockApi, org, permissions, token } from '../../test-utils';

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

const noSession = { 'POST /v1/auth/refresh': () => apiError(401, 'SESSION_ENDED') };

describe('sign-in', () => {
  it('signs in with a temporary password, forces a change, then shows permitted areas only', async () => {
    const { calls } = mockApi({
      ...noSession,
      'POST /v1/auth/password/login': () => ({ body: token({ password_change_required: true }) }),
      'POST /v1/auth/password/change': () => ({ body: token({ access_token: 'access-2' }) }),
      'GET /v1/me/permissions': () => ({ body: permissions({ 'USER.VIEW': 'ORGANIZATION', 'ROLE.VIEW': 'ALL' }) }),
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'asha@example.test' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Temp-pass-1234' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Choose a new password')).toBeInTheDocument();
    expect(calls.some((c) => c.key === 'GET /v1/me/permissions')).toBe(false); // refused by the server until changed

    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'Temp-pass-1234' } });
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'Mine-2026-pass' } });
    fireEvent.change(screen.getByLabelText('Repeat new password'), { target: { value: 'Mine-2026-pass' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }));

    expect(await screen.findByText('Welcome, Asha Rao')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Administration' });
    expect(nav).toHaveTextContent('Users');
    expect(nav).toHaveTextContent('Permission matrix');
    expect(nav).not.toHaveTextContent('Approvals'); // MAKER_CHECKER.VIEW not held
    const withToken = calls.find((c) => c.key === 'GET /v1/me/permissions');
    expect(withToken?.headers.Authorization).toBe('Bearer access-2');
  });

  it('shows the server message on wrong credentials', async () => {
    mockApi({ ...noSession, 'POST /v1/auth/password/login': () => apiError(401, 'INVALID_CREDENTIALS', 'The email or password is not correct.') });
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'a@example.test' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The email or password is not correct.');
  });

  it('signs in with a mobile OTP and never shows the code', async () => {
    const { calls } = mockApi({
      ...noSession,
      'POST /v1/auth/otp/request': () => ({ status: 201, body: { challenge_id: 'c1', expires_at: '', resend_after_seconds: 30, sent_to: '+91 ******3210' } }),
      'POST /v1/auth/otp/verify': () => ({ body: token({ organizations: [], active_organization_id: null }) }),
      'GET /v1/me/permissions': () => ({ body: permissions({}, null) }),
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Mobile OTP' }));
    fireEvent.change(screen.getByLabelText('Mobile number'), { target: { value: '9876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send code' }));
    expect(await screen.findByText('Code sent to +91 ******3210.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('One-time code'), { target: { value: '12a3456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('Welcome, Asha Rao')).toBeInTheDocument();
    expect(calls.find((c) => c.key === 'POST /v1/auth/otp/verify')?.body).toEqual({ challenge_id: 'c1', mobile: '9876543210', code: '123456' });
    expect(screen.queryByRole('navigation', { name: 'Administration' })).toBeNull();
  });
});

describe('organization context', () => {
  it('asks a multi-organization user to choose, then switches', async () => {
    const { calls } = mockApi({
      'POST /v1/auth/refresh': () => ({ body: token({ active_organization_id: null, organizations: [org('o1', 'Acme Hiring'), org('o2', 'Beta Works')] }) }),
      'GET /v1/me/permissions': () => ({ body: permissions({}, null) }),
      'POST /v1/me/organization/switch': (body) => ({
        body: { token: token({ access_token: 'access-o2', active_organization_id: (body as { organization_id: string }).organization_id,
                               organizations: [org('o1', 'Acme Hiring'), org('o2', 'Beta Works')] }),
                permissions: permissions({ 'USER.VIEW': 'ORGANIZATION' }, 'o2') },
      }),
    });
    render(<App />);
    expect(await screen.findByText('Choose an organization')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Beta Works/ }));
    expect(await screen.findByText('Acting for Beta Works.')).toBeInTheDocument();
    expect(calls.find((c) => c.key === 'POST /v1/me/organization/switch')?.body).toEqual({ organization_id: 'o2' });
    expect(screen.getByLabelText('Active organization')).toHaveValue('o2');
  });
});

describe('session refresh', () => {
  it('refreshes once on TOKEN_STALE and retries the request', async () => {
    let refreshes = 0;
    let permissionCalls = 0;
    mockApi({
      'POST /v1/auth/refresh': () => { refreshes += 1; return { body: token({ access_token: `access-r${refreshes}` }) }; },
      'GET /v1/me/permissions': () => ({ body: permissions({ 'ROLE.VIEW': 'ALL' }) }),
      'GET /v1/roles': () => {
        permissionCalls += 1;
        return permissionCalls === 1 ? apiError(401, 'TOKEN_STALE') : { body: { items: [], page: 1, size: 100, total: 0 } };
      },
      'GET /v1/permissions': () => ({ body: [] }),
    });
    window.history.pushState({}, '', '/admin/roles');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Roles' })).toBeInTheDocument();
    await waitFor(() => expect(permissionCalls).toBe(2));
    expect(refreshes).toBe(2); // start-up + the stale retry
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps a page closed without its permission even if the URL is typed', async () => {
    mockApi({
      'POST /v1/auth/refresh': () => ({ body: token() }),
      'GET /v1/me/permissions': () => ({ body: permissions({ 'USER.VIEW': 'ORGANIZATION' }) }),
    });
    window.history.pushState({}, '', '/admin/approvals');
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to open this page.');
  });
});
