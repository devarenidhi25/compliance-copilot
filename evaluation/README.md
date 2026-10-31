# Evaluation, validation, and experimentation

This folder holds **offline** tooling for Comnet: measuring retrieval, validating
citations, running RAG/CAG smoke tests, and comparing experiment configs. It does
not run at application startup and does not change product behavior until harnesses
are wired in later commits.

## Three pillars

| Pillar | Purpose | Status |
| --- | --- | --- |
| **Evaluation** | Metrics and reports (retrieval, RAG, CAG context layer) | Scaffold + schemas (commit 1); harnesses follow |
| **Validation** | Batch checks that quotes and AI items match store rules | Planned (`evaluation/harness/validation.py`) |
| **Experimentation** | YAML-defined sweeps writing to `evaluation/reports/` | Planned (`evaluation/run_experiment.py`) |

## Terminology

- **RAG** — Hybrid retrieval → evidence prompt → Ollama → citation validation (`backend/app/ai.py`).
- **CAG (here)** — **C**ontext layer: trimmed evidence window plus optional **focus**
  pass on verified statements only (`backend/app/focus.py`). Same Ollama model as RAG;
  not a separate embedding or weight file.

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for ingestion limits (no OCR/tables), chunking,
and when line-aligned diffs are used.

## Report schemas

JSON Schema drafts live under `evaluation/schemas/`:

- `retrieval_report.v1.json` — page-level retrieval metrics per mode
- `rag_report.v1.json` — end-to-end generation and citation stats
- `validation_report.v1.json` — batch citation/schema cases
- `experiment_manifest.v1.json` — multi-step run summary

Templates (committed): `evaluation/reports/TEMPLATE_*.json`.  
Machine runs write under `evaluation/reports/<run-id>/` (gitignored).

## Running retrieval evaluation (today)

Until harnesses move here, use the existing CLI from the repository root:

```powershell
.\.venv\Scripts\python.exe -m backend.app.eval_cli
.\.venv\Scripts\python.exe -m backend.app.eval_cli --modes bm25 --report data\eval-report.json
```

Gold questions: `datasets/eval/lodr_master_circular.json` (upload the bundled PDF and sync the index first).

Planned metrics per mode (in addition to hit@k and MRR@k): **precision@k**, **recall@k**, **F1@k**, **recall@1**.

## Models and parameters to record in every report

| Parameter | Env / default |
| --- | --- |
| Embedding | `EMBEDDING_MODEL` → `BAAI/bge-m3` |
| Retrieval modes | `bm25`, `semantic`, `hybrid` |
| LLM | `OLLAMA_MODEL` → `qwen3:8b` |
| Context | `OLLAMA_NUM_CTX`, `OLLAMA_PROMPT_CHARS` |
| Evidence depth | `AI_CHUNKS_PER_DOCUMENT` (default 6) |
| Focus (CAG layer) | `AI_FOCUS` (default true) |

## Experiments

Author configs under `evaluation/experiments/` (see [experiments/README.md](experiments/README.md)).
Run the experiment CLI once implemented:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiment evaluation\experiments\lodr_retrieval.yaml
```

Use a **single** server worker while indexing; do not write to Chroma from a second process while the API is using it.

## Perplexity and other LM metrics

Optional **perplexity** is not available from the Ollama chat API. A future
`evaluation/metrics/lm.py` may support held-out text via Hugging Face models behind an
explicit flag; such scores are experimental and are not compliance metrics.
