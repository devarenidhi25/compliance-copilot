"""Context layer on validated RAG output (project CAG terminology).

Comnet does not use a separate CAG model. After retrieval and citation validation,
an optional focus pass summarises verified statements only (``backend.app.focus``).
"""
from .focus import add_focus, enabled as focus_enabled


def apply_context_layer(result, question, client=None):
    """Attach validated answer-first focus to a RAG result; non-fatal on failure."""
    return add_focus(result, question, client=client)


__all__ = ['apply_context_layer', 'focus_enabled', 'add_focus']
