"""Metrics for the context layer (evidence budget + validated focus)."""


def context_budget_metrics(chars_before, chars_after, budget):
    return {
        'context_chars_before_budget': chars_before,
        'context_chars_after_budget': chars_after,
        'prompt_char_budget': budget,
        'context_trimmed': chars_after < chars_before,
    }


def focus_metrics(result):
    focus = result.get('focus')
    if not focus:
        return {
            'focus_success': False,
            'highlights_kept': 0,
            'key_phrases_kept': 0,
            'key_phrases_offered': 0,
        }
    return {
        'focus_success': True,
        'highlights_kept': len(focus.get('highlights', [])),
        'key_phrases_kept': focus.get('key_phrases_kept', 0),
        'key_phrases_offered': focus.get('key_phrases_offered', 0),
    }
