"""Authorized SQLite evidence with BM25 and explicitly configured local vectors."""
import hashlib
import json
import os
import re
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi


class RetrievalError(RuntimeError):
    pass


def tokens(value):
    return re.findall(r'\w+', value.lower())


def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        seen = set()
        for identifier in ranking:
            if identifier in seen:
                continue
            seen.add(identifier)
            scores[identifier] = scores.get(identifier, 0) + 1 / (k + len(seen))
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def inventory(chunks):
    return hashlib.sha256(json.dumps([(c['id'], c['content']) for c in chunks], sort_keys=True).encode()).hexdigest()


class LocalEmbedder:
    def __init__(self):
        self.path = Path(os.getenv('EMBEDDING_MODEL_PATH', 'data/models/bge-m3'))
        self.model = None
        self.loaded_identity = None
        self.lock = threading.RLock()

    def identity(self):
        marker = self.path / 'copilot-model.json'
        if not marker.exists():
            raise RetrievalError('Embedding model missing. Run: .venv/bin/python -m backend.app.index_cli download-model')
        try:
            identity = json.loads(marker.read_text())
            if not identity.get('revision') or not identity.get('model'):
                raise ValueError('Invalid model identity')
        except (ValueError, OSError, AttributeError) as exc:
            raise RetrievalError('Embedding model identity invalid; run download-model explicitly') from exc
        if identity['model'] != os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3'):
            raise RetrievalError('Embedding model does not match EMBEDDING_MODEL; download the configured model and rebuild the index')
        return identity

    def encode(self, texts):
        with self.lock:
            return self._encode(texts)

    def _encode(self, texts):
        identity = self.identity()
        if self.model is None or self.loaded_identity != identity:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(str(self.path/'snapshots'/identity['revision']), device=os.getenv('EMBEDDING_DEVICE', 'cpu'), local_files_only=True, trust_remote_code=False)
                self.loaded_identity = identity
            except Exception as exc:
                raise RetrievalError('Local embedding model cannot load. Check dependencies and EMBEDDING_MODEL_PATH; run download-model explicitly.') from exc
        try:
            return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()
        except Exception as exc:
            raise RetrievalError('Local embedding computation failed; check model files and available memory') from exc


class Retrieval:
    def __init__(self, store, path=None, embedder=None):
        self.store = store
        self.path = Path(path or os.getenv('CHROMA_PATH', 'data/chroma'))
        self.embedder = embedder or LocalEmbedder()

    def config(self):
        return {'corpus':str(Path(self.store.engine.url.database).resolve()), 'embedding':self.embedder.identity(), 'normalized':True, 'distance':'cosine', 'preprocessing':'exact-chunk-v1'}

    def manifest(self):
        try:
            manifest = json.loads((self.path/'manifest.json').read_text())
            if not isinstance(manifest, dict) or not {'config','collection','documents','dimensions'} <= manifest.keys() or not isinstance(manifest['config'],dict) or not isinstance(manifest['documents'],dict) or not isinstance(manifest['collection'],str):
                raise ValueError('Incomplete manifest')
            return manifest
        except FileNotFoundError:
            raise RetrievalError('Vector index not built. Run: .venv/bin/python -m backend.app.index_cli sync')
        except (ValueError, OSError) as exc:
            raise RetrievalError('Vector index manifest unreadable; inspect status and rebuild') from exc

    def collection(self, name, create=False):
        try:
            import chromadb
            from chromadb.config import Settings
            client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
            if create:
                return client.get_or_create_collection(name, metadata={'hnsw:space':'cosine'}, embedding_function=None)
            return client.get_collection(name, embedding_function=None)
        except Exception as exc:
            raise RetrievalError('Persistent vector index unavailable. Check Chroma dependencies, path and permissions.') from exc

    def candidates(self, org, filters=None):
        filters = filters or {}
        ids = filters.get('document_ids')
        if ids:
            docs = [self.store.describe(self.store.get_metadata(i, org)) for i in dict.fromkeys(ids)]
        else:
            docs = self.store.list(org)
        matched = []
        for doc in docs:
            meta = doc['metadata']
            if filters.get('kind') and doc['kind'] != filters['kind']:
                continue
            if filters.get('family_id') and doc['family_id'] != filters['family_id']:
                continue
            if any(filters.get(key) and meta[key]['value'] != filters[key] for key in ('regulator','document_type','version')):
                continue
            matched.append(doc)
        chunks = []
        for doc in matched:
            for chunk in self.store.chunks(doc['id'], org):
                if not chunk['content'].strip():
                    continue
                chunks.append({**chunk, 'family_id':doc['family_id'], 'version_id':doc['id'], 'version':doc['metadata']['version'], 'metadata':doc['metadata'], 'kind':doc['kind'], 'organization':doc['organization'], 'visibility':doc.get('visibility'), 'content_hash':doc['content_hash'], 'pdf_reference':f"/api/documents/{doc['id']}/pdf#page={chunk['page']}"})
        return matched, chunks

    def ready(self, docs, chunks):
        manifest = self.manifest()
        if manifest['config'] != self.config():
            raise RetrievalError('Embedding/index configuration changed. Run index_cli rebuild; existing vectors cannot be mixed.')
        for doc in docs:
            expected = inventory([c for c in chunks if c['document_id'] == doc['id']])
            if manifest['documents'].get(doc['id']) != expected:
                raise RetrievalError('Selected documents are not fully indexed. Run: .venv/bin/python -m backend.app.index_cli sync')
        return manifest

    def validate_vectors(self, manifest, chunks):
        collection = self.collection(manifest['collection'])
        try:
            for start in range(0, len(chunks), 200):
                expected = {c['id'] for c in chunks[start:start+200]}
                found = set(collection.get(ids=sorted(expected), include=[])['ids'])
                if expected != found:
                    raise RetrievalError('Vector index is incomplete; run index_cli rebuild')
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError('Vector index could not be checked; inspect storage and rebuild') from exc
        return collection

    def status(self, org):
        docs, chunks = self.candidates(org)
        if not docs:
            return {'state':'empty', 'accessible_documents':0, 'indexed_documents':0, 'instruction':'Upload/import a searchable PDF to begin.'}
        try:
            manifest = self.manifest()
            if manifest['config'] != self.config():
                raise RetrievalError('Index configuration mismatch; run index_cli rebuild')
            self.validate_vectors(manifest, [c for c in chunks if c['document_id'] in manifest['documents']])
            ready = sum(manifest['documents'].get(d['id']) == inventory([c for c in chunks if c['document_id']==d['id']]) for d in docs)
            return {'state':'ready' if ready==len(docs) else 'pending', 'accessible_documents':len(docs), 'indexed_documents':ready}
        except RetrievalError as exc:
            return {'state':'unavailable', 'accessible_documents':len(docs), 'instruction':str(exc)}

    def search(self, question, org, filters=None, mode='hybrid', limit=6):
        if mode not in ('bm25','semantic','hybrid') or not question.strip():
            raise ValueError('Specify a nonempty query and bm25, semantic or hybrid mode')
        docs, chunks = self.candidates(org, filters)
        if not chunks:
            return {'mode':mode, 'results':[], 'message':'No accessible matching evidence. Upload/import documents or adjust filters.'}
        lexical, semantic, unindexed, message = [], [], [], None
        if mode in ('bm25','hybrid'):
            corpus = [tokens(c['content']) for c in chunks]
            query = tokens(question)
            if any(corpus) and query:
                scores = BM25Okapi(corpus).get_scores(query)
                lexical = [chunks[i]['id'] for i in sorted(range(len(chunks)), key=lambda i:(-scores[i],chunks[i]['id'])) if set(query) & set(corpus[i])][:20]
        if mode in ('semantic','hybrid'):
            if (filters or {}).get('document_ids'):
                # Explicitly selected versions (as AI generation uses) must all be
                # indexed; answering from a silent subset would mislead the reviewer.
                manifest = self.ready(docs, chunks)
                indexed_docs, indexed_chunks = docs, chunks
            else:
                manifest, indexed_docs, unindexed = self.indexed_subset(docs, chunks)
                indexed_ids = {d['id'] for d in indexed_docs}
                indexed_chunks = [c for c in chunks if c['document_id'] in indexed_ids]
                if unindexed:
                    message = (f'{len(unindexed)} document(s) are not yet indexed and were searched by keyword only'
                               if mode == 'hybrid' else f'{len(unindexed)} document(s) are not yet indexed and were not searched')
                    message += '. An administrator can run index sync to include them.'
            if indexed_chunks:
                semantic = self.semantic_ranking(question, manifest, indexed_docs, indexed_chunks)
        allowed = {c['id']:c for c in chunks}
        semantic = [i for i in semantic if i in allowed]
        ranking = rrf(lexical, semantic) if mode=='hybrid' else rrf(lexical if mode=='bm25' else semantic)
        return {'mode':mode, 'results':[{**allowed[i], 'score':score} for i,score in ranking[:limit]], 'message':message,
                'unindexed_documents':unindexed}

    def indexed_subset(self, docs, chunks):
        """Split documents into those with a current index entry and those without."""
        manifest = self.manifest()
        if manifest['config'] != self.config():
            raise RetrievalError('Embedding/index configuration changed. Run index_cli rebuild; existing vectors cannot be mixed.')
        indexed, unindexed = [], []
        for doc in docs:
            expected = inventory([c for c in chunks if c['document_id'] == doc['id']])
            (indexed if manifest['documents'].get(doc['id']) == expected else unindexed).append(doc)
        return manifest, indexed, [d['id'] for d in unindexed]

    def semantic_ranking(self, question, manifest, docs, chunks):
        vector = self.embedder.encode([question])
        if manifest['config'] != self.config():
            raise RetrievalError('Embedding configuration changed during search; retry after rebuilding the index')
        if not vector or len(vector[0]) != manifest.get('dimensions'):
            raise RetrievalError('Query vector dimensions do not match the index; rebuild required')
        collection = self.validate_vectors(manifest, chunks)
        try:
            result = collection.query(query_embeddings=vector, n_results=min(20,len(chunks)), where={'document_id':{'$in':[d['id'] for d in docs]}}, include=['distances'])
            return [identifier for _,identifier in sorted(zip(result['distances'][0], result['ids'][0]), key=lambda pair:(pair[0],pair[1]))]
        except Exception as exc:
            raise RetrievalError('Semantic query failed; inspect index status and rebuild if necessary') from exc
