"""Retrieval evaluation: does the right page appear in the top-k results?

Usage (after uploading the document and syncing the index):

    python -m backend.app.eval_cli datasets/eval/lodr_master_circular.json

The question file names its document by SHA-256 content hash. For each retrieval
mode the evaluator reports hit@k, MRR@k, precision@k, recall@k, and F1@k.
Implementation lives in ``evaluation.harness.retrieval``.
"""
from evaluation.harness.retrieval import MODES, evaluate, find_document, load_spec, main, summary

__all__ = ['MODES', 'evaluate', 'find_document', 'load_spec', 'main', 'summary']

if __name__ == '__main__':
    main()
