import { type FormEvent, useState } from 'react';

import { ErrorNote, Notice } from '../../shared/ui';
import { identityApi } from '../identity/api';
import { useAuth } from './AuthContext';

type Mode = 'password' | 'otp';

export function LoginPage() {
  const { signedIn } = useAuth();
  const [mode, setMode] = useState<Mode>('password');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mobile, setMobile] = useState('');
  const [code, setCode] = useState('');
  const [challenge, setChallenge] = useState<{ id: string; sentTo: string } | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await action(); } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const passwordLogin = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => signedIn(await identityApi.login(email, password)));
  };
  const sendCode = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await identityApi.requestOtp(mobile);
      setChallenge({ id: r.challenge_id, sentTo: r.sent_to });
    });
  };
  const verifyCode = (e: FormEvent) => {
    e.preventDefault();
    if (challenge) void run(async () => signedIn(await identityApi.verifyOtp(challenge.id, mobile, code)));
  };

  return (
    <section className="card narrow" aria-labelledby="login-title">
      <h1 id="login-title">Sign in</h1>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={mode === 'password'} onClick={() => { setMode('password'); setError(null); }}>
          Email &amp; password
        </button>
        <button role="tab" aria-selected={mode === 'otp'} onClick={() => { setMode('otp'); setError(null); }}>
          Mobile OTP
        </button>
      </div>

      {mode === 'password' ? (
        <form onSubmit={passwordLogin} className="form">
          <label>Email<input type="email" autoComplete="username" required value={email}
                             onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" required value={password}
                                onChange={(e) => setPassword(e.target.value)} /></label>
          <button className="primary" disabled={busy}>Sign in</button>
        </form>
      ) : challenge === null ? (
        <form onSubmit={sendCode} className="form">
          <label>Mobile number<input inputMode="tel" autoComplete="tel" required placeholder="10-digit mobile"
                                     value={mobile} onChange={(e) => setMobile(e.target.value)} /></label>
          <button className="primary" disabled={busy}>Send code</button>
        </form>
      ) : (
        <form onSubmit={verifyCode} className="form">
          <Notice>Code sent to {challenge.sentTo}.</Notice>
          <label>One-time code<input inputMode="numeric" autoComplete="one-time-code" required maxLength={8}
                                     value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} /></label>
          <button className="primary" disabled={busy}>Verify</button>
          <button type="button" className="link" onClick={() => { setChallenge(null); setCode(''); }}>
            Use a different number
          </button>
        </form>
      )}
      <ErrorNote error={error} />
    </section>
  );
}
