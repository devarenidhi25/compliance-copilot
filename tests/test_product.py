"""Tests for the client-facing app API (backend/app/product.py)."""
import json
import threading
import time

import httpx
import pytest

from backend.app.main import Metadata
from backend.app.product import score_gap
from tests.test_pipeline import ADMIN, client, mock_model, pdf, upload  # noqa: F401  (client is a fixture)

PEOPLE = {'X-Copilot-User':'Asha Rao', 'X-Copilot-Role':'compliance_officer'}


def wait(client, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f'/api/app/jobs/{job_id}').json()
        if job['state'] in ('completed', 'failed'):
            return job
        time.sleep(0.05)
    raise AssertionError(f'job did not finish: {job}')


def cite_first_sent(monkeypatch, payload_for=None, seen=None):
    """Mock Ollama: answer with one item citing the first excerpt actually sent."""
    import backend.app.ai as module
    original = httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        prompt = json.loads(body['messages'][1]['content'])
        if seen is not None:
            seen.append(prompt)
        evidence = prompt['evidence']
        payload = payload_for(evidence) if payload_for else {'items':[{'statement':'SYNTHETIC grounded answer',
            'citations':[{'chunk_id':evidence[0]['chunk_id'], 'quote':evidence[0]['text']}]}]}
        return httpx.Response(200, json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))


def test_me_reports_organization_and_admin(client):
    assert client.get('/api/app/me').json() == {'organization':'alpha', 'is_admin':False, 'roles':client.get('/api/app/me').json()['roles']}
    assert client.get('/api/app/me', headers=ADMIN).json()['is_admin'] is True
    assert set(client.get('/api/app/me').json()['roles']) == {'compliance_officer', 'legal', 'risk', 'executive'}
    assert client.get('/api/app/me', headers={'Authorization':'Bearer wrong'}).status_code == 401


def test_library_has_page_counts_and_index_state(client):
    store = client.app.state.store
    pending = store.ingest(pdf('SYNTHETIC one.', 'SYNTHETIC two.', 'SYNTHETIC three.'), Metadata(title='SYNTHETIC pending', kind='regulatory', regulator='RBI'), 'alpha')
    library = client.get('/api/app/library').json()
    assert library['index']['state'] == 'unavailable' and library['documents'][0]['indexed'] is False
    assert library['documents'][0]['page_count'] == 3
    indexed = upload(client).json()  # upload() also syncs the index
    library = client.get('/api/app/library').json()
    states = {d['id']:d['indexed'] for d in library['documents']}
    assert states == {pending['id']:True, indexed['id']:True} and library['index']['state'] == 'ready'
    store.ingest(pdf('SYNTHETIC late arrival.'), Metadata(title='SYNTHETIC late', kind='regulatory', regulator='RBI'), 'alpha')
    library = client.get('/api/app/library').json()
    assert library['index']['state'] == 'pending' and sum(not d['indexed'] for d in library['documents']) == 1


def test_qa_job_runs_in_background_and_is_audited(client, monkeypatch):
    doc = upload(client).json()
    cite_first_sent(monkeypatch)
    started = client.post('/api/app/jobs', json={'task':'qa', 'question':'record the demo identifier', 'document_ids':[doc['id']]}, headers=PEOPLE)
    assert started.status_code == 202
    job = wait(client, started.json()['id'])
    assert job['state'] == 'completed' and job['stage'] == 'completed', job
    assert job['result']['items'][0]['review_status'] == 'pending_human_review'
    assert job['result']['audit_id'] == job['audit_id'] and job['audit_id'].startswith('AUD-')
    entries = client.get('/api/app/audit').json()['entries']
    assert entries[0]['id'] == job['audit_id']
    assert entries[0]['user_name'] == 'Asha Rao' and entries[0]['role_label'] == 'Compliance Officer'
    assert entries[0]['status'] == 'completed' and entries[0]['accepted'] == 1 and entries[0]['rejected'] == 0
    assert 'result' not in entries[0]
    detail = client.get(f"/api/app/audit/{job['audit_id']}").json()
    assert detail['result']['items'][0]['statement'] == 'SYNTHETIC grounded answer'
    # Another organization sees neither the job nor its audit entry.
    other = {'Authorization':'Bearer beta-secret'}
    assert client.get(f"/api/app/jobs/{job['id']}", headers=other).status_code == 404
    assert client.get(f"/api/app/audit/{job['audit_id']}", headers=other).status_code == 404
    assert client.get('/api/app/audit', headers=other).json()['entries'] == []


def test_job_reports_honest_stages(client, monkeypatch):
    doc = upload(client).json()
    stages_at_model_call = []
    import backend.app.ai as module
    original = httpx.AsyncClient

    def respond(request):
        jobs = list(client.app.state.job_runner.jobs.values())
        stages_at_model_call.append(jobs[-1]['stage'])
        evidence = json.loads(json.loads(request.content)['messages'][1]['content'])['evidence']
        payload = {'items':[{'statement':'SYNTHETIC', 'citations':[{'chunk_id':evidence[0]['chunk_id'], 'quote':evidence[0]['text']}]}]}
        return httpx.Response(200, json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    job = wait(client, client.post('/api/app/jobs', json={'task':'qa', 'question':'record', 'document_ids':[doc['id']]}).json()['id'])
    assert stages_at_model_call == ['drafting'] and job['state'] == 'completed'


def test_failed_generation_is_reported_and_audited(client, monkeypatch):
    import backend.app.ai as module
    doc = upload(client).json()
    original = httpx.AsyncClient

    def offline(request):
        raise httpx.ConnectError('refused')
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(offline), **kw))
    job = wait(client, client.post('/api/app/jobs', json={'task':'qa', 'question':'record', 'document_ids':[doc['id']]}).json()['id'])
    assert job['state'] == 'failed' and 'Cannot reach Ollama' in job['error'] and job['result'] is None
    entry = client.get('/api/app/audit').json()['entries'][0]
    assert entry['status'] == 'failed' and 'Cannot reach Ollama' in entry['error']


def test_unindexed_selection_fails_with_sync_instruction(client):
    store = client.app.state.store
    doc = store.ingest(pdf('SYNTHETIC never indexed.'), Metadata(title='SYNTHETIC raw', kind='regulatory', regulator='RBI'), 'alpha')
    job = wait(client, client.post('/api/app/jobs', json={'task':'qa', 'question':'never', 'document_ids':[doc['id']]}).json()['id'])
    assert job['state'] == 'failed' and 'index' in job['error'].lower()


def test_submit_validates_access_immediately(client):
    private = upload(client, kind='internal', regulator=None).json()
    other = {'Authorization':'Bearer beta-secret'}
    assert client.post('/api/app/jobs', json={'task':'qa', 'question':'x', 'document_ids':[private['id']]}, headers=other).status_code == 404
    assert client.post('/api/app/jobs', json={'task':'qa', 'question':'x', 'document_ids':[private['id'], private['id']]}).status_code == 422
    assert client.post('/api/app/jobs', json={'task':'summary', 'question':'x', 'document_ids':[private['id']]}).status_code == 422


def test_jobs_run_one_at_a_time_with_queue_position(client, monkeypatch):
    import backend.app.ai as module
    doc = upload(client).json()
    release = threading.Event()
    original = httpx.AsyncClient

    def slow(request):
        release.wait(5)
        evidence = json.loads(json.loads(request.content)['messages'][1]['content'])['evidence']
        payload = {'items':[{'statement':'SYNTHETIC', 'citations':[{'chunk_id':evidence[0]['chunk_id'], 'quote':evidence[0]['text']}]}]}
        return httpx.Response(200, json={'message':{'content':json.dumps(payload)}})
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(slow), **kw))
    body = {'task':'qa', 'question':'record', 'document_ids':[doc['id']]}
    first = client.post('/api/app/jobs', json=body).json()
    second = client.post('/api/app/jobs', json=body).json()
    deadline = time.monotonic() + 5
    while client.get(f"/api/app/jobs/{first['id']}").json()['state'] != 'running' and time.monotonic() < deadline:
        time.sleep(0.02)
    waiting = client.get(f"/api/app/jobs/{second['id']}").json()
    assert waiting['state'] == 'queued' and waiting['queue_position'] == 1
    release.set()
    assert wait(client, first['id'])['state'] == 'completed'
    assert wait(client, second['id'])['state'] == 'completed'


def test_gap_score_and_risk_from_labels():
    result = {'items':[{'assessment':label} for label in
                       ['APPEARS_ADDRESSED', 'PARTIALLY_ADDRESSED', 'POTENTIAL_GAP', 'POSSIBLE_CONFLICT', 'INSUFFICIENT_EVIDENCE']]}
    scored = score_gap(result)
    assert [i['risk'] for i in scored['items']] == ['low', 'medium', 'high', 'high', 'review']
    assert [i['status_label'] for i in scored['items']] == ['Addressed', 'Partially addressed', 'Potential gap', 'Possible conflict', 'Insufficient evidence']
    summary = scored['gap_summary']
    assert summary['score'] == round(100 * 1.5 / 4) == 38
    assert summary['assessed_items'] == 4 and summary['not_assessed_items'] == 1 and summary['high_risk_items'] == 2
    assert score_gap({'items':[{'assessment':'INSUFFICIENT_EVIDENCE'}]})['gap_summary']['score'] is None


def test_gap_job_returns_score(client, monkeypatch):
    regulation = upload(client, pdf('SYNTHETIC rule: verify the demo identity record.'), headers=ADMIN).json()
    policy = upload(client, pdf('SYNTHETIC policy: staff verify the demo identity record.'), kind='internal', regulator=None).json()

    def payload(evidence):
        by_doc = {}
        for item in evidence:
            by_doc.setdefault(item['document_id'], item)
        cites = [{'chunk_id':e['chunk_id'], 'quote':e['text']} for e in by_doc.values()]
        return {'items':[{'statement':'SYNTHETIC addressed', 'assessment':'APPEARS_ADDRESSED', 'citations':cites},
                         {'statement':'SYNTHETIC partial', 'assessment':'PARTIALLY_ADDRESSED', 'citations':cites}]}
    cite_first_sent(monkeypatch, payload_for=payload)
    job = wait(client, client.post('/api/app/jobs', json={'task':'gap_analysis', 'question':'identity verification',
                                                          'document_ids':[regulation['id'], policy['id']]}).json()['id'])
    assert job['state'] == 'completed', job
    assert job['result']['gap_summary']['score'] == 75
    assert [i['risk'] for i in job['result']['items']] == ['low', 'medium']


def test_existing_ai_endpoint_is_unchanged(client, monkeypatch):
    doc = upload(client).json()
    cite_first_sent(monkeypatch)
    response = client.post('/api/ai', json={'task':'qa', 'question':'record', 'document_ids':[doc['id']]})
    assert response.status_code == 200 and 'gap_summary' not in response.json() and 'audit_id' not in response.json()


def test_console_and_app_pages(client):
    assert client.get('/console').status_code == 200 and 'Compliance Copilot' in client.get('/console').text
    assert client.get('/').status_code == 200


def test_compare_returns_changes_with_lines_and_order(client):
    old = upload(client, pdf('SYNTHETIC rule one.', 'SYNTHETIC rule two.'), headers=ADMIN, effective_date='2024-01-01').json()
    new = upload(client, pdf('SYNTHETIC rule one.', 'SYNTHETIC inserted rule.', 'SYNTHETIC rule two.'), headers=ADMIN,
                 family_id=old['family_id'], effective_date='2025-01-01').json()
    result = client.get('/api/app/compare', params={'a':new['id'], 'b':old['id']}).json()
    assert result['reordered'] is True and result['older']['id'] == old['id'] and result['newer']['id'] == new['id']
    assert result['counts'] == {'added':1, 'removed':0, 'modified':0} and result['total_changes'] == 1
    assert result['changes'][0]['added'] == ['SYNTHETIC inserted rule.'] and result['changes'][0]['new_pages'] == [2, 2]
    assert result['changes'][0]['truncated'] is False and 'pdf' not in result['older']
    assert client.get('/api/app/compare', params={'a':old['id'], 'b':old['id']}).status_code == 422
    other = upload(client, pdf('SYNTHETIC unrelated.'), headers=ADMIN).json()
    assert client.get('/api/app/compare', params={'a':old['id'], 'b':other['id']}).status_code == 422


def test_restart_marks_unfinished_audit_entries_interrupted(client, tmp_path):
    from backend.app.main import create_app
    from backend.app.product import record_audit_start
    store = client.app.state.store
    record_audit_start(store, {'audit_id':'AUD-TEST-1', 'created_at':'2026-10-22T10:00:00+00:00', 'organization':'alpha', 'user':'A',
                               'role':None, 'task':'qa', 'question':'cut off', 'document_ids':['x']})
    create_app(store.engine.url.database)  # a restart on the same database
    entry = client.get('/api/app/audit/AUD-TEST-1').json()
    assert entry['status'] == 'failed' and 'server restart' in entry['error']
