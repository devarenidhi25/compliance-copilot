# Evidence and AI architecture (evaluation view)

This document describes what Comnet actually stores, indexes, and sends to models.
Use it when interpreting retrieval, RAG, and CAG evaluation numbers. It is not a
legal or compliance certification.

## Ingestion

| Step | Implementation | Notes |
| --- | --- | --- |
| PDF upload | `backend/app/store.py` → PyMuPDF `page.get_text('text', sort=True)` | Searchable PDF required; **no OCR** |
| HTML import | `ingest_html` → section title + body as pseudo-pages | Optional `section` on chunks |
| Limits | 20 MiB file, 1000 pages max, 10M chars extracted text | Encrypted PDFs rejected |

**Not implemented:** reliable **table extraction**, layout-aware parsing, cell-level
structure, or a separate “data context” store. Table content may appear as plain text
lines in a page; columns and headers are not guaranteed to survive extraction.

## Storage layers

1. **`documents`** — PDF blob, metadata JSON (title, regulator, dates, source URL, …).
2. **`pages`** — one row per PDF page with full page text.
3. **`chunks`** — retrieval and citation units:
   - Window size **1,200 characters**, step **1,000** characters (200-character overlap).
   - Scoped to a **page**; windows can split words or sentences.
   - Optional **`section`** label (mainly HTML imports).

## Retrieval (index)

| Mode | Mechanism |
| --- | --- |
| BM25 | Token match over chunk text (`rank_bm25`) |
| Semantic | Local **BGE-M3** embeddings in ChromaDB |
| Hybrid | Reciprocal rank fusion (constant **60**) over BM25 + semantic rankings |

Search operates on **chunk content** only. There is no line-level index for Q&A and
no table-specific index.

## RAG (retrieve → generate → validate)

Primary code: `backend/app/ai.py`, `backend/app/retrieval.py`.

1. **`select_evidence`** — hybrid search, top **`AI_CHUNKS_PER_DOCUMENT`** chunks per selected document (default 6).
2. **Prompt assembly** — task, question, document metadata, compact evidence (`chunk_id`, page, text), and for **comparison** only: **`stored_page_differences`** from `backend/app/compare.py`.
3. **`fit_budget`** — drops lowest-ranked evidence (keeps at least one chunk per document) and trims diffs to fit **`OLLAMA_NUM_CTX`** / **`OLLAMA_PROMPT_CHARS`**.
4. **Ollama** — local model (default **`qwen3:8b`**) with JSON output.
5. **`validate_item`** — every citation must reference a chunk that was **sent** in the prompt; quotes must match stored chunk text (whitespace/typography tolerant).

### Workflow-specific context

| Workflow | Extra context beyond retrieved chunks |
| --- | --- |
| Q&A | Regulatory documents only (internal selections noted, not used) |
| Comparison | Line-aligned **version diff** hunks; chunks from **changed pages** prioritized |
| Gap analysis | Regulatory + internal chunks; assessment labels in schema |
| Checklist | Same evidence pattern as Q&A with checklist-oriented schema |

**Line-by-line comparison** is **not** part of general Q&A RAG. It applies only to
the **Changes / comparison** workflow via `compare.py` (`difflib` on normalized lines
across stored page text).

## CAG (project terminology)

Comnet does **not** ship a separate “CAG model” or cache-augmented weights. In
evaluation and docs, **CAG** means the **context layer** on top of validated RAG output:

1. **Fixed evidence window** — whatever survived `fit_budget` (trimmed, ranked excerpts).
2. **Focus pass** — after citations pass validation, an optional second Ollama call builds
   an answer-first summary from **verified statements only** (`AI_FOCUS`, default on).
   Implementation: `backend/app/focus.py`; product entry point: `backend/app/cag.py`
   (`apply_context_layer`). Output is validated (highlights, key phrases); failures are non-fatal.

## What evaluation can and cannot claim

| Measurable today | Not measurable without new data or features |
| --- | --- |
| Page in top-k (LODRE JSON gold) | Table understanding |
| Hit@k, MRR@k (existing CLI) | Full-document recall |
| P/R/F1@k (planned in `evaluation/metrics`) | Legal correctness |
| Citation accept/reject rate (RAG harness) | Perplexity from Ollama chat API |
| Comparison diff coverage | OCR quality |

Recorded BM25 baseline on bundled LODR questions (12 items): **hit@6 0.833**, **MRR@6 0.750**
— retrieval only, not end-to-end RAG quality.
