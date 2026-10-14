"""Local administrator tooling. No index writes or downloads at app startup."""
import argparse
import fcntl
import json
import os
import uuid
from pathlib import Path

from sqlalchemy import text
from .retrieval import Retrieval, RetrievalError, inventory
from .store import Store


def synchronize(retrieval, rebuild=False):
    retrieval.path.mkdir(parents=True, exist_ok=True)
    with (retrieval.path/'writer.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = retrieval.config()
        old = None
        if (retrieval.path/'manifest.json').exists():
            old = retrieval.manifest()
            if not rebuild and old['config'] != config:
                raise RetrievalError('Configuration mismatch. Use rebuild to create a separate index generation.')
        manifest = {'config':config, 'collection':'copilot-'+uuid.uuid4().hex, 'documents':{}, 'dimensions':None} if rebuild or old is None else json.loads(json.dumps(old))
        collection = retrieval.collection(manifest['collection'], create=True)
        with retrieval.store.engine.connect() as conn:
            documents = [dict(r) for r in conn.execute(text('SELECT id,organization FROM documents')).mappings()]
        for document in documents:
            identifier = document['id']
            _, chunks = retrieval.candidates(document['organization'], {'document_ids':[identifier]})
            digest = inventory(chunks)
            if manifest['documents'].get(identifier) == digest:
                continue
            try:
                for offset in range(0,len(chunks),32):
                    batch = chunks[offset:offset+32]
                    vectors = retrieval.embedder.encode([c['content'] for c in batch])
                    if len(vectors) != len(batch) or not vectors or not vectors[0]:
                        raise RetrievalError('Embedding model returned invalid vectors')
                    dimensions = len(vectors[0])
                    if any(len(v) != dimensions for v in vectors) or manifest['dimensions'] not in (None, dimensions):
                        raise RetrievalError('Embedding dimensions changed; rebuild required')
                    manifest['dimensions'] = dimensions
                    collection.upsert(ids=[c['id'] for c in batch], embeddings=vectors, metadatas=[{'document_id':identifier,'scope':document['organization'] or '__regulatory__','page':c['page']} for c in batch])
            except Exception as exc:
                raise RetrievalError('Indexing failed; corpus preserved and active manifest unchanged. Retry sync or rebuild.') from exc
            manifest['documents'][identifier] = digest
        if config != retrieval.config():
            raise RetrievalError('Embedding configuration changed during indexing; active manifest preserved. Retry rebuild.')
        temporary = retrieval.path/'manifest.pending.json'
        temporary.write_text(json.dumps(manifest,sort_keys=True))
        os.replace(temporary, retrieval.path/'manifest.json')
        return {'documents':len(manifest['documents']), 'collection':manifest['collection']}


def download_model():
    from huggingface_hub import snapshot_download
    model = os.getenv('EMBEDDING_MODEL','BAAI/bge-m3')
    target = Path(os.getenv('EMBEDDING_MODEL_PATH','data/models/bge-m3'))
    target.mkdir(parents=True,exist_ok=True)
    from huggingface_hub import model_info
    revision = model_info(model).sha
    # Resolve/download the exact recorded revision to avoid a moving-main race.
    snapshot_download(model, revision=revision, local_dir=target/'snapshots'/revision, allow_patterns=['*.json','*.txt','*.model','*.safetensors','pytorch_model*.bin'], ignore_patterns=['onnx/*','imgs/*'])
    marker = target/'copilot-model.pending.json'
    marker.write_text(json.dumps({'model':model,'revision':revision}))
    os.replace(marker, target/'copilot-model.json')
    return {'model':model,'revision':revision,'path':str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['download-model','sync','rebuild','status'])
    args = parser.parse_args()
    try:
        if args.command=='download-model':
            result = download_model()
        else:
            retrieval = Retrieval(Store(os.getenv('COPILOT_DB','data/corpus.sqlite3')))
            if args.command=='status':
                result = {'manifest':retrieval.manifest(),'configured':retrieval.config()}
            else:
                result = synchronize(retrieval,rebuild=args.command=='rebuild')
        print(json.dumps(result,indent=2))
    except Exception as exc:
        parser.exit(1, f'{exc}\n')


if __name__=='__main__':
    main()
