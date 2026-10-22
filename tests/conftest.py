"""Keep tests away from the developer's real data/ directory and downloaded model.

Without this, a developer who has run download-model would see tests that
expect a missing model fail, and tests could write into data/.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    for variable, name in (('COPILOT_DB', 'corpus.sqlite3'), ('CHROMA_PATH', 'chroma'), ('EMBEDDING_MODEL_PATH', 'no-model')):
        monkeypatch.setenv(variable, str(tmp_path / 'isolated' / name))
    for variable in ('OLLAMA_NUM_CTX', 'OLLAMA_TIMEOUT', 'OLLAMA_THINK', 'OLLAMA_PROMPT_CHARS', 'AI_CHUNKS_PER_DOCUMENT', 'OLLAMA_MODEL', 'COPILOT_ADMIN_TOKENS'):
        monkeypatch.delenv(variable, raising=False)
