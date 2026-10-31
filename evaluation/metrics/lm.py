"""Optional language-model metrics (experimental; not compliance scores)."""
import os


def perplexity_status():
    """Perplexity is not available from the Ollama chat API used in production."""
    if os.getenv('EVAL_PERPLEXITY', '').strip().lower() in ('1', 'true', 'yes'):
        return {
            'available': False,
            'reason': 'EVAL_PERPLEXITY is set but HF perplexity evaluation is not implemented yet.',
        }
    return {
        'available': False,
        'reason': 'Ollama chat does not expose token log-probabilities; use retrieval/RAG metrics instead.',
    }
