import { useState } from 'react';

import { ErrorNote, useLoad } from '../../shared/ui';
import { identityApi } from '../identity/api';

/** Resources × actions, built entirely from the database. Read-only: edit a role on the Roles page. */
export function MatrixPage() {
  const roles = useLoad(() => identityApi.roles({ size: 100 }), []);
  const [roleId, setRoleId] = useState('');
  const matrix = useLoad(() => identityApi.matrix(roleId || undefined), [roleId]);
  const m = matrix.data;

  return (
    <section aria-labelledby="matrix-title">
      <div className="page-head">
        <h1 id="matrix-title">Permission matrix</h1>
        <label>Role{' '}
          <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            <option value="">All permissions (no role)</option>
            {roles.data?.items.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
      </div>
      <ErrorNote error={matrix.error} />
      {m && (
        <div className="table-wrap">
          <table className="data matrix">
            <thead>
              <tr><th>Resource</th>{m.columns.map((c) => <th key={c.action_id} scope="col">{c.name}</th>)}</tr>
            </thead>
            <tbody>
              {m.rows.map((row) => (
                <tr key={row.resource_id} className={row.is_active ? undefined : 'inactive'}>
                  <th scope="row">{row.resource_name}<div className="muted small">{row.module_name}</div></th>
                  {row.cells.map((cell, i) => (
                    <td key={m.columns[i].action_id} className="cell">
                      {cell === null ? <span className="muted" aria-label="not defined">·</span>
                        : roleId ? (
                          <span title={cell.permission_code} aria-label={`${cell.permission_code} ${cell.granted ? 'granted' : 'not granted'}`}
                                className={cell.granted ? 'granted' : 'denied'}>{cell.granted ? '✓' : '—'}</span>
                        ) : <code className="small">{cell.permission_code}</code>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
