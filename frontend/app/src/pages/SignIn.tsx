import { useState, type FormEvent } from 'react';
import { api, type Role } from '../lib/api';
import { ROLE_LABELS, useSession } from '../session';
import { ErrorNote } from '../components/ui';

const ROLE_HINTS: Record<Role, string> = {
  compliance_officer: 'Ask questions, check policies, follow changes',
  legal: 'Read regulatory text and compare versions',
  risk: 'Find gaps and high-risk areas',
  executive: 'Short answers and the overall picture',
};

export function SignIn() {
  const { signIn } = useSession();
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('compliance_officer');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const me = await api.me(code.trim());
      signIn({ token: code.trim(), name: name.trim(), role, organization: me.organization, isAdmin: me.is_admin });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="signin">
      <section className="signin-brand">
        <div>
          <h1>Compliance Copilot</h1>
          <p className="lede">Answers from RBI and SEBI regulation, with every quotation checked against the source before you see it.</p>
        </div>
        <p className="proof">
          Ask about a circular, see what changed between versions, and check your policies for gaps.
          Each finding links to the <mark>exact words on the exact page</mark> it came from.
        </p>
      </section>
      <section className="signin-form">
        <form onSubmit={submit}>
          <div>
            <h2>Sign in</h2>
            <p className="muted" style={{ marginTop: 4 }}>Use the access code your administrator gave you.</p>
          </div>
          <label className="field">
            <span>Your name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} autoComplete="name" />
            <small>Shown on your answers in the audit trail.</small>
          </label>
          <fieldset className="role-options">
            <legend>Your role</legend>
            {(Object.keys(ROLE_LABELS) as Role[]).map((value) => (
              <label key={value} className="role-option">
                <input type="radio" name="role" value={value} checked={role === value} onChange={() => setRole(value)} />
                <strong>{ROLE_LABELS[value]}</strong>
                <span>{ROLE_HINTS[value]}</span>
              </label>
            ))}
          </fieldset>
          <label className="field">
            <span>Access code</span>
            <input className="input" type="password" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="current-password" />
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <button className="button primary" type="submit" disabled={busy || !name.trim() || !code.trim()}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </div>
  );
}
