"""Metric functions for ranking, classification, and end-to-end RAG reports."""

from .cag import context_budget_metrics, focus_metrics
from .classification import micro_precision_recall_f1, precision_recall_f1
from .rag import build_rag_report, citation_acceptance_rate
from .ranking import (
    aggregate_retrieval,
    f1_at_k,
    first_relevant_rank,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    'aggregate_retrieval',
    'build_rag_report',
    'citation_acceptance_rate',
    'context_budget_metrics',
    'f1_at_k',
    'first_relevant_rank',
    'focus_metrics',
    'hit_at_k',
    'micro_precision_recall_f1',
    'mrr_at_k',
    'ndcg_at_k',
    'precision_at_k',
    'precision_recall_f1',
    'recall_at_k',
]
