import json
import multiprocessing
import time
import pytest
from backend.app.main import Metadata
from backend.app.store import Store
from backend.app.retrieval import Retrieval, RetrievalError, rrf
from backend.app.index_cli import synchronize
from tests.test_pipeline import pdf


from tests.fixtures.embedding import TestEmbedder


def hold_writer_lock(path, acquired, release):
    from backend.app.index_cli import writer_lock
    with writer_lock(path):
        acquired.set()
        release.wait(10)


@pytest.fixture
def retrieval(tmp_path):
    return Retrieval(Store(tmp_path/'corpus.sqlite',allow_synthetic=True),tmp_path/'chroma',TestEmbedder())


def add(r, text='SYNTHETIC identity requirement', **fields):
    meta = Metadata(title='SYNTHETIC fixture',kind='regulatory',regulator='RBI',**fields)
    return r.store.ingest(pdf(text),meta,'alpha')


def test_bm25_and_filters(retrieval):
    a=add(retrieval,'SYNTHETIC identity requirement',version='v1',document_type='direction')
    b=add(retrieval,'SYNTHETIC review register',version='v2',family_id=a['family_id'])
    assert retrieval.search('identity','alpha',mode='bm25')['results'][0]['document_id']==a['id']
    assert retrieval.search('unmatchedword','alpha',mode='bm25')['results']==[]
    assert retrieval.search('identity','alpha',{'version':'v2'},mode='bm25')['results']==[]
    assert retrieval.search('identity','alpha',{'regulator':'SEBI'},mode='bm25')['results']==[]
    assert len(retrieval.search('identity','alpha',{'document_type':'direction','family_id':a['family_id']},mode='bm25')['results'])==1


def test_rrf_deduplicates_and_ties():
    ranking=rrf(['a','a','b'],['b','c','a'])
    assert len(ranking)==3
    assert dict(ranking)['a']==pytest.approx(1/61+1/63)
    assert rrf(['b'],['a'])==[('a',1/61),('b',1/61)]


def test_writer_lock_excludes_other_processes(tmp_path):
    from backend.app.index_cli import writer_lock
    path=tmp_path/'writer.lock'
    acquired=multiprocessing.Event()
    release=multiprocessing.Event()
    process=multiprocessing.Process(target=hold_writer_lock,args=(path,acquired,release))
    process.start()
    try:
        assert acquired.wait(5)
        started=time.monotonic()
        with writer_lock(path):
            assert time.monotonic()-started >= 0.1
        release.set()
        process.join(5)
        assert process.exitcode==0
    finally:
        release.set()
        if process.is_alive():
            process.terminate()
            process.join()


def test_empty_and_missing_model(retrieval,tmp_path):
    assert retrieval.search('identity','alpha')['results']==[]
    add(retrieval)
    with pytest.raises(RetrievalError,match='not built'): retrieval.search('identity','alpha')
    missing=Retrieval(retrieval.store,tmp_path/'missing')
    with pytest.raises(RetrievalError,match='Embedding model missing'): missing.config()


def test_semantic_persistence_idempotence_and_provenance(retrieval):
    a=add(retrieval,'SYNTHETIC identity requirement\nPage one',version='v1')
    b=add(retrieval,'SYNTHETIC review register',version='v2',family_id=a['family_id'])
    synchronize(retrieval)
    manifest=retrieval.manifest()
    count=retrieval.collection(manifest['collection']).count()
    synchronize(retrieval)
    assert retrieval.collection(manifest['collection']).count()==count
    restarted=Retrieval(retrieval.store,retrieval.path,TestEmbedder())
    result=restarted.search('identity','alpha',mode='semantic')['results'][0]
    assert result['document_id']==a['id'] and result['page']==1
    assert result['version_id']==a['id'] and result['family_id']==a['family_id']
    assert retrieval.store.citation(result['id'],result['content'],'alpha')['page']==1
    assert len(restarted.search('review','alpha',mode='hybrid')['results'])==2
    assert restarted.search('identity','alpha',{'version':'v2'},mode='semantic')['results'][0]['document_id']==b['id']


def test_isolation(retrieval):
    a=add(retrieval)
    private=retrieval.store.ingest(pdf('SYNTHETIC private identity review'),Metadata(title='SYNTHETIC policy',kind='internal'),'beta')
    synchronize(retrieval)
    for mode in ('bm25','semantic','hybrid'):
        found=retrieval.search('identity','alpha',mode=mode)['results']
        assert {c['document_id'] for c in found}=={a['id']}
        with pytest.raises(LookupError): retrieval.search('identity','alpha',{'document_ids':[private['id']]},mode=mode)


def test_pending_mismatch_and_atomic_rebuild(retrieval):
    add(retrieval)
    synchronize(retrieval)
    old=retrieval.manifest()
    pending=add(retrieval,'SYNTHETIC second review document')
    assert retrieval.status('alpha')['state']=='pending'
    # Unfiltered search keeps working: the pending document is keyword-searched and reported.
    result=retrieval.search('review','alpha')
    assert result['unindexed_documents']==[pending['id']] and 'not yet indexed' in result['message']
    assert pending['id'] in {c['document_id'] for c in result['results']}
    semantic=retrieval.search('review','alpha',mode='semantic')
    assert pending['id'] not in {c['document_id'] for c in semantic['results']} and semantic['unindexed_documents']==[pending['id']]
    # Explicitly selecting the pending document still fails closed.
    with pytest.raises(RetrievalError,match='not fully indexed'): retrieval.search('review','alpha',{'document_ids':[pending['id']]})
    synchronize(retrieval)
    assert retrieval.search('review','alpha')['unindexed_documents']==[]
    class Changed(TestEmbedder):
        def identity(self): return {'model':'synthetic-test-only','revision':'2'}
    retrieval.embedder=Changed()
    with pytest.raises(RetrievalError,match='configuration changed'): retrieval.search('identity','alpha')
    with pytest.raises(RetrievalError,match='mismatch'): synchronize(retrieval)
    synchronize(retrieval,rebuild=True)
    assert retrieval.manifest()['collection']!=old['collection']
    assert retrieval.search('identity','alpha')['results']
    current=retrieval.manifest()
    class Broken(Changed):
        def encode(self,texts): raise RuntimeError('test-only failure')
    retrieval.embedder=Broken()
    with pytest.raises(RetrievalError,match='Indexing failed'): synchronize(retrieval,rebuild=True)
    assert retrieval.manifest()==current


def test_corrupt_vectors_fail_closed(retrieval):
    add(retrieval)
    synchronize(retrieval)
    collection=retrieval.collection(retrieval.manifest()['collection'])
    identifier=retrieval.store.list('alpha')[0]['id']
    chunk=retrieval.store.chunks(identifier,'alpha')[0]
    collection.delete(ids=[chunk['id']])
    with pytest.raises(RetrievalError,match='incomplete'): retrieval.search('identity','alpha')
    assert retrieval.status('alpha')['state']=='unavailable'
    synchronize(retrieval,rebuild=True)
    assert retrieval.search('identity','alpha')['results']


def test_physical_second_page_and_blank_text(retrieval):
    doc=retrieval.store.ingest(pdf('SYNTHETIC identity requirement','SYNTHETIC review register',''),Metadata(title='SYNTHETIC three-page fixture',kind='regulatory',regulator='RBI'),'alpha')
    synchronize(retrieval)
    result=retrieval.search('review','alpha',{'document_ids':[doc['id']]},mode='semantic')['results'][0]
    assert result['page']==2
    assert '#page=2' in result['pdf_reference']
    assert retrieval.store.citation(result['id'],'review register','alpha')['page']==2


def test_local_embedding_load_is_offline_and_errors_explicitly(tmp_path,monkeypatch):
    from backend.app.retrieval import LocalEmbedder
    import sentence_transformers
    monkeypatch.setenv('EMBEDDING_MODEL_PATH',str(tmp_path))
    (tmp_path/'copilot-model.json').write_text(json.dumps({'model':'BAAI/bge-m3','revision':'test-only'}))
    def broken(*args,**kwargs):
        assert kwargs['local_files_only'] is True and kwargs['trust_remote_code'] is False
        raise RuntimeError('test-only missing weights')
    monkeypatch.setattr(sentence_transformers,'SentenceTransformer',broken)
    with pytest.raises(RetrievalError,match='cannot load'): LocalEmbedder().encode(['identity'])


def test_explicit_model_download_records_exact_snapshot(tmp_path,monkeypatch):
    import huggingface_hub
    from types import SimpleNamespace
    from backend.app.index_cli import download_model
    monkeypatch.setenv('EMBEDDING_MODEL_PATH',str(tmp_path/'model'))
    monkeypatch.setattr(huggingface_hub,'model_info',lambda name:SimpleNamespace(sha='synthetic-revision'))
    calls=[]
    def download(*args,**kwargs):
        calls.append(kwargs)
        return str(kwargs['local_dir'])
    monkeypatch.setattr(huggingface_hub,'snapshot_download',download)
    result=download_model()
    assert result['revision']=='synthetic-revision'
    assert calls[0]['revision']=='synthetic-revision'
    assert calls[0]['local_dir']==tmp_path/'model'/'snapshots'/'synthetic-revision'
    assert json.loads((tmp_path/'model'/'copilot-model.json').read_text())['revision']=='synthetic-revision'
    original=(tmp_path/'model'/'copilot-model.json').read_text()
    def failure(*args,**kwargs): raise RuntimeError('synthetic download failure')
    monkeypatch.setattr(huggingface_hub,'snapshot_download',failure)
    with pytest.raises(RuntimeError): download_model()
    assert (tmp_path/'model'/'copilot-model.json').read_text()==original


def test_model_change_during_search_or_rebuild_fails_closed(retrieval):
    add(retrieval)
    synchronize(retrieval)
    original=retrieval.manifest()
    class Changing(TestEmbedder):
        changed=False
        def identity(self): return {'model':'synthetic-test-only','revision':'2' if self.changed else '1'}
        def encode(self,texts):
            self.changed=True
            return super().encode(texts)
    retrieval.embedder=Changing()
    with pytest.raises(RetrievalError,match='during search'): retrieval.search('identity','alpha')
    retrieval.embedder=Changing()
    with pytest.raises(RetrievalError,match='during indexing'): synchronize(retrieval,rebuild=True)
    assert retrieval.manifest()==original


def test_retrieval_evaluation_reports_hits_and_unavailable_modes(retrieval,tmp_path):
    import hashlib
    from backend.app.eval_cli import evaluate, load_spec, summary
    data=pdf('SYNTHETIC identity requirement','SYNTHETIC review register')
    doc=retrieval.store.ingest(data,Metadata(title='SYNTHETIC eval',kind='regulatory',regulator='RBI'),'alpha')
    path=tmp_path/'questions.json'
    path.write_text(json.dumps({'document':{'content_hash':hashlib.sha256(data).hexdigest()},'k':1,'questions':[
        {'id':'a','question':'review register','expected_pages':[2]},
        {'id':'b','question':'identity requirement','expected_pages':[2]}]}))
    spec=load_spec(path)
    before=evaluate(retrieval,spec,('bm25','semantic'))
    assert before['document_id']==doc['id']
    assert before['modes']['bm25']['hit@1']==0.5 and before['modes']['bm25']['mrr@1']==0.5
    assert before['modes']['semantic']['available'] is False
    synchronize(retrieval)
    after=evaluate(retrieval,spec,('semantic',))
    assert after['modes']['semantic']['available'] is True
    assert 'bm25' in summary(before) and 'unavailable' in summary(before)


def test_evaluation_requires_known_document(retrieval,tmp_path):
    from backend.app.eval_cli import evaluate, load_spec
    path=tmp_path/'q.json'
    path.write_text(json.dumps({'document':{'content_hash':'0'*64},'questions':[{'question':'x','expected_pages':[1]}]}))
    with pytest.raises(LookupError,match='upload it first'): evaluate(retrieval,load_spec(path))
    path.write_text(json.dumps({'document':{},'questions':[{'question':'x','expected_pages':[1]}]}))
    with pytest.raises(ValueError,match='content_hash'): load_spec(path)


def test_bundled_evaluation_file_matches_bundled_pdf():
    import hashlib
    from pathlib import Path
    from backend.app.eval_cli import load_spec
    spec=load_spec(Path('datasets/eval/lodr_master_circular.json'))
    data=Path('datasets/MASTER CIRCULAR_2026_1769776024792.pdf').read_bytes()
    assert spec['document']['content_hash']==hashlib.sha256(data).hexdigest()
    assert all(1<=p<=291 for q in spec['questions'] for p in q['expected_pages'])
