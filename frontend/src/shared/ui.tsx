import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../api/errors';

// Small shared pieces: an error line that shows the server's message and correlation
// ID, and a loader hook for "fetch on mount, reload on demand".

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  return (
    <p className="error" role="alert">
      {e ? e.message : 'Something went wrong. Please try again.'}
      {e?.fieldErrors.length ? <> — {e.fieldErrors.map((f) => f.message).join(' ')}</> : null}
      {e?.correlationId ? <span className="ref"> (ref {e.correlationId.slice(0, 8)})</span> : null}
    </p>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="notice" role="status">{children}</p>;
}

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(load, deps);
  // Only the latest request may update state: when deps change quickly (e.g. switching
  // lists), an earlier, slower response must not overwrite the newer one.
  const latest = useRef(0);
  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const result = await run();
      if (ticket !== latest.current) return;
      setData(result);
      setError(null);
    } catch (e) {
      if (ticket === latest.current) setError(e);
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [run]);
  useEffect(() => { void reload(); }, [reload]);
  return { data, error, loading, reload };
}

/** Text for a change that may have gone to a checker instead of applying at once. */
export function changeMessage(status: string, requestNumber?: string | null): string {
  if (status === 'PENDING_APPROVAL') return `Submitted for approval${requestNumber ? ` (${requestNumber})` : ''}. A different person must approve it.`;
  if (status === 'UNCHANGED') return 'Nothing changed.';
  return 'Saved.';
}
