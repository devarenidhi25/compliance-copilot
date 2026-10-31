# Validation (batch citation checks)

**Validation** here means proving that model-shaped items obey the same rules as
production `validate_item` in `backend/app/ai.py`: chunk IDs must be in the
evidence set, quotes must match stored text, gap items need regulatory and internal
citations, and assessment labels must be allowed.

This is separate from **retrieval evaluation** (page hit rates) and from **RAG**
runs that call Ollama. No network or model is required.

## Run the default suite

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_validation
.\.venv\Scripts\python.exe -m evaluation.run_validation --report evaluation\reports\validation-last.json
```

Fixtures: `evaluation/fixtures/validation/suite.json` (synthetic PDFs only).

Exit code **1** if any case fails expectation.

## Add cases

Each case ingests one or more synthetic documents, builds citations with
`chunk_index` / `document_index`, and sets `expect_pass` plus optional
`reason_contains` for expected rejections.
