"""Context-layer evaluation: prompt budget and validated focus."""
import argparse
import json
import os
from unittest.mock import patch

import httpx

from backend.app.ai import SYSTEM_PROMPT, compact, fit_budget, select_evidence, settings as ai_settings
from backend.app.cag import apply_context_layer
from backend.app.main import AIRequest

from evaluation.metrics.cag import context_budget_metrics, focus_metrics

REPORT_SCHEMA = 'evaluation/schemas/rag_report.v1.json'


def measure_context_budget(store, retrieval, org, document_id, question):
    config = ai_settings()
    chunks = select_evidence(retrieval, [document_id], org, question, config['chunks_per_document'])
    docs = [store.get_metadata(document_id, org)]
    prompt = {
        'task': 'qa',
        'question': question,
        'stored_page_differences': None,
        'documents': [{'id': d['id'], 'kind': d['kind'], 'metadata': {}} for d in docs],
        'evidence': [compact(c) for c in chunks],
        'output_schema': {'items': []},
    }
    before = len(SYSTEM_PROMPT) + len(json.dumps(prompt))
    fit_budget(prompt, config['prompt_chars'])
    after = len(SYSTEM_PROMPT) + len(json.dumps(prompt))
    return context_budget_metrics(before, after, config['prompt_chars'])


def evaluate_cag_layer(rag_result, question, focus_payload):
    """Run apply_context_layer with mocked focus Ollama JSON."""
    payload = json.dumps(focus_payload)

    def respond(request):
        return httpx.Response(200, json={'message': {'content': payload}})

    transport = httpx.MockTransport(respond)
    client = httpx.Client(transport=transport)
    with patch.dict(os.environ, {'AI_FOCUS': 'true'}):
        enriched = apply_context_layer(dict(rag_result), question, client=client)
    client.close()
    return {
        'layer': 'focus_on_verified_statements',
        **focus_metrics(enriched),
        'focus_seconds': enriched.get('focus_seconds'),
    }


def build_cag_report(context_metrics, focus_result):
    return {
        'schema': REPORT_SCHEMA,
        'cag': {**context_metrics, **focus_result},
        'parameters': {'ai_focus': True},
    }


def summary(report):
    cag = report['cag']
    return (
        f'CAG context trimmed={cag.get("context_trimmed")} '
        f'focus_success={cag.get("focus_success")} '
        f'highlights={cag.get("highlights_kept", 0)}'
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description='CAG context-layer evaluation (use tests or experiment runner).')
    parser.add_argument('--report', help='Write JSON report (requires in-process setup)')
    args = parser.parse_args(argv)
    parser.exit('Run via pytest tests/test_evaluation_rag.py or the experiment runner.', 2)


if __name__ == '__main__':
    main()
