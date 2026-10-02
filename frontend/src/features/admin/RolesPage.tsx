import { type FormEvent, useMemo, useState } from 'react';

import { changeMessage, ErrorNote, Notice, useLoad } from '../../shared/ui';
import { useAuth } from '../auth/AuthContext';
import { identityApi, type Permission } from '../identity/api';

export function RolesPage() {
  const { can } = useAuth();
  const roles = useLoad(() => identityApi.roles({ size: 100 }), []);
  const permissions = useLoad(() => identityApi.permissionList(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  return (
    <section aria-labelledby="roles-title">
      <h1 id="roles-title">Roles</h1>
      <p className="muted">A role is a set of permissions. Changes go to a second person for approval when required.</p>
      {message && <Notice>{message}</Notice>}
      {can('ROLE.CREATE') && permissions.data && (
        <CreateRole permissions={permissions.data} onDone={(m) => { setMessage(m); void roles.reload(); }} />
      )}
      <ErrorNote error={roles.error} />
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Role</th><th>Code</th><th>Status</th></tr></thead>
          <tbody>
            {roles.data?.items.map((r) => (
              <tr key={r.id} className={selected === r.id ? 'selected' : undefined}>
                <td><button className="link" onClick={() => setSelected(r.id)}>{r.name}</button>
                  {r.is_system && <span className="pill pill-system">system</span>}</td>
                <td><code>{r.role_code}</code></td>
                <td><span className={`pill pill-${r.status.toLowerCase()}`}>{r.status.replace('_', ' ')}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && permissions.data && (
        <RoleEditor key={selected} roleId={selected} permissions={permissions.data}
                    onDone={(m) => { setMessage(m); void roles.reload(); }} />
      )}
    </section>
  );
}

function PermissionPicker({ permissions, chosen, onChange, disabled }: {
  permissions: Permission[]; chosen: Set<string>; onChange: (next: Set<string>) => void; disabled?: boolean;
}) {
  const groups = useMemo(() => {
    const byModule = new Map<string, Permission[]>();
    permissions.filter((p) => p.is_active).forEach((p) => {
      byModule.set(p.module_code, [...(byModule.get(p.module_code) ?? []), p]);
    });
    return [...byModule.entries()];
  }, [permissions]);
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange(next);
  };
  return (
    <div className="picker">
      {groups.map(([module, items]) => (
        <fieldset key={module}>
          <legend>{module}</legend>
          {items.map((p) => (
            <label key={p.id} className="check">
              <input type="checkbox" checked={chosen.has(p.id)} disabled={disabled} onChange={() => toggle(p.id)} />
              <code>{p.permission_code}</code> <span className="muted">{p.description}</span>
            </label>
          ))}
        </fieldset>
      ))}
    </div>
  );
}

function CreateRole({ permissions, onDone }: { permissions: Permission[]; onDone: (message: string) => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<unknown>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const r = await identityApi.createRole({ name, description: description || undefined, permission_ids: [...chosen] });
      onDone(changeMessage(r.status, r.approval_request?.request_number));
      setName('');
      setDescription('');
      setChosen(new Set());
    } catch (err) {
      setError(err);
    }
  };

  return (
    <details className="card">
      <summary>Create a role</summary>
      <form onSubmit={submit} className="form">
        <label>Name<input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <PermissionPicker permissions={permissions} chosen={chosen} onChange={setChosen} />
        <button className="primary">Submit role</button>
      </form>
      <ErrorNote error={error} />
    </details>
  );
}

function RoleEditor({ roleId, permissions, onDone }: {
  roleId: string; permissions: Permission[]; onDone: (message: string) => void;
}) {
  const { can } = useAuth();
  const role = useLoad(() => identityApi.role(roleId), [roleId]);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const r = role.data;
  const current = chosen ?? new Set(r?.permission_ids ?? []);
  const editable = can('ROLE.EDIT') && r !== null && !r.pending_request;

  const run = async (action: () => Promise<{ status: string; approval_request: { request_number: string } | null }>) => {
    setError(null);
    try {
      const result = await action();
      onDone(changeMessage(result.status, result.approval_request?.request_number));
      setChosen(null);
      await role.reload();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <aside className="card" aria-label="Role details">
      <ErrorNote error={role.error} />
      {r && (
        <>
          <h2>{r.name} <span className={`pill pill-${r.status.toLowerCase()}`}>{r.status.replace('_', ' ')}</span></h2>
          <p className="muted">{r.description} · {r.holders} active holder(s)</p>
          {r.pending_request && (
            <Notice>Waiting for approval: {r.pending_request.request_number} — {r.pending_request.summary}</Notice>
          )}
          <PermissionPicker permissions={permissions} chosen={current} onChange={setChosen} disabled={!editable} />
          {editable && (
            <div className="actions">
              <button className="primary" disabled={chosen === null}
                      onClick={() => run(() => identityApi.setRolePermissions(r.id, [...current], r.version))}>
                Submit permission changes
              </button>
              {!r.is_system && ['ACTIVE', 'DISABLED'].includes(r.status) && (
                <button onClick={() => run(() => identityApi.setRoleStatus(r.id, r.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE', r.version))}>
                  {r.status === 'ACTIVE' ? 'Disable role' : 'Enable role'}
                </button>
              )}
            </div>
          )}
        </>
      )}
      <ErrorNote error={error} />
    </aside>
  );
}
