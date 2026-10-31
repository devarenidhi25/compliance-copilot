"""Retrieval evaluation against question files with expected PDF pages."""
import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text

from backend.app.paths import REPO_ROOT, corpus_path
from backend.app.retrieval import Retrieval, RetrievalError
from backend.app.store import Store

from evaluation.metrics.ranking import aggregate_retrieval, first_relevant_rank

MODES = ('bm25', 'semantic', 'hybrid')
DEFAULT_QUESTIONS = REPO_ROOT / 'datasets' / 'eval' / 'lodr_master_circular.json'
REPORT_SCHEMA = 'evaluation/schemas/retrieval_report.v1.json'


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(spec.get('questions'), list) or not spec['questions']:
        raise ValueError('Evaluation file needs a nonempty "questions" list')
    if not (spec.get('document') or {}).get('content_hash'):
        raise ValueError('Evaluation file needs document.content_hash (SHA-256 of the PDF)')
    for item in spec['questions']:
        if not item.get('question') or not item.get('expected_pages'):
            raise ValueError(f'Question {item.get("id")!r} needs question and expected_pages')
    return spec


def find_document(store, content_hash):
    with store.engine.connect() as conn:
        row = conn.execute(
            text('SELECT id, organization FROM documents WHERE content_hash=:h ORDER BY uploaded_at LIMIT 1'),
            {'h': content_hash},
        ).mappings().first()
    if not row:
        raise LookupError('Evaluation document not found in the corpus; upload it first (matched by content hash)')
    return row['id'], row['organization'] or '__evaluation__'


def evaluate(retrieval, spec, modes=MODES, *, questions_file=None):
    document_id, org = find_document(retrieval.store, spec['document']['content_hash'])
    k = int(spec.get('k', 6))
    report = {
        'schema': REPORT_SCHEMA,
        'document_id': document_id,
        'k': k,
        'questions_file': questions_file,
        'models': {
            'embedding': os.getenv('EMBEDDING_MODEL', 'BAAI/bge-m3'),
            'retrieval_modes': list(modes),
        },
        'modes': {},
    }
    for mode in modes:
        rows = []
        try:
            for item in spec['questions']:
                results = retrieval.search(
                    item['question'], org, {'document_ids': [document_id]}, mode=mode, limit=k,
                )['results']
                pages = [r['page'] for r in results]
                expected = item['expected_pages']
                rank = first_relevant_rank(pages, expected, k)
                rows.append({
                    'id': item.get('id'),
                    'rank': rank,
                    'retrieved_pages': pages,
                    'expected_pages': expected,
                })
        except RetrievalError as exc:
            report['modes'][mode] = {'available': False, 'reason': str(exc)}
            continue
        metrics = aggregate_retrieval(rows, k)
        per_question = [
            {'id': row['id'], 'rank': row['rank'], 'retrieved_pages': row['retrieved_pages']}
            for row in rows
        ]
        report['modes'][mode] = {'available': True, **metrics, 'questions': per_question}
    return report


def summary(report):
    k = report['k']
    header = (
        f'Document {report["document_id"]} · top {k} results',
        f'{"mode":<10}{"hit@"+str(k):>8}{"mrr@"+str(k):>8}{"P@"+str(k):>8}{"R@"+str(k):>8}{"F1@"+str(k):>8}',
    )
    lines = list(header)
    for mode, result in report['modes'].items():
        if result['available']:
            lines.append(
                f'{mode:<10}'
                f'{result[f"hit@{k}"]:>8.3f}'
                f'{result[f"mrr@{k}"]:>8.3f}'
                f'{result[f"precision@{k}"]:>8.3f}'
                f'{result[f"recall@{k}"]:>8.3f}'
                f'{result[f"f1@{k}"]:>8.3f}'
            )
        else:
            lines.append(f'{mode:<10}  unavailable: {result["reason"]}')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Retrieval evaluation: expected PDF pages in top-k search results.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Reports hit@k, MRR@k, precision@k, recall@k, and F1@k per mode. '
            'Upload the evaluation PDF and sync the index before running.'
        ),
    )
    parser.add_argument('questions', nargs='?', default=str(DEFAULT_QUESTIONS))
    parser.add_argument('--modes', default=','.join(MODES), help='Comma-separated subset of bm25,semantic,hybrid')
    parser.add_argument('--report', help='Optional path for the full JSON report')
    args = parser.parse_args(argv)
    modes = [m.strip() for m in args.modes.split(',') if m.strip()]
    if not set(modes) <= set(MODES):
        parser.error('--modes must be drawn from bm25, semantic, hybrid')
    questions_path = str(Path(args.questions))
    try:
        report = evaluate(
            Retrieval(Store(corpus_path())),
            load_spec(args.questions),
            modes,
            questions_file=questions_path,
        )
    except (ValueError, LookupError) as exc:
        parser.exit(1, f'{exc}\n')
    print(summary(report))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    else:
        json.dump({m: r.get('questions') for m, r in report['modes'].items()}, sys.stdout, indent=1)
        print()


if __name__ == '__main__':
    main()
