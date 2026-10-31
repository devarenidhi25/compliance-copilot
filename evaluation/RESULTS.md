# Recorded evaluation results

Numbers below come from **explicit runs** on this repository (see `evaluation/baselines/*.json` for raw JSON and `run.git_commit`). They measure **retrieval and rule compliance**, not legal accuracy or compliance certification.

**Last recorded:** 2026-10-31 (UTC) · **Git:** see `run.git_commit` in each baseline file · **Corpus:** SEBI LODR Master Circular ingested locally (`document_id` in retrieval baseline)

---

## 1. Retrieval — LODR 12 questions, k = 6

**Gold file:** `datasets/eval/lodr_master_circular.json`  
**Index:** BGE-M3 embeddings synced via `index_cli sync` (Windows CPU, ~18 min for LODR).

| Mode | hit@6 | MRR@6 | precision@6 | recall@6 | F1@6 | nDCG@6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **BM25** | **0.833** | **0.750** | **0.375** | **0.646** | **0.445** | **0.824** |
| **Semantic** | **1.000** | **1.000** | **0.625** | **0.896** | **0.712** | **1.375** |
| **Hybrid** | **1.000** | **0.861** | **0.542** | **0.854** | **0.637** | **1.150** |

Raw JSON: `evaluation/baselines/lodr_retrieval_all_modes.json`.

**BM25-only misses (no expected page in top 6):** `market-rumours`, `loan-defaults` (10/12 hits). Semantic and hybrid retrieve a gold page for all 12 questions on this run.

Reproduce:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_retrieval --modes bm25,semantic,hybrid --report evaluation\baselines\lodr_retrieval_all_modes.json
```

---

## 2. Validation — citation & schema batch

**Suite:** `evaluation/fixtures/validation/suite.json` (synthetic PDFs, no Ollama)

| Metric | Value |
| --- | ---: |
| Cases | 6 |
| Passed (expectation met) | **6** |
| Failed | **0** |

Reproduce: `python -m evaluation.run_validation`

---

## 3. Mock RAG + CAG smoke (offline)

Synthetic one-page PDF, mocked Ollama JSON, real hybrid retrieval + citation validation.

| Metric | Value |
| --- | ---: |
| items_proposed | 1 |
| items_accepted | 1 |
| **citation_acceptance_rate** | **1.0** |
| evidence_excerpts | 1 |
| context_chars (before/after budget) | 1567 / 1567 |
| context_trimmed | false |
| **focus_success** (CAG layer) | **true** |
| highlights_kept | 1 |
| key_phrases_kept / offered | 1 / 1 |
| Ollama model (config) | qwen3:8b |
| prompt_char_budget | 36864 |

Reproduce: `python -m evaluation.run_rag` or  
`python -m evaluation.run_experiment evaluation/experiments/rag_qa_mock.yaml`

---

## 4. Experiment manifest (rag_qa_mock)

| Step | Status |
| --- | --- |
| citation_validation_suite | success |
| rag_cag_mock_smoke | success |

**Perplexity:** not available (Ollama chat API; see `evaluation/metrics/lm.py`).

---

## 5. Models used in these runs

| Component | Model / method |
| --- | --- |
| Lexical retrieval | BM25 (`rank_bm25`) |
| Semantic retrieval | BGE-M3 (`BAAI/bge-m3`) when index synced |
| Hybrid | RRF (k = 60) |
| Generation & CAG focus | qwen3:8b via Ollama (mocked in smoke test) |

---

## 6. Not yet measured (needs gold data or live LLM)

| Metric | Status |
| --- | --- |
| End-to-end RAG on 12 LODR questions | No generation gold in `datasets/eval/rag/` |
| Gap assessment F1 | No labeled reg+internal pairs |
| Perplexity | Not exposed by Ollama |
| Live Ollama citation rate on LODR | Run via product API after Ollama up |

---

Full solution architecture: [`docs/SOLUTION_AND_EVALUATION.md`](../docs/SOLUTION_AND_EVALUATION.md)
