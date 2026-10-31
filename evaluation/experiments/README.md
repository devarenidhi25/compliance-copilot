# Experiment configs

YAML files in this directory describe repeatable evaluation sweeps. The experiment
runner (added in a later commit) will:

1. Load the config from the repository root.
2. Execute each step (retrieval, validation mock, RAG mock, …).
3. Write JSON under `evaluation/reports/<timestamp>/` plus a manifest.

## Conventions

- Paths in configs are relative to the **repository root**.
- Prefer **`mock: true`** steps in CI; **`live: true`** only on a machine with Ollama, the embedding model, and an indexed corpus.
- Record `git` commit hash in the manifest when the runner supports it.

## Planned examples

| File | Intent |
| --- | --- |
| `lodr_retrieval.yaml` | BM25 / semantic / hybrid on LODR question set |
| `rag_qa_mock.yaml` | Mock Ollama Q&A smoke test |

Configs will be added alongside `evaluation/run_experiment.py`.
