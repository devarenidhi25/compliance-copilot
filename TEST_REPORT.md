# Verification — 14 October 2026

## Results

Verified pre-change baseline: **28 passed**, six dependency deprecation warnings.
Retrieval-only gate, before workflow integration: **7 passed**, six warnings.
Final full suite: **45 passed, 0 failed**, six warnings, in **6.73 seconds**.

Exact test commands:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_retrieval.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

Tests ran outside the sandbox because the prior sandboxed FastAPI threaded client
stalled. Plugin autoload remains disabled to avoid unrelated host ROS plugins.
Intermediate full runs passed 35, 43, and 44 tests before the final additions.

Other executed checks:

```sh
.venv/bin/python -m compileall -q backend tests
node --input-type=module --check < <(sed -n '/<script type="module">/,/<\/script>/p' frontend/index.html | sed '1d;$d')
.venv/bin/pip check
.venv/bin/python -m backend.app.index_cli --help
```

All passed. Dependency imports for Sentence Transformers, Chroma and CPU PyTorch
passed; PyTorch reports `2.8.0+cpu`. Read-only production database inspection reports
**0 documents and 0 chunks**. No BGE-M3 weights were downloaded.

The first dependency installation failed with an assertion in pip 22's resolver.
Upgrading the virtual environment to pip 25.2 and installing the pinned requirements
resolved it. `pip check` reports no broken requirements. Six test warnings concern
PyMuPDF SWIG types and Starlette's deprecated AnyIO portal alias; they are not test failures.

## Coverage

The original ingestion, hash, metadata provenance, PDF-byte persistence, page/chunk,
version-family, duplicate rejection, citation, official URL/import and organization
isolation tests remain passing.

New coverage verifies:

- Independent BM25 and semantic rankings over actual stored synthetic chunks.
- Deterministic RRF scores, tie handling and duplicate-result suppression.
- Regulator, document UUID, version label, family and document-type filters.
- Real persistent Chroma storage, restart reads and idempotent synchronization.
- Pending-document state, configuration mismatch, successful rebuilds, failed
  rebuilds preserving the active manifest, missing-vector failures, and model
  configuration changes during search/indexing failing closed.
- Exact physical page-two citations and omission of blank-page chunks.
- Empty corpus, missing model setup, local-only model load errors, and explicit
  mocked download activation of an exact snapshot revision.
- Retrieval and generation isolation across organizations, including explicit
  foreign document IDs.
- All four AI workflows using hybrid-retrieved stored evidence; invented quotation
  rejection, missing paired evidence, unavailable Ollama and invalid assessment
  labels (including wrong JSON types).
- Public search/status APIs, filter validation, index readiness and rejection of
  generation from documents not yet indexed.

## Files changed

Modified: `backend/app/store.py`, `backend/app/main.py`, `backend/app/ai.py`,
`backend/requirements.txt`, `frontend/index.html`, `tests/test_pipeline.py`,
`README.md`, `datasets/README.md`, and `TEST_REPORT.md`.

Added: `backend/app/retrieval.py`, `backend/app/index_cli.py`,
`tests/test_retrieval.py`, `tests/__init__.py`, `tests/fixtures/embedding.py`,
and `tests/fixtures/README.md`.

The existing synthetic SOP files remain in the dedicated fixture directory;
application code never imports the test embedding implementation or seeds fixtures.

## Limits and next stage

Semantic tests use real Chroma with deterministic **test-only** vectors. They verify
index/query mechanics and integration, not real BGE-M3 model quality. Model download
is mocked in its unit test. Actual BGE-M3 inference, real Ollama generation, official
PDF fetching and interactive browser end-to-end behavior were not verified.
Browser checks cover script syntax and the served page/API, not UI interaction.

Configuration/setup is documented in README.md: `EMBEDDING_MODEL`,
`EMBEDDING_MODEL_PATH`, `EMBEDDING_DEVICE`, `CHROMA_PATH`, existing `COPILOT_DB`,
`COPILOT_ORG_TOKENS`, `OLLAMA_MODEL`, and `OLLAMA_URL`. Explicitly download BGE-M3,
then ingest actual official PDFs and synchronize the index. Separately install
Ollama and pull the configured model before live generation.

This remains a local development application with bounded evidence excerpts, an
in-memory BM25 candidate index, Linux writer locking, and retained old Chroma
collections. Citation validation cannot prove legal accuracy or completeness.
React/Vite, enterprise membership/authentication, Alembic migrations, persistent
human approvals/audit history and report export remain unimplemented.

Next recommended stage: persist human-review decisions and their evidence snapshots,
with audit history, before adding report export and a larger frontend.
