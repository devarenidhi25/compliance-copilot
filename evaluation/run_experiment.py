"""Run multi-step evaluation experiments from YAML configs."""
import argparse
import asyncio
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from backend.app.paths import REPO_ROOT, corpus_path
from backend.app.retrieval import Retrieval
from backend.app.store import Store

from evaluation.harness.rag import run_mock_smoke
from evaluation.harness.retrieval import evaluate, load_spec
from evaluation.harness.validation import run_suite as run_validation_suite
from evaluation.metrics.lm import perplexity_status

MANIFEST_SCHEMA = 'evaluation/schemas/experiment_manifest.v1.json'


def load_config(path):
    text = Path(path).read_text(encoding='utf-8')
    if Path(path).suffix.lower() in ('.yaml', '.yml'):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data.get('steps'), list) or not data['steps']:
        raise ValueError('Experiment config needs a nonempty "steps" list')
    return data


def git_commit():
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve(path):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def run_retrieval_step(step):
    modes = step.get('modes', ['bm25', 'semantic', 'hybrid'])
    questions = resolve(step['questions'])
    store = Store(corpus_path())
    report = evaluate(Retrieval(store), load_spec(questions), tuple(modes), questions_file=str(questions))
    return report


def run_validation_step(step):
    suite = resolve(step.get('suite', 'evaluation/fixtures/validation/suite.json'))
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / 'corpus.sqlite', allow_synthetic=True)
        try:
            return run_validation_suite(store, suite)
        finally:
            store.engine.dispose()


def run_rag_mock_step(_step):
    return asyncio.run(run_mock_smoke())


STEP_RUNNERS = {
    'retrieval': run_retrieval_step,
    'validation': run_validation_step,
    'rag_mock': run_rag_mock_step,
}


def run_experiment(config_path, output_dir=None):
    config = load_config(config_path)
    config_path = resolve(config_path)
    experiment_id = config.get('experiment_id') or config_path.stem
    started = datetime.now(timezone.utc)
    if output_dir is None:
        stamp = started.strftime('%Y%m%dT%H%M%SZ')
        output_dir = REPO_ROOT / 'evaluation' / 'reports' / f'{stamp}_{experiment_id}'
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    steps_out = []
    for step in config['steps']:
        name = step.get('name') or step.get('type', 'step')
        step_type = step.get('type')
        runner = STEP_RUNNERS.get(step_type)
        entry = {'name': name, 'type': step_type}
        if not runner:
            entry.update({'status': 'skipped', 'error': f'Unknown step type: {step_type}'})
            steps_out.append(entry)
            continue
        report_path = output_dir / f'{name}.json'
        try:
            report = runner(step)
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            try:
                rel_report = str(report_path.relative_to(REPO_ROOT.resolve()))
            except ValueError:
                rel_report = str(report_path)
            entry.update({'status': 'success', 'report_path': rel_report})
        except Exception as exc:
            entry.update({'status': 'failed', 'error': str(exc)})
        steps_out.append(entry)

    finished = datetime.now(timezone.utc)
    manifest = {
        'schema': MANIFEST_SCHEMA,
        'experiment_id': experiment_id,
        'description': config.get('description'),
        'config_path': str(
            config_path.relative_to(REPO_ROOT)
            if REPO_ROOT in config_path.parents or config_path == REPO_ROOT
            else config_path
        ),
        'started_at': started.isoformat(),
        'finished_at': finished.isoformat(),
        'git_commit': git_commit(),
        'perplexity': perplexity_status(),
        'steps': steps_out,
    }
    manifest_path = output_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest, output_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run evaluation experiment YAML/JSON configs.')
    parser.add_argument('config', help='Path to experiment config (YAML or JSON)')
    parser.add_argument('--output', help='Output directory (default: evaluation/reports/<timestamp>_<id>)')
    args = parser.parse_args(argv)
    try:
        manifest, output_dir = run_experiment(args.config, args.output)
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
    failed = sum(1 for step in manifest['steps'] if step['status'] == 'failed')
    skipped = sum(1 for step in manifest['steps'] if step['status'] == 'skipped')
    print(f'Experiment {manifest["experiment_id"]} → {output_dir}')
    for step in manifest['steps']:
        print(f'  [{step["status"]}] {step["name"]}' + (f' — {step.get("error")}' if step.get('error') else ''))
    if failed or skipped:
        raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
