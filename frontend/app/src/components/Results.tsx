import type { ReactNode } from 'react';
import type { AIResult, Citation, Job, ResultItem } from '../lib/api';
import { useLibrary, useSource } from '../context';
import { duration, ErrorNote } from './ui';

const STEPS: { stage: Job['stage']; label: string }[] = [
  { stage: 'retrieving', label: 'Finding evidence' },
  { stage: 'drafting', label: 'Drafting the answer' },
  { stage: 'verifying', label: 'Checking every quote' },
  { stage: 'completed', label: 'Ready' },
];

export function JobProgress({ job, onCancelView }: { job: Job; onCancelView?: () => void }) {
  const current = STEPS.findIndex((s) => s.stage === job.stage);
  return (
    <section className="panel progress" aria-live="polite">
      <div className="section-title">
        <h2>{job.state === 'queued' ? 'Waiting for the model' : 'Working on it'}</h2>
        <span className="muted small-text">{job.elapsed_seconds != null ? duration(job.elapsed_seconds) : ''}</span>
      </div>
      {job.state === 'queued' && (
        <p>{job.queue_position && job.queue_position > 1 ? `${job.queue_position - 1} request(s) ahead of yours.` : 'Your request is next.'}</p>
      )}
      <ol className="steps">
        {STEPS.map((step, i) => (
          <li key={step.stage} className={job.state === 'queued' ? '' : i < current ? 'done' : i === current ? 'current' : ''}>{step.label}</li>
        ))}
      </ol>
      <p className="muted small-text">
        The model runs on this computer, so an answer can take a few minutes. You can open other pages; the result will be waiting here.
      </p>
      {onCancelView && <div><button className="button quiet small" onClick={onCancelView}>Stop waiting and ask something else</button></div>}
    </section>
  );
}

/** Where a citation sits, in words: the document and page (or section for HTML sources). */
export function useWhere() {
  const { byId } = useLibrary();
  return (citation: Citation) => {
    const doc = byId.get(citation.document_id);
    const place = citation.section ? `section “${citation.section}”` : `page ${citation.page}`;
    return `${doc?.metadata.title.value ?? 'Document'}, ${place}`;
  };
}

function useOpenCitation() {
  const { open } = useSource();
  return (citation: Citation, label?: number) =>
    open({ documentId: citation.document_id, page: citation.page, quote: citation.quote, section: citation.section, label });
}

/** A small numbered chip that opens the cited page. */
export function CitationButton({ citation, n }: { citation: Citation; n: number }) {
  const openCitation = useOpenCitation();
  return (
    <button className="cite" title={`Open the source at page ${citation.page}`} aria-label={`Open source ${n}, page ${citation.page}`}
      onClick={() => openCitation(citation, n)}>
      {n}
    </button>
  );
}

/** The quoted words in highlighter, clickable to open the page they come from. */
export function Quote({ citation, label }: { citation: Citation; label?: number }) {
  const openCitation = useOpenCitation();
  return (
    <p className="quote">
      <button onClick={() => openCitation(citation, label)} aria-label={`Show this quotation on page ${citation.page}`}>
        <span className="hl">{citation.quote}</span>
      </button>
    </p>
  );
}

function Finding({ item, n }: { item: ResultItem; n: number }) {
  const where = useWhere();
  const openCitation = useOpenCitation();
  return (
    <li className="finding">
      <span className="num" aria-hidden="true">{n}</span>
      <div className="finding-body">
        <p className="statement"><span className="visually-hidden">Statement {n}: </span>{item.statement}</p>
        {item.citations.map((citation) => (
          <div key={citation.chunk_id + citation.quote} style={{ display: 'grid', gap: 4 }}>
            <Quote citation={citation} label={n} />
            <button className="button quiet small where" style={{ justifySelf: 'start', padding: 0, minHeight: 28 }} onClick={() => openCitation(citation, n)}>{where(citation)}</button>
          </div>
        ))}
      </div>
    </li>
  );
}

export function Rejected({ result }: { result: AIResult }) {
  if (!result.rejected_items.length) return null;
  const count = result.rejected_items.length;
  return (
    <details>
      <summary>{count} statement{count > 1 ? 's' : ''} removed: the quote did not match the source</summary>
      <ul className="small-text">
        {result.rejected_items.map((item) => (
          <li key={item.index}>{item.statement ? <>“{item.statement}” — </> : null}{item.reason}</li>
        ))}
      </ul>
    </details>
  );
}

export function ResultFooter({ result }: { result: AIResult }) {
  return (
    <div className="result-foot">
      <Rejected result={result} />
      <span>Pending human review</span>
      <span>{result.model}, {duration(result.generation_seconds)}, {result.evidence_excerpts} excerpts searched</span>
      {result.audit_id && <span>Audit reference {result.audit_id}</span>}
      {result.notes.length > 0 && (
        <details style={{ flexBasis: '100%' }}>
          <summary>How this answer was produced</summary>
          <ul className="small-text">{result.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          <p className="small-text muted" style={{ marginTop: 6 }}>{result.limitations}</p>
        </details>
      )}
    </div>
  );
}

/** Answers, checklists and change explanations: numbered statements, each with its quotation. */
export function AnswerView({ result, heading }: { result: AIResult; heading: ReactNode }) {
  const verified = result.items.length;
  return (
    <section aria-label="Result">
      <div className="answer-head">
        <h2>{heading}</h2>
        <span className="verified">{verified} statement{verified === 1 ? '' : 's'} verified against the source</span>
      </div>
      <ol className="answer">
        {result.items.map((item, i) => <Finding key={i} item={item} n={i + 1} />)}
      </ol>
      <ResultFooter result={result} />
    </section>
  );
}

export function JobOutcome({ job, children, onDismiss }: { job: Job | null; children: (result: AIResult) => ReactNode; onDismiss: () => void }) {
  if (!job) return null;
  if (job.state === 'queued' || job.state === 'running') return <JobProgress job={job} onCancelView={onDismiss} />;
  if (job.state === 'failed') {
    return (
      <ErrorNote>
        <strong>No result.</strong> {job.error}
        <div style={{ marginTop: 8 }}><button className="button small" onClick={onDismiss}>Dismiss</button></div>
      </ErrorNote>
    );
  }
  return job.result ? <>{children(job.result)}</> : null;
}
