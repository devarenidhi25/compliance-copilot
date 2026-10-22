import difflib
import hmac
import json
import os
import threading
from datetime import date, datetime, timezone
from typing import Literal, NamedTuple

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .compare import diff_hunks, order_versions, page_lines, stored_pages
from .importer import fetch_pdf
from .index_cli import synchronize
from .paths import FRONTEND_INDEX, corpus_path
from .store import Store
from .retrieval import Retrieval, RetrievalError
from starlette.concurrency import run_in_threadpool


class Metadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=500)
    kind: Literal['regulatory','internal']
    regulator: Literal['RBI','SEBI'] | None = None
    document_type: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    publication_date: date | None = None
    version: str | None = Field(default=None, max_length=200)
    effective_date: date | None = None
    family_id: str | None = None

    @model_validator(mode='after')
    def regulatory_regulator(self):
        if self.kind == 'regulatory' and not self.regulator:
            raise ValueError('Select a regulator for regulatory documents')
        return self


class ImportRequest(BaseModel):
    url: str
    metadata: Metadata


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_ids: list[str] | None = Field(default=None, max_length=100)
    regulator: Literal['RBI','SEBI'] | None = None
    kind: Literal['regulatory','internal'] | None = None
    family_id: str | None = None
    version: str | None = None
    document_type: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=4000)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    mode: Literal['bm25','semantic','hybrid'] = 'hybrid'
    limit: int = Field(default=6, ge=1, le=20)


class AIRequest(BaseModel):
    task: Literal['qa','comparison','gap_analysis','checklist']
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] = Field(min_length=1, max_length=4)


class CitationRequest(BaseModel):
    chunk_id: str
    quote: str


class IndexJob:
    """Runs index synchronization inside the server process, one job at a time.

    Chroma's persistent store is not safe to write from a second process while
    the server reads it, so administrators sync through the server instead.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {'state':'idle'}

    def start(self, retrieval, rebuild):
        with self.lock:
            if self.state['state'] == 'running':
                raise HTTPException(409, 'An index job is already running')
            self.state = {'state':'running', 'rebuild':rebuild, 'started_at':datetime.now(timezone.utc).isoformat()}
        threading.Thread(target=self._run, args=(retrieval, rebuild), daemon=True).start()
        return self.snapshot()

    def _run(self, retrieval, rebuild):
        try:
            outcome = {'state':'complete', 'result':synchronize(retrieval, rebuild=rebuild)}
        except Exception as exc:  # Reported to the administrator; the active index is preserved.
            outcome = {'state':'failed', 'error':str(exc)}
        with self.lock:
            self.state = {**self.state, **outcome, 'finished_at':datetime.now(timezone.utc).isoformat()}

    def snapshot(self):
        with self.lock:
            return dict(self.state)


class Principal(NamedTuple):
    org: str
    is_admin: bool


def token_config():
    """Parse COPILOT_ORG_TOKENS and COPILOT_ADMIN_TOKENS ({"organization": "token"})."""
    parsed = []
    for variable in ('COPILOT_ORG_TOKENS', 'COPILOT_ADMIN_TOKENS'):
        try:
            value = json.loads(os.getenv(variable) or '{}')
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'{variable} must be JSON like {{"your-organization":"token"}}: {exc}') from exc
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise RuntimeError(f'{variable} must map organization names to token strings')
        parsed.append(value)
    return tuple(parsed)


def create_app(db_path=None):
    app = FastAPI(title='Compliance Copilot document pipeline')
    store = Store(db_path or corpus_path())
    app.state.store = store
    app.state.retrieval = Retrieval(store)
    app.state.index_job = IndexJob()

    token_config()  # Fail at startup, not per request, on malformed token JSON.

    def principal(authorization: str = Header(default='')):
        # Server-side token mapping: clients cannot choose another organization's scope.
        org_tokens, admin_tokens = token_config()
        token = authorization.removeprefix('Bearer ')
        for tokens, is_admin in ((admin_tokens, True), (org_tokens, False)):
            for org, expected in tokens.items():
                if expected and hmac.compare_digest(token, expected):
                    return Principal(org, is_admin)
        raise HTTPException(401, 'Configure COPILOT_ORG_TOKENS and supply your organization bearer token')

    def organization(user: Principal = Depends(principal)):
        return user.org

    def administrator(user: Principal = Depends(principal)):
        if not user.is_admin:
            raise HTTPException(403, 'Administrator token required (COPILOT_ADMIN_TOKENS)')
        return user

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={'detail':str(exc)})

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={'detail':str(exc)})

    @app.exception_handler(RetrievalError)
    async def retrieval_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={'detail':str(exc)})

    @app.post('/api/retrieval/search')
    def search(body: SearchRequest, org=Depends(organization)):
        return app.state.retrieval.search(body.query, org, body.filters.model_dump(exclude_none=True), body.mode, body.limit)

    @app.get('/api/retrieval/status')
    def retrieval_status(org=Depends(organization)):
        return app.state.retrieval.status(org)

    @app.get('/', include_in_schema=False)
    def home():
        return FileResponse(FRONTEND_INDEX)

    @app.get('/api/documents')
    def documents(org=Depends(organization)):
        docs = store.list(org)
        return {'documents':docs, 'regulatory_empty':not any(d['kind']=='regulatory' for d in docs), 'message':'Upload a regulatory PDF or import an official RBI/SEBI PDF to begin.' if not docs else None}

    @app.post('/api/documents/upload', status_code=201)
    async def upload(file: UploadFile = File(), metadata: str = Form(), user: Principal = Depends(principal)):
        parsed = Metadata.model_validate_json(metadata)
        data = await file.read(20*1024*1024+1)
        # Unverified regulatory uploads stay private to the uploader's organization
        # unless an administrator adds them to the shared library.
        return store.ingest(data, parsed, user.org, shared=user.is_admin)

    @app.post('/api/documents/import', status_code=201)
    async def import_document(body: ImportRequest, org=Depends(organization)):
        if body.metadata.kind != 'regulatory':
            raise ValueError('Official import is only for regulatory documents')
        try:
            data, regulator = await fetch_pdf(body.url)
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'Official source unavailable; upload a manually downloaded PDF if permitted') from exc
        if regulator != body.metadata.regulator:
            raise ValueError('Selected regulator does not match official host')
        return store.ingest(data, body.metadata, org, verified_source=body.url, shared=True)

    @app.get('/api/documents/{identifier}/chunks')
    def chunks(identifier: str, org=Depends(organization)):
        return store.chunks(identifier, org)

    @app.get('/api/documents/{identifier}/pdf')
    def pdf(identifier: str, org=Depends(organization)):
        document = store.get(identifier,org)
        is_html = document['metadata'] and json.loads(document['metadata']).get('original_format',{}).get('value') == 'html'
        media_type = 'text/html; charset=utf-8' if is_html else 'application/pdf'
        filename = 'source.html' if is_html else 'source.pdf'
        headers = {'Content-Disposition':f'inline; filename="{filename}"', 'X-Content-Type-Options':'nosniff'}
        if is_html:
            # Stored official HTML may contain scripts; never run them with this app's origin.
            headers['Content-Security-Policy'] = 'sandbox; default-src \'none\'; img-src data:; style-src \'unsafe-inline\''
        return Response(document['pdf'], media_type=media_type, headers=headers)

    @app.post('/api/citations/validate')
    def citation(body: CitationRequest, org=Depends(organization)):
        return store.citation(body.chunk_id,body.quote,org)

    @app.get('/api/compare')
    def compare(old: str, new: str, org=Depends(organization)):
        a, b = store.get_metadata(old, org), store.get_metadata(new, org)
        if old == new or a['family_id'] != b['family_id']:
            raise ValueError('Select two distinct stored versions from the same family')
        older, newer, swapped = order_versions(a, b)
        old_pages, new_pages = stored_pages(store, older['id']), stored_pages(store, newer['id'])
        hunks = diff_hunks(old_pages, new_pages)
        diff = '\n'.join(difflib.unified_diff([line for _, line in page_lines(old_pages)], [line for _, line in page_lines(new_pages)],
                                              fromfile=older['id'], tofile=newer['id'], lineterm=''))
        note = 'Text comparison only; this is not an AI regulatory interpretation.'
        if swapped:
            note += ' Versions were ordered by date: the earlier version is shown as old.'
        return {'old':store.describe(older), 'new':store.describe(newer), 'reordered':swapped, 'diff':diff,
                'changes':[{k:h[k] for k in ('change','old_pages','new_pages')} | {'removed_lines':len(h['removed']), 'added_lines':len(h['added'])} for h in hunks],
                'note':note}

    @app.post('/api/admin/index/sync', status_code=202)
    def start_index_job(rebuild: bool = False, user: Principal = Depends(administrator)):
        return app.state.index_job.start(app.state.retrieval, rebuild)

    @app.get('/api/admin/index/sync')
    def index_job_status(user: Principal = Depends(administrator)):
        return app.state.index_job.snapshot()

    @app.get('/api/health')
    async def health(org=Depends(organization)):
        retrieval_status = await run_in_threadpool(app.state.retrieval.status, org)
        model = os.getenv('OLLAMA_MODEL','qwen3:8b')
        try:
            async with httpx.AsyncClient(timeout=3,trust_env=False) as client:
                response = await client.get(os.getenv('OLLAMA_URL','http://localhost:11434').rstrip('/')+'/api/tags')
                response.raise_for_status()
                available = any(m.get('name') == model for m in response.json().get('models',[]))
            return {'documents':'ready','retrieval':retrieval_status,'ollama':'ready' if available else 'model_missing','model':model,'instruction':None if available else f'Run: ollama pull {model}'}
        except (httpx.HTTPError,ValueError):
            return {'documents':'ready','retrieval':retrieval_status,'ollama':'unavailable','model':model,'instruction':f'Run: ollama serve; ollama pull {model}'}

    @app.post('/api/ai')
    async def ai(body: AIRequest, org=Depends(organization)):
        from .ai import generate
        try:
            return await generate(store, body, org, app.state.retrieval)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    return app


def __getattr__(name):
    # Created on first access (uvicorn backend.app.main:app), not at import, so
    # importing this module (tests, tooling) never creates data/ or a database.
    if name == 'app':
        global app
        app = create_app()
        return app
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
