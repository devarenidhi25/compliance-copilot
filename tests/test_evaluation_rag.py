import asyncio

import pytest

from backend.app.index_cli import synchronize
from backend.app.main import Metadata
from backend.app.retrieval import Retrieval
from backend.app.store import Store
from evaluation.harness.cag import evaluate_cag_layer, measure_context_budget
from evaluation.harness.rag import SMOKE_TEXT, _pdf, evaluate_rag
from tests.fixtures.embedding import TestEmbedder


@pytest.fixture
def rag_env(tmp_path):
    store = Store(tmp_path / 'corpus.sqlite', allow_synthetic=True)
    retrieval = Retrieval(store, tmp_path / 'chroma', TestEmbedder())
    doc = store.ingest(
        _pdf(SMOKE_TEXT),
        Metadata(title='SYNTHETIC RAG eval', kind='regulatory', regulator='RBI'),
        'alpha',
    )
    synchronize(retrieval)
    return store, retrieval, 'alpha', doc['id']


def test_rag_mock_acceptance(rag_env):
    store, retrieval, org, doc_id = rag_env
    payload = {
        'items': [
            {
                'statement': 'Retention applies.',
                'citations': [{'chunk_id': '__FIRST__', 'quote': 'retaining the demo identifier for five years'}],
            },
            {
                'statement': 'Fabricated.',
                'citations': [{'chunk_id': '__FIRST__', 'quote': 'destroy all identifiers immediately'}],
            },
        ]
    }
    result, report = asyncio.run(
        evaluate_rag(store, retrieval, org, doc_id, 'retain identifier', payload, mock=True),
    )
    assert report['items_accepted'] == 1
    assert report['items_rejected'] == 1
    assert report['citation_acceptance_rate'] == 0.5
    assert result['items'][0]['statement'] == 'Retention applies.'


def test_context_budget(rag_env):
    store, retrieval, org, doc_id = rag_env
    metrics = measure_context_budget(store, retrieval, org, doc_id, 'retain identifier')
    assert metrics['context_chars_after_budget'] <= metrics['context_chars_before_budget']


def test_cag_focus_layer(rag_env):
    store, retrieval, org, doc_id = rag_env
    payload = {
        'items': [
            {
                'statement': 'Retention applies.',
                'citations': [{'chunk_id': '__FIRST__', 'quote': 'retaining the demo identifier for five years'}],
            }
        ]
    }
    rag_result, _ = asyncio.run(
        evaluate_rag(store, retrieval, org, doc_id, 'retain identifier', payload, mock=True),
    )
    focus_payload = {
        'answer': 'Retain the demo identifier for five years.',
        'highlights': ['five years'],
        'items': [{'index': 0, 'label': 'five years', 'key_phrases': ['demo identifier for five years']}],
    }
    metrics = evaluate_cag_layer(rag_result, 'retain identifier', focus_payload)
    assert metrics['focus_success'] is True
    assert metrics['highlights_kept'] >= 1
