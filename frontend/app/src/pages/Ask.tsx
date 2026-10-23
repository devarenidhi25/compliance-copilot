import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLibrary } from '../context';
import { useJob } from '../hooks';
import { api } from '../lib/api';
import { DocumentPicker } from '../components/DocumentPicker';
import { AnswerView, JobOutcome } from '../components/Results';
import { Empty, ErrorNote } from '../components/ui';

const MAX_DOCUMENTS = 4;

export function defaultRegulations(families: ReturnType<typeof useLibrary>['families']) {
  return families.filter((f) => f.kind === 'regulatory').map((f) => f.latest).filter((d) => d.indexed).slice(0, MAX_DOCUMENTS).map((d) => d.id);
}

export function Ask() {
  const { families, byId } = useLibrary();
  const [params] = useSearchParams();
  const { job, error, busy, start, forget, setError } = useJob('ask');
  const [question, setQuestion] = useState(params.get('q') ?? '');
  const [mode, setMode] = useState<'qa' | 'checklist'>('qa');
  const [olderVersions, setOlderVersions] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [choosing, setChoosing] = useState(false);

  const regulations = families.filter((f) => f.kind === 'regulatory');
  const choices = useMemo(() => regulations.flatMap((f) => (olderVersions ? f.versions : [f.latest])), [regulations, olderVersions]);

  useEffect(() => {
    if (selected.length || !families.length) return;
    const requested = params.get('doc');
    if (requested && byId.get(requested)?.indexed) {
      setSelected([requested]);
      if (!regulations.some((f) => f.latest.id === requested)) setOlderVersions(true);
      return;
    }
    setSelected(job?.document_ids.length ? job.document_ids : defaultRegulations(families));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [families.length, job?.id]);

  useEffect(() => {
    if (job && !question) {
      setQuestion(job.question);
      if (job.task === 'checklist') setMode('checklist');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  const scope = selected.length === 1 ? `in ${byId.get(selected[0])?.metadata.title.value ?? '1 document'}` : `in ${selected.length} documents`;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setChoosing(false);
      start(await api.startJob(mode, question.trim(), selected));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  if (!regulations.length) {
    return <Empty title="No regulations yet">Upload an RBI or SEBI document in the Library, then index it.</Empty>;
  }

  return (
    <>
      <form className="stack" style={{ gap: 12, maxWidth: 940 }} onSubmit={submit}>
        <div className="askbar">
          <label htmlFor="question" className="visually-hidden">{mode === 'qa' ? 'Your question' : 'What the checklist should cover'}</label>
          <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} required maxLength={4000}
            placeholder={mode === 'qa' ? 'Ask about RBI or SEBI regulation…' : 'What should the checklist cover?'} />
          <span className="scope">
            {scope}
            <button type="button" className="link quiet" onClick={() => setChoosing(!choosing)} aria-expanded={choosing}>Change</button>
          </span>
          <button className="button primary" type="submit" disabled={busy || !question.trim() || !selected.length}>{mode === 'qa' ? 'Ask' : 'Draft'}</button>
        </div>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div className="segmented" role="group" aria-label="What you need">
            <button type="button" aria-pressed={mode === 'qa'} onClick={() => setMode('qa')}>Answer</button>
            <button type="button" aria-pressed={mode === 'checklist'} onClick={() => setMode('checklist')}>Action checklist</button>
          </div>
          {busy && <span className="label">A request is already running</span>}
        </div>
        {choosing && (
          <div className="panel soft stack" style={{ gap: 10 }}>
            <DocumentPicker documents={choices} selected={selected} onChange={setSelected} max={MAX_DOCUMENTS} label="Search these documents" />
            <label className="row small-text">
              <input type="checkbox" checked={olderVersions} onChange={(e) => setOlderVersions(e.target.checked)} />
              Include older versions
            </label>
          </div>
        )}
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>

      <JobOutcome job={job} onDismiss={forget}>
        {(result) => result.task === 'checklist'
          ? <AnswerView result={result} label="Action checklist" rowsHeading="Actions, with the words that require them" />
          : <AnswerView result={result} label="Answer" />}
      </JobOutcome>
    </>
  );
}
