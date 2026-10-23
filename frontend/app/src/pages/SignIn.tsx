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
      <div className="signin-inner">
        <section className="signin-intro">
          <h1>Compliance Copilot</h1>
          <p className="lede">
            Answers from RBI and SEBI regulation. Every statement carries the exact words it rests on,
            checked against the source page before you see it.
          </p>
          <figure className="sample" style={{ margin: 0 }} aria-label="Example of a verified statement">
            <div className="row" style={{ gap: 12, alignItems: 'flex-start', flexWrap: 'nowrap' }}>
              <span className="num" aria-hidden="true">1</span>
              <div style={{ display: 'grid', gap: 8 }}>
                <p className="statement">A board decision on a material event must reach the stock exchanges within 30 minutes of the meeting closing.</p>
                <p className="quote"><span className="hl">thirty minutes from the closure of the meeting of the board of directors</span></p>
                <figcaption className="meta">SEBI LODR Master Circular, Annexure 18A, page 236</figcaption>
              </div>
            </div>
          </figure>
        </section>

        <form className="signin-form" onSubmit={submit}>
          <div>
            <h2>Sign in</h2>
            <p className="muted small-text" style={{ marginTop: 4 }}>Use the access code your administrator gave you.</p>
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
      </div>
    </div>
  );
}
