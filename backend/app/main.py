import difflib
import hmac
import json
import os
from datetime import date
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .importer import fetch_pdf
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


def create_app(db_path=None):
    app = FastAPI(title='Compliance Copilot document pipeline')
    store = Store(db_path or os.getenv('COPILOT_DB','data/corpus.sqlite3'))
    app.state.store = store
    app.state.retrieval = Retrieval(store)

    def organization(authorization: str = Header(default='')):
        # Server-side token mapping: clients cannot choose another organization's scope.
        tokens = json.loads(os.getenv('COPILOT_ORG_TOKENS','{}'))
        token = authorization.removeprefix('Bearer ')
        for org, expected in tokens.items():
            if expected and hmac.compare_digest(token, expected):
                return org
        raise HTTPException(401, 'Configure COPILOT_ORG_TOKENS and supply your organization bearer token')

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
        return FileResponse('frontend/index.html')

    @app.get('/api/documents')
    def documents(org=Depends(organization)):
        docs = store.list(org)
        return {'documents':docs, 'regulatory_empty':not any(d['kind']=='regulatory' for d in docs), 'message':'Upload a regulatory PDF or import an official RBI/SEBI PDF to begin.' if not docs else None}

    @app.post('/api/documents/upload', status_code=201)
    async def upload(file: UploadFile = File(), metadata: str = Form(), org=Depends(organization)):
        parsed = Metadata.model_validate_json(metadata)
        data = await file.read(20*1024*1024+1)
        return store.ingest(data, parsed, org)

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
        return store.ingest(data, body.metadata, org, verified_source=body.url)

    @app.get('/api/documents/{identifier}/chunks')
    def chunks(identifier: str, org=Depends(organization)):
        return store.chunks(identifier, org)

    @app.get('/api/documents/{identifier}/pdf')
    def pdf(identifier: str, org=Depends(organization)):
        return Response(store.get(identifier,org)['pdf'], media_type='application/pdf', headers={'Content-Disposition':'inline; filename="source.pdf"'})

    @app.post('/api/citations/validate')
    def citation(body: CitationRequest, org=Depends(organization)):
        return store.citation(body.chunk_id,body.quote,org)

    @app.get('/api/compare')
    def compare(old: str, new: str, org=Depends(organization)):
        a,b = store.get(old,org),store.get(new,org)
        if old == new or a['family_id'] != b['family_id']:
            raise ValueError('Select two distinct stored versions from the same family')
        left,right = store.chunks(old,org),store.chunks(new,org)
        # Page text avoids duplicate overlap in chunk reconstruction.
        with store.engine.connect() as conn:
            from sqlalchemy import text
            texts = [[r[0] for r in conn.execute(text('SELECT content FROM pages WHERE document_id=:id ORDER BY number'),{'id':i})] for i in (old,new)]
        return {'old':store.describe(a),'new':store.describe(b),'diff':'\n'.join(difflib.unified_diff('\n'.join(texts[0]).splitlines(),'\n'.join(texts[1]).splitlines(),fromfile=old,tofile=new,lineterm='')), 'evidence':{'old':left,'new':right}, 'note':'Text comparison only; this is not an AI regulatory interpretation.'}

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


app = create_app()
