"""CLI entry: python -m evaluation.run_cag (see harness; smoke via run_rag)."""
import asyncio
import json
from pathlib import Path

from evaluation.harness.rag import run_mock_smoke, summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description='CAG context metrics from mock RAG smoke path.')
    parser.add_argument('--report', help='Write JSON report')
    args = parser.parse_args()
    report = asyncio.run(run_mock_smoke())
    cag_only = {'schema': report.get('schema'), 'cag': report.get('cag'), 'parameters': report.get('parameters')}
    print(summary(report))
    if args.report:
        Path(args.report).write_text(json.dumps(cag_only, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
