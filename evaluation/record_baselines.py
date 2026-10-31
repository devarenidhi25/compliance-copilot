"""Re-run evaluations and refresh evaluation/baselines/*.json (from repo root)."""
import argparse
import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.app.paths import REPO_ROOT

from evaluation.harness.rag import run_mock_smoke
from evaluation.harness.retrieval import evaluate, load_spec
from evaluation.harness.validation import run_suite as run_validation_suite
from backend.app.paths import corpus_path
from backend.app.retrieval import Retrieval
from backend.app.store import Store
import tempfile


def run_meta():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    return {
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'git_commit': commit,
    }


def write(name, payload):
    path = REPO_ROOT / 'evaluation' / 'baselines' / name
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print('wrote', path)


def record_retrieval(modes):
    store = Store(corpus_path())
    questions = REPO_ROOT / 'datasets' / 'eval' / 'lodr_master_circular.json'
    report = evaluate(Retrieval(store), load_spec(questions), tuple(modes), questions_file=str(questions))
    report = {'run': run_meta(), **report}
    report['questions_file'] = 'datasets/eval/lodr_master_circular.json'
    suffix = '_'.join(modes) if len(modes) < 3 else 'all_modes'
    write(f'lodr_retrieval_{suffix}.json', report)
    return report


def record_validation():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / 'corpus.sqlite', allow_synthetic=True)
        try:
            report = run_validation_suite(store, REPO_ROOT / 'evaluation/fixtures/validation/suite.json')
        finally:
            store.engine.dispose()
    write('validation_suite.json', {'run': run_meta(), **report})


def record_rag_mock():
    report = asyncio.run(run_mock_smoke())
    write('rag_qa_mock_smoke.json', {'run': run_meta(), **report})


def main():
    parser = argparse.ArgumentParser(description='Refresh committed evaluation baselines.')
    parser.add_argument('--retrieval', action='store_true', help='LODRE retrieval (needs PDF in corpus)')
    parser.add_argument('--modes', default='bm25,semantic,hybrid')
    parser.add_argument('--validation', action='store_true')
    parser.add_argument('--rag-mock', action='store_true')
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()
    if args.all:
        args.retrieval = args.validation = args.rag_mock = True
    if not (args.retrieval or args.validation or args.rag_mock):
        parser.error('Pass --all or specific flags')
    if args.validation:
        record_validation()
    if args.rag_mock:
        record_rag_mock()
    if args.retrieval:
        modes = [m.strip() for m in args.modes.split(',') if m.strip()]
        record_retrieval(modes)


if __name__ == '__main__':
    main()
