import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useLibrary } from '../context';
import { rememberJob, useLoad } from '../hooks';
import { api, type AuditEntry } from '../lib/api';
import { markPhrases } from '../lib/quote';
import { formatDateTime, versionName } from '../lib/library';
import { useSignedIn } from '../session';
import { ErrorNote } from '../components/ui';
import { defaultRegulations } from './Ask';

const EXAMPLES = [
  'When must a material event be disclosed to the stock exchanges?',
  'Who must verify market rumours?',
  'What must happen when a statutory auditor resigns?',
];

/** The latest finished entries of each kind, with full results for the two the page shows. */
async function loadRecent() {
  const { entries } = await api.audit(40);
  const done = entries.filter((e) => e.status === 'completed');
  const lastAnswer = done.find((e) => e.task === 'qa');
  const lastGap = done.find((e) => e.task === 'gap_analysis');
  const [answer, gap] = await Promise.all([
    lastAnswer ? api.auditEntry(lastAnswer.id) : null,
    lastGap ? api.auditEntry(lastGap.id) : null,
  ]);
  return { answer, gap };
}

function LastAnswer({ entry }: { entry: AuditEntry }) {
  const result = entry.result!;
  const text = result.focus?.answer ?? result.items[0]?.statement;
  if (!text) return null;
  return (
    <section aria-labelledby="last" className="stack" style={{ gap: 12 }}>
      <h2 id="last" className="label">Your last answer · {formatDateTime(entry.created_at)}</h2>
      <Link to={`/audit?open=${entry.id}`} className="last-answer">
        <span className="q">{entry.question}</span>
        <span className="a">{markPhrases(text, result.focus?.highlights ?? []).map((p, i) => (p.marked ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}</span>
        <span className="go">OPEN ANSWER</span>
      </Link>
    </section>
  );
}

export function Home() {
  const session = useSignedIn();
  const navigate = useNavigate();
  const { library, families } = useLibrary();
  const recent = useLoad(loadRecent);
  const [question, setQuestion] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const documents = library?.documents ?? [];
  const ready = documents.filter((d) => d.indexed);
  const waiting = documents.length - ready.length;
  const pages = ready.reduce((sum, d) => sum + d.page_count, 0);
  const comparable = families.find((f) => f.kind === 'regulatory' && f.versions.length > 1);
  const gapSummary = recent.data?.gap?.result?.gap_summary;
  const scope = defaultRegulations(families);

  const ask = async (text: string) => {
    if (!text.trim() || !scope.length) return;
    setBusy(true);
    setError('');
    try {
      const job = await api.startJob('qa', text.trim(), scope);
      rememberJob('ask', job.id);
      navigate('/ask');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setBusy(false);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void ask(question);
  };

  return (
    <>
      <section className="hero" aria-labelledby="hello">
        <h1 id="hello">What do you need to check, {session.name.split(' ')[0]}?</h1>
        <form className="askbar large" onSubmit={submit}>
          <label htmlFor="home-q" className="visually-hidden">Ask about a regulation</label>
          <input id="home-q" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about RBI or SEBI regulation…" maxLength={4000} />
          <button className="button primary" type="submit" disabled={busy || !question.trim() || !scope.length}>{busy ? 'Asking…' : 'Ask'}</button>
        </form>
        <div className="chips">
          <span className="label">Try</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="chip" disabled={busy || !scope.length} onClick={() => { setQuestion(example); void ask(example); }}>{example}</button>
          ))}
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <p className="status-line">
          <span className={`dot${scope.length ? '' : ' wait'}`} aria-hidden="true" />
          {scope.length
            ? `Searching ${scope.length} ready regulation${scope.length > 1 ? 's' : ''} · every answer is checked against its source page`
            : 'No regulation is ready yet. Upload one in the Library and index it.'}
        </p>
      </section>

      {recent.data?.answer?.result && <LastAnswer entry={recent.data.answer} />}

      <section aria-label="Tools" className="tiles">
        <Link to="/gaps" className="tile">
          <strong className="name">Gap analysis</strong>
          <span className="desc">Check a policy against a regulation and see what to fix first.</span>
          <span className="fact">
            {gapSummary
              ? <>Last check: <mark>{gapSummary.high_risk_items} high-risk gap{gapSummary.high_risk_items === 1 ? '' : 's'}</mark>{gapSummary.score != null ? `, ${gapSummary.score}% addressed` : ''}</>
              : 'No policy checked yet'}
          </span>
        </Link>
        <Link to="/changes" className="tile">
          <strong className="name">Change detection</strong>
          <span className="desc">See exactly what was added, removed or reworded between two versions.</span>
          <span className="fact">
            {comparable
              ? <>{comparable.latest.metadata.title.value}: <strong>{versionName(comparable.versions[1])} → {versionName(comparable.versions[0])}</strong></>
              : 'Upload a second version of a regulation to compare'}
          </span>
        </Link>
        <Link to="/library" className="tile">
          <strong className="name">Library</strong>
          <span className="desc">Circulars and your internal policies, with every version kept.</span>
          <span className="fact">
            <strong>{ready.length} document{ready.length === 1 ? '' : 's'} ready</strong> · {pages} pages
            {waiting > 0 && <> · {waiting} waiting to be indexed</>}
          </span>
        </Link>
      </section>
    </>
  );
}
