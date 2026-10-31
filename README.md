# Comnet — Compliance Copilot

Comnet is a local-first compliance research prototype for finding and reviewing
evidence in RBI and SEBI documents alongside an organization's own policies. It
addresses a practical review problem: requirements and internal controls are spread
across lengthy PDFs and changing circulars, making it slow to locate relevant clauses,
compare versions, and explain findings with traceable sources.

Comnet stores uploaded documents and extracted page text locally, retrieves relevant
passages, and supports four evidence-based review workflows: regulatory Q&A, version
comparison, policy gap analysis, and action checklists. Accepted AI statements include
quotations checked against the stored document text and links to the source page.
Compliance, legal, risk, and audit teams can use it to accelerate research and prepare
human reviews; it does not certify compliance, determine legal applicability, or
replace professional judgment.

## What is implemented

- **Document library and version families:** Upload searchable PDFs, record metadata,
  preserve each version immutably, and compare versions in the same family. PDF pages,
  extracted text, chunk offsets, and content hashes are retained in a local SQLite
  database. Documents are not preloaded at startup.
- **Search:** BM25 keyword search, local BGE-M3 semantic vectors, and hybrid search.
  Hybrid results merge each retriever's top candidates with reciprocal rank fusion
  (RRF, constant 60). Similarity and ranking scores are retrieval signals, not
  compliance probabilities.
- **Evidence-based AI review:** Q&A, version comparison, gap analysis, and checklists
  use selected stored evidence through a locally hosted Ollama model. Quotations must
  match stored text; invalid items are rejected and reported. The optional short,
  answer-first summary is built from verified statements and is itself subject to
  human review.
- **Review aids:** A line-aligned version diff identifies added, removed, and reworded
  passages; gap findings receive deterministic status, risk, and score values based on
  the model's labels. The web app shows citations, source pages, index state, AI job
  progress, and an organization-scoped audit trail.
- **Document access:** Server-configured bearer tokens scope private documents to an
  organization. Administrator tokens can manage the shared library and run indexing.
  This is development authentication, not enterprise identity management.
- **Optional official-source ingestion:** Import a direct PDF URL from an allowlisted
  RBI or SEBI host, or explicitly run the bounded crawler described below. Host checks
  establish source provenance only; they do not establish that metadata, applicability,
  or interpretations are legally correct.

All generated findings remain pending human review. Citation checks establish that a
quote comes from stored source text; they do not establish that an interpretation is
correct or that retrieved excerpts cover every relevant requirement.

## Data sources

The application starts with an empty database. It uses documents that an operator
uploads or imports; it does not silently download or seed regulatory material.

- **Primary evidence:** User-provided searchable PDFs, including RBI and SEBI
  regulatory documents and organization-owned internal policies/SOPs. Direct URL
  imports are limited to official RBI/SEBI hosts.
- **Crawler registry:** [`datasets/official_sources.json`](datasets/official_sources.json)
  lists eight official RBI and SEBI listing pages. Only RBI notifications, Master
  Directions, and FAQs are enabled initially; SEBI listings and RBI press releases are
  disabled. The opt-in crawler is bounded, does not run at startup, and cannot follow
  RBI ASP.NET postback pagination. It is not a continuous regulatory feed.
- **Retrieval evaluation:** The repository includes a SEBI LODR Master Circular PDF and
  a 12-question expected-page file in `datasets/`. These support an explicit retrieval
  evaluation after the same PDF is uploaded and indexed; neither is automatically
  loaded into the application's corpus. The recorded BM25 baseline is hit@6 0.833 and
  MRR@6 0.750 for that question set only. Semantic and hybrid evaluation require the
  local embedding model and should be measured on the operator's machine.
- **Development fixtures:** `tests/fixtures/` contains clearly marked synthetic KYC
  examples for isolated tests, not real policy or regulatory evidence.

See [`datasets/README.md`](datasets/README.md) for source handling, import limits,
version metadata, crawler behavior, and evaluation details.

## Technology

- **Backend:** Python 3.10+, FastAPI, Uvicorn, SQLAlchemy, SQLite, PyMuPDF,
  `rank-bm25`, ChromaDB, Sentence Transformers, and PyTorch.
- **Retrieval models:** BM25 token matching and BGE-M3 embeddings run locally.
  Embedding weights are downloaded explicitly, not during install, upload, or startup.
- **Generation:** Ollama serves the configured local model (default `qwen3:8b`).
  Documents and prompts are sent to that configured Ollama endpoint; no hosted model
  inference is built into the application.
- **Web app:** React 19, TypeScript, Vite, and PDF.js. The committed production build is
  served by FastAPI; Node.js 20+ is needed to work on or rebuild the frontend.

## Run locally

Commands below use PowerShell from the repository root. Python 3.10+ is required.

1. Create the environment and install the pinned backend dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip==25.2
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

2. Configure separate organization and administrator tokens. Use long, unique values;
   the JSON maps organization names to bearer tokens:

   ```powershell
   $env:COPILOT_ORG_TOKENS = '{"example-org":"replace-with-a-strong-token"}'
   $env:COPILOT_ADMIN_TOKENS = '{"example-org":"replace-with-a-different-admin-token"}'
   ```

3. Start the API and web app:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
   ```

   Open `http://127.0.0.1:8000`. Sign in with a display name, role, and configured
   token. The name and role are self-declared audit labels, not authentication.
   The older developer console is at `/console`; the API reference is at `/docs`.
   Keep this prototype on a trusted local machine: its token mapping is not a production
   identity or deployment boundary.

4. To enable semantic/hybrid retrieval and AI answers, download the embedding model
   explicitly, then have an administrator build the index:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.app.index_cli download-model
   .\.venv\Scripts\python.exe -m backend.app.index_cli sync
   ```

   Alternatively, an administrator can use **Index now** in the Library. Sync again
   after adding documents. To rebuild after changing the embedding model, use
   `.\.venv\Scripts\python.exe -m backend.app.index_cli rebuild`. Run a single server
   worker; do not write to Chroma from a second process while the server is using it.

5. To enable AI workflows, install and start Ollama separately and download the
   configured model:

   ```powershell
   ollama pull qwen3:8b
   ```

   Ollama defaults to `http://localhost:11434`. Document upload and BM25-only
   inspection do not require Ollama; semantic or hybrid search requires the embedding
   model and a synchronized index. CPU-only generation may be slow.

### Frontend development

With Node.js 20+:

```powershell
Set-Location frontend\app
npm ci
npm run dev       # Vite at http://localhost:5173; proxies /api to port 8000
npm test          # frontend unit tests
npm run build     # type-check and rebuild dist/, served by FastAPI
```

### Configuration

All paths default to locations under the repository root; the `data/` directory is
runtime state and is git-ignored.

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_ORG_TOKENS` | `{}` | JSON map of organization names to user tokens |
| `COPILOT_ADMIN_TOKENS` | `{}` | JSON map of organization names to administrator tokens |
| `COPILOT_DB` | `data/corpus.sqlite3` | SQLite document and evidence store |
| `CHROMA_PATH` | `data/chroma` | Persistent vector index |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding model identity |
| `EMBEDDING_MODEL_PATH` | `data/models/bge-m3` | Downloaded local model |
| `EMBEDDING_DEVICE` | `cpu` | Sentence Transformer device |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3:8b` | Ollama model name |
| `OLLAMA_NUM_CTX` | `16384` | Context window |
| `OLLAMA_TIMEOUT` | `300` | Generation timeout in seconds |
| `OLLAMA_THINK` | `false` | Ollama reasoning-mode flag |
| `OLLAMA_PROMPT_CHARS` | Derived from context window | Prompt character budget |
| `AI_CHUNKS_PER_DOCUMENT` | `6` | Evidence excerpts per selected document (1–20) |
| `AI_FOCUS` | `true` | Enable the short answer-first model call |

### Use the application

Upload regulatory PDFs and internal policies in **Library**, enter their metadata,
and select them for review. After indexing, use **Ask** for a regulatory question,
**Changes** to compare two versions, or **Gaps** to compare a regulatory document
with an internal policy. The app displays validated quotations and page references;
open the cited source and verify the evidence before acting. Gap scores are a
deterministic summary of model labels, not an assurance or independent compliance
assessment.

The authenticated API also exposes document upload/import, retrieval, citation
validation, version diff, AI requests, and administrator index operations. Interactive
API schemas are available at `/docs`.

### Crawler and retrieval evaluation

The crawler is an explicit, bounded operation; it is not run by the server:

```powershell
.\.venv\Scripts\python.exe -m backend.app.regulatory_ingest
```

It writes a run report to `data/ingestion-report.json`; inspect failures and unsupported
pagination in the report. Tests mock external HTTP responses, so they do not prove that
live publisher sites are accessible. Respect publisher terms and download limits.

After uploading the bundled SEBI LODR circular and syncing its index, run the
12-question retrieval evaluation:

```powershell
.\.venv\Scripts\python.exe -m backend.app.eval_cli
.\.venv\Scripts\python.exe -m backend.app.eval_cli --modes bm25 --report data\eval-report.json
```

The evaluator reports hit@6, MRR@6, precision@6, recall@6, and F1@6 per search mode
against expected PDF pages. The same harness is available as
``python -m evaluation.run_retrieval``. Semantic/hybrid modes need the downloaded
BGE-M3 model and a built index; the BM25 baseline above is not a general quality
or compliance metric.

### Evaluation package

Offline **evaluation**, **validation**, and **experimentation** live under
[`evaluation/`](evaluation/README.md). Read [`evaluation/ARCHITECTURE.md`](evaluation/ARCHITECTURE.md)
for what RAG includes (plain-text chunks, hybrid search, citation validation) and what
it does not (OCR, structured tables, line-level Q&A index). **RAG** is retrieve →
generate → validate (`backend/app/ai.py`); **CAG** here is the optional context layer
on verified output (`backend/app/cag.py`, same Ollama model as RAG).

| Command | Purpose |
| --- | --- |
| `python -m evaluation.run_retrieval` | Page retrieval metrics (hit/MRR/P/R/F1@k) |
| `python -m evaluation.run_validation` | Batch citation/schema fixtures |
| `python -m evaluation.run_rag` | Mock RAG + CAG smoke (no live Ollama) |
| `python -m evaluation.run_experiment evaluation/experiments/rag_qa_mock.yaml` | Multi-step offline sweep |

Schemas: `evaluation/schemas/`. Run artifacts: `evaluation/reports/` (gitignored).
Future generation gold sets: `datasets/eval/rag/`.

## Tests

Run the backend suite from the repository root:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use temporary databases, synthetic documents, deterministic test embeddings,
and mocked model/network responses; they do not require live AI or publisher access.
The frontend unit tests and production type-check/build are run with the commands in
**Frontend development**.

## Project structure

- `backend/app/` — API, document store/import, retrieval and indexing, AI workflows,
  CAG context layer, version comparison, crawler, and evaluation CLI shims.
- `frontend/app/src/` — React pages, shared UI, API client, and client-side tests.
- `frontend/app/dist/` — committed frontend build served by the backend.
- `datasets/` — official-source registry, evaluation question set, bundled evaluation
  PDF, and dataset notes.
- `evaluation/` — evaluation, validation, and experiment scaffolding, schemas, and reports.
- `tests/` — backend tests and synthetic-only fixtures.
- `data/` — local database, downloaded model, index, and reports; generated at runtime
  and excluded from version control.

## Limitations and future scope

This is a local development prototype, not a production compliance platform. It has no
real identity provider, role provisioning, automated regulatory refresh, OCR, reliable
table extraction, database migration framework, approval/rejection workflow, checklist
tracking, or report export. Search uses fixed 1,200-character windows that may split
words. Retrieved excerpts can miss relevant clauses, and PDF text extraction may not
preserve complex layouts. AI jobs run one at a time in server memory; in-progress jobs
are lost on restart. Automated tests do not establish real-world model quality or legal
accuracy.

Practical next steps include production identity and authorization, schema migrations,
durable job processing, reviewer approval and export, improved OCR/table handling, and
monitored regulatory-source updates. Commercially, possible future models include
per-seat or organization subscriptions, private/on-premise deployments, and paid
document-review services. These are product hypotheses, not current billing, customer
traction, or validated market demand. The current value proposition is a local,
inspectable evidence trail that can reduce manual document searching and help teams
prepare faster, better-grounded reviews.
