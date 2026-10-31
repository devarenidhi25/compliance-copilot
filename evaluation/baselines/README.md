# Committed evaluation baselines

These JSON files are **snapshots** from explicit runs (machine, date, git commit in each file).
Re-run locally to refresh; numbers are **not** compliance scores.

| File | Description |
| --- | --- |
| `lodr_retrieval_bm25.json` | 12-question LODR page retrieval, BM25 only |
| `lodr_retrieval_all_modes.json` | BM25 + semantic + hybrid (after index sync) |
| `rag_qa_mock_smoke.json` | Offline validation + mock RAG/CAG |
| `manifest_rag_qa_mock.json` | Experiment manifest for the smoke run |

Regenerate retrieval baselines after uploading the bundled PDF and syncing the index:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_retrieval --report evaluation\baselines\lodr_retrieval_bm25.json
```
