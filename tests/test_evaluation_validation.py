import json
from pathlib import Path

import pytest

from evaluation.harness.validation import load_suite, run_case, run_suite, summary
from backend.app.store import Store


SUITE = Path('evaluation/fixtures/validation/suite.json')


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'corpus.sqlite', allow_synthetic=True)


def test_load_suite():
    suite = load_suite(SUITE)
    assert len(suite['cases']) >= 5


def test_run_suite_all_pass(store):
    report = run_suite(store, SUITE)
    assert report['summary']['failed'] == 0
    assert 'ok' in summary(report)


def test_run_case_detects_bad_expectation(store):
    case = {
        'id': 'should_fail',
        'task': 'qa',
        'organization': 'alpha',
        'documents': [
            {
                'kind': 'regulatory',
                'title': 'SYNTHETIC validation reg',
                'pages': ['The SYNTHETIC identity requirement must be verified annually by staff.'],
            }
        ],
        'item': {
            'statement': 'Wrong expectation.',
            'citations': [{'chunk_index': 0, 'quote': 'SYNTHETIC identity requirement must be verified annually by staff'}],
        },
        'expect_pass': False,
        'reason_contains': 'not provided',
    }
    case['allowed_chunk_indices'] = []
    row = run_case(store, case)
    assert row['passed'] is True
    assert row['accepted'] is False


def test_cli_suite_file_integrity():
    data = json.loads(SUITE.read_text(encoding='utf-8'))
    for case in data['cases']:
        assert case.get('id') and 'expect_pass' in case
