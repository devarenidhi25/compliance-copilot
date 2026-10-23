import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLoad } from '../hooks';
import { api, type AuditEntry } from '../lib/api';
import { formatDateTime } from '../lib/library';
import { AnswerView } from '../components/Results';
import { duration, Empty, ErrorNote, PageHead } from '../components/ui';
import { GapResult } from './Gaps';

const TASK_NAMES: Record<string, string> = { qa: 'Question', checklist: 'Checklist', comparison: 'Change explanation', gap_analysis: 'Gap check' };

function Status({ entry }: { entry: AuditEntry }) {
  if (entry.status === 'completed') {
    return <span className="badge ok">✓ {entry.accepted} verified{entry.rejected ? ` · ${entry.rejected} removed` : ''}</span>;
  }
  if (entry.status === 'failed') return <span className="badge bad">Did not complete</span>;
  return <span className="badge warn">In progress</span>;
}

function Record({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useLoad(() => api.auditEntry(id), [id]);
  const top = useRef<HTMLElement>(null);
  useEffect(() => top.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }), [id]);
  return (
    <section ref={top} className="stack" style={{ gap: 28, scrollMarginTop: 16 }} aria-label={`Record ${id}`}>
      <div className="section-head" style={{ marginBottom: 0 }}>
        <span className="label">Record {id}</span>
        <button className="link" onClick={onClose}>Close record</button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {data && (
        <>
          <div className="stack" style={{ gap: 6 }}>
            <h2>“{data.question}”</h2>
            <p className="label">
              {TASK_NAMES[data.task]} by {data.user_name ?? 'unknown'}{data.role_label ? ` (${data.role_label})` : ''} · {formatDateTime(data.created_at)}
              {' · '}{data.document_ids.length} document{data.document_ids.length > 1 ? 's' : ''}
              {data.generation_seconds ? ` · ${duration(data.generation_seconds)}` : ''}
            </p>
          </div>
          {data.error && <ErrorNote>{data.error}</ErrorNote>}
          {data.result && (data.task === 'gap_analysis' && data.result.gap_summary
            ? <GapResult result={data.result} />
            : <AnswerView result={data.result} label={data.task === 'checklist' ? 'Action checklist' : data.task === 'comparison' ? 'What changed and what it means' : 'Answer'} />)}
        </>
      )}
    </section>
  );
}

export function Audit() {
  const [params, setParams] = useSearchParams();
  const { data, error, loading, reload } = useLoad(() => api.audit(100));
  const open = params.get('open');
  const setOpen = (id: string | null) => setParams(id ? { open: id } : {});
  return (
    <>
      <PageHead title="Audit trail" intro="Every AI request made by your organisation: who asked, which documents were searched, and what came back after the quotes were checked."
        actions={<button className="button" onClick={() => void reload()}>Refresh</button>} />
      {open && <Record id={open} onClose={() => setOpen(null)} />}
      {error && <ErrorNote>{error}</ErrorNote>}
      <section>
        {loading && !data && <p className="muted">Loading…</p>}
        {data && data.entries.length === 0 && <Empty title="No AI requests yet">Questions, checklists, change explanations and gap checks will be recorded here.</Empty>}
        {data && data.entries.length > 0 && (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>When</th><th>Request</th><th>By</th><th>Outcome</th><th>Reference</th></tr></thead>
            <tbody>
              {data.entries.map((entry) => (
                <tr key={entry.id} className="clickable" onClick={() => setOpen(entry.id)} tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && setOpen(entry.id)} aria-label={`Open record ${entry.id}`}>
                  <td className="label" style={{ whiteSpace: 'nowrap' }}>{formatDateTime(entry.created_at)}</td>
                  <td><div className="label">{TASK_NAMES[entry.task]}</div>{entry.question}</td>
                  <td>{entry.user_name ?? 'unknown'}<div className="label">{entry.role_label ?? ''}</div></td>
                  <td><Status entry={entry} /></td>
                  <td className="label" style={{ whiteSpace: 'nowrap' }}>{entry.id}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
    </>
  );
}
