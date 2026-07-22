# Task 13 implementation report

## Outcome

Shipped the server-rendered institution workspace for program review, managed companies, and support cases. The FastAPI surface uses typed async SQLAlchemy sessions, Jinja autoescaping, 303 POST/Redirect/GET mutations, explicit actor/reason validation, and the existing authoritative `ReverseMatchingService`, `AssessmentRepository.review`, and `CaseRepository.transition` paths.

Institution-owned PDF/HWPX notices now enter the same canonical notice and document-ingestion pipeline as collected sources with `SourceName.MANUAL`. Validation, parsing, persistence, and the immutable attribution event share one caller-owned transaction, so rejected attachments cannot leave a partial notice.

Case HTML and PDF load the same consultation data model. Both expose official source freshness, document evidence locations, automatic/review state, rule version, and immutable audit actor/reason/before/after values with UTC timestamps converted to `Asia/Seoul`. The searchable PDF uses Jinja autoescaping, rejects resource-bearing HTML/CSS before rendering, invokes WeasyPrint with a fixed argument vector and stdin/stdout only, enforces a 30-second timeout, and emits stable deployment-safe error codes.

The runtime used for acceptance evidence was the official WeasyPrint v68.1 Windows bundle from `https://github.com/Kozea/WeasyPrint/releases/download/v68.1/weasyprint-windows.zip`, unpacked only under ignored `.tools/`. Production requires `GRANTCOMPASS_WEASYPRINT_EXECUTABLE` to name an approved executable; no binary or host path is committed.

No migration was required. The existing program, source, version, attachment, document, evidence, assessment, managed-company, case, and audit tables already represent the required workflow.

## Verification

- Initial HTTP RED: `ModuleNotFoundError: No module named 'grantcompass.web'`.
- Initial PDF RED: `ModuleNotFoundError: No module named 'grantcompass.reports.pdf'`.
- Browser favicon regression: RED `404 != 204`; GREEN `1 passed`.
- PDF audit-margin regression: RED span exceeded A4 content margin; GREEN `1 passed in 3.14s`.
- Task 13 HTTP acceptance: `10 passed in 3.98s`.
- Task 13 PDF unit suite: `4 passed in 8.50s`.
- Full suite final: `500 passed in 117.77s`.
- Ruff format/check: `188 files already formatted`; `All checks passed!` for `src tests migrations`.
- basedpyright all: `0 errors, 0 warnings, 0 notes`.
- File limit: largest Task 13 Python/HTML file is 233 lines; all are below 250.
- `git diff --check`: pass.

## Manual QA

Real Playwright/Chromium exercised the programs ledger, program dossier, attributed reverse match, attributed assessment review, case dossier, attributed case transition, companies ledger, and 390px manual-notice form with a real PDF upload. The manual submission redirected to the new canonical `manual` program with `parsed` document status. Desktop and mobile screenshots were inspected under `.omo/evidence/task13/output/playwright/`; all final pages reported zero console errors.

The live case PDF was downloaded, confirmed as searchable, rendered with PyMuPDF, and visually inspected. The final representative is one page; its maximum text edge is 549.92pt on a 595.28pt page, with long audit JSON wrapped inside the right margin. Evidence remains untracked under `.omo/evidence/task13/`.

## Handoff

Deployments must provision the approved WeasyPrint executable and set `GRANTCOMPASS_WEASYPRINT_EXECUTABLE`. Optional Biome HTML LSP was unavailable and was not globally installed; the rendered browser/PDF surfaces and project checks were used instead. Ruff was intentionally scoped to tracked project trees because pre-existing untracked `.omo/evidence/task12-fix/manual_review_driver.py` is outside Task 13 ownership.

## Review fix wave 1

### RED and GREEN

- Fresh inherited-fix baseline (direct `.venv/Scripts/python.exe -m pytest -q --cache-clear -o cache_dir=<unique /tmp> --basetemp=<unique /tmp>` over the Task 13 focused files and Task 12 review/audit regressions): `65 passed, 3 failed in 20.08s`. Cached review sessions evaluated stale audit/automatic state before the persisted revision: stale revisions returned `MALFORMED_AUDIT`, and a same-revision independent automatic-state change returned `MALFORMED_ASSESSMENT` instead of the intended semantic error.
- The repository now refreshes the assessment before comparing `expected_review_revision`; it therefore returns `CONCURRENT_CHANGE` before any cached audit semantic validation, while same-revision independent mutations retain the existing malformed-state validation. Focused Task 12 precedence coverage then passed: `8 passed in 2.87s`.
- Fresh focused GREEN command: `.venv/Scripts/python.exe -m pytest -q --cache-clear -o cache_dir=<unique /tmp> --basetemp=<unique /tmp> tests/e2e/test_institution_web.py tests/e2e/test_institution_review_web.py tests/e2e/test_institution_upload_web.py tests/unit/test_pdf_report.py tests/unit/test_pdf_runtime.py tests/integration/test_assessment_review_history.py tests/integration/test_audit_boundary_regressions.py tests/integration/test_audit_identity_map_regressions.py tests/integration/test_review_concurrency_regressions.py` → `68 passed in 17.93s`.

### Static and full-suite evidence

- `.venv/Scripts/python.exe -m ruff check src tests` → `All checks passed!`.
- `.venv/Scripts/python.exe -m ruff format --check src tests` → `186 files already formatted`.
- `.venv/Scripts/basedpyright.exe` → `0 errors, 0 warnings, 0 notes`.
- Fresh full-suite command: `.venv/Scripts/python.exe -m pytest -q --cache-clear -o cache_dir=<unique /tmp> --basetemp=<unique /tmp>` → `524 passed in 131.95s`.
- `git diff --check` passed. Task 13 production Python/HTML maximum is `249` lines (`src/grantcompass/reports/consultation_data.py`); every Task 13 production Python/HTML file is below 250 lines.

### Browser, upload, and PDF QA

- A seeded live FastAPI workspace at `http://127.0.0.1:8010` was exercised in Chrome. The program dossier rendered `2026-07-20 18:00 KST`; a browser submission changed only industry condition `#2` from automatic `satisfied` to override/effective `unsatisfied`, preserving automatic aggregate `eligible` while showing effective aggregate `ineligible` and attributed reviewer/reason.
- A browser back-navigation replay of a revision-1 review form produced a real `POST /assessments/1/review` `409 Conflict` in the live server log. A subsequent reverse match rendered exactly one latest row for the managed profile (`#3/#4`, automatic), while case HTML retained the two earlier reviewer/audit entries. A final latest-assessment review gave the PDF automatic/override/effective evidence and retained all three audits. A fresh final case tab had `consoleEntries: []` for error/warning levels.
- Chromium's direct 50 MiB+1 file chooser transfer did not complete within the 120-second QA bound and was aborted before a result. The same live multipart route was then exercised once through the project HTTP client with `/tmp/task13-oversized.pdf` (52,428,801 bytes): `POST /programs/manual` returned `422 attachment_too_large`; immediate SQLite counts before/after were identical: program `1`, manual notice version `0`, attachment `1`, document `1`, audit `3`.
- `/cases/1/report.pdf` rendered in Chrome's PDF viewer as a searchable two-page PDF. PyMuPDF verified `%PDF`, `PAGES=2`, `SEARCHABLE=True`, 4,134 extracted characters, and all expected automatic/override/effective/reviewer/audit strings. Visual inspection confirmed the state table and source section on page 1 and retained audit history on page 2; measured text bounds were `45.35pt` minimum X and `549.92pt` maximum X on a `595.28pt` A4 page, preserving 45.35pt margins. The local server log contained only the expected local PDF requests; render-boundary tests block external/file/CSS/font/media resources.
