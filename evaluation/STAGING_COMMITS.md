# Staging split for RAG/CAG work (commits 5a and 5b)

## Commit 5a — CAG module (product)

```powershell
git add backend/app/cag.py backend/app/product.py tests/test_cag.py evaluation/ARCHITECTURE.md
git commit -m "Add CAG context layer module wrapping validated focus pass."
```

## Commit 5b — RAG/CAG evaluation harnesses

```powershell
git add evaluation/metrics/rag.py evaluation/metrics/cag.py evaluation/metrics/__init__.py `
  evaluation/harness/rag.py evaluation/harness/cag.py `
  evaluation/run_rag.py evaluation/run_cag.py `
  tests/test_evaluation_rag.py evaluation/README.md evaluation/STAGING_COMMITS.md
git commit -m "Add RAG and CAG context evaluation harnesses."
```
