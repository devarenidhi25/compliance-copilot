import { useState, type FormEvent } from 'react';
import { useLibrary } from '../context';
import { useJob } from '../hooks';
import { api, type AIResult, type ResultItem } from '../lib/api';
import { versionName } from '../lib/library';
import { JobOutcome, Quote, ResultFooter, useWhere } from '../components/Results';
import { Empty, ErrorNote, PageHead, RiskBadge } from '../components/ui';

type Filter = 'all' | 'high' | 'medium' | 'low' | 'review';
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All findings' },
  { key: 'high', label: 'High risk' },
  { key: 'medium', label: 'Partial' },
  { key: 'low', label: 'Addressed' },
  { key: 'review', label: 'Needs review' },
];

function Evidence({ item, n, kindOf }: { item: ResultItem; n: number; kindOf: (id: string) => string | undefined }) {
  const where = useWhere();
  const groups = [
    { label: 'Regulation says', citations: item.citations.filter((c) => kindOf(c.document_id) === 'regulatory') },
    { label: 'Your policy says', citations: item.citations.filter((c) => kindOf(c.document_id) === 'internal') },
  ];
  return (
    <div className="evidence-pair">
      {groups.map((group) => (
        <div key={group.label}>
          <div className="label">{group.label}</div>
          {group.citations.length === 0 && <p className="small-text muted">Not located in the selected excerpts.</p>}
          {group.citations.map((c) => (
            <div key={c.chunk_id + c.quote} style={{ display: 'grid', gap: 2, marginBottom: 8 }}>
              <Quote citation={c} label={n} />
              <span className="small-text muted">{where(c)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function GapResult({ result }: { result: AIResult }) {
  const { byId } = useLibrary();
  const [filter, setFilter] = useState<Filter>('all');
  const summary = result.gap_summary!;
  const order = { high: 0, medium: 1, review: 2, low: 3 } as Record<string, number>;
  const items = [...result.items].sort((a, b) => (order[a.risk ?? 'review'] ?? 2) - (order[b.risk ?? 'review'] ?? 2));
  const shown = items.filter((item) => filter === 'all' || item.risk === filter);
  const kindOf = (id: string) => byId.get(id)?.kind;

  return (
    <>
      <section className="panel">
        <div className="score">
          <div className="score-figure">{summary.score ?? '—'}{summary.score != null && <small>%</small>}</div>
          <div>
            <h2>{summary.score == null ? 'Not enough evidence to score' : 'of assessed requirements addressed'}</h2>
            <p className="muted small-text" style={{ marginTop: 4 }}>
              {summary.high_risk_items} high-risk finding{summary.high_risk_items === 1 ? '' : 's'}, {summary.assessed_items} assessed,
              {' '}{summary.not_assessed_items} needing review because the excerpts were not conclusive.
            </p>
            {summary.score != null && <div className="meter" aria-hidden="true"><span style={{ width: `${summary.score}%` }} /></div>}
            <details style={{ marginTop: 10 }}>
              <summary>How the score is calculated</summary>
              <p className="small-text muted">{summary.method}</p>
            </details>
          </div>
        </div>
      </section>
      <section className="panel">
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="segmented" role="group" aria-label="Filter findings">
            {FILTERS.map((f) => (
              <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label}{f.key !== 'all' ? ` (${items.filter((i) => i.risk === f.key).length})` : ''}
              </button>
            ))}
          </div>
        </div>
        {shown.length === 0 && <Empty title="No findings in this group" />}
        <div className="table-wrap"><table className="table">
          <thead><tr><th style={{ width: '58%' }}>Finding and evidence</th><th>Policy status</th><th>Risk</th></tr></thead>
          <tbody>
            {shown.map((item, i) => (
              <tr key={i}>
                <td>
                  <div className="row" style={{ gap: 12, alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                    <span className="num" aria-hidden="true">{i + 1}</span>
                    <div style={{ minWidth: 0 }}>
                      <p className="statement" style={{ fontSize: 15 }}>{item.statement}</p>
                      <Evidence item={item} n={i + 1} kindOf={kindOf} />
                    </div>
                  </div>
                </td>
                <td>{item.status_label}</td>
                <td><RiskBadge risk={item.risk} /></td>
              </tr>
            ))}
          </tbody>
        </table></div>
        <ResultFooter result={result} />
      </section>
    </>
  );
}

export function Gaps() {
  const { families } = useLibrary();
  const { job, error, busy, start, forget, setError } = useJob('gaps');
  const regulations = families.filter((f) => f.kind === 'regulatory').flatMap((f) => f.versions).filter((d) => d.indexed);
  const policies = families.filter((f) => f.kind === 'internal').flatMap((f) => f.versions).filter((d) => d.indexed);
  const [regulationId, setRegulationId] = useState('');
  const [policyId, setPolicyId] = useState('');
  const [focus, setFocus] = useState('');
  const regulation = regulationId || regulations[0]?.id || '';
  const policy = policyId || policies[0]?.id || '';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      start(await api.startJob('gap_analysis',
        focus.trim() || 'Assess whether the internal policy meets the requirements of the regulation, requirement by requirement.',
        [regulation, policy]));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  return (
    <>
      <PageHead title="Gap analysis" intro="Check one of your policies against a regulation. Each finding shows the regulation's words beside your policy's, with a status and a risk level." />
      {!regulations.length || !policies.length ? (
        <section className="panel">
          <Empty title={!policies.length ? 'Upload an internal policy first' : 'Index a regulation first'}>
            A gap check needs at least one indexed regulation and one indexed internal policy in the Library.
          </Empty>
        </section>
      ) : (
        <form className="panel stack" onSubmit={submit}>
          <div className="grid-2">
            <label className="field">
              <span>Regulation</span>
              <select className="select" value={regulation} onChange={(e) => setRegulationId(e.target.value)}>
                {regulations.map((d) => <option key={d.id} value={d.id}>{d.metadata.title.value} ({versionName(d)})</option>)}
              </select>
            </label>
            <label className="field">
              <span>Your policy</span>
              <select className="select" value={policy} onChange={(e) => setPolicyId(e.target.value)}>
                {policies.map((d) => <option key={d.id} value={d.id}>{d.metadata.title.value} ({versionName(d)})</option>)}
              </select>
            </label>
          </div>
          <label className="field">
            <span>Focus (optional)</span>
            <input className="input" value={focus} onChange={(e) => setFocus(e.target.value)} maxLength={4000}
              placeholder="For example: customer identification and periodic KYC updates" />
            <small>Narrowing the focus gives sharper findings; the check reads the most relevant excerpts of each document.</small>
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div><button className="button primary" type="submit" disabled={busy}>Run gap check</button></div>
        </form>
      )}
      <div style={{ marginTop: 16 }}>
        <JobOutcome job={job} onDismiss={forget}>{(result) => <GapResult result={result} />}</JobOutcome>
      </div>
    </>
  );
}
