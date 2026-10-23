import type { ReactNode } from 'react';
import type { AIResult, Citation, Job, ResultItem } from '../lib/api';
import { markPhrases, markQuote } from '../lib/quote';
import { useLibrary, useSource } from '../context';
import { duration, ErrorNote } from './ui';

const STEPS: { stage: Job['stage']; label: string }[] = [
  { stage: 'retrieving', label: 'Finding evidence' },
  { stage: 'drafting', label: 'Drafting' },
  { stage: 'verifying', label: 'Checking quotes' },
  { stage: 'summarising', label: 'Short answer' },
  { stage: 'completed', label: 'Ready' },
];

export function JobProgress({ job, onCancelView }: { job: Job; onCancelView?: () => void }) {
  const current = STEPS.findIndex((s) => s.stage === job.stage);
  return (
    <section className="panel progress" aria-live="polite">
      <div className="section-head" style={{ marginBottom: 0 }}>
        <h2>{job.state === 'queued' ? 'Waiting for the model' : 'Working on it'}</h2>
        <span className="label">{job.elapsed_seconds != null ? duration(job.elapsed_seconds) : ''}</span>
      </div>
      {job.state === 'queued' && (
        <p>{job.queue_position && job.queue_position > 1 ? `${job.queue_position - 1} request(s) ahead of yours.` : 'Your request is next.'}</p>
      )}
      <ol className="steps">
        {STEPS.map((step, i) => (
          <li key={step.stage} className={job.state === 'queued' ? '' : i < current ? 'done' : i === current ? 'current' : ''}>{step.label}</li>
        ))}
      </ol>
      <p className="muted small-text">The model runs on this computer, so this can take a few minutes. You can open other pages; the result will be waiting here.</p>
      {onCancelView && <div><button className="link quiet" onClick={onCancelView}>Stop waiting</button></div>}
    </section>
  );
}

export function useOpenCitation() {
  const { open } = useSource();
  return (citation: Citation, label?: number) =>
    open({ documentId: citation.document_id, page: citation.page, quote: citation.quote, section: citation.section, label, keyPhrase: citation.key_phrase });
}

export function usePlace() {
  const { byId } = useLibrary();
  return {
    title: (citation: Citation) => byId.get(citation.document_id)?.metadata.title.value ?? 'Document',
    short: (citation: Citation) => (citation.section ? `§ ${citation.section}` : `P. ${citation.page}`),
    long: (citation: Citation) => {
      const title = byId.get(citation.document_id)?.metadata.title.value ?? 'Document';
      return `${title}, ${citation.section ? `section “${citation.section}”` : `page ${citation.page}`}`;
    },
  };
}

/** A quotation with the words that answer the question in lime; clicking opens its page. */
export function KeyQuote({ citation, label }: { citation: Citation; label?: number }) {
  const openCitation = useOpenCitation();
  const parts = citation.key_phrase ? markQuote(citation.quote, citation.key_phrase) : [{ text: citation.quote, marked: false }];
  return (
    <p className="quote">
      <button className="open" onClick={() => openCitation(citation, label)} aria-label={`Show this quotation on page ${citation.page}`}>
        “{parts.map((part, i) => (part.marked ? <mark key={i} className="key">{part.text}</mark> : <span key={i}>{part.text}</span>))}”
      </button>
    </p>
  );
}

function uniqueCitations(citations: Citation[]) {
  const seen = new Set<string>();
  return citations.filter((c) => {
    const key = `${c.document_id}|${c.page}|${c.section ?? ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** One line on what the answer rests on: a single page, or how many sources. */
export function SourcesLine({ items }: { items: ResultItem[] }) {
  const place = usePlace();
  const all = uniqueCitations(items.flatMap((i) => i.citations));
  if (!all.length) return null;
  if (all.length === 1) return <span className="muted">{place.long(all[0])}</span>;
  const docs = new Set(all.map((c) => c.document_id)).size;
  return <span className="muted">{all.length} places in {docs} document{docs > 1 ? 's' : ''}</span>;
}

export function VerifiedLine({ result }: { result: AIResult }) {
  const accepted = result.items.length;
  const removed = result.rejected_items.length;
  return (
    <p className="verified-line">
      <span className="ok">
        <span className="check" aria-hidden="true">✓</span>
        {removed === 0 && accepted > 1 ? `All ${accepted} statements match the source word for word` : `${accepted} statement${accepted === 1 ? '' : 's'} match the source word for word`}
      </span>
      <SourcesLine items={result.items} />
    </p>
  );
}

export function Details({ result, extra }: { result: AIResult; extra?: ReactNode }) {
  const removed = result.rejected_items.length;
  const bits = [
    removed ? `${removed} unverified statement${removed > 1 ? 's' : ''} removed` : null,
    `${result.evidence_excerpts} excerpts searched`,
    duration((result.generation_seconds ?? 0) + (result.focus_seconds ?? 0)),
    result.audit_id,
    'pending human review',
  ].filter(Boolean);
  return (
    <details className="details">
      <summary>Details · {bits.join(' · ')}</summary>
      {extra}
      {removed > 0 && (
        <>
          <p style={{ marginTop: 8 }}>Removed because their quotes did not match the source:</p>
          <ul>{result.rejected_items.map((item) => <li key={item.index}>{item.statement ? <>“{item.statement}” — </> : null}{item.reason}</li>)}</ul>
        </>
      )}
      <ul>
        {result.notes.map((note) => <li key={note}>{note}</li>)}
        {result.focus && <li>{result.focus.note}</li>}
        <li>Model {result.model}. {result.limitations}</li>
      </ul>
    </details>
  );
}

function figureFor(result: AIResult, index: number) {
  return result.focus?.labels[String(index)];
}

/** Each statement with the words from the source that back it. */
export function WhereRows({ result, heading }: { result: AIResult; heading: string }) {
  const place = usePlace();
  const openCitation = useOpenCitation();
  return (
    <section aria-label={heading}>
      <div className="section-head"><h2>{heading}</h2></div>
      <ol className="ruled">
        {result.items.map((item, i) => {
          const figure = figureFor(result, i);
          return (
            <li key={i} className="where">
              <span className={`fig${figure ? '' : ' num'}`}>{figure ?? String(i + 1).padStart(2, '0')}</span>
              <div className="what">
                <p className="statement">{item.statement}</p>
                {item.citations.map((citation) => <KeyQuote key={citation.chunk_id + citation.quote} citation={citation} label={i + 1} />)}
              </div>
              <div style={{ display: 'grid', gap: 6, justifyItems: 'end' }}>
                {uniqueCitations(item.citations).map((citation) => (
                  <button key={citation.chunk_id} className="link" title={place.long(citation)} onClick={() => openCitation(citation, i + 1)}>
                    {place.short(citation)}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Answer-first: the short answer with the deciding words in lime, then where the source says so. */
export function AnswerView({ result, label, rowsHeading = 'Where the source says so' }: { result: AIResult; label: string; rowsHeading?: string }) {
  const answer = result.focus?.answer;
  return (
    <div className="stack" style={{ gap: 40 }}>
      <section className="answer-block" aria-label={label}>
        <span className="label">{label}</span>
        {answer ? (
          <p className="answer-text">
            {markPhrases(answer, result.focus?.highlights ?? []).map((part, i) => (part.marked ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>))}
          </p>
        ) : (
          <p className="answer-text" style={{ fontSize: 24 }}>{result.items.length === 1 ? result.items[0].statement : `${result.items.length} verified statements, below.`}</p>
        )}
        <VerifiedLine result={result} />
      </section>
      <WhereRows result={result} heading={rowsHeading} />
      <Details result={result} />
    </div>
  );
}

export function JobOutcome({ job, children, onDismiss }: { job: Job | null; children: (result: AIResult) => ReactNode; onDismiss: () => void }) {
  if (!job) return null;
  if (job.state === 'queued' || job.state === 'running') return <JobProgress job={job} onCancelView={onDismiss} />;
  if (job.state === 'failed') {
    return (
      <ErrorNote>
        <strong>No result.</strong> {job.error}
        <div style={{ marginTop: 8 }}><button className="link" onClick={onDismiss}>Dismiss</button></div>
      </ErrorNote>
    );
  }
  return job.result ? <>{children(job.result)}</> : null;
}
