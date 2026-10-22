# Verification — 22 October 2026

## Automated tests

Full suite: **90 passed, 0 failed** (Linux, Python 3.13).

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

`tests/conftest.py` points the database, Chroma and model paths at temporary folders
for every test, so the suite never writes to `data/` and is not affected by a model
downloaded on the developer's machine (previously, a downloaded model made the
missing-model test fail).

Also run: frontend script syntax check (`node --check` on the page's module script),
and the server started with `uvicorn backend.app.main:app` from a directory other than
the repository root (page served, API answered, tenant token refused on the admin
endpoint).

## What the tests cover

Carried over: ingestion, hashing, metadata provenance, page/chunk mapping, version
families, duplicate rejection, citations, official URL restrictions and import,
organization isolation, BM25/semantic/hybrid retrieval and RRF, persistent Chroma,
index sync/rebuild/failure handling, model download and local-only loading, crawler
discovery and versioning, and all four AI workflows with mocked model output.

Added in this round:

- **Citations:** whitespace and curly-quote/dash tolerant matching that returns the
  exact original span; too-short quotes rejected.
- **AI generation:** compact evidence; `num_ctx` and `think: false` sent to Ollama;
  prompt budget trimming (weakest evidence first, one excerpt per document kept,
  page differences capped); per-item validation with `rejected_items`; gap items need
  one regulatory and one internal citation; Q&A notes ignored internal documents;
  specific errors for timeout, unreachable Ollama, out-of-memory, missing model,
  non-JSON and empty output; `AI_CHUNKS_PER_DOCUMENT`.
- **Search:** unfiltered search skips and reports unindexed documents; explicit
  selection still fails closed.
- **Visibility:** tenant regulatory uploads private, admin uploads and imports shared,
  tenants blocked from shared families, identical errors for missing and foreign
  families, malformed token JSON rejected at startup.
- **Comparison:** an inserted page is one change; date-based version ordering; API
  change list; AI comparison sends aligned changes and changed-page evidence.
- **Crawler:** "Read more" not treated as pagination; postback pagination reported;
  download errors vs. extraction failures classified by stage; 20 MiB streaming cap;
  4xx not retried; gzip decoded once.
- **Portability:** importing the app creates nothing; repository-root path defaults;
  frontend served from any working directory; in-server admin index job.
- **Hardening:** sandboxed HTML sources, `nosniff`, database indexes, foreign keys.
- **Evaluation:** hit@k/MRR@k computation, unavailable-mode reporting, and a check
  that the bundled question file matches the bundled PDF's hash.

## End-to-end checks on the real SEBI LODR Master Circular (291 pages)

Run through the HTTP API with the test embedder and a stand-in for Ollama:
administrator upload (shared, 4.5 s); visible to another organization; tenant refused
on the index job; in-server index job completed; hybrid search returned results;
AI Q&A accepted a grounded item and rejected a fabricated quotation with its reason;
an administrator added a second version (one page inserted, one removed) while a
tenant was refused; comparison reordered the versions by date and reported exactly two
changes with correct page numbers; the unindexed second version was keyword-searched
and reported. For four selected documents the AI prompt is about 20,000 characters
(previously about 58,000); the line-aligned diff of the full circular takes 0.24 s.

Retrieval evaluation (`datasets/eval/lodr_master_circular.json`, 12 questions),
BM25 only: **hit@6 0.833, MRR@6 0.750**. Semantic and hybrid scores need the
BGE-M3 weights and should be recorded on a machine that has them.

## Live run on a team machine (Windows, CPU only)

With qwen3:8b, regulatory Q&A on the circular ("What is the timeline for disclosing
material events to stock exchanges?") returned a cited answer giving the 30-minute,
12-hour and 24-hour disclosure timelines with no rejected items. That run used Phase 1
and the thinking/error-reporting fix. Before those fixes the same request failed:
qwen3's thinking mode produced an empty JSON object and generation exceeded the
300-second timeout at about 3.7 output tokens per second.

## Not verified here

Real BGE-M3 inference and semantic/hybrid evaluation scores, real Ollama output beyond
the single live Q&A above, live crawling of RBI/SEBI sites, and interactive browser
behavior (the new admin panel, quote validation prompt and sandboxed HTML viewer were
syntax-checked, not clicked through).
