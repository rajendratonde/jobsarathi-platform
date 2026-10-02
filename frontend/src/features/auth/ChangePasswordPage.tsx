import { type FormEvent, useState } from 'react';

import { ErrorNote } from '../../shared/ui';
import { identityApi } from '../identity/api';
import { useAuth } from './AuthContext';

export function ChangePasswordPage() {
  const { session, signedIn, signOut } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [mismatch, setMismatch] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setMismatch(next !== confirm);
    if (next !== confirm) return;
    try {
      await signedIn(await identityApi.changePassword(current, next));
    } catch (err) {
      setError(err);
    }
  };

  return (
    <section className="card narrow" aria-labelledby="pw-title">
      <h1 id="pw-title">Choose a new password</h1>
      {session?.passwordChangeRequired && (
        <p className="muted">You signed in with a temporary password. Choose your own to continue.</p>
      )}
      <form onSubmit={submit} className="form">
        <label>Current password<input type="password" autoComplete="current-password" required value={current}
                                      onChange={(e) => setCurrent(e.target.value)} /></label>
        <label>New password<input type="password" autoComplete="new-password" required minLength={10} value={next}
                                  onChange={(e) => setNext(e.target.value)} /></label>
        <label>Repeat new password<input type="password" autoComplete="new-password" required value={confirm}
                                         onChange={(e) => setConfirm(e.target.value)} /></label>
        <p className="hint">At least 10 characters, with letters and numbers.</p>
        {mismatch && <p className="error" role="alert">The two new passwords are different.</p>}
        <button className="primary">Save password</button>
        <button type="button" className="link" onClick={() => void signOut()}>Sign out</button>
      </form>
      <ErrorNote error={error} />
    </section>
  );
}
