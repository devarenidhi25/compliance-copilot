# Compliance Copilot — grounded hybrid retrieval

A locally runnable first stage with FastAPI, SQLAlchemy/SQLite and PyMuPDF:
PDF upload, restricted official URL import, explicit metadata provenance, immutable
version families, page-scoped chunks, citation validation, organization-isolated
internal policies, stored-version text comparison, and BM25/local semantic retrieval
through persistent Chroma with reciprocal rank fusion (RRF). No regulatory documents are
seeded. A small browser interface is served by the backend.

The four AI workflows call local Ollama using selected stored evidence, reject
invalid citations, and expose service errors without fabricated fallback responses.
This is a local development application, not a completed production compliance platform.
SQLite stores documents you ingest; it does not provide or hardcode regulatory data.

## Run

Python 3.10+ is supported (the detected host uses 3.10). From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install --upgrade pip==25.2
.venv/bin/pip install -r backend/requirements.txt
export COPILOT_ORG_TOKENS='{"your-organization":"replace-with-a-strong-unique-token"}'
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, enter the configured token, and open the library.
Upload your actual PDFs. The API reference is `http://127.0.0.1:8000/docs`.
`COPILOT_DB` optionally changes the database path (default `data/corpus.sqlite3`).
Keep this server local; the token mapping is development authentication, not a
replacement for membership management or production identity controls.

For AI, separately install Ollama, then run:

```sh
ollama pull qwen3:8b
ollama serve
```

`OLLAMA_URL` defaults to `http://localhost:11434`; `OLLAMA_MODEL` to `qwen3:8b`.
`OLLAMA_NUM_CTX` (default `16384`) sets the model context window sent with every
request; Ollama's own default is much smaller and silently truncates long prompts.
`OLLAMA_TIMEOUT` (default `300` seconds) bounds each generation; raise it on slow CPUs.
`OLLAMA_THINK` (default `false`) controls reasoning mode. Keep it off for qwen3: with
thinking on, the model spends its output on reasoning and returns an empty JSON object.
`AI_CHUNKS_PER_DOCUMENT` (default `6`, range 1–20) sets how many excerpts per selected
document are sent to the model; lower it on CPU-only machines to speed up generation.
Generation failures report the specific cause (timeout, Ollama unreachable, Ollama error
such as insufficient memory, missing model, or non-JSON output). Successful responses
include `generation_seconds` and the number of evidence excerpts used.
`OLLAMA_PROMPT_CHARS` optionally overrides the prompt budget (default derived from
`OLLAMA_NUM_CTX`). When evidence exceeds the budget, the lowest-ranked excerpts are
dropped first (one excerpt per document is always kept) and the response says so.
No model is downloaded by the backend. Generate from selected document UUIDs in
the interface; comparisons need two versions from one family, gaps need both
regulatory and organization-internal evidence. Ingested documents remain usable
when Ollama is offline. Citation validation verifies exact text, not legal conclusions.

## Local embedding setup and index lifecycle

Install dependencies first. The pinned installation uses CPU PyTorch. Model weights
are **not** downloaded during installation, upload, search, or server startup.
Download them explicitly when ready (internet and several GB of disk/RAM required):

```sh
.venv/bin/python -m backend.app.index_cli download-model
```

The default is `BAAI/bge-m3`, loaded with Sentence Transformers for dense embeddings.
The setup command records the exact Hub snapshot revision and downloads model/tokenizer
files without ONNX variants. It stores revision-specific weights under `data/models/bge-m3/snapshots/` and
atomically updates `data/models/bge-m3/copilot-model.json` after success.
Runtime loading is local-only. No hosted inference receives your documents.

After uploading/importing actual PDFs, run the local administrator command:

```sh
.venv/bin/python -m backend.app.index_cli sync
.venv/bin/python -m backend.app.index_cli status
```

Uploads remain available even before indexing. The interface reports pending or
unavailable indexes. AI generation requires a complete hybrid index for its selected
versions; explicit BM25-only search remains available for evidence inspection.
There is no silent keyword-only AI fallback.

Configuration defaults (export variables before starting both server and CLI):

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Model identity to download/use |
| `EMBEDDING_MODEL_PATH` | `data/models/bge-m3` | Local model directory with setup marker |
| `EMBEDDING_DEVICE` | `cpu` | Inference device; pinned PyTorch installation is CPU only |
| `CHROMA_PATH` | `data/chroma` | Persistent vectors and active-index manifest |
| `COPILOT_DB` | `data/corpus.sqlite3` | Authoritative PDF/chunk database |

Changing model identity/revision or preprocessing requires a full rebuild:

```sh
.venv/bin/python -m backend.app.index_cli rebuild
```

Rebuild stages a new collection and switches the manifest only after success.
Failed rebuilds preserve the previous active generation; uploads/PDFs are unaffected.
Old/staging collections are retained for recovery and consume disk; automatic cleanup
is not included. Incremental sync upserts stable chunk IDs and does not duplicate
vectors. CLI writers use a Linux file lock. Run a single local backend worker;
production distributed indexing is outside this stage.

Restart the server after downloading/replacing model files. If local model loading
fails, inspect dependencies, RAM and `EMBEDDING_MODEL_PATH`. If vector IDs are missing,
use `rebuild`; `sync` skips versions already recorded as complete. When moving the
corpus database to another path, rebuild to bind the index to the new corpus path.

## Evidence APIs

`POST /api/retrieval/search` accepts `query`, `mode` (`bm25`, `semantic`, `hybrid`),
`limit` (1–20), and optional `filters`: `document_ids`, `regulator`, `kind`,
`family_id`, `version` (metadata label), and `document_type`. A document UUID is also
its immutable version UUID. Unknown metadata does not match a metadata filter.
Results retain exact text, physical PDF page, chunk/document/family IDs, metadata
provenance and source PDF references. All retrieval/status routes require your
organization bearer token. Unknown or inaccessible explicitly selected documents
return 404. `GET /api/retrieval/status` exposes only accessible-document counts.
`GET /api/health` includes index and Ollama status.

BM25 tokenizes lowercase Unicode words; semantic search uses normalized dense vectors
and cosine distance. Hybrid search merges the top 20 candidates per retriever using
RRF with constant 60, deduplicates chunk IDs, and resolves ties by ID. Ranking scores
are not compliance probabilities. AI retrieves up to six chunks per selected document.
Q&A uses regulatory evidence; gap analysis retrieves regulatory/internal evidence
separately; comparison also supplies hints from at most ten changed physical pages.
These bounded excerpts do not establish absence of a provision from a complete policy.

AI responses preserve `statement` and add `interpretation`, exact-quotation
`source_facts`, and gap `assessment`. Quotations are matched ignoring whitespace and
typographic quote/dash differences, and the stored citation is always the exact original
source span. Each model item is validated independently: items with an unsupported
quotation, an unprovided chunk ID or an invalid label are dropped and listed in
`rejected_items` with a reason; the request fails only when no item survives.
Gap items must cite at least one regulatory and one internal excerpt; comparison items
must cite both versions. Q&A uses regulatory documents only and notes any ignored
internal selections. The supported labels are `APPEARS_ADDRESSED`,
`PARTIALLY_ADDRESSED`, `POTENTIAL_GAP`, `POSSIBLE_CONFLICT`, `INSUFFICIENT_EVIDENCE`.
Labels are model assessments requiring review, not legal determinations. Every item
remains `pending_human_review`; approvals are not yet persisted.

## Tests

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

Plugin autoload is disabled to avoid unrelated host ROS pytest plugins. Tests use
synthetic PDFs in temporary databases and mock external imports/model responses.
They do not download official documents or require a model. See
[datasets/README.md](datasets/README.md) for sources, versioning and citation checks.

## Deliberate first-stage limits

The interface remains plain JavaScript/HTML rather than React/Vite. Retrieval tests
use real temporary Chroma storage with deterministic test-only embeddings; they do
not verify the quality of downloaded BGE-M3 weights. Ollama output is validated but real model inference requires
installed weights and a running service. Persistent human review, report export,
audit/task history, JWT membership management and Alembic migrations remain for
subsequent implementation. No legal determinations or compliance certification.
