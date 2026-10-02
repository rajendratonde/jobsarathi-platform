import { useState } from 'react';

import { ErrorNote } from '../../shared/ui';
import { useAuth } from './AuthContext';

/** Full page shown when the user belongs to several organizations and has not chosen one. */
export function OrganizationSelectPage() {
  const { session, switchOrganization } = useAuth();
  const [error, setError] = useState<unknown>(null);
  if (!session) return null;
  return (
    <section className="card narrow" aria-labelledby="org-title">
      <h1 id="org-title">Choose an organization</h1>
      <p className="muted">You can act for these organizations. You can switch later from the top bar.</p>
      {session.organizations.length === 0 && <p>You are not an active member of any organization yet.</p>}
      <ul className="choices">
        {session.organizations.map((o) => (
          <li key={o.organization.id}>
            <button onClick={() => switchOrganization(o.organization.id).catch(setError)}>
              <strong>{o.organization.name}</strong>
              <span className="muted"> {o.organization.organization_code} · {o.roles.join(', ') || 'no roles'}</span>
            </button>
          </li>
        ))}
      </ul>
      <ErrorNote error={error} />
    </section>
  );
}

/** Compact switcher for the top bar; hidden when there is nothing to switch to. */
export function OrganizationSwitcher() {
  const { session, switchOrganization } = useAuth();
  if (!session || session.organizations.length < 2) return null;
  return (
    <label className="org-switch">
      <span className="sr-only">Active organization</span>
      <select value={session.activeOrganizationId ?? ''} onChange={(e) => void switchOrganization(e.target.value)}>
        {session.activeOrganizationId === null && <option value="">Choose organization</option>}
        {session.organizations.map((o) => (
          <option key={o.organization.id} value={o.organization.id}>{o.organization.name}</option>
        ))}
      </select>
    </label>
  );
}
