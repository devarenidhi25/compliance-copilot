# Experiment configs

YAML (or JSON) files describe repeatable evaluation sweeps. The runner:

1. Loads the config from the repository root.
2. Executes each step (retrieval, validation, RAG mock, …).
3. Writes JSON under `evaluation/reports/<timestamp>_<id>/` plus `manifest.json`.

## Run

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiment evaluation\experiments\rag_qa_mock.yaml
.\.venv\Scripts\python.exe -m evaluation.run_experiment evaluation\experiments\lodr_retrieval.yaml
```

`lodr_retrieval.yaml` needs the evaluation PDF uploaded and the index synced on your machine.
`rag_qa_mock.yaml` is fully offline (validation + mock RAG/CAG).

## Conventions

- Paths in configs are relative to the **repository root**.
- **`mock`** steps need no Ollama; **`retrieval`** steps use `data/corpus.sqlite3` (or `COPILOT_DB`).
- The manifest records `git_commit` when git is available.

## Bundled configs

| File | Steps |
| --- | --- |
| `lodr_retrieval.yaml` | BM25, semantic, hybrid on LODR questions |
| `rag_qa_mock.yaml` | Validation suite + mock RAG/CAG smoke |

PyYAML is required for `.yaml` configs (already present via project dependencies).
