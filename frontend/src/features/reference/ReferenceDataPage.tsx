import { type FormEvent, type ReactNode, useId, useState } from 'react';

import { ApiError } from '../../api/errors';
import { changeMessage, ErrorNote, Notice, useLoad } from '../../shared/ui';
import { type AdminValue, type FieldDef, type ListDef, referenceApi } from './api';

// Reference lists are edited, never deleted: a value is deactivated instead, and its
// code never changes. Whether a change needs a second person comes from the server.

export function ReferenceDataPage() {
  const lists = useLoad(() => referenceApi.lists(), []);
  const [listKey, setListKey] = useState('states');
  const [message, setMessage] = useState<string | null>(null);
  const def = lists.data?.find((l) => l.list === listKey);

  return (
    <section aria-labelledby="ref-title">
      <div className="page-head">
        <h1 id="ref-title">Reference data</h1>
        <label>List{' '}
          <select value={listKey} onChange={(e) => { setListKey(e.target.value); setMessage(null); }}>
            {lists.data?.map((l) => <option key={l.list} value={l.list}>{l.label} ({l.active})</option>)}
          </select>
        </label>
      </div>
      <p className="muted">
        Values are shared by every JobSarathi service. Codes never change; deactivate a value instead of deleting it.
        {def?.requires_approval && <> Changes to this list need approval by a second person.</>}
      </p>
      <ErrorNote error={lists.error} />
      {message && <Notice>{message}</Notice>}
      {def && <ListEditor key={def.list} def={def} onMessage={(m) => { setMessage(m); void lists.reload(); }} />}
    </section>
  );
}

function ListEditor({ def, onMessage }: { def: ListDef; onMessage: (message: string) => void }) {
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [state, setState] = useState('all');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminValue | null>(null);
  const [error, setError] = useState<unknown>(null);
  const values = useLoad(() => referenceApi.values(def.list, { q, state, page }), [def.list, q, state, page]);

  const done = (status: string, requestNumber?: string | null) => {
    onMessage(changeMessage(status, requestNumber));
    setEditing(null);
    void values.reload();
  };

  const toggle = async (v: AdminValue) => {
    setError(null);
    try {
      const r = await referenceApi.setActive(def.list, v.id, !v.is_active, v.version);
      done(r.status, r.approval_request?.request_number);
    } catch (e) {
      setError(e);
    }
  };

  const extras = def.fields;
  return (
    <>
      <ValueForm key={`new-${def.list}`} def={def} onDone={done} />
      <div className="page-head">
        <form className="inline" onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(search); }}>
          <label className="sr-only" htmlFor="ref-q">Search values</label>
          <input id="ref-q" placeholder="Code or name" value={search} onChange={(e) => setSearch(e.target.value)} />
          <button>Search</button>
        </form>
        <label>Status{' '}
          <select value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
            <option value="all">All</option><option value="active">Active</option><option value="inactive">Inactive</option>
          </select>
        </label>
      </div>
      <ErrorNote error={values.error ?? error} />
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr><th>Code</th><th>Name</th>{extras.map((f) => <th key={f.name}>{f.label}</th>)}<th>Order</th><th>Status</th><th /></tr>
          </thead>
          <tbody>
            {values.data?.items.map((v) => (
              <tr key={v.id} className={v.is_active ? undefined : 'inactive'}>
                <td><code>{v.code}</code></td>
                <td>{v.name}{v.name_hi && <div className="muted small">{v.name_hi}</div>}</td>
                {extras.map((f) => <td key={f.name}>{String(v[f.name] ?? '—')}</td>)}
                <td>{v.sort_order}</td>
                <td>
                  <span className={`pill pill-${v.is_active ? 'active' : 'disabled'}`}>{v.is_active ? 'Active' : 'Inactive'}</span>
                  {v.pending_request && (
                    <span className="pill pill-pending" title={v.pending_request.summary ?? ''}>
                      Pending approval · {v.pending_request.request_number}
                    </span>
                  )}
                </td>
                <td className="nowrap">
                  {!v.pending_request && <>
                    <button className="link" onClick={() => setEditing(v)}>Edit</button>
                    <button className="link" onClick={() => toggle(v)}>{v.is_active ? 'Deactivate' : 'Activate'}</button>
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {values.data && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page} · {values.data.total} values</span>
          <button disabled={page * values.data.size >= values.data.total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
      {editing && <ValueForm key={editing.id} def={def} value={editing} onDone={done} onCancel={() => setEditing(null)} />}
    </>
  );
}

/** Label, control and an error message linked to the control (the error never becomes part of the label). */
function Field({ label, error, children }: {
  label: string; error?: string; children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id, error ? `${id}-error` : undefined)}
      {error && <span id={`${id}-error`} className="field-error">{error}</span>}
    </div>
  );
}

function ParentSelect({ id, describedBy, field, value, onChange }: {
  id: string; describedBy?: string; field: FieldDef; value: string; onChange: (v: string) => void;
}) {
  const options = useLoad(() => referenceApi.publicList(field.parent_list ?? ''), [field.parent_list]);
  return (
    <select id={id} aria-describedby={describedBy} aria-invalid={Boolean(describedBy)} value={value}
            required={field.required} onChange={(e) => onChange(e.target.value)}>
      <option value="">{field.required ? `Choose ${field.label.toLowerCase()}` : 'None'}</option>
      {options.data?.items.map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
    </select>
  );
}

function ValueForm({ def, value, onDone, onCancel }: {
  def: ListDef; value?: AdminValue; onDone: (status: string, requestNumber?: string | null) => void; onCancel?: () => void;
}) {
  const editing = value !== undefined;
  const initial: Record<string, string> = {
    code: value?.code ?? '', name: value?.name ?? '', name_hi: value?.name_hi ?? '',
    sort_order: String(value?.sort_order ?? 0),
    ...Object.fromEntries(def.fields.map((f) => [f.name, value?.[f.name] == null ? '' : String(value[f.name])])),
  };
  const [form, setForm] = useState(initial);
  const [error, setError] = useState<unknown>(null);
  const set = (name: string) => (v: string) => setForm((f) => ({ ...f, [name]: v }));
  const fieldError = (name: string) => (error instanceof ApiError ? error.forField(name) : undefined);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = { name: form.name, name_hi: form.name_hi || null, sort_order: Number(form.sort_order) };
    for (const f of def.fields) {
      if (editing && f.immutable) continue;
      const raw = form[f.name];
      body[f.name] = raw === '' ? null : f.kind === 'int' ? Number(raw) : raw;
    }
    try {
      const r = editing
        ? await referenceApi.update(def.list, value.id, body, value.version)
        : await referenceApi.create(def.list, { ...body, code: form.code });
      onDone(r.status, r.approval_request?.request_number);
      if (!editing) setForm(initial);
    } catch (err) {
      setError(err);
    }
  };

  const input = (name: string, label: string, props: Record<string, unknown> = {}) => (
    <Field key={name} label={label} error={fieldError(name)}>
      {(id, describedBy) => (
        <input id={id} value={form[name]} onChange={(e) => set(name)(e.target.value)}
               aria-invalid={Boolean(fieldError(name))} aria-describedby={describedBy} {...props} />
      )}
    </Field>
  );

  const body = (
    <form onSubmit={submit} className="form grid2" aria-label={editing ? `Edit ${value.code}` : `Add to ${def.label}`}>
      {editing ? <p className="muted">Code <code>{value.code}</code> (never changes)</p>
        : input('code', 'Code', { required: true, maxLength: 50, placeholder: 'CAPITALS_AND_DIGITS' })}
      {input('name', 'Name', { required: true, maxLength: 150 })}
      {input('name_hi', 'Hindi name', { maxLength: 150 })}
      {def.fields.map((f) => f.kind === 'parent' ? (
        <Field key={f.name} label={f.label} error={fieldError(f.name)}>
          {(id, describedBy) => <ParentSelect id={id} describedBy={describedBy} field={f} value={form[f.name]} onChange={set(f.name)} />}
        </Field>
      ) : editing && f.immutable ? (
        <p key={f.name} className="muted">{f.label}: <code>{form[f.name]}</code></p>
      ) : input(f.name, f.label, f.kind === 'int' ? { type: 'number', min: 0, required: f.required } : { required: f.required }))}
      {input('sort_order', 'Sort order', { type: 'number', min: 0 })}
      <div className="actions">
        <button className="primary">{editing ? 'Save changes' : 'Add value'}</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancel</button>}
      </div>
      <ErrorNote error={error} />
    </form>
  );

  return editing ? <aside className="card" aria-label="Edit value"><h2>Edit {value.name}</h2>{body}</aside>
    : <details className="card"><summary>Add a value</summary>{body}</details>;
}
