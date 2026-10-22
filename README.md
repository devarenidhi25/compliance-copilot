# Compliance Copilot — grounded hybrid retrieval

A locally runnable compliance assistant built with FastAPI, SQLAlchemy/SQLite, PyMuPDF,
BM25 and persistent Chroma vectors (BGE-M3), and a local Ollama model. It supports PDF
upload, restricted official RBI/SEBI URL import, explicit metadata provenance, immutable
version families, page-scoped chunks, citation validation, organization-isolated
internal policies, line-aligned version comparison, and hybrid search with reciprocal
rank fusion (RRF). No regulatory documents are seeded. A small browser interface is
served by the backend.

Four AI workflows (Q&A, version comparison, gap analysis, checklist) answer only from
selected stored evidence. Every accepted statement carries quotations that are
validated against the stored source text; unsupported statements are dropped and
reported. This is a local development application, not a production compliance
platform, and it makes no legal determinations.

## Run

Python 3.10+ is supported. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install --upgrade pip==25.2
.venv/bin/pip install -r backend/requirements.txt
export COPILOT_ORG_TOKENS='{"your-organization":"replace-with-a-strong-unique-token"}'
export COPILOT_ADMIN_TOKENS='{"your-organization":"replace-with-a-different-admin-token"}'
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

On Windows (Git Bash) the virtual-environment folder is `Scripts` instead of `bin`, for
example `.venv/Scripts/uvicorn ...` and `.venv/Scripts/python -m ...`. The requirements
install CPU-only PyTorch on Windows and Linux and the standard PyTorch wheel on macOS.
If your system drive is short of space, set `PIP_CACHE_DIR`, `HF_HOME` and (for Ollama)
`OLLAMA_MODELS` to folders on another drive before installing or downloading.

Open `http://127.0.0.1:8000` and sign in with your name, your role and a configured
token as the access code. The previous developer page remains at `/console`, and the
API reference is at `/docs`. Keep this server local; token mapping is development
authentication, not a replacement for real identity management.

## Web app

The client-facing app (React, TypeScript, Vite) lives in `frontend/app/`. Its built
files in `frontend/app/dist/` are committed, so running the server is enough: Node is
only needed to change the app.

| Page | What it does |
| --- | --- |
| Sign in | Name, role (Compliance Officer, Legal, Risk, Executive) and access code. The role orders the home page and is recorded in the audit trail. |
| Home | Tasks in the order most useful for the role, library status, recent AI activity. |
| Ask | A question or an action checklist over up to four regulations. Statements carry numbered citations; selecting one opens the PDF at the page with the quoted words highlighted. Removed statements are listed with the reason. |
| Library | Documents grouped into version families with page counts, visibility and index status; upload drawer (including "new version of an existing document"); administrators can index from here. |
| Change detection | Pick a document and two versions; every added, removed or modified passage with page links in both versions, and an optional AI explanation. |
| Gap analysis | Pick a regulation and an internal policy; compliance score, findings sorted by risk, and the regulation's words beside the policy's for each finding. |
| Audit trail | Every AI request with who asked, the role, documents, model, timing, outcome and the full recorded result. |

AI requests run as background jobs, one at a time, with live progress (finding evidence,
drafting, checking quotes). Reviewers can leave the page and come back to the result.
The gap score is computed from the model's labels, not by the model: Addressed counts 1,
Partially addressed 0.5, Potential gap or Possible conflict 0, and Insufficient evidence
is left out of the score and shown as "Needs review".

To change the app (Node 20 or newer):

```sh
cd frontend/app
npm ci
npm run dev     # http://localhost:5173, API calls proxied to the server on port 8000
npm test        # unit tests for quote highlighting and version grouping
npm run build   # type-check and rebuild dist/, which the server serves
```

The app's API is under `/api/app` (`me`, `library`, `jobs`, `compare`, `audit`) and is
additive: the original endpoints are unchanged. The name and role sent with requests
are self-declared display values for the audit trail, not authentication.

### Tokens and document visibility

- `COPILOT_ORG_TOKENS` maps organization names to tokens. A token's organization decides
  which internal documents it can see.
- `COPILOT_ADMIN_TOKENS` uses the same format. An administrator token belongs to its
  organization and can additionally write to the shared library and run index jobs.
- Malformed token JSON stops the server at startup with a clear message.

| Document | Who can see it |
| --- | --- |
| Internal policy / SOP | The uploading organization only |
| Regulatory PDF uploaded with an organization token | The uploading organization only |
| Regulatory PDF uploaded with an administrator token | Everyone (shared library) |
| Official URL import or crawler ingestion (host-verified) | Everyone (shared library) |

Only administrators can add versions to a shared document family. The interface labels
every document as shared or organization-only and shows whether each metadata field is
user supplied or verified.

## Local AI with Ollama

Install Ollama, then pull the model (on Windows the Ollama app runs in the background
after installation, so `ollama serve` is usually unnecessary):

```sh
ollama pull qwen3:8b
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen3:8b` | Model name; `qwen3:4b` is about twice as fast on CPU |
| `OLLAMA_NUM_CTX` | `16384` | Context window sent with every request (Ollama's own default silently truncates long prompts) |
| `OLLAMA_TIMEOUT` | `300` | Seconds allowed per generation; raise it on CPU-only machines |
| `OLLAMA_THINK` | `false` | Reasoning mode; keep off for qwen3, which otherwise returns an empty JSON object |
| `AI_CHUNKS_PER_DOCUMENT` | `6` | Evidence excerpts per selected document (1–20); lower it to speed up CPU generation |
| `OLLAMA_PROMPT_CHARS` | derived from `OLLAMA_NUM_CTX` | Prompt size budget; lowest-ranked excerpts are dropped first, one per document is always kept |

Suggested CPU-only settings: `OLLAMA_NUM_CTX=8192`, `OLLAMA_TIMEOUT=900`,
`AI_CHUNKS_PER_DOCUMENT=3`. Failures report the specific cause: timeout, Ollama
unreachable, Ollama errors such as insufficient memory, missing model, or output that
is not JSON. Successful responses include `generation_seconds`, the model and the
number of evidence excerpts used. Ingested documents remain usable when Ollama is off.

## Embedding model and search index

Model weights are never downloaded during installation, upload, search or startup.
Download them explicitly (about 2.3 GB; internet, disk and RAM required):

```sh
.venv/bin/python -m backend.app.index_cli download-model
```

The default model is `BAAI/bge-m3`, loaded locally with Sentence Transformers. The
command records the exact Hub snapshot revision under `data/models/bge-m3/`. No hosted
inference receives your documents. Restart the server after downloading a model.

After uploading documents, index them. The recommended way is the **Search index
(administrator)** panel in the interface, or the equivalent API, which runs the job
inside the server process in the background:

```sh
curl -X POST "http://127.0.0.1:8000/api/admin/index/sync" -H "Authorization: Bearer <admin-token>"
curl "http://127.0.0.1:8000/api/admin/index/sync" -H "Authorization: Bearer <admin-token>"   # job status
```

Add `?rebuild=true` for a full rebuild, needed after changing the embedding model.
The command-line equivalents (`index_cli sync`, `rebuild`, `status`) still work, but
Chroma's store is not designed to be written by a second process while the server
reads it: stop the server first, or restart it afterwards.

Rebuilds stage a new collection and switch over only after success; a failed rebuild
keeps the previous index. Old collections are retained and consume disk. Incremental
sync upserts stable chunk IDs and never duplicates vectors. Run a single server worker.

### Paths and configuration

Default paths resolve from the repository root, so the server and tools work from any
working directory. Environment variables override them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_DB` | `data/corpus.sqlite3` | Authoritative document/page/chunk database |
| `CHROMA_PATH` | `data/chroma` | Persistent vectors and active-index manifest |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Model identity to download/use |
| `EMBEDDING_MODEL_PATH` | `data/models/bge-m3` | Local model directory with setup marker |
| `EMBEDDING_DEVICE` | `cpu` | Inference device |

The index records the resolved corpus path; after moving the database, rebuild.

## Search

`POST /api/retrieval/search` accepts `query`, `mode` (`bm25`, `semantic`, `hybrid`),
`limit` (1–20) and optional `filters`: `document_ids`, `regulator`, `kind`,
`family_id`, `version` and `document_type`. Results keep exact text, physical PDF
page, chunk/document/family IDs, visibility and metadata provenance.

When a search is not restricted to explicit `document_ids`, documents that are not yet
indexed are searched by keyword only and listed in `unindexed_documents`, so one new
upload does not break search for everyone. Explicitly selected documents, as AI
generation uses, must be fully indexed; there is no silent keyword-only AI fallback.

BM25 tokenizes lowercase Unicode words; semantic search uses normalized dense vectors
and cosine distance. Hybrid search merges the top 20 candidates per retriever using RRF
(constant 60). Ranking scores are not compliance probabilities.

## AI workflows

- **Q&A** answers from the selected regulatory documents; selected internal documents
  are not used, and the response says so.
- **Checklist** proposes reviewable actions from the selected documents.
- **Gap analysis** needs regulatory and internal documents; each finding must cite at
  least one of each and carry one label: `APPEARS_ADDRESSED`, `PARTIALLY_ADDRESSED`,
  `POTENTIAL_GAP`, `POSSIBLE_CONFLICT` or `INSUFFICIENT_EVIDENCE`.
- **Comparison** needs two versions from one family. Versions are ordered by effective
  date, then publication date, then upload time. Changes are found by aligning lines
  across the whole document, so an inserted page is one change rather than every later
  page; the first ten changes and evidence from the changed pages are sent to the model.

Quotations are matched ignoring whitespace and typographic quote/dash differences, must
be at least 12 characters (unless the whole chunk), and the stored citation is always
the exact original source span. Each model item is validated independently: items with
an unsupported quotation, a chunk ID that was not provided, missing required citations
or an invalid label are dropped and listed in `rejected_items` with the reason. The
request fails only when no item survives. Every item remains `pending_human_review`.
Citation validation checks provenance, not whether the interpretation is correct.

`GET /api/compare?old=…&new=…` returns the text diff and a list of changed passages with
their page ranges in both versions, without AI interpretation.

## Official-source crawler and evaluation

`python -m backend.app.regulatory_ingest` performs bounded ingestion from the listing
pages in `datasets/official_sources.json` into the shared library. RBI listings
paginate with ASP.NET postbacks, which are not followed; the report lists them under
`unfollowed_pagination`. See [datasets/README.md](datasets/README.md) for sources,
versioning and the retrieval evaluation (`python -m backend.app.eval_cli`), which
reports hit@6 and MRR@6 per search mode for a question set with known answer pages.

## Tests

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

On Windows Git Bash: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/Scripts/python -m pytest -q`.
Tests use synthetic PDFs in temporary databases, deterministic test-only embeddings and
mocked network/model responses. They are isolated from your `data/` folder and any
downloaded model, and never download documents or models.

## Known limits

The web app has unit tests for its logic but no automated browser tests in the suite; it
was checked by a scripted browser walkthrough (see TEST_REPORT.md). Tests do not measure
BGE-M3 or Ollama answer quality; use the evaluation tool and manual review for that.
Chunks are fixed 1,200-character windows that can split words. AI jobs are held in
server memory: a job running when the server restarts is lost and its audit entry is
marked as interrupted, while finished results remain in the audit trail. Approving or rejecting
findings, checklist tracking, report export, persona summaries, real identity management
and database migrations are not implemented yet.
