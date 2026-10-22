import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.main import Metadata, AIRequest, create_app
from backend.app.store import Store
from backend.app.importer import official_url, fetch_pdf
from backend.app.ai import generate
from backend.app.retrieval import Retrieval
from backend.app.index_cli import synchronize
from tests.fixtures.embedding import TestEmbedder


def pdf(*pages):
    with pymupdf.open() as document:
        for content in pages:
            page = document.new_page()
            page.insert_text((40,40),content)
        return document.tobytes()


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('COPILOT_ORG_TOKENS',json.dumps({'alpha':'alpha-secret','beta':'beta-secret'}))
    monkeypatch.setenv('COPILOT_ADMIN_TOKENS',json.dumps({'alpha':'alpha-admin'}))
    app = create_app(str(tmp_path/'test.sqlite'))
    # Synthetic fixtures are explicitly enabled only on this isolated test store.
    app.state.store.allow_synthetic = True
    app.state.retrieval = Retrieval(app.state.store, tmp_path/'chroma', TestEmbedder())
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer alpha-secret'
        yield c


def upload(client,content=None,headers=None,**meta):
    metadata={'title':'SYNTHETIC test regulation','kind':'regulatory','regulator':'RBI',**meta}
    response = client.post('/api/documents/upload', files={'file':('fixture.pdf',content or pdf('SYNTHETIC test rule: record the demo identifier.','SYNTHETIC page two: review the demo register.'),'application/pdf')},data={'metadata':json.dumps(metadata)},headers=headers)
    if response.status_code == 201:
        synchronize(client.app.state.retrieval)
    return response


ADMIN={'Authorization':'Bearer alpha-admin'}


def test_empty_and_auth(client):
    assert client.get('/api/documents').json()['regulatory_empty']
    assert client.get('/api/documents',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.post('/api/ai',json={'task':'qa','question':'demo','document_ids':[]}).status_code==422


def test_metadata_pages_citations_and_persistence(client):
    data=pdf('SYNTHETIC page one: retain demo record.','SYNTHETIC page two: review demo record.')
    response=upload(client,data,version='demo-1')
    assert response.status_code==201,response.text
    doc=response.json()
    assert doc['content_hash']==hashlib.sha256(data).hexdigest()
    assert doc['metadata']['title']['status']=='user_supplied'
    assert doc['metadata']['publication_date']=={'value':None,'status':'unknown'}
    assert doc['metadata']['version']['value']=='demo-1'
    chunks=client.get(f"/api/documents/{doc['id']}/chunks").json()
    assert [c['page'] for c in chunks]==[1,2]
    assert chunks==client.get(f"/api/documents/{doc['id']}/chunks").json()
    valid=client.post('/api/citations/validate',json={'chunk_id':chunks[1]['id'],'quote':'review demo record.'})
    assert valid.status_code==200 and valid.json()['page']==2
    assert client.post('/api/citations/validate',json={'chunk_id':chunks[1]['id'],'quote':'invented quote'}).status_code==422
    assert client.get(f"/api/documents/{doc['id']}/pdf").content==data
    store=client.app.state.store
    reopened=Store(store.engine.url.database,allow_synthetic=True)
    assert reopened.get(doc['id'],'alpha')['content_hash']==doc['content_hash']


def test_versions_compare_and_duplicates(client):
    data=pdf('SYNTHETIC earlier: retain identifier.')
    old=upload(client,data).json()
    new=upload(client,pdf('SYNTHETIC later: retain identifier and demo review date.'),family_id=old['family_id'],version='demo-2').json()
    assert old['id']!=new['id']
    assert len(client.get('/api/documents').json()['documents'])==2
    comparison=client.get('/api/compare',params={'old':old['id'],'new':new['id']})
    assert comparison.status_code==200
    assert '+SYNTHETIC later:' in comparison.json()['diff']
    assert upload(client,data,family_id=old['family_id']).status_code==422
    assert client.get('/api/compare',params={'old':old['id'],'new':old['id']}).status_code==422
    assert upload(client,family_id='does-not-exist').status_code==422
    assert upload(client,family_id=old['family_id'],regulator='SEBI').status_code==422


def test_organization_isolation(client):
    doc=upload(client,kind='internal',regulator=None).json()
    chunks=client.get(f"/api/documents/{doc['id']}/chunks").json()
    client.headers['Authorization']='Bearer beta-secret'
    assert client.get('/api/documents').json()['documents']==[]
    for suffix in ['pdf','chunks']:
        assert client.get(f"/api/documents/{doc['id']}/{suffix}").status_code==404
    assert client.post('/api/citations/validate',json={'chunk_id':chunks[0]['id'],'quote':chunks[0]['content']}).status_code==404
    assert upload(client,kind='internal',regulator=None,family_id=doc['family_id']).status_code==422
    assert client.post('/api/ai',json={'task':'qa','question':'record','document_ids':[doc['id']]}).status_code==404


def test_invalid_pdf_and_ocr(client):
    assert upload(client,b'not a pdf').status_code==422
    assert upload(client,pdf('')).status_code==422
    assert upload(client,b'%PDF-broken').status_code==422
    assert upload(client,publication_date='not-date').status_code==422


def test_production_rejects_synthetic(tmp_path):
    store=Store(tmp_path/'production.sqlite')
    with pytest.raises(ValueError,match='Synthetic'):
        store.ingest(Path('tests/fixtures/synthetic_kyc_sop.pdf').read_bytes(),Metadata(title='SYNTHETIC SOP',kind='internal'), 'alpha')
    assert store.list('alpha')==[]


@pytest.mark.parametrize('url',['http://www.rbi.org.in/a.pdf','https://rbi.org.in.evil.example/a.pdf','https://127.0.0.1/a.pdf','https://evil.example/a.pdf','https://www.sebi.gov.in:8080/a.pdf','https://user@www.sebi.gov.in/a.pdf','https://www.sebi.gov.in/a.pdf#page=1'])
def test_restricted_urls(url):
    with pytest.raises(ValueError): official_url(url)


def test_official_host_validation():
    assert official_url('https://rbidocs.rbi.org.in/a.pdf')=='RBI'
    assert official_url('https://www.sebi.gov.in/a.pdf')=='SEBI'


@pytest.mark.parametrize('status,content_type,expected',[(302,'application/pdf','Redirect'),(403,'text/html','HTTP 403'),(200,'text/html','not served')])
def test_import_restrictions(monkeypatch,status,content_type,expected):
    import backend.app.importer as module
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(status,headers={'Content-Type':content_type},content=b'blocked'))
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    with pytest.raises(ValueError,match=expected): asyncio.run(fetch_pdf('https://www.sebi.gov.in/a.pdf'))


def test_import_verified_source_only(client,monkeypatch):
    import backend.app.main as module
    async def fake_fetch(url): return pdf('SYNTHETIC official-source transport fixture.'),'SEBI'
    monkeypatch.setattr(module,'fetch_pdf',fake_fetch)
    response=client.post('/api/documents/import',json={'url':'https://www.sebi.gov.in/a.pdf','metadata':{'title':'SYNTHETIC import fixture','kind':'regulatory','regulator':'SEBI','publication_date':'2024-01-01'}})
    assert response.status_code==201
    meta=response.json()['metadata']
    assert meta['source_url']['status']=='verified'
    assert meta['regulator']['status']=='verified'
    assert meta['publication_date']['status']=='user_supplied'
    assert meta['title']['status']=='user_supplied'


def test_ai_grounding_and_no_fake_fallback(client,monkeypatch):
    import backend.app.ai as module
    doc=upload(client).json()
    chunk=client.get(f"/api/documents/{doc['id']}/chunks").json()[0]
    original=httpx.AsyncClient
    def response(payload):
        return httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(payload)}}))
    valid={'items':[{'statement':'SYNTHETIC fixture interpretation','citations':[{'chunk_id':chunk['id'],'quote':chunk['content']}]}]}
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=response(valid),**kw))
    body={'task':'qa','question':'record demo identifier','document_ids':[doc['id']]}
    result=client.post('/api/ai',json=body)
    assert result.status_code==200 and result.json()['items'][0]['review_status']=='pending_human_review'
    invalid={'items':[{'statement':'fixture','citations':[{'chunk_id':chunk['id'],'quote':'fabricated'}]}]}
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=response(invalid),**kw))
    assert client.post('/api/ai',json=body).status_code==503
    def unavailable(request): raise httpx.ConnectError('offline')
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(unavailable),**kw))
    result=client.post('/api/ai',json=body)
    assert result.status_code==503 and 'ollama pull' in result.json()['detail']


def test_import_stream_success_and_size_limit(monkeypatch):
    import backend.app.importer as module
    original=httpx.AsyncClient
    data=pdf('SYNTHETIC streaming transport fixture')
    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'application/pdf'},content=data))
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    content,regulator=asyncio.run(fetch_pdf('https://www.rbi.org.in/a.pdf'))
    assert content==data and regulator=='RBI'
    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'application/pdf'},content=b'x'*(20*1024*1024+1)))
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    with pytest.raises(ValueError,match='20 MiB'): asyncio.run(fetch_pdf('https://www.rbi.org.in/a.pdf'))


def test_chunk_offsets_do_not_cross_pages(client):
    data=pdf('SYNTHETIC\n'+'demo line evidence\n'*100,'SYNTHETIC second page evidence')
    doc=upload(client,data).json()
    chunks=client.get(f"/api/documents/{doc['id']}/chunks").json()
    with pymupdf.open(stream=data,filetype='pdf') as document:
        pages=[p.get_text('text',sort=True) for p in document]
    assert len(chunks)>2
    for c in chunks:
        assert c['content']==pages[c['page']-1][c['start_offset']:c['end_offset']]


@pytest.mark.parametrize('task',['comparison','gap_analysis','checklist'])
def test_remaining_ai_workflows(client,monkeypatch,task):
    import backend.app.ai as module
    first=upload(client).json()
    if task=='comparison':
        second=upload(client,pdf('SYNTHETIC changed regulation evidence.'),family_id=first['family_id']).json()
    elif task=='gap_analysis':
        second=upload(client,Path('tests/fixtures/synthetic_kyc_sop.pdf').read_bytes(),kind='internal',regulator=None).json()
    else: second=None
    ids=[first['id']]+([second['id']] if second else [])
    citations=[]
    for identifier in ids:
        chunk=client.get(f'/api/documents/{identifier}/chunks').json()[0]
        citations.append({'chunk_id':chunk['id'],'quote':chunk['content']})
    original=httpx.AsyncClient
    payload={'items':[{'statement':'SYNTHETIC deterministic workflow fixture','assessment':'INSUFFICIENT_EVIDENCE','citations':citations}]}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(payload)}}))
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    response=client.post('/api/ai',json={'task':task,'question':'review demo evidence','document_ids':ids})
    assert response.status_code==200,response.text
    assert len(response.json()['items'][0]['citations'])==len(ids)
    if second:
        payload['items'][0]['citations']=citations[:1]
        assert client.post('/api/ai',json={'task':task,'question':'demo','document_ids':ids}).status_code==503


def test_production_accepts_real_terminology(tmp_path):
    store=Store(tmp_path/'production.sqlite')
    # This remains a synthetic test fixture: it verifies that the ordinary term
    # "synthetic" in financial text is not confused with the demo watermark.
    document=store.ingest(pdf('The term synthetic instrument appears in this test excerpt.'),Metadata(title='Test terminology',kind='regulatory',regulator='RBI'),'alpha')
    assert document['id']


@pytest.mark.parametrize('mode',['ready','missing','offline'])
def test_health_and_interface(client,monkeypatch,mode):
    import backend.app.main as module
    original=httpx.AsyncClient
    def respond(request):
        if mode=='offline': raise httpx.ConnectError('offline')
        return httpx.Response(200,json={'models':[{'name':'qwen3:8b'}] if mode=='ready' else []})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    result=client.get('/api/health')
    assert result.status_code==200
    assert result.json()['ollama']=={'ready':'ready','missing':'model_missing','offline':'unavailable'}[mode]
    assert client.get('/').status_code==200


def test_search_api_filters_status_and_pending(client):
    assert client.get('/api/retrieval/status').json()['state']=='empty'
    doc=upload(client,document_type='direction',version='demo-v1').json()
    body={'query':'record','mode':'hybrid','filters':{'document_ids':[doc['id']],'version':'demo-v1','regulator':'RBI','document_type':'direction'}}
    result=client.post('/api/retrieval/search',json=body)
    assert result.status_code==200 and result.json()['results'][0]['page']==1
    assert client.get('/api/retrieval/status').json()['state']=='ready'
    assert client.post('/api/retrieval/search',json={**body,'limit':1000}).status_code==422
    pending=client.app.state.store.ingest(pdf('SYNTHETIC pending document'),Metadata(title='SYNTHETIC pending',kind='regulatory',regulator='RBI'),'alpha')
    assert client.get('/api/retrieval/status').json()['state']=='pending'
    generation=client.post('/api/ai',json={'task':'qa','question':'pending','document_ids':[pending['id']]})
    assert generation.status_code==503 and 'sync' in generation.json()['detail']
    assert client.post('/api/retrieval/search',json={'query':'pending','mode':'bm25','filters':{'document_ids':[pending['id']]}}).status_code==200


def test_search_and_generation_cannot_use_foreign_policy(client,monkeypatch):
    private=upload(client,kind='internal',regulator=None).json()
    reg=upload(client,headers=ADMIN).json()
    client.headers['Authorization']='Bearer beta-secret'
    result=client.post('/api/retrieval/search',json={'query':'record','mode':'hybrid'})
    assert {c['document_id'] for c in result.json()['results']}=={reg['id']}
    assert client.post('/api/retrieval/search',json={'query':'record','filters':{'document_ids':[private['id']]}}).status_code==404
    assert client.post('/api/ai',json={'task':'gap_analysis','question':'review','document_ids':[reg['id'],private['id']]}).status_code==404


@pytest.mark.parametrize('assessment',['CERTIFIED_COMPLIANT',None,[],{}])
def test_invalid_assessment_rejected(client,monkeypatch,assessment):
    import backend.app.ai as module
    reg=upload(client).json()
    policy=upload(client,kind='internal',regulator=None).json()
    citations=[]
    for document in [reg,policy]:
        chunk=client.get(f"/api/documents/{document['id']}/chunks").json()[0]
        citations.append({'chunk_id':chunk['id'],'quote':chunk['content']})
    original=httpx.AsyncClient
    payload={'items':[{'statement':'SYNTHETIC fixture','assessment':assessment,'citations':citations}]}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'content':json.dumps(payload)}}))
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    response=client.post('/api/ai',json={'task':'gap_analysis','question':'review','document_ids':[reg['id'],policy['id']]})
    assert response.status_code==503 and 'assessment' in response.json()['detail']


def mock_model(monkeypatch, payload, captured=None):
    import backend.app.ai as module
    original=httpx.AsyncClient
    def respond(request):
        if captured is not None: captured.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))


def test_locate_quote_tolerates_whitespace_and_typography():
    from backend.app.store import locate_quote
    content='   The  regulated entity\n      shall   carry out “periodic updation” of KYC–records.\n'
    assert locate_quote(content,'The regulated entity shall carry out')=='The  regulated entity\n      shall   carry out'
    assert locate_quote(content,'carry out "periodic updation" of KYC-records.')=='carry out “periodic updation” of KYC–records.'
    with pytest.raises(ValueError,match='at least'): locate_quote(content,'KYC')
    with pytest.raises(ValueError,match='excerpt'): locate_quote(content,'shall not carry out periodic updation')
    with pytest.raises(ValueError,match='nonempty'): locate_quote(content,'   \n ')
    # A very short chunk can still be quoted in full.
    assert locate_quote('  Short.\n','Short.')=='Short.'


def test_citation_api_returns_original_span(client):
    doc=upload(client,pdf('SYNTHETIC rule:   retain   the demo identifier.')).json()
    chunk=client.get(f"/api/documents/{doc['id']}/chunks").json()[0]
    result=client.post('/api/citations/validate',json={'chunk_id':chunk['id'],'quote':'rule: retain the demo identifier.'})
    assert result.status_code==200,result.text
    assert result.json()['quote'] in chunk['content']


def test_ai_keeps_valid_items_and_reports_rejected(client,monkeypatch):
    doc=upload(client,pdf('SYNTHETIC rule:   retain   the demo identifier for five years.')).json()
    chunk=client.get(f"/api/documents/{doc['id']}/chunks").json()[0]
    payload={'items':[
        {'statement':'SYNTHETIC retention','citations':[{'chunk_id':chunk['id'],'quote':'retain the demo identifier for five years.'}]},
        {'statement':'SYNTHETIC invented','citations':[{'chunk_id':chunk['id'],'quote':'destroy the identifier immediately'}]},
        {'statement':'SYNTHETIC wrong chunk','citations':[{'chunk_id':'not-provided','quote':'retain the demo identifier'}]},
        'not an object']}
    captured=[]
    mock_model(monkeypatch,payload,captured)
    response=client.post('/api/ai',json={'task':'qa','question':'retain identifier','document_ids':[doc['id']]})
    assert response.status_code==200,response.text
    result=response.json()
    assert [i['statement'] for i in result['items']]==['SYNTHETIC retention']
    assert result['items'][0]['citations'][0]['quote'] in chunk['content']
    assert [r['index'] for r in result['rejected_items']]==[1,2,3]
    assert 'source validation' in result['rejected_items'][0]['reason']
    assert 'not provided' in result['rejected_items'][1]['reason']
    assert '3 model item(s) were rejected' in result['limitations']
    # Request shape: context window set, evidence compact and whitespace-collapsed.
    request=captured[0]
    assert request['options']['num_ctx']==16384
    prompt=json.loads(request['messages'][1]['content'])
    evidence=prompt['evidence'][0]
    assert set(evidence)=={'chunk_id','document_id','page','text'}
    assert '  ' not in evidence['text'] and '\n' not in evidence['text']
    assert prompt['documents'][0]['metadata']['title']=='SYNTHETIC test regulation'


def test_ai_num_ctx_is_configurable(client,monkeypatch):
    monkeypatch.setenv('OLLAMA_NUM_CTX','32768')
    doc=upload(client).json()
    chunk=client.get(f"/api/documents/{doc['id']}/chunks").json()[0]
    captured=[]
    mock_model(monkeypatch,{'items':[{'statement':'SYNTHETIC','citations':[{'chunk_id':chunk['id'],'quote':chunk['content']}]}]},captured)
    assert client.post('/api/ai',json={'task':'qa','question':'record','document_ids':[doc['id']]}).status_code==200
    assert captured[0]['options']['num_ctx']==32768


def test_fit_budget_trims_weakest_evidence_per_document():
    from backend.app.ai import fit_budget, SYSTEM_PROMPT
    evidence=[{'chunk_id':f'{d}-{r}','document_id':d,'page':1,'text':'x'*1200} for d in 'abcd' for r in range(6)]
    prompt={'task':'qa','question':'q','stored_page_differences':None,'documents':[],'evidence':evidence,'output_schema':{}}
    notes=fit_budget(prompt,12000)
    assert len(SYSTEM_PROMPT)+len(json.dumps(prompt))<=12000
    kept=prompt['evidence']
    assert {e['document_id'] for e in kept}==set('abcd')
    # The highest-ranked chunk of every document survives.
    assert {f'{d}-0' for d in 'abcd'} <= {e['chunk_id'] for e in kept}
    assert any('omitted' in n for n in notes)
    # Budget too small even with one chunk each: keep one per document and say so.
    prompt['evidence']=[{'chunk_id':f'{d}-0','document_id':d,'page':1,'text':'x'*5000} for d in 'abcd']
    notes=fit_budget(prompt,8000)
    assert len(prompt['evidence'])==4 and any('OLLAMA_NUM_CTX' in n for n in notes)


def test_fit_budget_caps_page_differences():
    from backend.app.ai import fit_budget
    differences=[{'physical_page':i,'diff':'y'*3000} for i in range(1,11)]
    prompt={'task':'comparison','question':'q','stored_page_differences':differences,'documents':[],'evidence':[],'output_schema':{}}
    notes=fit_budget(prompt,15000)
    assert 1<=len(prompt['stored_page_differences'])<10
    assert len(json.dumps(prompt['stored_page_differences']))<=5000
    assert any('page difference' in n for n in notes)


def test_gap_item_needs_one_regulatory_and_one_internal_not_every_document(client,monkeypatch):
    first=upload(client,pdf('SYNTHETIC rule one: verify the demo identity record.')).json()
    second=upload(client,pdf('SYNTHETIC rule two: review the demo register annually.')).json()
    policy=upload(client,pdf('SYNTHETIC policy: staff verify the demo identity record.'),kind='internal',regulator=None).json()
    quote=lambda d:client.get(f"/api/documents/{d['id']}/chunks").json()[0]['content']
    cite=lambda d:{'chunk_id':client.get(f"/api/documents/{d['id']}/chunks").json()[0]['id'],'quote':quote(d)}
    payload={'items':[
        {'statement':'SYNTHETIC addressed','assessment':'APPEARS_ADDRESSED','citations':[cite(first),cite(policy)]},
        {'statement':'SYNTHETIC regulatory only','assessment':'POTENTIAL_GAP','citations':[cite(second)]}]}
    mock_model(monkeypatch,payload)
    response=client.post('/api/ai',json={'task':'gap_analysis','question':'review','document_ids':[first['id'],second['id'],policy['id']]})
    assert response.status_code==200,response.text
    result=response.json()
    assert [i['statement'] for i in result['items']]==['SYNTHETIC addressed']
    assert 'regulatory and one internal' in result['rejected_items'][0]['reason']


def test_qa_reports_ignored_internal_documents(client,monkeypatch):
    reg=upload(client).json()
    policy=upload(client,kind='internal',regulator=None).json()
    chunk=client.get(f"/api/documents/{reg['id']}/chunks").json()[0]
    captured=[]
    mock_model(monkeypatch,{'items':[{'statement':'SYNTHETIC','citations':[{'chunk_id':chunk['id'],'quote':chunk['content']}]}]},captured)
    response=client.post('/api/ai',json={'task':'qa','question':'record','document_ids':[reg['id'],policy['id']]})
    assert response.status_code==200,response.text
    assert any('internal document' in n for n in response.json()['notes'])
    prompt=json.loads(captured[0]['messages'][1]['content'])
    assert {e['document_id'] for e in prompt['evidence']}=={reg['id']}


def test_ai_disables_thinking_and_honours_chunk_limit(client,monkeypatch):
    monkeypatch.setenv('AI_CHUNKS_PER_DOCUMENT','1')
    import backend.app.ai as module
    doc=upload(client).json()
    captured=[]
    original=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content); captured.append(body)
        sent=json.loads(body['messages'][1]['content'])['evidence'][0]
        payload={'items':[{'statement':'SYNTHETIC','citations':[{'chunk_id':sent['chunk_id'],'quote':sent['text']}]}]}
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    response=client.post('/api/ai',json={'task':'qa','question':'record review','document_ids':[doc['id']]})
    assert response.status_code==200,response.text
    assert captured[0]['think'] is False
    assert len(json.loads(captured[0]['messages'][1]['content'])['evidence'])==1
    assert response.json()['evidence_excerpts']==1 and response.json()['generation_seconds']>=0


@pytest.mark.parametrize('failure,expected',[
    ('timeout','did not finish within'),
    ('connect','Cannot reach Ollama'),
    ('memory','model requires more system memory'),
    ('missing','ollama pull'),
    ('thinking','did not return valid JSON'),
    ('empty','no evidence items')])
def test_ai_reports_specific_ollama_failures(client,monkeypatch,failure,expected):
    import backend.app.ai as module
    doc=upload(client).json()
    original=httpx.AsyncClient
    def respond(request):
        if failure=='timeout': raise httpx.ReadTimeout('slow')
        if failure=='connect': raise httpx.ConnectError('refused')
        if failure=='memory': return httpx.Response(500,json={'error':'model requires more system memory (9.1 GiB) than is available (6.0 GiB)'})
        if failure=='missing': return httpx.Response(404,json={'error':'model "qwen3:8b" not found'})
        if failure=='thinking': return httpx.Response(200,json={'message':{'content':'<think>hmm','thinking':'...'}})
        return httpx.Response(200,json={'message':{'content':'{\n\n}'}})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    response=client.post('/api/ai',json={'task':'qa','question':'record','document_ids':[doc['id']]})
    assert response.status_code==503
    assert expected in response.json()['detail'],response.json()['detail']


def test_tenant_regulatory_upload_is_private_until_admin(client):
    tenant=upload(client,pdf('SYNTHETIC tenant copy of a circular.')).json()
    assert tenant['organization']=='alpha' and tenant['visibility']=='organization'
    shared=upload(client,pdf('SYNTHETIC administrator circular.'),headers=ADMIN).json()
    assert shared['organization'] is None and shared['visibility']=='shared'
    client.headers['Authorization']='Bearer beta-secret'
    visible={d['id'] for d in client.get('/api/documents').json()['documents']}
    assert visible=={shared['id']}
    assert client.get(f"/api/documents/{tenant['id']}/chunks").status_code==404
    found=client.post('/api/retrieval/search',json={'query':'circular','mode':'bm25'}).json()['results']
    assert {c['document_id'] for c in found}=={shared['id']} and found[0]['visibility']=='shared'
    # Tenants cannot add versions to a shared family; administrators can.
    response=upload(client,pdf('SYNTHETIC tenant revision.'),family_id=shared['family_id'])
    assert response.status_code==422 and 'only an administrator' in response.json()['detail']
    client.headers['Authorization']='Bearer alpha-secret'
    assert upload(client,pdf('SYNTHETIC admin revision.'),family_id=shared['family_id'],headers=ADMIN).status_code==201


def test_admin_token_still_identifies_its_organization(client):
    policy=upload(client,kind='internal',regulator=None,headers=ADMIN).json()
    assert policy['organization']=='alpha'
    assert client.get(f"/api/documents/{policy['id']}/chunks").status_code==200


def test_import_is_shared(client,monkeypatch):
    import backend.app.main as module
    async def fake_fetch(url): return pdf('SYNTHETIC official import.'),'SEBI'
    monkeypatch.setattr(module,'fetch_pdf',fake_fetch)
    response=client.post('/api/documents/import',json={'url':'https://www.sebi.gov.in/a.pdf','metadata':{'title':'SYNTHETIC import','kind':'regulatory','regulator':'SEBI'}})
    assert response.json()['visibility']=='shared'


def test_family_errors_do_not_reveal_foreign_families(client):
    private=upload(client,kind='internal',regulator=None).json()
    client.headers['Authorization']='Bearer beta-secret'
    foreign=upload(client,kind='internal',regulator=None,family_id=private['family_id']).json()['detail']
    missing=upload(client,kind='internal',regulator=None,family_id='does-not-exist').json()['detail']
    assert foreign==missing


def test_malformed_token_configuration_fails_at_startup(tmp_path,monkeypatch):
    monkeypatch.setenv('COPILOT_ORG_TOKENS','{team: token}')
    with pytest.raises(RuntimeError,match='COPILOT_ORG_TOKENS must be JSON'):
        create_app(str(tmp_path/'bad.sqlite'))


def test_inserted_page_is_one_change_not_every_later_page():
    from backend.app.compare import diff_hunks
    old=[f'Paragraph {i}: rule text for page {i}.' for i in range(1,6)]
    new=old[:1]+['Paragraph X: newly inserted page.']+old[1:]
    hunks=diff_hunks(old,new)
    assert len(hunks)==1
    assert hunks[0]['change']=='added' and hunks[0]['new_pages']==[2,2] and hunks[0]['added']==['Paragraph X: newly inserted page.']
    changed=diff_hunks(old,old[:2]+['Paragraph 3: amended rule text.']+old[3:])
    assert len(changed)==1 and changed[0]['change']=='modified' and changed[0]['old_pages']==changed[0]['new_pages']==[3,3]
    # Whitespace-only differences are not changes.
    assert diff_hunks(['A  rule\n   text  '],['A rule\ntext'])==[]


def test_version_order_uses_dates_then_upload_time():
    from backend.app.compare import order_versions
    def doc(i,uploaded,effective=None,published=None):
        return {'id':i,'uploaded_at':uploaded,'metadata':{'effective_date':{'value':effective},'publication_date':{'value':published}}}
    later=doc('b','2026-01-01',effective='2025-06-01'); earlier=doc('a','2026-02-01',effective='2024-04-01')
    assert order_versions(later,earlier)==(earlier,later,True)
    assert order_versions(earlier,later)==(earlier,later,False)
    # Without dates on both, upload time decides.
    assert order_versions(doc('x','2026-03-01',published='2020-01-01'),doc('y','2026-01-01'))[2] is True


def test_compare_api_orders_versions_and_lists_changes(client):
    old=upload(client,pdf('SYNTHETIC rule one.','SYNTHETIC rule two.'),version='v1',effective_date='2024-01-01').json()
    new=upload(client,pdf('SYNTHETIC rule one.','SYNTHETIC inserted rule.','SYNTHETIC rule two.'),family_id=old['family_id'],version='v2',effective_date='2025-01-01').json()
    result=client.get('/api/compare',params={'old':new['id'],'new':old['id']}).json()
    assert result['reordered'] is True and result['old']['id']==old['id']
    assert result['changes']==[{'change':'added','old_pages':[1,1],'new_pages':[2,2],'removed_lines':0,'added_lines':1}]
    assert '+SYNTHETIC inserted rule.' in result['diff'] and 'evidence' not in result


def test_ai_comparison_sends_aligned_changes_older_first(client,monkeypatch):
    old=upload(client,pdf('SYNTHETIC rule one: verify identity.','SYNTHETIC rule two: review register.'),effective_date='2024-01-01').json()
    new=upload(client,pdf('SYNTHETIC rule one: verify identity.','SYNTHETIC inserted rule: retain records.','SYNTHETIC rule two: review register.'),family_id=old['family_id'],effective_date='2025-01-01').json()
    import backend.app.ai as module
    captured=[]
    original=httpx.AsyncClient
    def respond(request):
        body=json.loads(request.content); captured.append(body)
        prompt=json.loads(body['messages'][1]['content'])
        by_doc={}
        for e in prompt['evidence']: by_doc.setdefault(e['document_id'],e)
        payload={'items':[{'statement':'SYNTHETIC change','citations':[{'chunk_id':e['chunk_id'],'quote':e['text']} for e in by_doc.values()]}]}
        return httpx.Response(200,json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    response=client.post('/api/ai',json={'task':'comparison','question':'what changed','document_ids':[new['id'],old['id']]})
    assert response.status_code==200,response.text
    prompt=json.loads(captured[0]['messages'][1]['content'])
    assert [d['id'] for d in prompt['documents']]==[old['id'],new['id']]
    assert len(prompt['stored_page_differences'])==1 and prompt['stored_page_differences'][0]['new_pages']==[2,2]
    # The changed page of the newer version is in the evidence.
    assert any(e['document_id']==new['id'] and e['page']==2 for e in prompt['evidence'])
    assert any('ordered by date' in n for n in response.json()['notes'])


def test_importing_main_does_not_create_app_or_data(tmp_path,monkeypatch):
    import importlib, sys
    monkeypatch.chdir(tmp_path)
    sys.modules.pop('backend.app.main',None)
    module=importlib.import_module('backend.app.main')
    assert 'app' not in vars(module)
    assert not (tmp_path/'data').exists()


def test_defaults_resolve_from_repository_root(monkeypatch):
    from backend.app import paths
    monkeypatch.delenv('COPILOT_DB',raising=False)
    assert paths.corpus_path()==paths.REPO_ROOT/'data'/'corpus.sqlite3'
    assert paths.FRONTEND_INDEX.exists()
    monkeypatch.setenv('COPILOT_DB','custom.sqlite3')
    assert str(paths.corpus_path())=='custom.sqlite3'


def test_frontend_served_from_any_working_directory(client,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert client.get('/').status_code==200


def test_admin_index_sync_runs_in_server(client):
    store=client.app.state.store
    doc=store.ingest(pdf('SYNTHETIC unindexed identity rule.'),Metadata(title='SYNTHETIC pending',kind='regulatory',regulator='RBI'),'alpha')
    assert client.get('/api/retrieval/status').json()['state']=='unavailable'  # no index built yet
    assert client.post('/api/admin/index/sync').status_code==403
    started=client.post('/api/admin/index/sync',headers=ADMIN)
    assert started.status_code==202
    import time
    for _ in range(100):
        job=client.get('/api/admin/index/sync',headers=ADMIN).json()
        if job['state']!='running': break
        time.sleep(0.05)
    assert job['state']=='complete',job
    assert client.get('/api/retrieval/status').json()['state']=='ready'
    assert client.post('/api/retrieval/search',json={'query':'identity','mode':'semantic','filters':{'document_ids':[doc['id']]}}).status_code==200
