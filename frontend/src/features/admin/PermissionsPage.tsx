import { useState } from 'react';

import { changeMessage, ErrorNote, Notice, useLoad } from '../../shared/ui';
import { useAuth } from '../auth/AuthContext';
import { identityApi } from '../identity/api';

export function PermissionsPage() {
  const { can } = useAuth();
  const list = useLoad(() => identityApi.permissionList(), []);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const toggle = async (id: string, active: boolean) => {
    setError(null);
    try {
      const r = await identityApi.setPermissionStatus(id, !active);
      setMessage(changeMessage(r.status, r.approval_request?.request_number));
      await list.reload();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <section aria-labelledby="perm-title">
      <h1 id="perm-title">Permissions</h1>
      <p className="muted">The catalogue: module → resource × action. “Enforced” means a service has declared it checks it.</p>
      {message && <Notice>{message}</Notice>}
      <ErrorNote error={list.error ?? error} />
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Permission</th><th>Module</th><th>Enforced</th><th>Status</th><th /></tr></thead>
          <tbody>
            {list.data?.map((p) => (
              <tr key={p.id}>
                <td><code>{p.permission_code}</code><div className="muted small">{p.description}</div></td>
                <td>{p.module_code}</td>
                <td>{p.is_enforced ? `yes (${p.declared_by_service})` : 'no'}</td>
                <td><span className={`pill pill-${p.is_active ? 'active' : 'disabled'}`}>{p.is_active ? 'ACTIVE' : 'DISABLED'}</span></td>
                <td>
                  {can('ROLE.EDIT') && p.declared_by_service !== 'identity' && (
                    <button className="link" onClick={() => toggle(p.id, p.is_active)}>{p.is_active ? 'Disable' : 'Enable'}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
