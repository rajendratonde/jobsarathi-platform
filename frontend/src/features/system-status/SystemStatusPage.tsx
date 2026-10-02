import { useCallback, useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { ApiError } from '../../api/errors';
import { SERVICES } from '../../config/env';

// Foundation page: shows whether each service and its database are ready.
// It uses only the public health endpoints; no business data.

interface ReadyBody {
  status: string;
  service: string;
  version: string;
  checks: { database?: { status: string }; migrations?: { status: string; current: string | null } };
}

type Row = { state: 'loading' } | { state: 'ok' | 'unavailable'; body: ReadyBody } | { state: 'error'; message: string };

export function SystemStatusPage() {
  const [rows, setRows] = useState<Record<string, Row>>({});

  const load = useCallback(async (signal?: AbortSignal) => {
    setRows(Object.fromEntries(SERVICES.map((s) => [s.key, { state: 'loading' } as Row])));
    await Promise.all(
      SERVICES.map(async (service) => {
        let row: Row;
        try {
          const body = await apiRequest<ReadyBody>(service.key, '/health/ready', { signal });
          row = { state: 'ok', body };
        } catch (error) {
          if (error instanceof DOMException && error.name === 'AbortError') return;
          row =
            error instanceof ApiError && error.status === 503
              ? { state: 'unavailable', body: { status: 'unavailable', service: service.key, version: '', checks: {} } }
              : { state: 'error', message: error instanceof ApiError ? error.message : 'Unexpected error' };
        }
        setRows((current) => ({ ...current, [service.key]: row }));
      }),
    );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <section className="page">
      <div className="page-head">
        <div>
          <h1>System status</h1>
          <p className="muted">Readiness of the eight JobSarathi services and their databases.</p>
        </div>
        <button type="button" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Service</th>
            <th scope="col">Status</th>
            <th scope="col">Database</th>
            <th scope="col">Schema</th>
          </tr>
        </thead>
        <tbody>
          {SERVICES.map((service) => {
            const row = rows[service.key] ?? { state: 'loading' };
            return (
              <tr key={service.key}>
                <td>{service.name}</td>
                <td>
                  <span className={`pill pill-${row.state}`}>
                    {row.state === 'loading' ? 'Checking…' : row.state === 'ok' ? 'Ready' : row.state === 'unavailable' ? 'Not ready' : 'Unreachable'}
                  </span>
                </td>
                <td>{'body' in row ? row.body.checks.database?.status ?? '—' : '—'}</td>
                <td>{'body' in row ? row.body.checks.migrations?.current ?? '—' : row.state === 'error' ? row.message : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
