import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLibrary } from '../context';
import { useJob } from '../hooks';
import { api } from '../lib/api';
import { useSignedIn } from '../session';
import { DocumentPicker } from '../components/DocumentPicker';
import { AnswerView, JobOutcome } from '../components/Results';
import { Empty, ErrorNote, PageHead } from '../components/ui';

const MAX_DOCUMENTS = 4;

export function Ask() {
  const session = useSignedIn();
  const { families, byId } = useLibrary();
  const [params] = useSearchParams();
  const { job, error, busy, start, forget, setError } = useJob('ask');
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<'qa' | 'checklist'>('qa');
  const [olderVersions, setOlderVersions] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  const regulations = families.filter((f) => f.kind === 'regulatory');
  const choices = useMemo(
    () => regulations.flatMap((f) => (olderVersions ? f.versions : [f.latest])),
    [regulations, olderVersions],
  );

  // Preselect the requested document, or the latest indexed version of recent regulations.
  useEffect(() => {
    if (selected.length || !families.length) return;
    const requested = params.get('doc');
    if (requested && byId.get(requested)?.indexed) {
      setSelected([requested]);
      if (!regulations.some((f) => f.latest.id === requested)) setOlderVersions(true);
      return;
    }
    setSelected(regulations.map((f) => f.latest).filter((d) => d.indexed).slice(0, MAX_DOCUMENTS).map((d) => d.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [families.length]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      start(await api.startJob(mode, question.trim(), selected));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  return (
    <>
      <PageHead title="Ask" intro={session.role === 'executive'
        ? 'Ask in plain language. Each statement in the answer links to the clause it comes from.'
        : 'Ask about the selected regulations. Every statement in the answer quotes its source, and quotes that do not match the source are removed.'} />
      {!regulations.length ? (
        <section className="panel"><Empty title="No regulations yet">Upload an RBI or SEBI document in the Library first.</Empty></section>
      ) : (
        <form className="panel stack" onSubmit={submit}>
          <div className="segmented" role="group" aria-label="What do you need">
            <button type="button" aria-pressed={mode === 'qa'} onClick={() => setMode('qa')}>Answer a question</button>
            <button type="button" aria-pressed={mode === 'checklist'} onClick={() => setMode('checklist')}>Draft an action checklist</button>
          </div>
          <label className="field">
            <span>{mode === 'qa' ? 'Your question' : 'What should the checklist cover?'}</span>
            <textarea className="textarea" value={question} onChange={(e) => setQuestion(e.target.value)} required maxLength={4000}
              placeholder={mode === 'qa' ? 'For example: How quickly must we disclose a material event to the stock exchanges?' : 'For example: Steps to comply with the event disclosure timelines'} />
          </label>
          <DocumentPicker documents={choices} selected={selected} onChange={setSelected} max={MAX_DOCUMENTS} label="Search these documents" />
          <label className="row small-text">
            <input type="checkbox" checked={olderVersions} onChange={(e) => setOlderVersions(e.target.checked)} />
            Include older versions
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="row">
            <button className="button primary" type="submit" disabled={busy || !question.trim() || !selected.length}>
              {mode === 'qa' ? 'Get answer' : 'Draft checklist'}
            </button>
            {busy && <span className="muted small-text">A request is already running.</span>}
          </div>
        </form>
      )}
      <div style={{ marginTop: 16 }}>
        {job && <p className="muted small-text" style={{ marginBottom: 8 }}>{job.task === 'checklist' ? 'Checklist for' : 'Question'}: “{job.question}”</p>}
        <JobOutcome job={job} onDismiss={forget}>
          {(result) => <AnswerView result={result} heading={result.task === 'checklist' ? 'Action checklist' : 'Answer'} />}
        </JobOutcome>
      </div>
    </>
  );
}
