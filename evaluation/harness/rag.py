"""End-to-end RAG evaluation with optional mocked Ollama responses."""
import argparse
import asyncio
import json
import os
import gc
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf

from backend.app.ai import generate, settings as ai_settings
from backend.app.index_cli import synchronize
from backend.app.main import AIRequest, Metadata
from backend.app.retrieval import Retrieval
from backend.app.store import Store

from evaluation.harness.cag import build_cag_report, evaluate_cag_layer, measure_context_budget
from evaluation.metrics.rag import build_rag_report

REPORT_SCHEMA = 'evaluation/schemas/rag_report.v1.json'
SMOKE_TEXT = 'SYNTHETIC RAG evaluation requires retaining the demo identifier for five years.'


def _pdf(*pages):
    with pymupdf.open() as document:
        for content in pages:
            page = document.new_page()
            page.insert_text((40, 40), content)
        return document.tobytes()


async def evaluate_rag(store, retrieval, org, document_id, question, model_payload, *, mock=True):
    chunk = store.chunks(document_id, org)[0]
    payload = dict(model_payload)
    if 'items' not in payload:
        payload = {'items': payload}
    for item in payload['items']:
        for citation in item.get('citations', []):
            if citation.get('chunk_id') in (None, '__FIRST__'):
                citation['chunk_id'] = chunk['id']
    body = AIRequest(task='qa', question=question, document_ids=[document_id])
    with patch('backend.app.ai.call_model', new=AsyncMock(return_value=payload)):
        result = await generate(store, body, org, retrieval)
    report = build_rag_report(result, mock=mock)
    report['schema'] = REPORT_SCHEMA
    report['parameters'] = {
        'chunks_per_document': ai_settings()['chunks_per_document'],
        'ollama_num_ctx': ai_settings()['num_ctx'],
        'prompt_chars': ai_settings()['prompt_chars'],
        'ai_focus': os.getenv('AI_FOCUS', 'true').strip().lower() not in ('0', 'false', 'no'),
    }
    return result, report


async def run_mock_smoke():
    from tests.fixtures.embedding import TestEmbedder

    question = 'retain identifier'
    payload = {
        'items': [
            {
                'statement': 'SYNTHETIC retention rule applies.',
                'citations': [{'chunk_id': '__FIRST__', 'quote': 'retaining the demo identifier for five years'}],
            }
        ]
    }
    focus_payload = {
        'answer': 'Retain the demo identifier for five years.',
        'highlights': ['five years'],
        'items': [{'index': 0, 'label': 'five years retention', 'key_phrases': ['demo identifier for five years']}],
    }
    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    store = Store(tmp_path / 'corpus.sqlite', allow_synthetic=True)
    retrieval = Retrieval(store, tmp_path / 'chroma', TestEmbedder())
    try:
        doc = store.ingest(
            _pdf(SMOKE_TEXT),
            Metadata(title='SYNTHETIC RAG eval', kind='regulatory', regulator='RBI'),
            'alpha',
        )
        synchronize(retrieval)
        org = 'alpha'
        rag_result, rag_report = await evaluate_rag(
            store, retrieval, org, doc['id'], question, payload, mock=True,
        )
        context = measure_context_budget(store, retrieval, org, doc['id'], question)
        focus = evaluate_cag_layer(rag_result, question, focus_payload)
        cag_report = build_cag_report(context, focus)
        rag_report['cag'] = cag_report['cag']
        return rag_report
    finally:
        store.engine.dispose()
        retrieval._client = None
        gc.collect()
        shutil.rmtree(tmp, ignore_errors=True)


def summary(report):
    rate = report['citation_acceptance_rate']
    mode = 'mock' if report.get('mock') else 'live'
    cag = report.get('cag', {})
    return (
        f'RAG eval ({mode}) task={report["task"]} '
        f'accepted={report["items_accepted"]}/{report["items_proposed"]} '
        f'citation_rate={rate} '
        f'focus_success={cag.get("focus_success")}'
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description='RAG evaluation harness (mock smoke test by default).')
    parser.add_argument('--report', help='Write JSON report to this path')
    parser.add_argument('--live', action='store_true', help='Call real Ollama (not implemented)')
    args = parser.parse_args(argv)
    if args.live:
        parser.error('Live RAG evaluation is not wired in this CLI; use the product API.')
    report = asyncio.run(run_mock_smoke())
    print(summary(report))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['items_accepted'] < 1:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
