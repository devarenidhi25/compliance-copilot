import { NavLink, Outlet } from 'react-router-dom';
import { LibraryProvider, SourceProvider, useSource } from '../context';
import { ROLE_LABELS, useSession, useSignedIn } from '../session';
import { SourcePane } from './SourceViewer';

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/ask', label: 'Ask' },
  { to: '/library', label: 'Library' },
  { to: '/changes', label: 'Change detection' },
  { to: '/gaps', label: 'Gap analysis' },
  { to: '/audit', label: 'Audit trail' },
];

function Workspace() {
  const { target } = useSource();
  return (
    <div className={`workspace${target ? ' with-source' : ''}`}>
      <main className="main" id="main">
        <div className="main-inner">
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
            <div className="brand">
              <strong>Compliance Copilot</strong>
              <span>{session.organization}</span>
            </div>
            <nav aria-label="Main">
              {NAV.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>
              ))}
            </nav>
            <div className="who">
              <span>
                <strong>{session.name}</strong>, {ROLE_LABELS[session.role]}{session.isAdmin ? ' (administrator)' : ''}
              </span>
              <button className="button small" onClick={signOut}>Sign out</button>
            </div>
          </header>
          <Workspace />
        </div>
      </SourceProvider>
    </LibraryProvider>
  );
}
