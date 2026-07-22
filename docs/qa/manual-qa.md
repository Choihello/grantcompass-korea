# GrantCompass Korea 0.1 manual QA

Date: 2026-07-22 (Asia/Seoul)

## Build under test

- Base commit: `aace81ebadf421ba7269da2ec190e8fa6225ec56`
- Base subject: `fix: harden manual upload and PDF runtime boundaries`
- Pre-commit implementation manifest SHA-256:
  `cfad5b9cc4899e2b6e0e37b2bc5fe260958a65cdc30ae58812e80440cf07a99a`
- Manifest definition: SHA-256 of the newline-joined, path-sorted list of
  `<file SHA-256><two spaces><path>` for the Task 14 implementation, tests, release docs,
  demo fixture, and screenshots, excluding this QA record and the Task 14 SDD report.
- Host: Windows, Python 3.12.10, uv 0.11.28.
- Data: saved official-source transport fixtures and conspicuously synthetic applicant data.
- Credentials: no live API key was used.

## Clean-like installation

From the checkout root, a fresh `.task14-qa/clean-venv` was created from the locked dependency
set. The first sandboxed download was blocked by network policy; the same command was then run
with approved network access.

```powershell
$env:UV_PROJECT_ENVIRONMENT='.task14-qa\clean-venv'
$env:UV_CACHE_DIR="$env:TEMP\grantcompass-task14-clean-uv-cache"
.\.tools\uv-dist\uv.exe sync --locked --all-groups
.\.task14-qa\clean-venv\Scripts\grantcompass.exe --help
$env:GRANTCOMPASS_DATABASE_URL='sqlite+aiosqlite:///./.task14-qa/clean-install.db'
.\.task14-qa\clean-venv\Scripts\grantcompass.exe db init
.\.task14-qa\clean-venv\Scripts\grantcompass.exe profile create `
  --name '명백한합성설치검증기업' --founded-on 2024-01-01 `
  --region 서울 --industry software --json
```

Observed: the lock resolved 71 packages, 69 packages installed, CLI help listed all five command
groups, schema initialization returned `database_initialized`, and profile creation returned ID 1
and the synthetic display name. Result: PASS.

## Founder CLI journey

The installed `.venv\Scripts\grantcompass.exe` was exercised against a new SQLite database.
Fixture-backed transports were injected through the production Typer application for collection;
search and report used the installed executable directly.

1. `grantcompass db init` returned `database_initialized`.
2. Profile creation returned ID 1 for `명백한합성창업자기업`.
3. `sources sync --source all` recorded K-Startup and 기업마당 as fresh with zero failures.
4. `search --profile 1 --json` returned five results spanning `eligible`, `conditional`,
   `needs_review`, `ineligible`, and `missing_rules`.
5. The first evidence item retained the official K-Startup URL, block `block-1`, page 1, and
   section `신청자격`.
6. `report --profile 1 --out .task14-qa/reports/founder.md --json` wrote five results; inspection
   confirmed official URL, document hash, block, page, and section coordinates.
7. Searching a missing profile returned stable `profile_not_found` with exit code 3.

Result: PASS.

## Institution browser journey

A real Chromium session was run against local Uvicorn using a fixture-seeded SQLite database.

1. `/programs` showed two synthetic programs.
2. `/programs/1` showed the official URL and page/section evidence.
3. All-company reverse matching showed the synthetic company.
4. A condition override was saved with actor `합성 기관담당자`, result `conditional`, and reason
   `합성 증빙 재확인 필요`.
5. Consultation stage was changed to `contacted` with reason `합성 상담 완료`.
6. The resulting case preserved current stage, effective decision, and both attributed immutable
   audit entries.

Sanitized capture: [institution-workspace.png](../assets/institution-workspace.png).
Result: PASS.

## Visible failure scenarios

Persisted source-run, attachment, conflict, and incomplete-profile rows were seeded. The browser
page `/programs/failure-scenario` displayed these stable IDs:

- `source_503_stale`
- `scan_pdf_ocr_required`
- `conflicting_deadlines`
- `incomplete_profile_needs_review`

The page reported `hidden_failures=0`. A real GET of `/health/failures` returned HTTP 200, while
the test client verified the exact JSON mirror and empty hidden list. Sanitized capture:
[failure-scenarios.png](../assets/failure-scenarios.png). Result: PASS.

## PDF runtime limitation

The browser report request reached the real consultation PDF route and failed visibly with
`weasyprint_render_failed`. The host could not load WeasyPrint because `libgobject-2.0-0` was
missing. This is the documented optional native-runtime limitation and no PDF success is claimed.

The automated runtime gate skips only when no native runtime can be loaded. Once an explicit
executable is selected, timeout, process failure, and invalid output remain test failures.

## Reproducible release gates

```powershell
$env:UV_CACHE_DIR='.task14-qa\uv-cache'
$env:RUFF_CACHE_DIR='.task14-qa\ruff-cache'
.\.tools\uv-dist\uv.exe run --no-sync ruff check .
.\.tools\uv-dist\uv.exe run --no-sync ruff format --check .
.\.tools\uv-dist\uv.exe run --no-sync basedpyright
.\.tools\uv-dist\uv.exe run --no-sync pytest `
  tests/integration/test_document_benchmark.py `
  tests/integration/test_assessment_benchmark.py -q
.\.tools\uv-dist\uv.exe run --no-sync pytest -q `
  --junitxml=.task14-qa/full-final.xml
.\.tools\uv-dist\uv.exe lock --check
```

Observed:

- Ruff lint: all checks passed.
- Ruff format: 204 files already formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- Lockfile check: resolved 71 packages without changing `uv.lock`.
- Benchmark loaders: exactly 30 document cases and 100 assessment cases.
- Benchmark tests: 6 passed in 13.15 seconds.
- Full suite: 545 passed, 1 skipped in 136.44 seconds; JUnit records 546 tests, zero failures,
  zero errors, one skip. The skip is the native WeasyPrint runtime check described above.
- Changed-file size: every changed code, test, and release-document file is below 250 pure lines;
  the largest is `src/grantcompass/web/routes.py` at 219 pure lines (245 physical lines).
- `git diff --check`: passed.

`uv build` was run with approved network access after the sandboxed build-backend download was
blocked. It produced:

- `grantcompass_korea-0.1.0-py3-none-any.whl`, SHA-256
  `71c03136dbcd6ac1d298143049456a4fad57e1b9d6b11fac1a6e574eb043d921`
- `grantcompass_korea-0.1.0.tar.gz`, SHA-256
  `8a82204740e259b1fe5dfbdc768075de3ca93119e08b807f9ad0df41fc0e3a75`

Overall release QA result: PASS with the explicitly documented host-native WeasyPrint limitation.
