import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLibrary, useSource } from '../context';
import { useJob } from '../hooks';
import { api, type Change, type Comparison } from '../lib/api';
import { formatDate, versionName } from '../lib/library';
import { AnswerView, JobOutcome } from '../components/Results';
import { Empty, ErrorNote, PageHead } from '../components/ui';

const KIND = { added: { label: 'Added', tone: 'good' }, removed: { label: 'Removed', tone: 'bad' }, modified: { label: 'Modified', tone: 'warn' } };

function pages([from, to]: [number, number]) {
  return from === to ? `page ${from}` : `pages ${from}–${to}`;
}

function ChangeBlock({ change, result }: { change: Change; result: Comparison }) {
  const { open } = useSource();
  const kind = KIND[change.change];
  return (
    <article className="change">
      <div className="change-head">
        <span className={`badge ${kind.tone}`}>{kind.label}</span>
        <div className="row small-text" style={{ gap: 4 }}>
          {change.change !== 'added' && (
            <button className="button quiet small" onClick={() => open({ documentId: result.older.id, page: change.old_pages[0], quote: change.removed[0] })}>
              Earlier version, {pages(change.old_pages)}
            </button>
          )}
          {change.change !== 'removed' && (
            <button className="button quiet small" onClick={() => open({ documentId: result.newer.id, page: change.new_pages[0], quote: change.added[0] })}>
              Later version, {pages(change.new_pages)}
            </button>
          )}
        </div>
      </div>
      <div className="change-lines">
        {change.removed.map((line, i) => <div key={`r${i}`} className="line removed">{line}</div>)}
        {change.added.map((line, i) => <div key={`a${i}`} className="line added">{line}</div>)}
        {change.truncated && <div className="line muted small-text">Long change shortened; open the page to read all of it.</div>}
      </div>
    </article>
  );
}

export function Changes() {
  const { families, byId } = useLibrary();
  const [params] = useSearchParams();
  const candidates = families.filter((f) => f.kind === 'regulatory' && f.versions.length > 1);
  const [familyId, setFamilyId] = useState('');
  const [olderId, setOlderId] = useState('');
  const [newerId, setNewerId] = useState('');
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const explain = useJob('changes');
  const family = candidates.find((f) => f.id === familyId);

  useEffect(() => {
    const wanted = params.get('family');
    if (!familyId && candidates.length) setFamilyId(candidates.some((f) => f.id === wanted) ? wanted! : candidates[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates.length]);

  useEffect(() => {
    if (!family) return;
    setNewerId(family.versions[0].id);
    setOlderId(family.versions[1].id);
    setResult(null);
  }, [familyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const compare = async () => {
    setLoading(true);
    setError('');
    try {
      setResult(await api.compare(olderId, newerId));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  };

  const explainChanges = async () => {
    if (!result) return;
    try {
      explain.start(await api.startJob('comparison',
        'Summarise what changed between these two versions and what a compliance team must do differently as a result.',
        [result.older.id, result.newer.id]));
    } catch (exc) {
      explain.setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  if (!candidates.length) {
    return (
      <>
        <PageHead title="Change detection" />
        <section className="panel">
          <Empty title="No document has two versions yet">
            Upload a newer version of a regulation in the Library and choose “new version of an existing document”. Then compare the two here.
          </Empty>
        </section>
      </>
    );
  }

  // Explaining needs both versions indexed; comparing the text does not.
  const both = !!result && !!byId.get(result.older.id)?.indexed && !!byId.get(result.newer.id)?.indexed;
  return (
    <>
      <PageHead title="Change detection" intro="Line up two versions of a regulation and review every passage that was added, removed or modified, page by page." />
      <section className="panel stack">
        <label className="field">
          <span>Document</span>
          <select className="select" value={familyId} onChange={(e) => setFamilyId(e.target.value)}>
            {candidates.map((f) => <option key={f.id} value={f.id}>{f.latest.metadata.title.value} ({f.versions.length} versions)</option>)}
          </select>
        </label>
        {family && (
          <div className="grid-2">
            {([['Earlier version', olderId, setOlderId], ['Later version', newerId, setNewerId]] as const).map(([label, value, setValue]) => (
              <label className="field" key={label}>
                <span>{label}</span>
                <select className="select" value={value} onChange={(e) => setValue(e.target.value)}>
                  {family.versions.map((v) => <option key={v.id} value={v.id}>{versionName(v)}{v.metadata.effective_date?.value ? `, effective ${formatDate(v.metadata.effective_date.value)}` : ''}</option>)}
                </select>
              </label>
            ))}
          </div>
        )}
        {error && <ErrorNote>{error}</ErrorNote>}
        <div><button className="button primary" onClick={compare} disabled={loading || !olderId || olderId === newerId}>{loading ? 'Comparing…' : 'Compare versions'}</button></div>
      </section>

      {result && (
        <section style={{ marginTop: 16 }}>
          <div className="section-title">
            <div>
              <h2>
                {result.total_changes === 0 ? 'No differences in the text' : `${result.total_changes} change${result.total_changes > 1 ? 's' : ''}`}
              </h2>
              <p className="muted small-text">
                {result.counts.added} added, {result.counts.removed} removed, {result.counts.modified} modified.
                From {versionName(result.older)} to {versionName(result.newer)}.
                {result.reordered && ' The versions were put in date order.'}
              </p>
            </div>
            {result.total_changes > 0 && (both
              ? <button className="button" onClick={explainChanges} disabled={explain.busy}>Explain these changes</button>
              : <span className="small-text muted">Index both versions to have the changes explained.</span>)}
          </div>
          {explain.error && <ErrorNote>{explain.error}</ErrorNote>}
          <div style={{ marginBottom: 16 }}>
            <JobOutcome job={explain.job} onDismiss={explain.forget}>
              {(answer) => <AnswerView result={answer} heading="What changed and what it means" />}
            </JobOutcome>
          </div>
          {result.changes.map((change, i) => <ChangeBlock key={i} change={change} result={result} />)}
          {result.total_changes > result.changes.length && (
            <p className="muted small-text" style={{ marginTop: 10 }}>Showing the first {result.changes.length} of {result.total_changes} changes.</p>
          )}
        </section>
      )}
    </>
  );
}
