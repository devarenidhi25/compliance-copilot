import { useState } from 'react';
import { useLoad } from '../hooks';
import { api, type AuditEntry } from '../lib/api';
import { formatDateTime } from '../lib/library';
import { AnswerView } from '../components/Results';
import { duration, Empty, ErrorNote, PageHead } from '../components/ui';

const TASK_NAMES: Record<string, string> = { qa: 'Question', checklist: 'Checklist', comparison: 'Change explanation', gap_analysis: 'Gap check' };

function Status({ entry }: { entry: AuditEntry }) {
  if (entry.status === 'completed') {
    return <span className="badge good">{entry.accepted} accepted{entry.rejected ? `, ${entry.rejected} removed` : ''}</span>;
  }
  if (entry.status === 'failed') return <span className="badge bad">Did not complete</span>;
  return <span className="badge warn">In progress</span>;
}

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useLoad(() => api.auditEntry(id), [id]);
  return (
    <section className="stack" style={{ marginTop: 16 }}>
      <div className="row"><h2 className="grow">Record {id}</h2><button className="button small" onClick={onClose}>Close record</button></div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {data && (
        <>
          <div className="panel small-text">
            <p><strong>{TASK_NAMES[data.task]}</strong> by {data.user_name ?? 'unknown'}{data.role_label ? ` (${data.role_label})` : ''}, {formatDateTime(data.created_at)}</p>
            <p style={{ marginTop: 4, color: 'var(--ink)' }}>“{data.question}”</p>
            <p className="muted" style={{ marginTop: 4 }}>
              {data.document_ids.length} document{data.document_ids.length > 1 ? 's' : ''} searched
              {data.model ? `, model ${data.model}` : ''}{data.generation_seconds ? `, ${duration(data.generation_seconds)}` : ''}.
            </p>
          </div>
          {data.error && <ErrorNote>{data.error}</ErrorNote>}
          {data.result && (
            <AnswerView result={data.result} heading={data.task === 'gap_analysis' ? `Findings (score ${data.result.gap_summary?.score ?? '—'}%)` : 'Recorded result'} />
          )}
        </>
      )}
    </section>
  );
}

export function Audit() {
  const { data, error, loading, reload } = useLoad(() => api.audit(100));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <PageHead title="Audit trail" intro="Every AI request made by your organisation: who asked, what was searched, and what was returned after quote checking."
        actions={<button className="button" onClick={() => void reload()}>Refresh</button>} />
      {error && <ErrorNote>{error}</ErrorNote>}
      <section className="panel">
        {loading && !data && <p className="muted">Loading…</p>}
        {data && data.entries.length === 0 && <Empty title="No AI requests yet">Questions, checklists, change explanations and gap checks will be recorded here.</Empty>}
        {data && data.entries.length > 0 && (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>When</th><th>Request</th><th>By</th><th>Outcome</th><th>Reference</th></tr></thead>
            <tbody>
              {data.entries.map((entry) => (
                <tr key={entry.id} className="clickable" onClick={() => setOpen(entry.id)} tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && setOpen(entry.id)} aria-label={`Open record ${entry.id}`}>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(entry.created_at)}</td>
                  <td><div className="small-text muted">{TASK_NAMES[entry.task]}</div>{entry.question}</td>
                  <td>{entry.user_name ?? 'unknown'}<div className="small-text muted">{entry.role_label ?? ''}</div></td>
                  <td><Status entry={entry} /></td>
                  <td className="small-text muted" style={{ whiteSpace: 'nowrap' }}>{entry.id}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
      {open && <Detail id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
