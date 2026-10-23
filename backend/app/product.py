"""API for the client-facing web app.

Additive only: it reuses the existing store, retrieval and AI pipeline without
changing them, and adds what the product UI needs on top:

- who the caller is (organization, administrator flag),
- the library with per-document page counts and index state,
- AI requests as background jobs with live stages (queued, retrieving,
  drafting, verifying) so the UI can show progress during slow CPU generation,
- a compliance score and risk level derived from gap-analysis labels,
- a persistent audit trail of every AI request and its validated result.

All routes live under /api/app and use the same bearer tokens as the rest of
the API. X-Copilot-User and X-Copilot-Role headers are self-declared display
values recorded in the audit trail; they are not authentication.
"""
import asyncio
import json
import mimetypes
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .ai import generate
from .compare import diff_hunks, order_versions, stored_pages
from .focus import add_focus
from .retrieval import RetrievalError

ROLES = {'compliance_officer':'Compliance Officer', 'legal':'Legal', 'risk':'Risk', 'executive':'Executive'}
STAGES = ('queued', 'retrieving', 'drafting', 'verifying', 'summarising', 'completed')
MAX_JOBS_KEPT = 200
MAX_CHANGES = 300
MAX_LINES_PER_CHANGE = 60

# Deterministic mapping from the model's gap label to what the reviewer sees.
# Weight feeds the compliance score; None = not assessed (excluded from it).
GAP_LABELS = {
    'APPEARS_ADDRESSED':     {'status':'Addressed',             'risk':'low',    'weight':1.0},
    'PARTIALLY_ADDRESSED':   {'status':'Partially addressed',   'risk':'medium', 'weight':0.5},
    'POTENTIAL_GAP':         {'status':'Potential gap',         'risk':'high',   'weight':0.0},
    'POSSIBLE_CONFLICT':     {'status':'Possible conflict',     'risk':'high',   'weight':0.0},
    'INSUFFICIENT_EVIDENCE': {'status':'Insufficient evidence', 'risk':'review', 'weight':None},
}

AUDIT_SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, finished_at TEXT, organization TEXT NOT NULL,
    user_name TEXT, user_role TEXT, task TEXT NOT NULL, question TEXT NOT NULL, document_ids TEXT NOT NULL,
    status TEXT NOT NULL, model TEXT, generation_seconds REAL, accepted INTEGER, rejected INTEGER,
    error TEXT, result TEXT)''',
    'CREATE INDEX IF NOT EXISTS idx_audit_org_time ON audit_log(organization, created_at)',
]


class JobRequest(BaseModel):
    task: Literal['qa', 'comparison', 'gap_analysis', 'checklist']
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] = Field(min_length=1, max_length=4)


def now():
    return datetime.now(timezone.utc).isoformat()


def score_gap(result):
    """Add status/risk to each gap item and a summary with a compliance score.

    Score = mean weight of assessed items (Addressed 1, Partial 0.5, Gap or
    Conflict 0) as a percentage; Insufficient evidence is excluded and counted.
    """
    counts = {label:0 for label in GAP_LABELS}
    weights = []
    for item in result['items']:
        info = GAP_LABELS.get(item.get('assessment'), GAP_LABELS['INSUFFICIENT_EVIDENCE'])
        item['status_label'] = info['status']
        item['risk'] = info['risk']
        counts[item.get('assessment') if item.get('assessment') in GAP_LABELS else 'INSUFFICIENT_EVIDENCE'] += 1
        if info['weight'] is not None:
            weights.append(info['weight'])
    result['gap_summary'] = {
        'score': round(100 * sum(weights) / len(weights)) if weights else None,
        'assessed_items': len(weights),
        'not_assessed_items': counts['INSUFFICIENT_EVIDENCE'],
        'high_risk_items': counts['POTENTIAL_GAP'] + counts['POSSIBLE_CONFLICT'],
        'counts': counts,
        'method': 'Addressed = 1, Partially addressed = 0.5, Potential gap or Possible conflict = 0; '
                  'Insufficient evidence is excluded. Model assessments require human review.',
    }
    return result


class _TrackedRetrieval:
    """Reports retrieval progress for a job while delegating to the real Retrieval."""

    def __init__(self, inner, job):
        self._inner, self._job = inner, job

    def search(self, *args, **kwargs):
        self._job['stage'] = 'retrieving'
        result = self._inner.search(*args, **kwargs)
        # After the last per-document search, generation drafts the answer.
        self._job['stage'] = 'drafting'
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _TrackedStore:
    """Marks the verification stage when quotations are checked; delegates everything else."""

    def __init__(self, inner, job):
        self._inner, self._job = inner, job

    def citation(self, *args, **kwargs):
        self._job['stage'] = 'verifying'
        return self._inner.citation(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class JobRunner:
    """Runs AI jobs one at a time on a background thread (local models are serial anyway)."""

    def __init__(self):
        self.jobs = {}
        self.order = []
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.worker = None

    def submit(self, store, retrieval, org, request, user, role):
        job = {'id':uuid.uuid4().hex, 'organization':org, 'task':request.task, 'question':request.question,
               'document_ids':list(request.document_ids), 'state':'queued', 'stage':'queued',
               'created_at':now(), 'started_at':None, 'finished_at':None, 'result':None, 'error':None,
               'audit_id':audit_id(), 'user':user, 'role':role}
        record_audit_start(store, job)
        with self.lock:
            self.jobs[job['id']] = job
            self.order.append(job['id'])
            while len(self.order) > MAX_JOBS_KEPT:
                old = self.order.pop(0)
                if self.jobs.get(old, {}).get('state') in ('completed', 'failed'):
                    self.jobs.pop(old, None)
                else:
                    self.order.insert(0, old)
                    break
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._work, daemon=True)
                self.worker.start()
        self.queue.put((job, store, retrieval))
        return job

    def _work(self):
        while True:
            job, store, retrieval = self.queue.get()
            try:
                self._run(job, store, retrieval)
            finally:
                self.queue.task_done()

    def _run(self, job, store, retrieval):
        job['state'], job['stage'], job['started_at'] = 'running', 'retrieving', now()
        started = time.monotonic()
        body = SimpleNamespace(task=job['task'], question=job['question'], document_ids=job['document_ids'])
        try:
            result = asyncio.run(generate(_TrackedStore(store, job), body, job['organization'], _TrackedRetrieval(retrieval, job)))
            if job['task'] == 'gap_analysis':
                result = score_gap(result)
            # Answer-first focus: optional, validated, and never fatal to the verified result.
            job['stage'] = 'summarising'
            focus_started = time.monotonic()
            result = add_focus(result, job['question'])
            result['focus_seconds'] = round(time.monotonic() - focus_started, 1)
            result['audit_id'] = job['audit_id']
            job['result'], job['state'], job['stage'] = result, 'completed', 'completed'
        except (ValueError, LookupError, RuntimeError) as exc:  # RetrievalError is a RuntimeError
            job['error'], job['state'] = str(exc), 'failed'
        except Exception as exc:  # Unexpected: reported, never fabricated as a result.
            job['error'], job['state'] = f'Unexpected {type(exc).__name__}: {exc}', 'failed'
        job['finished_at'] = now()
        job['elapsed_seconds'] = round(time.monotonic() - started, 1)
        record_audit_finish(store, job)

    def view(self, job_id, org):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job['organization'] != org:
                raise LookupError('Job not found')
            waiting = [j for j in (self.jobs[i] for i in self.order if i in self.jobs) if j['state'] == 'queued']
        position = next((i + 1 for i, j in enumerate(waiting) if j['id'] == job_id), None)
        elapsed = job.get('elapsed_seconds')
        if elapsed is None and job['started_at']:
            elapsed = round((datetime.now(timezone.utc) - datetime.fromisoformat(job['started_at'])).total_seconds(), 1)
        return {k:job[k] for k in ('id', 'task', 'question', 'document_ids', 'state', 'stage', 'created_at', 'started_at',
                                   'finished_at', 'result', 'error', 'audit_id')} | {'queue_position':position, 'elapsed_seconds':elapsed,
                                                                                     'stages':list(STAGES)}


def audit_id():
    return f"AUD-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def ensure_audit_table(store):
    with store.engine.begin() as conn:
        for statement in AUDIT_SCHEMA:
            conn.execute(text(statement))
        # Jobs live in server memory; any still open at startup were cut off by a restart.
        conn.execute(text("UPDATE audit_log SET status='failed', finished_at=:now, "
                          "error='Interrupted by a server restart before it finished' WHERE status='queued'"), {'now':now()})


def record_audit_start(store, job):
    with store.engine.begin() as conn:
        conn.execute(text('INSERT INTO audit_log (id, created_at, organization, user_name, user_role, task, question, document_ids, status) '
                          'VALUES (:id, :created, :org, :user, :role, :task, :question, :docs, :status)'),
                     {'id':job['audit_id'], 'created':job['created_at'], 'org':job['organization'], 'user':job['user'],
                      'role':job['role'], 'task':job['task'], 'question':job['question'],
                      'docs':json.dumps(job['document_ids']), 'status':'queued'})


def record_audit_finish(store, job):
    result = job['result'] or {}
    with store.engine.begin() as conn:
        conn.execute(text('UPDATE audit_log SET finished_at=:finished, status=:status, model=:model, generation_seconds=:seconds, '
                          'accepted=:accepted, rejected=:rejected, error=:error, result=:result WHERE id=:id'),
                     {'id':job['audit_id'], 'finished':job['finished_at'], 'status':job['state'], 'model':result.get('model'),
                      'seconds':result.get('generation_seconds'), 'accepted':len(result.get('items', [])) if job['result'] else None,
                      'rejected':len(result.get('rejected_items', [])) if job['result'] else None,
                      'error':job['error'], 'result':json.dumps(job['result']) if job['result'] else None})


def _audit_row(row, full=False):
    entry = dict(row)
    entry['document_ids'] = json.loads(entry['document_ids'])
    entry['role_label'] = ROLES.get(entry['user_role'])
    if full:
        entry['result'] = json.loads(entry['result']) if entry['result'] else None
    else:
        entry.pop('result', None)
    entry.pop('organization', None)
    return entry


def page_counts(store):
    with store.engine.connect() as conn:
        return {row[0]:row[1] for row in conn.execute(text('SELECT document_id, COUNT(*) FROM pages GROUP BY document_id'))}


def install(app, principal):
    """Create the audit table and register the product routes on an app."""
    # Windows can map script types wrongly in its registry; browsers refuse to run
    # module scripts (the app and the PDF worker) served with the wrong type.
    for extension, kind in (('.js', 'text/javascript'), ('.mjs', 'text/javascript'), ('.css', 'text/css'), ('.woff2', 'font/woff2'), ('.woff', 'font/woff')):
        mimetypes.add_type(kind, extension)
    ensure_audit_table(app.state.store)
    app.state.job_runner = JobRunner()
    router = APIRouter(prefix='/api/app', tags=['product'])

    def identity(user_name, user_role):
        role = user_role if user_role in ROLES else None
        name = (user_name or '').strip()[:100] or None
        return name, role

    @router.get('/me')
    def me(user=Depends(principal)):
        return {'organization':user.org, 'is_admin':user.is_admin, 'roles':ROLES}

    @router.get('/library')
    def library(request: Request, user=Depends(principal)):
        store, retrieval = request.app.state.store, request.app.state.retrieval
        documents = store.list(user.org)
        pages = page_counts(store)
        index = {'state':'ready', 'message':None}
        indexed = set()
        try:
            docs, chunks = retrieval.candidates(user.org)
            if docs:
                _, ready_docs, unindexed = retrieval.indexed_subset(docs, chunks)
                indexed = {d['id'] for d in ready_docs}
                if unindexed:
                    index = {'state':'pending', 'message':f'{len(unindexed)} document(s) waiting to be indexed'}
        except RetrievalError as exc:
            index = {'state':'unavailable', 'message':str(exc)}
        for document in documents:
            document['page_count'] = pages.get(document['id'], 0)
            document['indexed'] = document['id'] in indexed
        return {'documents':documents, 'index':index, 'is_admin':user.is_admin}

    @router.post('/jobs', status_code=202)
    def submit_job(body: JobRequest, request: Request, user=Depends(principal),
                   x_copilot_user: str | None = Header(default=None), x_copilot_role: str | None = Header(default=None)):
        store = request.app.state.store
        if len(set(body.document_ids)) != len(body.document_ids):
            raise ValueError('Select distinct document versions')
        for identifier in body.document_ids:
            store.get_metadata(identifier, user.org)  # 404 now, not minutes later
        name, role = identity(x_copilot_user, x_copilot_role)
        job = request.app.state.job_runner.submit(store, request.app.state.retrieval, user.org, body, name, role)
        return request.app.state.job_runner.view(job['id'], user.org)

    @router.get('/jobs/{job_id}')
    def job_status(job_id: str, request: Request, user=Depends(principal)):
        return request.app.state.job_runner.view(job_id, user.org)

    @router.get('/compare')
    def compare(a: str, b: str, request: Request, user=Depends(principal)):
        store = request.app.state.store
        first, second = store.get_metadata(a, user.org), store.get_metadata(b, user.org)
        if a == b or first['family_id'] != second['family_id']:
            raise ValueError('Select two different versions of the same document')
        older, newer, swapped = order_versions(first, second)
        hunks = diff_hunks(stored_pages(store, older['id']), stored_pages(store, newer['id']))
        counts = {kind:sum(h['change'] == kind for h in hunks) for kind in ('added', 'removed', 'modified')}
        changes = []
        for hunk in hunks[:MAX_CHANGES]:
            truncated = len(hunk['removed']) > MAX_LINES_PER_CHANGE or len(hunk['added']) > MAX_LINES_PER_CHANGE
            changes.append({**hunk, 'removed':hunk['removed'][:MAX_LINES_PER_CHANGE], 'added':hunk['added'][:MAX_LINES_PER_CHANGE],
                            'truncated':truncated})
        return {'older':store.describe(older), 'newer':store.describe(newer), 'reordered':swapped,
                'changes':changes, 'total_changes':len(hunks), 'counts':counts}

    @router.get('/audit')
    def audit_list(request: Request, limit: int = 50, user=Depends(principal)):
        limit = max(1, min(limit, 200))
        with request.app.state.store.engine.connect() as conn:
            rows = conn.execute(text('SELECT * FROM audit_log WHERE organization=:org ORDER BY created_at DESC LIMIT :limit'),
                                {'org':user.org, 'limit':limit}).mappings()
            return {'entries':[_audit_row(row) for row in rows]}

    @router.get('/audit/{entry_id}')
    def audit_entry(entry_id: str, request: Request, user=Depends(principal)):
        with request.app.state.store.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM audit_log WHERE id=:id AND organization=:org'),
                               {'id':entry_id, 'org':user.org}).mappings().first()
        if not row:
            raise LookupError('Audit entry not found')
        return _audit_row(row, full=True)

    app.include_router(router)
