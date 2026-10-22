import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { setApiSession, type Role, type Session } from './lib/api';

// The session lives in sessionStorage: it survives reloads but not closing the
// browser, and the access code is never written to long-lived storage.
const KEY = 'compliance-copilot-session';

export const ROLE_LABELS: Record<Role, string> = {
  compliance_officer: 'Compliance Officer',
  legal: 'Legal',
  risk: 'Risk',
  executive: 'Executive',
};

interface SessionContextValue {
  session: Session | null;
  signIn: (session: Session) => void;
  signOut: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

function stored(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const initial = stored();
    setApiSession(initial);
    return initial;
  });

  useEffect(() => setApiSession(session), [session]);

  const signIn = (next: Session) => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* private mode: the session still works until the page is closed */
    }
    setApiSession(next);
    setSession(next);
  };

  const signOut = () => {
    try {
      sessionStorage.clear();
    } catch {
      /* nothing stored */
    }
    setApiSession(null);
    setSession(null);
  };

  return <SessionContext.Provider value={{ session, signIn, signOut }}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside SessionProvider');
  return value;
}

export function useSignedIn(): Session {
  const { session } = useSession();
  if (!session) throw new Error('Signed-in page rendered without a session');
  return session;
}
