import { type FormEvent, useState } from 'react';

import { changeMessage, ErrorNote, Notice, useLoad } from '../../shared/ui';
import { useAuth } from '../auth/AuthContext';
import { identityApi, type UserDetail } from '../identity/api';

export function UsersPage() {
  const { can, session } = useAuth();
  const [q, setQ] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const users = useLoad(() => identityApi.users({ q: search, page }), [search, page]);

  return (
    <section aria-labelledby="users-title">
      <div className="page-head">
        <h1 id="users-title">Users</h1>
        <form className="inline" onSubmit={(e) => { e.preventDefault(); setPage(1); setSearch(q); }}>
          <label className="sr-only" htmlFor="user-q">Search users</label>
          <input id="user-q" placeholder="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
          <button>Search</button>
        </form>
      </div>
      {can('USER.CREATE') && <CreateUser organizationId={session?.activeOrganizationId ?? null} onCreated={users.reload} />}
      <ErrorNote error={users.error} />
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Name</th><th>Status</th><th>Last sign-in</th></tr></thead>
          <tbody>
            {users.data?.items.map((u) => (
              <tr key={u.id} className={selected === u.id ? 'selected' : undefined}>
                <td><button className="link" onClick={() => setSelected(u.id)}>{u.display_name}</button></td>
                <td><span className={`pill pill-${u.status.toLowerCase()}`}>{u.status}</span></td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {users.data && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page} · {users.data.total} users</span>
          <button disabled={page * users.data.size >= users.data.total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
      {selected && <UserPanel userId={selected} onChanged={users.reload} />}
    </section>
  );
}

function CreateUser({ organizationId, onCreated }: { organizationId: string | null; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);
  const [error, setError] = useState<unknown>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await identityApi.createUser({ display_name: name, email, organization_id: organizationId });
      setCreated({ email, password: r.temporary_password });
      setName('');
      setEmail('');
      onCreated();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <details className="card">
      <summary>Add a user</summary>
      <form onSubmit={submit} className="form grid2">
        <label>Full name<input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <button className="primary">Create user</button>
      </form>
      {created && (
        <Notice>
          Temporary password for {created.email}: <code>{created.password}</code> — shown once. The user must change it at
          first sign-in.
        </Notice>
      )}
      <ErrorNote error={error} />
    </details>
  );
}

function UserPanel({ userId, onChanged }: { userId: string; onChanged: () => void }) {
  const { can } = useAuth();
  const detail = useLoad(() => identityApi.user(userId), [userId]);
  const roles = useLoad(() => identityApi.userRoles(userId), [userId]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const act = async (action: () => Promise<string>) => {
    setError(null);
    try {
      setMessage(await action());
      await Promise.all([detail.reload(), roles.reload()]);
      onChanged();
    } catch (e) {
      setError(e);
    }
  };

  const user = detail.data;
  return (
    <aside className="card" aria-label="User details">
      <ErrorNote error={detail.error} />
      {user && (
        <>
          <h2>{user.display_name}</h2>
          <p className="muted">{user.identities.map((i) => `${i.identity_type === 'MOBILE_OTP' ? 'Mobile' : 'Email'} ${i.identifier}`).join(' · ')}</p>
          <p>Organizations: {user.memberships.map((m) => `${m.organization_name} (${m.status.toLowerCase()})`).join(', ') || '—'}</p>
          <div className="actions">
            {can('USER.DISABLE') && (
              <button onClick={() => act(async () => {
                await identityApi.setUserStatus(user.id, user.status === 'DISABLED' ? 'ACTIVE' : 'DISABLED');
                return 'Status changed.';
              })}>{user.status === 'DISABLED' ? 'Enable' : 'Disable'}</button>
            )}
            {can('USER.EDIT') && user.identities.some((i) => i.identity_type === 'EMAIL_PASSWORD') && (
              <button onClick={() => act(async () => {
                const r = await identityApi.resetPassword(user.id);
                return `Temporary password (shown once): ${r.temporary_password}`;
              })}>Reset password</button>
            )}
          </div>
          <h3>Roles</h3>
          <ul className="plain">
            {roles.data?.map((a) => (
              <li key={a.id}>
                <strong>{a.role.name}</strong> · {a.scope_type.toLowerCase()} · {a.organization?.name ?? 'personal'}{' '}
                <span className={`pill pill-${a.status.toLowerCase()}`}>{a.status}</span>
                {can('ROLE.ASSIGN') && a.status !== 'REVOKED' && (
                  <button className="link" onClick={() => act(async () => {
                    await identityApi.revokeRole(user.id, a.id);
                    return 'Role revoked.';
                  })}>Revoke</button>
                )}
              </li>
            ))}
          </ul>
          {can('ROLE.ASSIGN') && <AssignRole user={user} onDone={(m) => act(async () => m)} />}
        </>
      )}
      {message && <Notice>{message}</Notice>}
      <ErrorNote error={error} />
    </aside>
  );
}

function AssignRole({ user, onDone }: { user: UserDetail; onDone: (message: string) => void }) {
  const roles = useLoad(() => identityApi.roles({ size: 100 }), []);
  const [roleId, setRoleId] = useState('');
  const [membershipId, setMembershipId] = useState(user.memberships[0]?.membership_id ?? '');
  const [scope, setScope] = useState('ORGANIZATION');
  const [error, setError] = useState<unknown>(null);
  const active = roles.data?.items.filter((r) => r.status === 'ACTIVE') ?? [];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await identityApi.assignRole(user.id, {
        role_id: roleId, membership_id: scope === 'OWN' && !membershipId ? null : membershipId || null, scope_type: scope,
      });
      onDone(changeMessage(r.status, r.approval_request?.request_number));
    } catch (err) {
      setError(err);
    }
  };

  return (
    <form onSubmit={submit} className="form grid2">
      <label>Role
        <select required value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="">Choose a role</option>
          {active.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
      </label>
      <label>Organization
        <select value={membershipId} onChange={(e) => setMembershipId(e.target.value)}>
          <option value="">None (personal)</option>
          {user.memberships.map((m) => <option key={m.membership_id} value={m.membership_id}>{m.organization_name}</option>)}
        </select>
      </label>
      <label>Scope
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="OWN">Own records</option>
          <option value="ORGANIZATION">Whole organization</option>
          <option value="ALL">Everything (platform only)</option>
        </select>
      </label>
      <button className="primary">Assign role</button>
      <ErrorNote error={error} />
    </form>
  );
}
