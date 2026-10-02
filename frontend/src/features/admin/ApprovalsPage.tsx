import { useState } from 'react';

import { ErrorNote, Notice, useLoad } from '../../shared/ui';
import { identityApi } from '../identity/api';

export function ApprovalsPage() {
  const [status, setStatus] = useState('PENDING');
  const list = useLoad(() => identityApi.approvals(status), [status]);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <section aria-labelledby="appr-title">
      <div className="page-head">
        <h1 id="appr-title">Approvals</h1>
        <label>Show{' '}
          <select value={status} onChange={(e) => { setStatus(e.target.value); setSelected(null); }}>
            {['PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'SUPERSEDED'].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <p className="muted">Access changes need a second person. You cannot decide a change you submitted or one that changes your own access.</p>
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
      {selected && <ApprovalPanel key={selected} id={selected} onDone={list.reload} />}
    </section>
  );
}

function ApprovalPanel({ id, onDone }: { id: string; onDone: () => void }) {
  const detail = useLoad(() => identityApi.approval(id), [id]);
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
    }
  };

  return (
    <aside className="card" aria-label="Approval request">
      <ErrorNote error={detail.error} />
      {d && (
        <>
          <h2>{d.request_number} <span className={`pill pill-${d.status.toLowerCase()}`}>{d.status}</span></h2>
          <p>{d.change_summary}</p>
          <p className="muted small">{d.entity_type} · {d.action_type} · record version {d.entity_version}</p>
          {d.proposed_changes && <pre className="proposal">{JSON.stringify(d.proposed_changes, null, 2)}</pre>}
          {d.decision_reason && <p>Reason: {d.decision_reason}</p>}
          <ol className="history">
            {d.actions.map((a, i) => <li key={i}>{a.action.toLowerCase()} · {new Date(a.acted_at).toLocaleString()}{a.comment ? ` — ${a.comment}` : ''}</li>)}
          </ol>
          {d.can_decide && (
            <div className="form">
              <button className="primary" onClick={() => run(() => identityApi.approve(d.id, d.entity_version))}>Approve</button>
              <label>Reason for rejecting<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              <button disabled={reason.trim().length < 5}
                      onClick={() => run(() => identityApi.reject(d.id, d.entity_version, reason))}>Reject</button>
            </div>
          )}
          {d.can_withdraw && <button onClick={() => run(() => identityApi.withdraw(d.id))}>Withdraw my request</button>}
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
