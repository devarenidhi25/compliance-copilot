import { NavLink, Outlet } from 'react-router-dom';
import { LibraryProvider, SourceProvider, useSource } from '../context';
import { ROLE_LABELS, useSession, useSignedIn } from '../session';
import { SourcePane } from './SourceViewer';
import { Icon } from './ui';

const NAV = [
  { to: '/', label: 'Home', icon: Icon.home, end: true },
  { to: '/ask', label: 'Ask', icon: Icon.ask },
  { to: '/library', label: 'Library', icon: Icon.library },
  { to: '/changes', label: 'Change detection', icon: Icon.changes },
  { to: '/gaps', label: 'Gap analysis', icon: Icon.gaps },
  { to: '/audit', label: 'Audit trail', icon: Icon.audit },
];

function Workspace() {
  const { target } = useSource();
  return (
    <div className={`workspace${target ? ' with-source' : ''}`}>
      <main className="main" id="main">
        <Outlet />
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
          <aside className="sidebar">
            <div className="brand">
              <strong>Compliance Copilot</strong>
              <span>RBI and SEBI regulation</span>
            </div>
            <nav aria-label="Main">
              {NAV.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end}>
                  {item.icon}
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="who">
              <strong>{session.name}</strong>
              {ROLE_LABELS[session.role]}, {session.organization}
              {session.isAdmin && <div style={{ marginTop: 4, color: 'var(--amber)' }}>Administrator</div>}
              <button className="button small" onClick={signOut}>Sign out</button>
            </div>
          </aside>
          <Workspace />
        </div>
      </SourceProvider>
    </LibraryProvider>
  );
}
