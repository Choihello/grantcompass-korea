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
