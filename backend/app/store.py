"""Immutable PDF versions and page-scoped evidence. No corpus seeding."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from sqlalchemy import create_engine, event, text

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
    content TEXT NOT NULL, section TEXT)''',
    'CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, page, start_offset)',
    'CREATE INDEX IF NOT EXISTS idx_documents_organization ON documents(organization)',
]



def _enable_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()


MIN_QUOTE_CHARS = 12
# PDF text and model output disagree on typographic variants; compare them as equal.
_EQUIVALENT = str.maketrans({'‘':"'", '’':"'", '‚':"'", '‛':"'", '′':"'",
                             '“':'"', '”':'"', '„':'"', '″':'"',
                             '‐':'-', '‑':'-', '‒':'-', '–':'-', '—':'-', '−':'-'})


def _normalized(value):
    """Collapse whitespace runs to one space; return text and a map to original indices."""
    chars, positions, pending_space = [], [], False
    for index, char in enumerate(value):
        if char.isspace():
            pending_space = bool(chars)
            continue
        if pending_space:
            chars.append(' ')
            positions.append(index - 1)
            pending_space = False
        chars.append(char.translate(_EQUIVALENT))
        positions.append(index)
    return ''.join(chars), positions


def collapse_whitespace(value):
    return _normalized(value)[0]


def locate_quote(content, quote):
    """Find quote in content ignoring whitespace/typographic differences.

    Returns the exact original substring of content, so stored citations remain
    verbatim source text. Very short fragments are rejected unless they are the
    whole chunk, because a single common word is not meaningful evidence.
    """
    if not isinstance(quote, str):
        raise ValueError('Quote must be text')
    needle = _normalized(quote)[0]
    haystack, positions = _normalized(content)
    if not needle:
        raise ValueError('Quote must be a nonempty excerpt from the stored chunk')
    if len(needle) < MIN_QUOTE_CHARS and needle != haystack:
        raise ValueError(f'Quote must be at least {MIN_QUOTE_CHARS} characters of source text')
    start = haystack.find(needle)
    if start < 0:
        raise ValueError('Quote must be an excerpt from the stored chunk (whitespace differences are tolerated)')
    return content[positions[start]:positions[start + len(needle) - 1] + 1]


class Store:
    def __init__(self, path, *, allow_synthetic=False):
        self.allow_synthetic = allow_synthetic
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f'sqlite:///{path}')
        event.listen(self.engine, 'connect', _enable_foreign_keys)
        with self.engine.begin() as conn:
            for statement in SCHEMA[:3]:
                conn.execute(text(statement))
            columns = {row[1] for row in conn.execute(text('PRAGMA table_info(chunks)'))}
            if 'section' not in columns:
                conn.execute(text('ALTER TABLE chunks ADD COLUMN section TEXT'))
            for statement in SCHEMA[3:]:
                conn.execute(text(statement))

    def list(self, organization):
        with self.engine.connect() as conn:
            rows = conn.execute(text('SELECT id,family_id,organization,kind,metadata,content_hash,uploaded_at FROM documents WHERE organization IS NULL OR organization=:org ORDER BY uploaded_at'), {'org': organization})
            return [self.describe(dict(row)) for row in rows.mappings()]

    @staticmethod
    def describe(row):
        row.pop('pdf', None)
        row['metadata'] = json.loads(row['metadata'])
        if 'organization' in row:
            row['visibility'] = 'shared' if row['organization'] is None else 'organization'
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

    def ingest(self, data, metadata, organization, verified_source=None, source_metadata=None, shared=None):
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
        return self._store_extracted(data, metadata, organization, pages, verified_source, source_metadata, shared=shared)

    def ingest_html(self, data, metadata, organization, sections, verified_source=None, source_metadata=None, shared=None):
        if len(data) > 20 * 1024 * 1024:
            raise ValueError('HTML document exceeds 20 MiB limit')
        sections = [(str(title or '').strip(), str(content or '').strip()) for title, content in sections]
        sections = [(title, content) for title, content in sections if content]
        if not sections:
            raise ValueError('HTML document contains no extractable text')
        if sum(len(title) + len(content) for title, content in sections) > 10_000_000:
            raise ValueError('Extracted text exceeds limit')
        pages = [f'{title}\n{content}' if title else content for title, content in sections]
        return self._store_extracted(data, metadata, organization, pages, verified_source,
                                     {**(source_metadata or {}), 'original_format':'html'},
                                     section_names=[title or f'Section {i+1}' for i, (title, _) in enumerate(sections)], shared=shared)

    def _store_extracted(self, data, metadata, organization, pages, verified_source=None,
                         source_metadata=None, section_names=None, shared=None):
        """Store an extracted document version.

        Internal documents always belong to the organization. Regulatory documents
        join the shared library only when shared is true (administrator uploads)
        or, by default, when fetched from a verified official source; otherwise
        they stay private to the uploading organization.
        """
        if not self.allow_synthetic and (metadata.title.upper().startswith('SYNTHETIC') or any('SYNTHETIC KYC SOP' in p.upper() or 'SYNTHETIC DEMONSTRATION ONLY' in p.upper() for p in pages)):
            raise ValueError('Synthetic documents belong in the isolated test/demo database')
        doc_id = str(uuid.uuid4())
        family_id = metadata.family_id or str(uuid.uuid4())
        if shared is None:
            shared = bool(verified_source)
        scope = None if metadata.kind == 'regulatory' and shared else organization
        fields = {}
        for key in ['title', 'regulator', 'document_type', 'source_url', 'publication_date', 'version', 'effective_date']:
            value = getattr(metadata, key)
            fields[key] = {'value': str(value) if value is not None else None, 'status': 'user_supplied' if value is not None else 'unknown'}
        for key, value in (source_metadata or {}).items():
            fields[key] = {'value': value, 'status': 'verified' if value is not None else 'unknown'}
        fields.setdefault('original_format', {'value':'pdf', 'status':'verified'})
        fields.setdefault('ingestion_status', {'value':'stored', 'status':'verified'})
        fields.setdefault('extraction_status', {'value':'complete', 'status':'verified'})
        if verified_source:
            fields['source_url'] = {'value': verified_source, 'status': 'verified', 'verification': 'Fetched over HTTPS from an allowlisted official host'}
            fields['regulator'] = {'value': metadata.regulator, 'status': 'verified', 'verification': 'Official source host; document applicability requires human review'}
        digest = hashlib.sha256(data).hexdigest()
        with self.engine.begin() as conn:
            previous = conn.execute(text('SELECT organization,kind,metadata FROM documents WHERE family_id=:id LIMIT 1'), {'id': family_id}).mappings().first()
            if metadata.family_id:
                # One message for missing and foreign families, so errors do not
                # reveal which private family IDs exist.
                if not previous or previous['organization'] not in (None, organization):
                    raise ValueError('Version family not found among your accessible documents; omit the family ID to create a new family')
                if previous['organization'] is None and scope is not None:
                    raise ValueError('This family is in the shared regulatory library; only an administrator can add versions to it. '
                                     'Omit the family ID to store your copy privately for your organization.')
                if previous['organization'] is not None and scope is None:
                    raise ValueError('This family is private to an organization; shared versions need their own family')
                if previous['kind'] != metadata.kind or json.loads(previous['metadata'])['regulator']['value'] != metadata.regulator:
                    raise ValueError('Version family must have the same kind and regulator')
            duplicate = conn.execute(text('SELECT id FROM documents WHERE family_id=:family AND content_hash=:hash'), {'family': family_id, 'hash': digest}).scalar()
            if duplicate:
                raise ValueError(f'Identical version already stored: {duplicate}')
            conn.execute(text('INSERT INTO documents VALUES (:id,:family,:org,:kind,:meta,:hash,:time,:pdf)'), {'id':doc_id,'family':family_id,'org':scope,'kind':metadata.kind,'meta':json.dumps(fields),'hash':digest,'time':datetime.now(timezone.utc).isoformat(),'pdf':data})
            for number, content in enumerate(pages, 1):
                conn.execute(text('INSERT INTO pages VALUES (:id,:number,:content)'), {'id':doc_id,'number':number,'content':content})
                for start in range(0, len(content), 1000):
                    chunk = content[start:start+1200]
                    chunk_id = str(uuid.uuid5(uuid.UUID(doc_id), f'{number}:{start}'))
                    section = section_names[number-1] if section_names else None
                    conn.execute(text('INSERT INTO chunks (id,document_id,page,start_offset,end_offset,content,section) VALUES (:cid,:id,:page,:start,:end,:content,:section)'), {'cid':chunk_id,'id':doc_id,'page':number,'start':start,'end':start+len(chunk),'content':chunk,'section':section})
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
        # Returned quote is the exact original span, not the model's spacing.
        quote = locate_quote(row['content'], quote)
        metadata = json.loads(doc['metadata'])
        result = {'document_id':doc['id'], 'chunk_id':chunk_id, 'page':row['page'], 'quote':quote, 'source_url':metadata['source_url'], 'pdf_reference':f"/api/documents/{doc['id']}/pdf#page={row['page']}", 'source_reference':f"/api/documents/{doc['id']}/pdf#page={row['page']}", 'content_hash':doc['content_hash']}
        if row.get('section'):
            result['section'] = row['section']
            result['source_reference'] = f"/api/documents/{doc['id']}/pdf#section={row['section']}"
        return result
