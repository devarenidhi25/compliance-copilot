"""Page-level retrieval metrics for ranked lists (e.g. expected PDF pages in top-k)."""
import math


def first_relevant_rank(retrieved, relevant, k):
    """1-based rank of the first item in retrieved[:k] that appears in relevant, or None."""
    if k < 1:
        return None
    relevant = set(relevant)
    for index, item in enumerate(retrieved[:k]):
        if item in relevant:
            return index + 1
    return None


def hit_at_k(ranks, k):
    """Share of queries with at least one relevant item in the top k (ranks are 1-based or None)."""
    if not ranks:
        return 0.0
    return sum(rank is not None and rank <= k for rank in ranks) / len(ranks)


def mrr_at_k(ranks, k):
    """Mean reciprocal rank of the first relevant item within top k; 0 when none."""
    if not ranks:
        return 0.0
    total = 0.0
    for rank in ranks:
        if rank is not None and rank <= k:
            total += 1 / rank
    return total / len(ranks)


def _overlap_counts(retrieved, relevant, k):
    relevant = set(relevant)
    top = retrieved[:k]
    hits = sum(1 for item in top if item in relevant)
    return hits, len(top), len(relevant)


def precision_at_k(retrieved_lists, relevant_lists, k):
    """Macro-averaged precision@k: |relevant in top k| / k per query."""
    if not retrieved_lists or k < 1:
        return 0.0
    total = 0.0
    for retrieved, relevant in zip(retrieved_lists, relevant_lists, strict=True):
        hits, top_len, _ = _overlap_counts(retrieved, relevant, k)
        total += hits / top_len if top_len else 0.0
    return total / len(retrieved_lists)


def recall_at_k(retrieved_lists, relevant_lists, k):
    """Macro-averaged recall@k: |relevant in top k| / |gold| per query (0 if gold empty)."""
    if not retrieved_lists or k < 1:
        return 0.0
    total = 0.0
    for retrieved, relevant in zip(retrieved_lists, relevant_lists, strict=True):
        hits, _, gold_len = _overlap_counts(retrieved, relevant, k)
        total += min(1.0, hits / gold_len) if gold_len else 0.0
    return total / len(retrieved_lists)


def f1_at_k(retrieved_lists, relevant_lists, k):
    """Macro-averaged F1@k from precision and recall at k per query."""
    if not retrieved_lists or k < 1:
        return 0.0
    scores = []
    for retrieved, relevant in zip(retrieved_lists, relevant_lists, strict=True):
        hits, top_len, gold_len = _overlap_counts(retrieved, relevant, k)
        if not top_len or not gold_len:
            scores.append(0.0)
            continue
        precision = hits / top_len
        recall = min(1.0, hits / gold_len)
        if precision + recall == 0:
            scores.append(0.0)
        else:
            scores.append(2 * precision * recall / (precision + recall))
    return sum(scores) / len(scores)


def ndcg_at_k(retrieved_lists, relevant_lists, k):
    """Binary-relevance nDCG@k, macro-averaged over queries."""
    if not retrieved_lists or k < 1:
        return 0.0

    def dcg(relevant_set, ranked):
        value = 0.0
        for index, item in enumerate(ranked[:k]):
            if item in relevant_set:
                value += 1.0 / math.log2(index + 2)
        return value

    def idcg(relevant_set):
        ideal = min(len(relevant_set), k)
        return sum(1.0 / math.log2(index + 2) for index in range(ideal))

    total = 0.0
    for retrieved, relevant in zip(retrieved_lists, relevant_lists, strict=True):
        relevant_set = set(relevant)
        if not relevant_set:
            continue
        ideal = idcg(relevant_set)
        total += dcg(relevant_set, retrieved) / ideal if ideal else 0.0
    return total / len(retrieved_lists)


def aggregate_retrieval(rows, k):
    """Build summary metrics from per-question rows with retrieved_pages and expected pages.

    Each row: {"retrieved_pages": [...], "expected_pages": [...]} or rank precomputed.
    """
    ranks = []
    retrieved_lists = []
    relevant_lists = []
    for row in rows:
        retrieved = row['retrieved_pages']
        relevant = row['expected_pages']
        retrieved_lists.append(retrieved)
        relevant_lists.append(relevant)
        ranks.append(row.get('rank', first_relevant_rank(retrieved, relevant, k)))
    prefix = f'@{k}'
    return {
        f'hit{prefix}': round(hit_at_k(ranks, k), 3),
        f'mrr{prefix}': round(mrr_at_k(ranks, k), 3),
        f'precision{prefix}': round(precision_at_k(retrieved_lists, relevant_lists, k), 3),
        f'recall{prefix}': round(recall_at_k(retrieved_lists, relevant_lists, k), 3),
        f'f1{prefix}': round(f1_at_k(retrieved_lists, relevant_lists, k), 3),
        f'ndcg{prefix}': round(ndcg_at_k(retrieved_lists, relevant_lists, k), 3),
    }
