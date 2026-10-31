# Evaluation, validation, and experimentation

This folder holds **offline** tooling for Comnet: measuring retrieval, validating
citations, running RAG/CAG smoke tests, and comparing experiment configs. It does
not run at application startup.

**Recorded numbers:** [`RESULTS.md`](RESULTS.md) · raw JSON: [`baselines/`](baselines/) · refresh: `python -m evaluation.record_baselines --all`

## Three pillars

| Pillar | Purpose | Status |
| --- | --- | --- |
| **Evaluation** | Metrics and reports (retrieval, RAG, CAG context layer) | Retrieval + RAG/CAG mock harnesses |
| **Validation** | Batch checks that quotes and AI items match store rules | `python -m evaluation.run_validation` |
| **Experimentation** | YAML-defined sweeps writing to `evaluation/reports/` | `python -m evaluation.run_experiment` |

## Terminology

- **RAG** — Hybrid retrieval → evidence prompt → Ollama → citation validation (`backend/app/ai.py`).
- **CAG (here)** — **C**ontext layer: trimmed evidence window plus optional **focus**
  pass on verified statements only (`backend/app/cag.py` → `focus.py`). Same Ollama
  model as RAG; not a separate embedding or weight file.

Mock end-to-end: ``python -m evaluation.run_rag`` (RAG + context metrics).

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

## Running retrieval evaluation

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_retrieval
.\.venv\Scripts\python.exe -m backend.app.eval_cli --modes bm25 --report data\eval-report.json
```

Gold questions: `datasets/eval/lodr_master_circular.json` (upload the bundled PDF and sync the index first).

Per mode: **hit@k**, **MRR@k**, **precision@k**, **recall@k**, **F1@k**, **nDCG@k** (in JSON reports).

## Validation and RAG/CAG smoke

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_validation
.\.venv\Scripts\python.exe -m evaluation.run_rag
.\.venv\Scripts\python.exe -m evaluation.run_cag
```

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

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiment evaluation\experiments\rag_qa_mock.yaml
.\.venv\Scripts\python.exe -m evaluation.run_experiment evaluation\experiments\lodr_retrieval.yaml
```

Use a **single** server worker while indexing; do not write to Chroma from a second process while the API is using it.

## Perplexity and other LM metrics

**Perplexity** is not available from the Ollama chat API. `evaluation/metrics/lm.py`
records status in experiment manifests; setting `EVAL_PERPLEXITY=1` is reserved for a
future Hugging Face held-out text path. Such scores are experimental and are not
compliance metrics.

## Tests

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_metrics.py tests/test_evaluation_validation.py tests/test_evaluation_rag.py tests/test_evaluation_experiment.py tests/test_cag.py -q
```
