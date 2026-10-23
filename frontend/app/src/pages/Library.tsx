import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useLibrary, useSource } from '../context';
import { api, type IndexJob, type LibraryDocument } from '../lib/api';
import { formatDate, joinableFamilies, versionName, type Family } from '../lib/library';
import { useSignedIn } from '../session';
import { Empty, ErrorNote, IndexBadge, PageHead, VisibilityBadge } from '../components/ui';

type Scope = 'all' | 'regulatory' | 'internal';

function IndexBanner() {
  const session = useSignedIn();
  const { library, reload } = useLibrary();
  const [job, setJob] = useState<IndexJob | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (job?.state !== 'running') return;
    const timer = setTimeout(async () => {
      try {
        const next = await api.indexJob();
        setJob(next);
        if (next.state === 'complete') await reload();
        if (next.state === 'failed') setError(next.error ?? 'Indexing failed');
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [job, reload]);

  if (!library || (library.index.state === 'ready' && job?.state !== 'running')) return null;
  const start = async () => {
    setError('');
    try {
      setJob(await api.startIndexSync());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };
  return (
    <div className="notice warn" style={{ marginBottom: 16, alignItems: 'center' }}>
      <div className="grow">
        {job?.state === 'running'
          ? 'Indexing documents for search and AI. Large documents take several minutes on a laptop.'
          : library.index.state === 'pending'
            ? `${library.index.message}. They can be browsed now but not used for answers yet.`
            : 'The search index has not been built yet, so documents cannot be used for answers.'}
        {!session.isAdmin && ' An administrator can index them.'}
        {error && <div style={{ marginTop: 6, color: 'var(--bad)' }}>{error}</div>}
      </div>
      {session.isAdmin && (
        <button className="button primary small" onClick={start} disabled={job?.state === 'running'}>
          {job?.state === 'running' ? 'Indexing…' : 'Index now'}
        </button>
      )}
    </div>
  );
}

function UploadDrawer({ onClose }: { onClose: (uploaded?: LibraryDocument) => void }) {
  const session = useSignedIn();
  const { families } = useLibrary();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<'regulatory' | 'internal'>('regulatory');
  const [form, setForm] = useState({ title: '', regulator: 'RBI', document_type: '', version: '', effective_date: '', publication_date: '', family_id: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const joinable = joinableFamilies(families, kind, session.isAdmin);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const chooseFile = (chosen: File | null) => {
    setFile(chosen);
    if (chosen && !form.title) setForm((f) => ({ ...f, title: chosen.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ').trim() }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError('');
    const family = families.find((f) => f.id === form.family_id);
    try {
      const uploaded = await api.upload(file, {
        title: form.title.trim(),
        kind,
        regulator: kind === 'regulatory' ? (family?.regulator ?? form.regulator) : null,
        document_type: form.document_type || null,
        version: form.version || null,
        effective_date: form.effective_date || null,
        publication_date: form.publication_date || null,
        family_id: form.family_id || null,
      });
      onClose(uploaded);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drawer-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <form className="drawer" onSubmit={submit} aria-label="Upload a document">
        <div className="row"><h2 className="grow">Upload a document</h2><button type="button" className="link" onClick={() => onClose()}>Close</button></div>
        <label className="field">
          <span>PDF file</span>
          <input className="input" type="file" accept="application/pdf" onChange={(e) => chooseFile(e.target.files?.[0] ?? null)} required />
          <small>Up to 20 MB. Scanned PDFs need OCR first so their text can be read.</small>
        </label>
        <div className="field">
          <span>This document is</span>
          <div className="segmented" role="group">
            <button type="button" aria-pressed={kind === 'regulatory'} onClick={() => { setKind('regulatory'); setForm((f) => ({ ...f, family_id: '' })); }}>A regulation or circular</button>
            <button type="button" aria-pressed={kind === 'internal'} onClick={() => { setKind('internal'); setForm((f) => ({ ...f, family_id: '' })); }}>Our internal policy</button>
          </div>
          <small>
            {kind === 'internal' ? 'Internal policies are only visible to your organisation.'
              : session.isAdmin ? 'As an administrator, your upload joins the shared library.'
                : 'Your upload is visible to your organisation only. Administrators add documents to the shared library.'}
          </small>
        </div>
        <label className="field">
          <span>Title</span>
          <input className="input" value={form.title} onChange={set('title')} required maxLength={500} />
        </label>
        {joinable.length > 0 && (
          <label className="field">
            <span>Is this a new version of an existing document?</span>
            <select className="select" value={form.family_id} onChange={set('family_id')}>
              <option value="">No, it is a new document</option>
              {joinable.map((f: Family) => <option key={f.id} value={f.id}>{f.latest.metadata.title.value} ({f.versions.length} version{f.versions.length > 1 ? 's' : ''})</option>)}
            </select>
          </label>
        )}
        <div className="grid-2">
          {kind === 'regulatory' && !form.family_id && (
            <label className="field">
              <span>Regulator</span>
              <select className="select" value={form.regulator} onChange={set('regulator')}><option>RBI</option><option>SEBI</option></select>
            </label>
          )}
          <label className="field">
            <span>Document type</span>
            <input className="input" value={form.document_type} onChange={set('document_type')} placeholder={kind === 'internal' ? 'Policy, SOP' : 'Master direction, circular'} />
          </label>
          <label className="field">
            <span>Version label</span>
            <input className="input" value={form.version} onChange={set('version')} placeholder="e.g. Amended Jan 2026" />
          </label>
          <label className="field">
            <span>Effective date</span>
            <input className="input" type="date" value={form.effective_date} onChange={set('effective_date')} />
          </label>
          <label className="field">
            <span>Publication date</span>
            <input className="input" type="date" value={form.publication_date} onChange={set('publication_date')} />
          </label>
        </div>
        <p className="small-text muted">Dates decide which version counts as newer when comparing. What you enter is recorded as supplied by you.</p>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="row">
          <button className="button primary" type="submit" disabled={busy || !file || !form.title.trim()}>{busy ? 'Uploading…' : 'Upload'}</button>
          <button className="button" type="button" onClick={() => onClose()}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

function FamilyRow({ family, expanded, onToggle }: { family: Family; expanded: boolean; onToggle: () => void }) {
  const { open } = useSource();
  const latest = family.latest;
  return (
    <div className="family">
      <button className="family-head" onClick={onToggle} aria-expanded={expanded}>
        <div>
          <h3>{latest.metadata.title.value}</h3>
          <div className="meta">
            <span>{family.kind === 'internal' ? 'Internal policy' : family.regulator}</span>
            <span>{family.versions.length} version{family.versions.length > 1 ? 's' : ''}</span>
            <span>latest: {versionName(latest)}</span>
            <VisibilityBadge doc={latest} />
            {family.versions.some((v) => !v.indexed) && <span className="badge warn"><span className="dot" />Not all indexed</span>}
          </div>
        </div>
        <span className="muted small-text">{expanded ? 'Hide versions' : 'Show versions'}</span>
      </button>
      {expanded && (
        <div className="family-versions">
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Version</th><th>Effective</th><th>Pages</th><th>Uploaded</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {family.versions.map((v) => (
                <tr key={v.id}>
                  <td>{versionName(v)}{v.metadata.source_url?.status === 'verified' && <div className="small-text muted">Fetched from the official site</div>}</td>
                  <td>{formatDate(v.metadata.effective_date?.value) || <span className="muted">Not given</span>}</td>
                  <td>{v.page_count}</td>
                  <td>{formatDate(v.uploaded_at)}</td>
                  <td><IndexBadge doc={v} /></td>
                  <td>
                    <div className="row" style={{ gap: 4, justifyContent: 'flex-end' }}>
                      <button className="button small" onClick={() => open({ documentId: v.id, page: 1 })}>Read</button>
                      {v.indexed && family.kind === 'regulatory' && <Link className="button small" to={`/ask?doc=${v.id}`}>Ask</Link>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
          {family.versions.length > 1 && family.kind === 'regulatory' && (
            <div style={{ marginTop: 10 }}><Link className="button small" to={`/changes?family=${family.id}`}>Compare versions</Link></div>
          )}
        </div>
      )}
    </div>
  );
}

export function Library() {
  const { families, loading, error, reload } = useLibrary();
  const [scope, setScope] = useState<Scope>('all');
  const [query, setQuery] = useState('');
  const [uploading, setUploading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const shown = useMemo(() => families.filter((f) => (scope === 'all' || f.kind === scope)
    && f.versions.some((v) => v.metadata.title.value.toLowerCase().includes(query.trim().toLowerCase()))), [families, scope, query]);

  return (
    <>
      <PageHead title="Library" intro="Regulations and your internal policies, with every version kept. Documents must be indexed before they can be used for answers."
        actions={<button className="button primary" onClick={() => setUploading(true)}>Upload document</button>} />
      <IndexBanner />
      {message && <div className="notice info" style={{ marginBottom: 16 }}>{message}</div>}
      {error && <ErrorNote>{error}</ErrorNote>}
      <section>
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="segmented" role="group" aria-label="Show">
            {(['all', 'regulatory', 'internal'] as Scope[]).map((s) => (
              <button key={s} aria-pressed={scope === s} onClick={() => setScope(s)}>{s === 'all' ? 'All' : s === 'regulatory' ? 'Regulations' : 'Internal policies'}</button>
            ))}
          </div>
          <input className="input grow" style={{ maxWidth: 360 }} placeholder="Search by title" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search by title" />
        </div>
        {loading && !families.length && <p className="muted">Loading the library…</p>}
        {!loading && !families.length && (
          <Empty title="The library is empty">Upload an RBI or SEBI document, or one of your internal policies, to get started.</Empty>
        )}
        {families.length > 0 && !shown.length && <Empty title="No matches">Try a different title or show all documents.</Empty>}
        {shown.map((family) => (
          <FamilyRow key={family.id} family={family} expanded={expanded === family.id} onToggle={() => setExpanded(expanded === family.id ? null : family.id)} />
        ))}
      </section>
      {uploading && (
        <UploadDrawer onClose={async (uploaded) => {
          setUploading(false);
          if (uploaded) {
            await reload();
            setExpanded(uploaded.family_id);
            setMessage(`Uploaded “${uploaded.metadata.title.value}” (${uploaded.visibility === 'shared' ? 'shared library' : 'visible to your organisation'}). It needs indexing before it can be used for answers.`);
          }
        }} />
      )}
    </>
  );
}
