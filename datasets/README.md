# Dataset and document strategy

## Empty by default

There is no bundled regulatory dataset and no startup seeding. `data/corpus.sqlite3`
starts with empty tables. Runtime code never reads `tests/fixtures`. Use actual
PDFs uploaded by your organization or downloaded from official sources.

Find documents manually at RBI's [notifications](https://www.rbi.org.in/Scripts/NotificationUser.aspx)
and [master directions](https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx),
and SEBI's [legal library](https://www.sebi.gov.in/legal.html). Follow the publisher's
PDF download link, check title, circular number, publication date, effective date,
update date and applicability against the document and official landing page.
Some consolidated directions change at the same URL: preserve each downloaded
snapshot. A publication date is not necessarily its effective date.

## Ingest

Run the server as described in the root README. Open the library, authenticate with
your organization token, and upload a searchable PDF or supply a direct official
PDF URL. API examples and schemas are at `/docs`. Import performs one HTTPS request:
no crawling, automatic link discovery, redirects, retries, or CAPTCHA bypass.
Allowed hosts are exactly `rbi.org.in`, `www.rbi.org.in`, `website.rbi.org.in`,
`rbidocs.rbi.org.in`, `sebi.gov.in`, and `www.sebi.gov.in`. Other hosts are rejected.
HTML landing pages must be opened manually to locate the direct PDF. If a site
blocks access, use a permitted manual download; respect publisher terms and
restrictions. The importer does not infer a right to bulk-download documents.

Limits: 20 MiB, 1000 pages, 10 million extracted characters, unencrypted searchable
PDFs. Image-only scans receive an OCR instruction; this stage does not run OCR.
Blank pages are preserved even when they have no chunks. Page numbers refer to
1-based PDF physical pages, which may differ from printed page labels.

## Metadata and versions

Title, regulator, type, source URL, publication date, version label and effective
date are recorded per immutable document version. Optional values remain `unknown`;
entered values are `user_supplied`. A successful official URL import labels the
fetched source URL and host-derived regulator `verified`; this does not verify
title, dates, legal applicability or interpretation. Uploading a file and typing
an official URL does **not** verify the file's origin. SHA-256 is computed over
original PDF bytes; upload time is a server-generated UTC timestamp.

Every upload receives a document UUID and a family UUID. To add another version,
copy the existing family ID into the upload/import form and provide a meaningful
version label and dates from the source. Different content is stored separately;
identical content in the same family is rejected. Previous bytes, pages and chunks
are retained. Families cannot change regulator, document scope or organization.
Text comparison takes two actual stored version IDs in the same family. Date
order is selected explicitly by the user; dates do not silently select a version.

## Organization isolation

Regulatory PDFs form a shared official-document library. Internal policies and
SOPs require an organization scope resolved from a server-managed bearer token.
List, PDF, chunks, citation validation, comparison and AI routes apply that scope.
Clients cannot select an organization by changing a form field. Server administrators
remain able to access the database; this is a local prototype, not enterprise IAM.
Use strong unique tokens and local-only hosting. No token is stored in the browser.

## Citation verification

Chunks never cross pages. Each stores document UUID, stable chunk UUID, PDF page,
start/end character offsets into extracted page text, and exact text. IDs remain
stable on reread/restart of a stored version. Reuploading bytes into a new family
creates new IDs. The PDF bytes remain in the database as the authoritative source.
`POST /api/citations/validate` accepts a chunk ID and exact quotation, checks access
and substring membership, and returns document ID, page, SHA-256, source metadata
and a PDF reference. Open the source PDF from the library and compare the quote to
the physical page; inspect extraction order for complex columns/tables. PDF endpoints
require bearer authentication; evidence links alone do not grant access.

AI responses reject invented chunk IDs, quotes, and missing citations. Comparison
and gap items must cite every selected document. These checks validate provenance,
not legal accuracy or whether a citation logically supports an interpretation.
Hybrid-retrieved excerpts are incomplete; an unlocated policy provision does not
prove it is absent. All accepted AI items are pending human review.

## Synthetic development fixtures

`tests/fixtures/synthetic_kyc_sop.txt` and `.pdf` are deliberately fictional KYC SOPs.
They are neither company policies nor RBI/SEBI material. Every PDF page carries a
synthetic label. Regenerate the PDF with:

```sh
.venv/bin/python tests/fixtures/build_demo.py
```

Production ingestion rejects titles starting with `SYNTHETIC` and the known
synthetic SOP/demo page markers. Tests explicitly enable
synthetic processing on temporary isolated stores; the runtime never enables it.
This marker check is an additional guard, not proof of authenticity of other PDFs.
For demonstrations use the generated fixture with the automated tests, or an
explicitly separate temporary Store configured with `allow_synthetic=True`; never
use the production database. There is no sample-data import button in production.

## Persistent evidence indexing

SQLite is the source of truth for user-ingested documents. Chroma stores derived
vectors keyed by the existing immutable chunk UUIDs. BM25 is computed over only
accessible, matching chunks. Every vector query is restricted to document IDs
already authorized by SQLite; returned IDs are rehydrated and checked against
stored chunks before any evidence can reach generation.

Use the root README's explicit `download-model`, `sync`, `status`, and `rebuild`
commands. Ingestion does not download models or automatically index documents.
Missing/pending/mismatched indexes block hybrid generation with setup instructions;
explicit BM25-only evidence inspection remains available. Never configure the
production server or administrator CLI to use a test database/index by accident.

The active manifest records corpus path, exact model snapshot identity, dimensions,
normalization, distance metric, preprocessing version, and per-document chunk
inventories. Repeat sync uses stable IDs without duplication. A rebuild uses a
separate collection, switches the manifest atomically after success, and retains
the old generation. These are derived indexes: rebuild them from stored original
chunks rather than inventing vectors or copying one organization's evidence to another.

Version filters can use immutable document UUIDs or metadata version labels. Labels
are user supplied and may repeat; select UUIDs for unambiguous version comparison.
No automatic selection of a newest/effective regulation is performed. Verify dates,
applicability and interpretations manually against official source PDFs.

## Remaining work

No automatic regulatory refresh, verified-metadata review UI, schema migration
framework, OCR, or structured table extraction is included.
Add migrations before evolving persistent schemas. Embedding identity is pinned to the index; rebuild when it changes. Human approval, reports and audit
history will need persistent records instead of treating generated text as approved.
