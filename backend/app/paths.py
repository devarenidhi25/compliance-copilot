"""Default file locations, resolved from the repository root.

Defaults no longer depend on the directory the server or CLI is started from.
Environment variables still override them; relative values given there are
used as written (relative to the current directory).
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_INDEX = REPO_ROOT / 'frontend' / 'index.html'
# The client-facing app, built from frontend/app with `npm run build`.
APP_INDEX = REPO_ROOT / 'frontend' / 'app' / 'dist' / 'index.html'
DEFAULT_REGISTRY = REPO_ROOT / 'datasets' / 'official_sources.json'
DEFAULT_INGESTION_REPORT = REPO_ROOT / 'data' / 'ingestion-report.json'


def setting_path(variable, default):
    value = os.getenv(variable)
    return Path(value) if value else REPO_ROOT / default


def corpus_path():
    return setting_path('COPILOT_DB', 'data/corpus.sqlite3')


def chroma_path():
    return setting_path('CHROMA_PATH', 'data/chroma')


def model_path():
    return setting_path('EMBEDDING_MODEL_PATH', 'data/models/bge-m3')
