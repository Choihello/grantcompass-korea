# Task 14 — 0.1 release hardening report

Status: complete

## Outcome

GrantCompass Korea 0.1 now has a review-ready release surface: privacy and prompt-injection
boundaries are regression-tested, credential-bearing HTTP logs are centrally redacted,
persisted failure states have human and machine-visible routes, demo data and screenshots are
synthetic, release operations are documented, and all automated/manual release gates passed.

No Git tag was created. Unrelated Task 9 and scratch artifacts were preserved and excluded from
the Task 14 commit.

## Test-driven evidence

The mandatory focused tests were written before the failure-surface implementation.

RED:

```text
pytest tests/unit/test_profile_privacy.py \
  tests/unit/test_prompt_injection_boundary.py \
  tests/e2e/test_failure_scenarios.py -q
1 failed, 8 passed
```

The expected failure was `/programs/failure-scenario` returning 422 because the route did not
exist. After implementation, the same focused set was GREEN: `9 passed in 0.81s`.

A separate log-redaction regression test was also captured RED (`1 failed`, raw secrets visible
in `httpx2` logs) and GREEN (`1 passed in 0.11s`). It covers concurrent credentials without
temporarily mutating the logger level.

## Implemented release surfaces

- Applicant profile inputs reject undeclared personal or secret fields through the production
  `ApplicantProfile` whitelist.
- Prompt-like announcement and document text remains inert data; only supported deterministic
  rule syntax is extracted. Report HTML resource references remain blocked before renderer I/O.
- A permanent stateless `httpx2` filter redacts `serviceKey` and `crtfcKey` query values.
- `/programs/failure-scenario` and `/health/failures` derive these stable IDs from persisted rows:
  `source_503_stale`, `scan_pdf_ocr_required`, `conflicting_deadlines`, and
  `incomplete_profile_needs_review`.
- Runtime WeasyPrint QA skips only when native loading is unavailable. A selected executable that
  times out, fails, or returns invalid PDF bytes fails the test.
- Three demo profiles, two screenshots, and all QA values are conspicuously synthetic.

## Documentation

`README.md` now covers Python/uv installation, `.env`, database initialization versus migrations,
both source syncs, founder search/report flow, institution web use, evidence coordinates, PDF and
OCR prerequisites, Windows Task Scheduler, cron, supported sources, current limitations,
verification, and the post-0.1 roadmap.

`SECURITY.md` documents the profile whitelist, content and deployment trust boundaries,
credential-log defense, lack of built-in web authentication, and operator failure health.
`CONTRIBUTING.md` documents fixture sanitization, untrusted input, source-contract updates,
test-first work, and reviewable commits. `docs/sources/kstartup.md` records completion of the
central log-redaction gate.

Manual evidence and exact build identity are in `docs/qa/manual-qa.md`.

## Automated verification

- Focused Task 14 behavior: 9 passed.
- Credential-log redaction: 1 passed.
- Unit suite: 315 passed in 12.35 seconds.
- Document and assessment benchmarks: 6 passed in 13.15 seconds.
- Corpus size: exactly 30 document cases and 100 assessment cases.
- Full suite: 545 passed, 1 skipped in 136.44 seconds.
- Sole skip: native WeasyPrint dependencies unavailable on the Windows QA host.
- Ruff lint: all checks passed.
- Ruff format: 204 files already formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- `uv lock --check`: resolved 71 packages without a lockfile change.
- `uv build`: wheel and source distribution built successfully.
- Clean-like locked install: fresh virtual environment installed successfully; help, database
  initialization, and synthetic profile creation passed.
- All changed code, test, and release-document files: below 250 pure lines.
- `git diff --check`: passed.

## Manual verification

- Founder CLI: initialized storage, created a synthetic profile, fixture-synced both sources,
  searched five eligibility states, retained official evidence coordinates, wrote a five-result
  report, and returned stable exit code 3 for a missing profile.
- Institution browser: reviewed two synthetic programs, performed reverse matching, saved an
  attributed conditional override, changed consultation stage, and verified immutable audit
  history.
- Failure browser: displayed all four persisted failure IDs and zero hidden failures; health GET
  returned 200 and the exact JSON contract is covered end-to-end.
- Consultation PDF: real request reached the renderer and visibly failed because the host lacked
  `libgobject-2.0-0`; this is documented and no successful native render is claimed.

## Release artifacts

- Wheel SHA-256: `71c03136dbcd6ac1d298143049456a4fad57e1b9d6b11fac1a6e574eb043d921`
- Source distribution SHA-256:
  `8a82204740e259b1fe5dfbdc768075de3ca93119e08b807f9ad0df41fc0e3a75`

The intended commit subject is `docs: prepare GrantCompass Korea 0.1 release`.
