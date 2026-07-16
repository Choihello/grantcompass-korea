# Document rule benchmark method

## Purpose

This benchmark checks whether GrantCompass can parse a source attachment, extract only the
supported deterministic eligibility conditions, and retain an exact evidence location. It is a
regression benchmark for parser and rule-provider behavior, not a measurement of production
recall.

## Corpus

The corpus contains 30 distinct synthetic documents:

- 15 HWPX files parsed by `HwpxParser`
- 15 PDF files parsed by `PdfParser`
- business-age, representative-age, region inclusion and exclusion, and industry-exclusion cases
- numeric boundary operators and one PDF near-miss that must produce no rule
- one PDF containing all four supported rule families

Every source is generated locally. The repository does not download, copy, or embed third-party
announcements, private attachments, or personal information. `reviewed_by_role` identifies a
non-personal review role rather than an individual.

## Generation

Run the PEP 723 script from the repository root:

```console
uv run scripts/build_benchmark.py
```

When the project environment is already synchronized and network access is unavailable, use:

```console
uv run --no-sync python scripts/build_benchmark.py
```

The generator fixes ZIP timestamps, serialization settings, document names, and source text.
Independent generations must have identical relative paths and SHA-256 hashes.

PDF generation uses PyMuPDF's built-in Korean font instead of ReportLab. This is an intentional
exception: the benchmark must exercise a reproducible Korean text layer that the production
PyMuPDF parser can extract exactly without relying on an operating-system font. Generated PDFs
are visually rendered during review to check clipping, glyphs, and legibility.

## Manifest contract

`documents.jsonl` is parsed as untrusted input into frozen Pydantic models. Each row records:

- a benchmark-local HWPX or PDF path
- the document identifier and SHA-256 content hash
- exact normalized rules
- exact evidence coordinates and quoted substrings
- the non-personal reviewer role

Evidence uses `grantcompass://documents/<percent-encoded-document-id>`. An accepted evidence item
must agree with the parsed document identifier and hash, and with the referenced block's page,
section path, and source substring.

## Verification

The integration test reads every generated binary through the real HWPX or PDF parser before
calling `RegexRuleCandidateProvider`. It rejects parser warnings, hash drift, missing evidence,
unexpected rules, unresolved locations, duplicate fixture paths, format imbalance, and generation
nondeterminism.

The deterministic provider intentionally recognizes only:

- business age in months or years
- representative age
- region inclusion or exclusion
- industry exclusion

Other prose remains unclassified and requires a later human-review or structured-model path.
