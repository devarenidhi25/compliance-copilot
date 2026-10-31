# RAG / generation gold sets (future)

Retrieval gold for the bundled SEBI LODR circular lives in
[`../lodr_master_circular.json`](../lodr_master_circular.json) (expected **pages** only).

This directory is reserved for **end-to-end RAG** fixtures: questions with optional
expected statements, assessment labels, or citation spans. None are bundled yet;
mock smoke tests use synthetic PDFs under `evaluation/harness/rag.py`.

When adding files here:

- Keep documents matched by `content_hash` like the retrieval eval file.
- Record `OLLAMA_MODEL`, retrieval mode, and `AI_CHUNKS_PER_DOCUMENT` in experiment manifests.
- Do not treat automated scores as compliance or legal conclusions.
