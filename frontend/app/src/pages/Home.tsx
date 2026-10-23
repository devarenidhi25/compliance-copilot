import { Link } from 'react-router-dom';
import { useLibrary } from '../context';
import { useLoad } from '../hooks';
import { api, type Role } from '../lib/api';
import { formatDateTime } from '../lib/library';
import { ROLE_LABELS, useSignedIn } from '../session';
import { Empty } from '../components/ui';

const TASKS = {
  ask: { to: '/ask', title: 'Ask about a regulation', text: 'Get an answer in plain language with the exact clauses it rests on.', go: 'Ask a question' },
  gaps: { to: '/gaps', title: 'Check a policy for gaps', text: 'Compare one of your policies against a regulation and see what needs attention.', go: 'Start a gap check' },
  changes: { to: '/changes', title: 'See what changed', text: 'Line up two versions of a circular and review every added, removed or modified passage.', go: 'Compare versions' },
  library: { to: '/library', title: 'Manage the library', text: 'Upload regulations and internal policies, and keep version history in one place.', go: 'Open the library' },
};

// Each role sees its most likely work first.
const ORDER: Record<Role, (keyof typeof TASKS)[]> = {
  compliance_officer: ['ask', 'gaps', 'changes', 'library'],
  legal: ['changes', 'ask', 'gaps', 'library'],
  risk: ['gaps', 'changes', 'ask', 'library'],
  executive: ['ask', 'changes', 'gaps', 'library'],
};

const TASK_NAMES: Record<string, string> = { qa: 'Question', checklist: 'Checklist', comparison: 'Change explanation', gap_analysis: 'Gap check' };

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
}

export function Home() {
  const session = useSignedIn();
  const { library, families } = useLibrary();
  const recent = useLoad(() => api.audit(6));
  const documents = library?.documents ?? [];
  const regulations = families.filter((f) => f.kind === 'regulatory').length;
  const policies = families.filter((f) => f.kind === 'internal').length;
  const waiting = documents.filter((d) => !d.indexed).length;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>{greeting()}, {session.name.split(' ')[0]}</h1>
          <p>Signed in as {ROLE_LABELS[session.role]} for {session.organization}.</p>
        </div>
      </header>
      <div className="home">
        <section className="panel">
          <h2 style={{ marginBottom: 4 }}>What would you like to do?</h2>
          <ul className="task-list">
            {ORDER[session.role].map((key) => {
              const task = TASKS[key];
              return (
                <li key={key}>
                  <Link to={task.to}>
                    <strong>{task.title}</strong>
                    <span>{task.text}</span>
                    <em className="go" style={{ fontStyle: 'normal' }}>{task.go}</em>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
        <div className="stack">
          <section className="panel">
            <div className="section-title"><h2>Library</h2><Link to="/library" className="small-text">View all</Link></div>
            <div className="facts">
              <div><strong>{regulations}</strong><span>regulations</span></div>
              <div><strong>{policies}</strong><span>internal policies</span></div>
              <div><strong>{documents.length}</strong><span>stored versions</span></div>
              <div><strong>{waiting}</strong><span>waiting to be indexed</span></div>
            </div>
            {waiting > 0 && (
              <p className="small-text muted" style={{ marginTop: 12 }}>
                {session.isAdmin ? 'Index them from the Library so they can be used for answers.' : 'An administrator needs to index them before they can be used for answers.'}
              </p>
            )}
          </section>
          <section className="panel">
            <div className="section-title"><h2>Recent activity</h2><Link to="/audit" className="small-text">Audit trail</Link></div>
            {recent.data && recent.data.entries.length === 0 && <Empty title="Nothing yet">Questions and checks your team runs will appear here.</Empty>}
            <ul className="activity">
              {recent.data?.entries.map((entry) => (
                <li key={entry.id}>
                  <div className="small-text muted">{TASK_NAMES[entry.task]} by {entry.user_name ?? 'unknown'}, {formatDateTime(entry.created_at)}</div>
                  <div style={{ color: 'var(--ink)' }}>{entry.question}</div>
                  {entry.status === 'failed' && <span className="badge bad" style={{ marginTop: 4 }}>Did not complete</span>}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </>
  );
}
