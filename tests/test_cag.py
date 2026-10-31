import json

import httpx
import pytest

from backend.app.cag import apply_context_layer, focus_enabled


def test_focus_enabled_respects_env(monkeypatch):
    monkeypatch.setenv('AI_FOCUS', 'false')
    assert focus_enabled() is False
    monkeypatch.setenv('AI_FOCUS', 'true')
    assert focus_enabled() is True


def test_apply_context_layer_attaches_validated_focus(monkeypatch):
    result = {
        'task': 'qa',
        'items': [
            {
                'statement': 'Retention applies.',
                'citations': [{'quote': 'retaining the demo identifier for five years.'}],
            }
        ],
    }
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        body = {
            'answer': 'Retain the demo identifier for five years.',
            'highlights': ['five years'],
            'items': [{'index': 0, 'label': 'five years', 'key_phrases': ['demo identifier for five years']}],
        }
        return httpx.Response(200, json={'message': {'content': json.dumps(body)}})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setenv('AI_FOCUS', 'true')
    out = apply_context_layer(result, 'retain identifier', client=client)
    client.close()
    assert out.get('focus') is not None
    assert out['focus']['highlights']
    assert seen
