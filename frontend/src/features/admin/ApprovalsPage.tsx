import { useState } from 'react';

import { ErrorNote, Notice, useLoad } from '../../shared/ui';
import { useAuth } from '../auth/AuthContext';
import { approvalsApi } from '../identity/api';

// One queue per service that has approvable records. A source is shown when the
// user holds its permission; nothing here names a role.
const SOURCES = [
  { service: 'identity', label: 'Access control', permission: 'MAKER_CHECKER.VIEW' },
  { service: 'reference', label: 'Reference data', permission: 'MAKER_CHECKER.VIEW' },
];

export const STATUS_LABELS: Record<string, string> = {
  PENDING: 'Pending approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
  SUPERSEDED: 'Stale (record changed)',
};

export function ApprovalsPage() {
  const { can } = useAuth();
  const sources = SOURCES.filter((s) => can(s.permission));
  const [service, setService] = useState(sources[0]?.service ?? 'identity');
  const [status, setStatus] = useState('PENDING');
  const api = approvalsApi(service);
  const list = useLoad(() => api.list(status), [service, status]);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <section aria-labelledby="appr-title">
      <div className="page-head">
        <h1 id="appr-title">Approvals</h1>
        <div className="inline">
          <label>Area{' '}
            <select value={service} onChange={(e) => { setService(e.target.value); setSelected(null); }}>
              {sources.map((s) => <option key={s.service} value={s.service}>{s.label}</option>)}
            </select>
          </label>
          <label>Show{' '}
            <select value={status} onChange={(e) => { setStatus(e.target.value); setSelected(null); }}>
              {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
      </div>
      <p className="muted">Changes here need a second person. You cannot decide a change you submitted or one that changes your own access.</p>
      <ErrorNote error={list.error} />
      {list.data?.items.length === 0 && <p>Nothing here.</p>}
      <ul className="queue">
        {list.data?.items.map((a) => (
          <li key={a.id}>
            <button className="link" onClick={() => setSelected(a.id)}>{a.request_number}</button>{' '}
            {a.change_summary ?? `${a.action_type} ${a.entity_type}`}
            <span className="muted small"> · {new Date(a.submitted_at).toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {selected && <ApprovalPanel key={`${service}-${selected}`} service={service} id={selected} onDone={list.reload} />}
    </section>
  );
}

function ApprovalPanel({ service, id, onDone }: { service: string; id: string; onDone: () => void }) {
  const api = approvalsApi(service);
  const detail = useLoad(() => api.get(id), [service, id]);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const d = detail.data;

  const run = async (action: () => Promise<{ status: string }>) => {
    setError(null);
    try {
      const r = await action();
      setMessage(`Request ${r.status.toLowerCase()}.`);
      await detail.reload();
      onDone();
    } catch (e) {
      setError(e);
      await detail.reload();
      onDone(); // a refused decision can still change the queue (e.g. the request became stale)
    }
  };

  return (
    <aside className="card" aria-label="Approval request">
      <ErrorNote error={detail.error} />
      {d && (
        <>
          <h2>{d.request_number}{' '}
            <span className={`pill pill-${d.status.toLowerCase()}`}>{STATUS_LABELS[d.status] ?? d.status}</span></h2>
          <p>{d.change_summary}</p>
          <p className="muted small">{d.entity_type} · {d.action_type} · {d.entity_version === 0 ? 'new record' : `record version ${d.entity_version}`}</p>
          {d.proposed_changes && <pre className="proposal">{JSON.stringify(d.proposed_changes, null, 2)}</pre>}
          {d.decision_reason && <p>Reason: {d.decision_reason}</p>}
          <ol className="history">
            {d.actions.map((a, i) => <li key={i}>{a.action.toLowerCase()} · {new Date(a.acted_at).toLocaleString()}{a.comment ? ` — ${a.comment}` : ''}</li>)}
          </ol>
          {d.can_decide && (
            <div className="form">
              <button className="primary" onClick={() => run(() => api.approve(d.id, d.entity_version))}>Approve</button>
              <label>Reason for rejecting<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              <button disabled={reason.trim().length < 5}
                      onClick={() => run(() => api.reject(d.id, d.entity_version, reason))}>Reject</button>
            </div>
          )}
          {d.can_withdraw && <button onClick={() => run(() => api.withdraw(d.id))}>Withdraw my request</button>}
          {d.status === 'PENDING' && !d.can_decide && !d.can_withdraw && (
            <p className="muted">Another approver must decide this request.</p>
          )}
        </>
      )}
      {message && <Notice>{message}</Notice>}
      <ErrorNote error={error} />
    </aside>
  );
}
