"""Retrieval evaluation: does the right page appear in the top-k results?

Usage (after uploading the document and syncing the index):

    python -m backend.app.eval_cli datasets/eval/lodr_master_circular.json

The question file names its document by SHA-256 content hash, so it works with
whatever document ID the upload received. For each retrieval mode it reports
hit@k (share of questions with an expected page in the top k) and MRR@k (mean
reciprocal rank of the first correct page; 0 when none is in the top k).
"""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

from .paths import REPO_ROOT, corpus_path
from .retrieval import Retrieval, RetrievalError
from .store import Store

MODES = ('bm25', 'semantic', 'hybrid')


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
        row = conn.execute(text('SELECT id, organization FROM documents WHERE content_hash=:h ORDER BY uploaded_at LIMIT 1'),
                           {'h':content_hash}).mappings().first()
    if not row:
        raise LookupError('Evaluation document not found in the corpus; upload it first (matched by content hash)')
    # Shared documents are visible to any organization; private ones to their owner.
    return row['id'], row['organization'] or '__evaluation__'


def evaluate(retrieval, spec, modes=MODES):
    document_id, org = find_document(retrieval.store, spec['document']['content_hash'])
    k = int(spec.get('k', 6))
    report = {'document_id':document_id, 'k':k, 'modes':{}}
    for mode in modes:
        ranks, rows = [], []
        try:
            for item in spec['questions']:
                results = retrieval.search(item['question'], org, {'document_ids':[document_id]}, mode=mode, limit=k)['results']
                pages = [r['page'] for r in results]
                expected = set(item['expected_pages'])
                rank = next((i + 1 for i, page in enumerate(pages) if page in expected), None)
                ranks.append(rank)
                rows.append({'id':item.get('id'), 'rank':rank, 'retrieved_pages':pages})
        except RetrievalError as exc:
            report['modes'][mode] = {'available':False, 'reason':str(exc)}
            continue
        report['modes'][mode] = {'available':True,
                                 f'hit@{k}':round(sum(r is not None for r in ranks) / len(ranks), 3),
                                 f'mrr@{k}':round(sum(1 / r for r in ranks if r) / len(ranks), 3),
                                 'questions':rows}
    return report


def summary(report):
    k = report['k']
    lines = [f'Document {report["document_id"]} · top {k} results', f'{"mode":<10}{"hit@"+str(k):>8}{"mrr@"+str(k):>8}']
    for mode, result in report['modes'].items():
        if result['available']:
            lines.append(f'{mode:<10}{result[f"hit@{k}"]:>8.3f}{result[f"mrr@{k}"]:>8.3f}')
        else:
            lines.append(f'{mode:<10}  unavailable: {result["reason"]}')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('questions', nargs='?', default=str(REPO_ROOT/'datasets'/'eval'/'lodr_master_circular.json'))
    parser.add_argument('--modes', default=','.join(MODES), help='Comma-separated subset of bm25,semantic,hybrid')
    parser.add_argument('--report', help='Optional path for the full JSON report')
    args = parser.parse_args()
    modes = [m.strip() for m in args.modes.split(',') if m.strip()]
    if not set(modes) <= set(MODES):
        parser.error('--modes must be drawn from bm25, semantic, hybrid')
    try:
        report = evaluate(Retrieval(Store(corpus_path())), load_spec(args.questions), modes)
    except (ValueError, LookupError) as exc:
        parser.exit(1, f'{exc}\n')
    print(summary(report))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    else:
        json.dump({m:r.get('questions') for m, r in report['modes'].items()}, sys.stdout, indent=1)
        print()


if __name__ == '__main__':
    main()
