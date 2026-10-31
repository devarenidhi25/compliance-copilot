# Comnet — ML solution (RAG + CAG) and evaluation

**Recorded metric values:** [`evaluation/RESULTS.md`](../evaluation/RESULTS.md) and [`evaluation/baselines/`](../evaluation/baselines/).

## Solution summary

Comnet answers compliance research questions by **retrieving** text from uploaded RBI/SEBI PDFs and internal policies, **generating** JSON findings with a **local LLM**, and **rejecting** any quote that does not match stored text. An optional **CAG context layer** (same LLM) summarizes only **validated** statements for reviewers.

## Model stack

| Layer | Technology | Default |
| --- | --- | --- |
| Keyword search | BM25 | In-process |
| Semantic search | Sentence Transformers | `BAAI/bge-m3` |
| Vector DB | ChromaDB | `data/chroma` |
| Hybrid merge | Reciprocal rank fusion | k = 60 |
| RAG generation | Ollama chat JSON | `qwen3:8b` |
| CAG focus pass | Ollama (verified text only) | Same model, `AI_FOCUS=true` |

No fine-tuning, reranker, OCR, or table parser in the current codebase.

## RAG pipeline

1. Ingest PDF → pages → 1,200-character chunks (1,000-char step).
2. `select_evidence`: hybrid search, 6 chunks/document (configurable).
3. Build prompt with metadata + evidence (+ version diffs for comparison).
4. `fit_budget` trim to context limit.
5. Ollama → JSON items → `validate_item` (citations must match chunks sent).

## CAG (this project)

Not a separate model. **`backend/app/cag.py`** exposes `apply_context_layer()` → **`focus.py`**: answer-first summary with validated highlights/key phrases.

## Evaluation · validation · experimentation

| Pillar | CLI | What you get |
| --- | --- | --- |
| Evaluation | `python -m evaluation.run_retrieval` | hit/MRR/P/R/F1/nDCG@k |
| Validation | `python -m evaluation.run_validation` | 6/6 synthetic citation cases |
| Experiment | `python -m evaluation.run_experiment …` | Manifest + step JSON |

See **RESULTS.md** for the latest **numeric table** (e.g. LODR hit@6: BM25 **0.833**, semantic/hybrid **1.000** on the recorded run).
