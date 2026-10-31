"""Summaries for end-to-end RAG evaluation reports."""


def citation_acceptance_rate(items_accepted, items_rejected):
    total = items_accepted + items_rejected
    return round(items_accepted / total, 3) if total else 0.0


def build_rag_report(result, *, mock=False, retrieval_mode='hybrid'):
    accepted = len(result.get('items', []))
    rejected = len(result.get('rejected_items', []))
    return {
        'task': result.get('task'),
        'mock': mock,
        'models': {
            'ollama_model': result.get('model'),
            'retrieval_mode': retrieval_mode,
        },
        'generation_seconds': result.get('generation_seconds'),
        'evidence_excerpts': result.get('evidence_excerpts'),
        'items_proposed': accepted + rejected,
        'items_accepted': accepted,
        'items_rejected': rejected,
        'citation_acceptance_rate': citation_acceptance_rate(accepted, rejected),
        'rejected_items': result.get('rejected_items', []),
        'notes': result.get('notes', []),
    }
