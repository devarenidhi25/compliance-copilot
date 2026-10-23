import { Link, NavLink, Outlet } from 'react-router-dom';
import { LibraryProvider, SourceProvider, useSource } from '../context';
import { ROLE_LABELS, useSession, useSignedIn } from '../session';
import { SourcePane } from './SourceViewer';

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/ask', label: 'Ask' },
  { to: '/changes', label: 'Changes' },
  { to: '/gaps', label: 'Gaps' },
  { to: '/library', label: 'Library' },
  { to: '/audit', label: 'Audit' },
];

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]!.toUpperCase()).join('') || '?';
}

function Workspace() {
  const { target } = useSource();
  return (
    <div className={`workspace${target ? ' with-source' : ''}`}>
      <main className="main" id="main">
        <div className="page">
          <Outlet />
        </div>
      </main>
      <SourcePane />
    </div>
  );
}

export function Shell() {
  const session = useSignedIn();
  const { signOut } = useSession();
  return (
    <LibraryProvider>
      <SourceProvider>
        <div className="shell">
          <header className="topbar">
            <div className="topbar-inner">
              <Link to="/" className="brand"><span className="logo" aria-hidden="true" />Compliance Copilot</Link>
              <nav aria-label="Main">
                {NAV.map((item) => <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>)}
              </nav>
              <div className="who">
                <span className="avatar" aria-hidden="true">{initials(session.name)}</span>
                <span className="name" title={`${ROLE_LABELS[session.role]}${session.isAdmin ? ', administrator' : ''}, ${session.organization}`}>{session.name}</span>
                <button className="link quiet" onClick={signOut}>Sign out</button>
              </div>
            </div>
          </header>
          <Workspace />
        </div>
      </SourceProvider>
    </LibraryProvider>
  );
}
