"""Batch validation of AI items against store citation rules (no model calls)."""
import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

import pymupdf

from backend.app.ai import validate_item
from backend.app.main import Metadata
from backend.app.store import Store

REPORT_SCHEMA = 'evaluation/schemas/validation_report.v1.json'
DEFAULT_SUITE = Path(__file__).resolve().parents[1] / 'fixtures' / 'validation' / 'suite.json'


def _pdf(*pages):
    with pymupdf.open() as document:
        for content in pages:
            page = document.new_page()
            page.insert_text((40, 40), content)
        return document.tobytes()


def load_suite(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data.get('cases'), list) or not data['cases']:
        raise ValueError('Validation suite needs a nonempty "cases" list')
    return data


def _ingest_documents(store, case):
    org = case.get('organization', 'alpha')
    doc_records = []
    all_chunks = []
    for index, spec in enumerate(case['documents']):
        meta = Metadata(
            title=spec.get('title', f'SYNTHETIC validation {index}'),
            kind=spec['kind'],
            regulator=spec.get('regulator', 'RBI'),
        )
        doc = store.ingest(_pdf(*spec['pages']), meta, org)
        chunks = store.chunks(doc['id'], org)
        doc_records.append(store.get_metadata(doc['id'], org))
        all_chunks.append(chunks)
    return org, doc_records, all_chunks


def _resolve_chunk(all_chunks, citation_spec):
    doc_index = citation_spec.get('document_index', 0)
    chunk_index = citation_spec['chunk_index']
    return all_chunks[doc_index][chunk_index]['id']


def _materialize_item(case, all_chunks):
    item = json.loads(json.dumps(case['item']))
    for citation in item.get('citations', []):
        citation['chunk_id'] = _resolve_chunk(all_chunks, citation)
        citation.pop('chunk_index', None)
        citation.pop('document_index', None)
    return item


def run_case(store, case):
    org, docs, all_chunks = _ingest_documents(store, case)
    flat_chunks = [chunk for doc_chunks in all_chunks for chunk in doc_chunks]
    if 'allowed_chunk_indices' in case:
        allowed = {
            flat_chunks[i]['id']
            for i in case['allowed_chunk_indices']
            if 0 <= i < len(flat_chunks)
        }
    else:
        allowed = {chunk['id'] for chunk in flat_chunks}
    item = _materialize_item(case, all_chunks)
    try:
        validate_item(item, case['task'], store, org, allowed, docs)
        accepted = True
        reason = None
    except ValueError as exc:
        accepted = False
        reason = str(exc)
    expect_pass = case['expect_pass']
    if expect_pass:
        case_passed = accepted
    else:
        case_passed = not accepted
        if case.get('reason_contains'):
            case_passed = case_passed and case['reason_contains'].lower() in (reason or '').lower()
    return {
        'id': case['id'],
        'passed': case_passed,
        'accepted': accepted,
        'expected_pass': expect_pass,
        'reason': reason,
    }


def run_suite(store, suite_path):
    suite = load_suite(suite_path)
    cases = [run_case(store, case) for case in suite['cases']]
    reasons = Counter(
        row['reason'] for row in cases if row['reason'] and not row['passed']
    )
    passed = sum(1 for row in cases if row['passed'])
    return {
        'schema': REPORT_SCHEMA,
        'suite': str(Path(suite_path)),
        'cases': cases,
        'summary': {
            'passed': passed,
            'failed': len(cases) - passed,
            'reasons': dict(reasons),
        },
    }


def summary(report):
    lines = [
        f'Validation suite: {report["suite"]}',
        f'Cases passed: {report["summary"]["passed"]}/{report["summary"]["passed"] + report["summary"]["failed"]}',
    ]
    for row in report['cases']:
        mark = 'ok' if row['passed'] else 'FAIL'
        detail = '' if row['passed'] else f' — {row.get("reason") or "expectation mismatch"}'
        lines.append(f'  [{mark}] {row["id"]}{detail}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run citation and schema validation fixtures.')
    parser.add_argument('suite', nargs='?', default=str(DEFAULT_SUITE))
    parser.add_argument('--report', help='Write full JSON report to this path')
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'corpus.sqlite', allow_synthetic=True)
            try:
                report = run_suite(store, args.suite)
            finally:
                store.engine.dispose()
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
    print(summary(report))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['summary']['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
