import { useEffect, useState, type FormEvent } from 'react';
import { useLibrary } from '../context';
import { useJob } from '../hooks';
import { api, type AIResult, type ResultItem } from '../lib/api';
import { versionName } from '../lib/library';
import { Details, JobOutcome, KeyQuote, usePlace } from '../components/Results';
import { Empty, ErrorNote } from '../components/ui';

const KIND_LABEL: Record<string, string> = {
  POTENTIAL_GAP: 'Gap',
  POSSIBLE_CONFLICT: 'Conflict',
  PARTIALLY_ADDRESSED: 'Partial',
  APPEARS_ADDRESSED: 'Addressed',
  INSUFFICIENT_EVIDENCE: 'Needs review',
};

function Side({ item, kind, heading, label }: { item: ResultItem; kind: 'regulatory' | 'internal'; heading: string; label: number }) {
  const { byId } = useLibrary();
  const place = usePlace();
  const citations = item.citations.filter((c) => byId.get(c.document_id)?.kind === kind);
  return (
    <div>
      <span className="label">{heading}{citations[0] ? ` · ${place.short(citations[0])}` : ''}</span>
      {citations.length === 0 && <p className="small-text muted">Not located in the excerpts that were checked.</p>}
      {citations.map((c) => <KeyQuote key={c.chunk_id + c.quote} citation={c} label={label} />)}
    </div>
  );
}

function Pair({ item, label }: { item: ResultItem; label: number }) {
  return (
    <div className="pair">
      <Side item={item} kind="regulatory" heading="The regulation requires" label={label} />
      <Side item={item} kind="internal" heading="Your policy says" label={label} />
    </div>
  );
}

function AlsoRow({ item, label }: { item: ResultItem; label: number }) {
  const [open, setOpen] = useState(false);
  const badge = item.risk === 'low'
    ? <span className="badge ok">✓ Addressed</span>
    : item.risk === 'review'
      ? <span className="badge dashed">Needs review</span>
      : <span className="badge">{KIND_LABEL[item.assessment ?? ''] ?? 'Finding'} · {item.risk}</span>;
  return (
    <li className="also">
      <span>{badge}</span>
      <span style={{ fontSize: 16 }}>{item.statement}</span>
      <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Hide quotes' : 'Show quotes'}</button>
      {open && <Pair item={item} label={label} />}
    </li>
  );
}

export function GapResult({ result }: { result: AIResult }) {
  const summary = result.gap_summary!;
  const numbered = result.items.map((item, i) => ({ item, n: i + 1 }));
  const fixFirst = numbered.filter(({ item }) => item.risk === 'high');
  const order: Record<string, number> = { medium: 0, review: 1, low: 2 };
  const also = numbered.filter(({ item }) => item.risk !== 'high').sort((a, b) => (order[a.item.risk ?? 'review'] ?? 1) - (order[b.item.risk ?? 'review'] ?? 1));
  const c = summary.counts;
  const assessed = Math.max(summary.assessed_items, 1);
  const addressed = c.APPEARS_ADDRESSED ?? 0;
  const partial = c.PARTIALLY_ADDRESSED ?? 0;
  const gaps = summary.high_risk_items;

  return (
    <div className="stack" style={{ gap: 40 }}>
      <section className="verdict" aria-label="Verdict">
        <h1>
          {gaps > 0
            ? <><mark>{gaps} gap{gaps > 1 ? 's' : ''} to fix</mark> before this policy matches the regulation.</>
            : summary.assessed_items > 0
              ? <>No high-risk gaps in the parts that were checked.</>
              : <>The excerpts were not conclusive enough to assess this policy.</>}
        </h1>
        <div className="score">
          <div className="figure">
            <strong>{summary.score == null ? '—' : `${summary.score}%`}</strong>
            <span className="muted small-text">of assessed requirements addressed</span>
          </div>
          <div className="scorebar" aria-hidden="true">
            <span style={{ width: `${(addressed / assessed) * 100}%`, background: 'var(--ink)' }} />
            <span style={{ width: `${(partial / assessed) * 100}%`, background: '#8c887d' }} />
          </div>
          <span className="label">{addressed} addressed · {partial} partial · {gaps} gap{gaps === 1 ? '' : 's'} · {summary.not_assessed_items} needs review</span>
        </div>
      </section>

      {fixFirst.length > 0 && (
        <section aria-labelledby="fix">
          <div className="section-head"><h2 id="fix">Fix first</h2></div>
          {fixFirst.map(({ item, n }) => (
            <article key={n} className="fix-card">
              <div className="fix-head">
                <span className="badge solid">High risk · {KIND_LABEL[item.assessment ?? ''] ?? 'Gap'}</span>
                <h3>{item.statement}</h3>
              </div>
              <Pair item={item} label={n} />
            </article>
          ))}
        </section>
      )}

      {also.length > 0 && (
        <section aria-labelledby="also">
          <div className="section-head"><h2 id="also" style={{ fontSize: 18 }}>{fixFirst.length ? 'Also found' : 'Findings'}</h2></div>
          <ul className="ruled">{also.map(({ item, n }) => <AlsoRow key={n} item={item} label={n} />)}</ul>
        </section>
      )}

      <Details result={result} extra={<p style={{ marginTop: 8 }}>{summary.method}</p>} />
    </div>
  );
}

export function Gaps() {
  const { families, byId } = useLibrary();
  const { job, error, busy, start, forget, setError } = useJob('gaps');
  const regulations = families.filter((f) => f.kind === 'regulatory').flatMap((f) => f.versions).filter((d) => d.indexed);
  const policies = families.filter((f) => f.kind === 'internal').flatMap((f) => f.versions).filter((d) => d.indexed);
  const [regulationId, setRegulationId] = useState('');
  const [policyId, setPolicyId] = useState('');
  const [focus, setFocus] = useState('');
  const [editing, setEditing] = useState(true);
  const regulation = regulationId || regulations[0]?.id || '';
  const policy = policyId || policies[0]?.id || '';

  useEffect(() => {
    if (!job) return;
    setEditing(false);
    const reg = job.document_ids.find((id) => byId.get(id)?.kind === 'regulatory');
    const pol = job.document_ids.find((id) => byId.get(id)?.kind === 'internal');
    if (reg) setRegulationId(reg);
    if (pol) setPolicyId(pol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, byId.size]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      start(await api.startJob('gap_analysis',
        focus.trim() || 'Assess whether the internal policy meets the requirements of the regulation, requirement by requirement.',
        [regulation, policy]));
      setEditing(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  if (!regulations.length || !policies.length) {
    return (
      <>
        <h1>Gap analysis</h1>
        <Empty title={!policies.length ? 'Upload one of your policies first' : 'Index a regulation first'}>
          A gap check compares an indexed internal policy with an indexed regulation. Add them in the Library.
        </Empty>
      </>
    );
  }

  const title = (id: string) => {
    const doc = byId.get(id);
    return doc ? `${doc.metadata.title.value} (${versionName(doc)})` : 'Document';
  };

  return (
    <>
      {editing || !job ? (
        <form className="stack" style={{ gap: 16 }} onSubmit={submit}>
          <div className="page-head">
            <div>
              <h1>Gap analysis</h1>
              <p>Check one of your policies against a regulation. You'll see what to fix first, with both documents' words side by side.</p>
            </div>
          </div>
          <div className="grid-2">
            <label className="field">
              <span>Regulation</span>
              <select className="select" value={regulation} onChange={(e) => setRegulationId(e.target.value)}>
                {regulations.map((d) => <option key={d.id} value={d.id}>{title(d.id)}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Your policy</span>
              <select className="select" value={policy} onChange={(e) => setPolicyId(e.target.value)}>
                {policies.map((d) => <option key={d.id} value={d.id}>{title(d.id)}</option>)}
              </select>
            </label>
          </div>
          <div className="askbar">
            <label htmlFor="gap-focus" className="visually-hidden">Focus of the check (optional)</label>
            <input id="gap-focus" value={focus} onChange={(e) => setFocus(e.target.value)} maxLength={4000}
              placeholder="Focus, optional: for example, timelines for disclosing material events" />
            <button className="button primary" type="submit" disabled={busy}>Run gap check</button>
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      ) : (
        <p className="row" style={{ fontSize: 15, color: 'var(--text)' }}>
          <span><strong style={{ color: 'var(--ink)', fontWeight: 500 }}>{title(policy)}</strong> checked against <strong style={{ color: 'var(--ink)', fontWeight: 500 }}>{title(regulation)}</strong></span>
          <button className="link" onClick={() => setEditing(true)} disabled={busy}>Change</button>
        </p>
      )}
      <JobOutcome job={job} onDismiss={() => { forget(); setEditing(true); }}>{(result) => <GapResult result={result} />}</JobOutcome>
    </>
  );
}
