"""Answer-first focus for validated AI results (additive; used by the product API).

After an answer has passed citation validation, one short follow-up call asks the
model for what a reviewer looks for first:

- a one- or two-sentence direct answer, built only from the verified statements,
- the phrases in that answer that directly answer the question (to highlight),
- a short label per statement (for example "30 minutes"),
- for each quotation, the shortest phrase in it that answers the question.

Everything returned is checked before it is used: highlights must appear in the
answer, and each key phrase must appear word for word in its quotation (ignoring
whitespace, case, and typographic quote or dash differences). The returned key
phrase is the exact original span of the quotation. Anything that fails a check
is dropped. If the call fails, the result is returned unchanged with a note, so a
slow or unavailable model never costs the reviewer the verified answer.
"""
import json
import os

import httpx

from .ai import settings
from .store import _normalized

MAX_ANSWER_CHARS = 600
MAX_LABEL_CHARS = 40
MAX_HIGHLIGHTS = 4

SYSTEM_PROMPT = (
    'You help a compliance reviewer see the answer at a glance. You receive a question and statements that '
    'have already been verified against the source, each with numbered quotations. Use only these statements. '
    'Return only JSON: {"answer": "one or two plain sentences that answer the question directly, using only the '
    'statements", "highlights": ["up to 4 short phrases copied exactly from your answer that are the direct answer, '
    'such as a deadline, amount or obligation"], "items": [{"index": <statement index>, "label": "at most 4 words: '
    'the specific value or topic of this statement", "key_phrases": ["for each quotation of this statement, in order: '
    'the shortest phrase copied exactly from that quotation that answers the question"]}]}. '
    'Copy phrases character for character. Do not add facts, advice or legal conclusions.'
)


def enabled():
    return os.getenv('AI_FOCUS', 'true').strip().lower() not in ('0', 'false', 'no')


def locate(text, phrase):
    """Exact original span of phrase inside text, ignoring whitespace/case/typography; None if absent."""
    if not isinstance(phrase, str) or not phrase.strip():
        return None
    haystack, positions = _normalized(text)
    needle = _normalized(phrase)[0]
    start = haystack.find(needle)
    if start < 0 and len(haystack.lower()) == len(haystack) and len(needle.lower()) == len(needle):
        start = haystack.lower().find(needle.lower())
    if start < 0:
        return None
    return text[positions[start]:positions[start + len(needle) - 1] + 1]


def build_prompt(task, question, items):
    return {
        'task': task,
        'question': question,
        'statements': [
            {'index': index, 'statement': item['statement'],
             'quotations': [{'number': n, 'text': citation['quote']} for n, citation in enumerate(item['citations'], 1)]}
            for index, item in enumerate(items)
        ],
    }


def call_model(prompt, config, client=None):
    owns = client is None
    client = client or httpx.Client(timeout=config['timeout'], trust_env=False)
    try:
        response = client.post(config['url'] + '/api/chat', json={
            'model': config['model'], 'stream': False, 'format': 'json', 'think': config['think'],
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': json.dumps(prompt)}],
            'options': {'temperature': 0, 'num_ctx': config['num_ctx']}})
        response.raise_for_status()
        return json.loads(response.json()['message']['content'])
    finally:
        if owns:
            client.close()


def apply(result, output):
    """Validate the model's focus output and attach what passes to the result."""
    if not isinstance(output, dict):
        raise ValueError('focus output is not a JSON object')
    items = result['items']
    answer = output.get('answer')
    answer = answer.strip()[:MAX_ANSWER_CHARS] if isinstance(answer, str) and answer.strip() else None
    highlights = []
    if answer and isinstance(output.get('highlights'), list):
        for phrase in output['highlights']:
            if isinstance(phrase, str) and phrase.strip() and phrase.strip() in answer and phrase.strip() not in highlights:
                highlights.append(phrase.strip())
            if len(highlights) == MAX_HIGHLIGHTS:
                break
    labels, phrases_kept, phrases_offered = {}, 0, 0
    for entry in output.get('items') if isinstance(output.get('items'), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get('index'), int) or not 0 <= entry['index'] < len(items):
            continue
        item = items[entry['index']]
        label = entry.get('label')
        if isinstance(label, str) and label.strip() and len(label.strip()) <= MAX_LABEL_CHARS:
            labels[str(entry['index'])] = label.strip()
        phrases = entry.get('key_phrases') if isinstance(entry.get('key_phrases'), list) else []
        for citation, phrase in zip(item['citations'], phrases):
            phrases_offered += 1
            span = locate(citation['quote'], phrase)
            if span:
                citation['key_phrase'] = span
                phrases_kept += 1
    result['focus'] = {'answer': answer, 'highlights': highlights, 'labels': labels,
                       'key_phrases_kept': phrases_kept, 'key_phrases_offered': phrases_offered,
                       'note': 'The answer summarises the verified statements below; key phrases are checked against their quotations.'}
    return result


def add_focus(result, question, client=None):
    """Attach a validated focus to a result; on any failure keep the result and add a note."""
    if not enabled() or not result.get('items'):
        result['focus'] = None
        return result
    try:
        output = call_model(build_prompt(result['task'], question, result['items']), settings(), client)
        return apply(result, output)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        result['focus'] = None
        result.setdefault('notes', []).append(f'The short answer could not be prepared ({type(exc).__name__}); the verified statements are shown instead.')
        return result
