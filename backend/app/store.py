"""Immutable PDF versions and page-scoped evidence. No corpus seeding."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from sqlalchemy import create_engine, text

SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, family_id TEXT NOT NULL, organization TEXT,
    kind TEXT NOT NULL, metadata TEXT NOT NULL, content_hash TEXT NOT NULL,
    uploaded_at TEXT NOT NULL, pdf BLOB NOT NULL,
    UNIQUE(family_id, content_hash))''',
    '''CREATE TABLE IF NOT EXISTS pages (
    document_id TEXT NOT NULL REFERENCES documents(id), number INTEGER NOT NULL,
    content TEXT NOT NULL, PRIMARY KEY(document_id, number))''',
    '''CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
    page INTEGER NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
    content TEXT NOT NULL)''',
]


class Store:
    def __init__(self, path, *, allow_synthetic=False):
        self.allow_synthetic = allow_synthetic
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f'sqlite:///{path}')
        with self.engine.begin() as conn:
            for statement in SCHEMA:
                conn.execute(text(statement))

    def list(self, organization):
        with self.engine.connect() as conn:
            rows = conn.execute(text('SELECT id,family_id,organization,kind,metadata,content_hash,uploaded_at FROM documents WHERE organization IS NULL OR organization=:org ORDER BY uploaded_at'), {'org': organization})
            return [self.describe(dict(row)) for row in rows.mappings()]

    @staticmethod
    def describe(row):
        row.pop('pdf', None)
        row['metadata'] = json.loads(row['metadata'])
        return row

    def get(self, identifier, organization):
        with self.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM documents WHERE id=:id AND (organization IS NULL OR organization=:org)'), {'id': identifier, 'org': organization}).mappings().first()
            if not row:
                raise LookupError('Document not found')
            return dict(row)

    def get_metadata(self, identifier, organization):
        with self.engine.connect() as conn:
            row = conn.execute(text('SELECT id,family_id,organization,kind,metadata,content_hash,uploaded_at FROM documents WHERE id=:id AND (organization IS NULL OR organization=:org)'), {'id':identifier,'org':organization}).mappings().first()
            if not row:
                raise LookupError('Document not found')
            return dict(row)

    def ingest(self, data, metadata, organization, verified_source=None):
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('PDF exceeds 20 MiB limit')
        if not data.startswith(b'%PDF-'):
            raise ValueError('Upload a valid PDF')
        try:
            with pymupdf.open(stream=data, filetype='pdf') as pdf:
                if pdf.needs_pass or pdf.page_count > 1000:
                    raise ValueError('Encrypted PDFs and PDFs over 1000 pages are unsupported')
                pages = [page.get_text('text', sort=True) for page in pdf]
        except (RuntimeError, pymupdf.FileDataError) as exc:
            raise ValueError('PDF could not be parsed') from exc
        if not any(p.strip() for p in pages):
            raise ValueError('No extractable text. Run OCR locally and upload a searchable PDF.')
        if sum(map(len, pages)) > 10_000_000:
            raise ValueError('Extracted text exceeds limit')
        if not self.allow_synthetic and (metadata.title.upper().startswith('SYNTHETIC') or any('SYNTHETIC KYC SOP' in p.upper() or 'SYNTHETIC DEMONSTRATION ONLY' in p.upper() for p in pages)):
            raise ValueError('Synthetic documents belong in the isolated test/demo database')
        doc_id = str(uuid.uuid4())
        family_id = metadata.family_id or str(uuid.uuid4())
        scope = organization if metadata.kind == 'internal' else None
        fields = {}
        for key in ['title', 'regulator', 'document_type', 'source_url', 'publication_date', 'version', 'effective_date']:
            value = getattr(metadata, key)
            fields[key] = {'value': str(value) if value is not None else None, 'status': 'user_supplied' if value is not None else 'unknown'}
        if verified_source:
            fields['source_url'] = {'value': verified_source, 'status': 'verified', 'verification': 'Fetched over HTTPS from an allowlisted official host'}
            fields['regulator'] = {'value': metadata.regulator, 'status': 'verified', 'verification': 'Official source host; document applicability requires human review'}
        digest = hashlib.sha256(data).hexdigest()
        with self.engine.begin() as conn:
            previous = conn.execute(text('SELECT organization,kind,metadata FROM documents WHERE family_id=:id LIMIT 1'), {'id': family_id}).mappings().first()
            if metadata.family_id and not previous:
                raise ValueError('Select an existing family ID or omit it to create a new family')
            if previous and (previous['organization'] != scope or previous['kind'] != metadata.kind or json.loads(previous['metadata'])['regulator']['value'] != metadata.regulator):
                raise ValueError('Version family must have the same scope, kind and regulator')
            duplicate = conn.execute(text('SELECT id FROM documents WHERE family_id=:family AND content_hash=:hash'), {'family': family_id, 'hash': digest}).scalar()
            if duplicate:
                raise ValueError(f'Identical version already stored: {duplicate}')
            conn.execute(text('INSERT INTO documents VALUES (:id,:family,:org,:kind,:meta,:hash,:time,:pdf)'), {'id':doc_id,'family':family_id,'org':scope,'kind':metadata.kind,'meta':json.dumps(fields),'hash':digest,'time':datetime.now(timezone.utc).isoformat(),'pdf':data})
            for number, content in enumerate(pages, 1):
                conn.execute(text('INSERT INTO pages VALUES (:id,:number,:content)'), {'id':doc_id,'number':number,'content':content})
                for start in range(0, len(content), 1000):
                    chunk = content[start:start+1200]
                    chunk_id = str(uuid.uuid5(uuid.UUID(doc_id), f'{number}:{start}'))
                    conn.execute(text('INSERT INTO chunks VALUES (:cid,:id,:page,:start,:end,:content)'), {'cid':chunk_id,'id':doc_id,'page':number,'start':start,'end':start+len(chunk),'content':chunk})
        return self.describe(self.get(doc_id, organization))

    def chunks(self, identifier, organization):
        self.get_metadata(identifier, organization)
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text('SELECT * FROM chunks WHERE document_id=:id ORDER BY page,start_offset'), {'id':identifier}).mappings()]

    def citation(self, chunk_id, quote, organization):
        with self.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM chunks WHERE id=:id'), {'id':chunk_id}).mappings().first()
        if not row:
            raise LookupError('Citation not found')
        doc = self.get_metadata(row['document_id'], organization)
        if not quote.strip() or quote not in row['content']:
            raise ValueError('Quote must be an exact nonempty excerpt from the stored chunk')
        return {'document_id':doc['id'], 'chunk_id':chunk_id, 'page':row['page'], 'quote':quote, 'source_url':json.loads(doc['metadata'])['source_url'], 'pdf_reference':f"/api/documents/{doc['id']}/pdf#page={row['page']}", 'content_hash':doc['content_hash']}
