import json
from pathlib import Path

import pytest

from evaluation.run_experiment import load_config, run_experiment


RAG_MOCK = Path('evaluation/experiments/rag_qa_mock.yaml')


def test_load_config():
    config = load_config(RAG_MOCK)
    assert config['experiment_id'] == 'rag_qa_mock'
    assert len(config['steps']) == 2


def test_run_rag_mock_experiment(tmp_path):
    out = tmp_path / 'run'
    manifest, output_dir = run_experiment(RAG_MOCK, output_dir=out)
    assert output_dir == out
    assert manifest['experiment_id'] == 'rag_qa_mock'
    assert (out / 'manifest.json').exists()
    assert all(step['status'] == 'success' for step in manifest['steps'])
    rag_report = json.loads((out / 'rag_cag_mock_smoke.json').read_text(encoding='utf-8'))
    assert rag_report['items_accepted'] >= 1


def test_lodr_retrieval_step_fails_without_corpus(tmp_path):
    manifest, _ = run_experiment('evaluation/experiments/lodr_retrieval.yaml', output_dir=tmp_path)
    assert manifest['steps'][0]['status'] == 'failed'
    assert manifest['steps'][0].get('error')
