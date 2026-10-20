import json
from pathlib import Path

import httpx
import pytest
import pymupdf
from sqlalchemy import text

from backend.app.regulatory_ingest import load_registry, run_ingestion
from backend.app.store import Store


def pdf_bytes(text):
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_text((40,40),text)
        return doc.tobytes()


def registry(tmp_path, urls):
    path=tmp_path/'sources.json'
    path.write_text(json.dumps({'sources':[
        {'id':'pilot','url':urls[0],'regulator':'RBI','category':'master_directions','enabled':True},
        {'id':'disabled','url':'https://www.sebi.gov.in/legal.html','regulator':'SEBI','category':'legal','enabled':False}
    ]}))
    return path


def test_registry_config_and_allowlist(tmp_path):
    configured=load_registry(Path(__file__).parents[1]/'datasets'/'official_sources.json')
    assert len(configured['sources'])==8
    assert {item['id'] for item in configured['sources'] if item['enabled']} == {
        'rbi_notifications','rbi_master_directions','rbi_faqs'}
    assert not any(item['enabled'] for item in configured['sources'] if item['regulator']=='SEBI')
    path=registry(tmp_path,['https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'])
    assert load_registry(path)['sources'][0]['enabled'] is True
    path=registry(tmp_path,['https://example.org/listing'])
    with pytest.raises(ValueError,match='HTTPS PDF URL'):
        load_registry(path)


def test_discovery_pdf_html_duplicates_and_changed_versions(tmp_path):
    listing='''<html><body>
      <a href="/pdf/kyc.pdf">KYC Master Direction 2024-01-01</a>
      <a href="/html/customer-due-diligence.html">Customer Due Diligence FAQ</a>
      <a href="/pdf/unrelated.pdf">Securities settlement circular</a>
      <a rel="next" href="?page=2">Next</a>
    </body></html>'''
    base='https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'
    current_pdf=pdf_bytes('Official test evidence: customer KYC records')
    changed_pdf=pdf_bytes('Updated official test evidence: customer KYC records')
    state={'pdf':current_pdf}
    def handler(request):
        if request.url.path.endswith('BS_ViewMasterDirections.aspx'):
            return httpx.Response(200,headers={'content-type':'text/html'},text=listing)
        if request.url.path.endswith('kyc.pdf'):
            return httpx.Response(200,headers={'content-type':'application/pdf'},content=state['pdf'])
        if request.url.path.endswith('customer-due-diligence.html'):
            return httpx.Response(200,headers={'content-type':'text/html'},text='<h1>Customer identification</h1><p>Official KYC source text.</p>')
        return httpx.Response(404)
    client=httpx.Client(transport=httpx.MockTransport(handler))
    store=Store(tmp_path/'corpus.sqlite3')
    path=registry(tmp_path,[base])
    first=run_ingestion(store,path,client=client,request_delay=0)
    assert first['documents_discovered']==2
    assert first['listing_pages_processed']==2
    assert first['documents_added']==2, (first['failed_urls'], first['extraction_failures'])
    docs=store.list('any-org')
    pdf_doc=next(d for d in docs if d['metadata']['original_format']['value']=='pdf')
    html_doc=next(d for d in docs if d['metadata']['original_format']['value']=='html')
    assert store.get(pdf_doc['id'],'any-org')['pdf']==current_pdf
    assert pdf_doc['metadata']['source_url']['value']=='https://www.rbi.org.in/pdf/kyc.pdf'
    html_chunk=store.chunks(html_doc['id'],'any-org')[0]
    assert html_chunk['section']=='Customer identification'
    citation=store.citation(html_chunk['id'],'Official KYC source text.','any-org')
    assert citation['section']=='Customer identification'
    assert citation['source_url']['value'].endswith('customer-due-diligence.html')
    duplicate=run_ingestion(store,path,client=client,request_delay=0)
    assert duplicate['duplicates_skipped']==2
    state['pdf']=changed_pdf
    updated=run_ingestion(store,path,client=client,request_delay=0)
    assert updated['documents_updated']==1
    assert len([d for d in store.list('any-org') if d['metadata']['source_url']['value'].endswith('kyc.pdf')])==2
    client.close()


def test_listing_failure_unsupported_and_partial_document_failures(tmp_path):
    base='https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'
    listing='''<a href="/kyc/item-one">KYC item one</a>
      <a href="/kyc/item-two">KYC item two</a>'''
    def handler(request):
        if request.url.path.endswith('BS_ViewMasterDirections.aspx'):
            return httpx.Response(200,headers={'content-type':'text/html'},text=listing)
        if request.url.path.endswith('item-one'):
            return httpx.Response(200,headers={'content-type':'application/msword'},content=b'unsupported')
        return httpx.Response(503)
    client=httpx.Client(transport=httpx.MockTransport(handler))
    store=Store(tmp_path/'corpus.sqlite3')
    result=run_ingestion(store,registry(tmp_path,[base]),client=client,request_delay=0)
    assert len(result['unsupported_formats'])==1
    assert result['failed_urls'] and result['failed_urls'][0]['url'].endswith('item-two')
    client.close()


def test_malformed_listing_and_explicit_caps(tmp_path):
    base='https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(
        200,headers={'content-type':'text/html'},text='<html><body>changed page</body></html>')))
    store=Store(tmp_path/'corpus.sqlite3')
    result=run_ingestion(store,registry(tmp_path,[base]),client=client,request_delay=0)
    assert result['failed_urls'][0]['url']==base
    with pytest.raises(ValueError,match='max_listing_pages'):
        run_ingestion(store,registry(tmp_path,[base]),max_listing_pages=6,client=client)
    client.close()


def test_request_timeout_is_reported(tmp_path):
    base='https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'
    def handler(request):
        raise httpx.TimeoutException('mock timeout')
    client=httpx.Client(transport=httpx.MockTransport(handler))
    result=run_ingestion(Store(tmp_path/'corpus.sqlite3'),registry(tmp_path,[base]),client=client,request_delay=0)
    assert result['failed_urls'][0]['reason']
    client.close()


def test_existing_database_gets_additive_section_column(tmp_path):
    import sqlite3
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, page INTEGER NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, content TEXT NOT NULL)')
    store=Store(path)
    with store.engine.connect() as conn:
        columns={row[1] for row in conn.execute(text('PRAGMA table_info(chunks)'))}
    assert 'section' in columns
