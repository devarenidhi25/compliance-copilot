import pytest

from evaluation.metrics.classification import micro_precision_recall_f1, precision_recall_f1
from evaluation.metrics.ranking import (
    aggregate_retrieval,
    f1_at_k,
    first_relevant_rank,
    hit_at_k,
    mrr_at_k,
    precision_at_k,
    recall_at_k,
)


def test_first_relevant_rank_and_hit_mrr():
    retrieved = [10, 20, 30]
    assert first_relevant_rank(retrieved, {20, 99}, 3) == 2
    assert first_relevant_rank(retrieved, {99}, 3) is None
    ranks = [2, None]
    assert hit_at_k(ranks, 1) == 0.0
    assert hit_at_k(ranks, 2) == 0.5
    assert mrr_at_k(ranks, 2) == 0.25


def test_precision_recall_f1_at_k():
    retrieved_lists = [[1, 2, 3], [4, 5]]
    relevant_lists = [{2, 3}, {4, 6}]
    k = 3
    assert precision_at_k(retrieved_lists, relevant_lists, k) == pytest.approx((2 / 3 + 1 / 2) / 2)
    assert recall_at_k(retrieved_lists, relevant_lists, k) == pytest.approx((2 / 2 + 1 / 2) / 2)
    assert f1_at_k(retrieved_lists, relevant_lists, k) == pytest.approx(
        ((2 * (2 / 3) * 1) / (2 / 3 + 1) + (2 * 0.5 * 0.5) / 1) / 2
    )


def test_aggregate_retrieval_matches_eval_cli_style():
    rows = [
        {'retrieved_pages': [2], 'expected_pages': [2]},
        {'retrieved_pages': [1], 'expected_pages': [2]},
    ]
    summary = aggregate_retrieval(rows, k=1)
    assert summary['hit@1'] == 0.5
    assert summary['mrr@1'] == 0.5
    assert summary['precision@1'] == 0.5
    assert summary['recall@1'] == 0.5
    assert summary['f1@1'] == 0.5


def test_classification_macro_and_micro():
    y_true = ['A', 'A', 'B', 'C']
    y_pred = ['A', 'B', 'B', 'C']
    macro = precision_recall_f1(y_true, y_pred, labels=['A', 'B', 'C'])
    assert macro['macro']['f1'] > 0
    assert macro['per_label']['A']['support'] == 2
    micro = micro_precision_recall_f1(y_true, y_pred, labels=['A', 'B', 'C'])
    assert micro['support'] == 4
    assert micro['f1'] == pytest.approx(0.75)


def test_classification_length_mismatch():
    with pytest.raises(ValueError):
        precision_recall_f1(['A'], ['A', 'B'])
