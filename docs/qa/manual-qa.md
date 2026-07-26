# GrantCompass Korea 0.1 manual QA

Date: 2026-07-26 (Asia/Seoul)

## Release-evidence authority

The Task 14 record below is historical evidence for commit
`15879c453d7ee855c05ca3e70b99c608c1ee037d`; it is not the current authoritative release
evidence. The latest executable pre-release baseline entering Task 15 is
`2a0ec72764da45f15a31d9f57fdf2de5bb930728`. After the independent release gates pass, the
controller-created annotated release tags and their exact-SHA evidence ledger are authoritative.
This document does not claim that those tags exist.

## Historical Task 14 final build under test

- Functional commit C: `15879c453d7ee855c05ca3e70b99c608c1ee037d`
- Commit C tree: `6c500aae8ced3903e594605a3952262a2dc9da49`
- Commit C subject: `fix: expose persisted hidden failure inventory`
- The final follow-up commit D changes only this QA record,
  `.superpowers/sdd/task-14-report.md`, and the two browser captures under `docs/assets/`.
  It contains no executable code, tests, package inputs, or built-artifact inputs.
- Host: Windows, Python 3.12.10, uv 0.11.28.
- Data: saved official-source transport fixtures and conspicuously synthetic applicant data.
- Credentials: no live API key was used.

### Final C persisted-failure QA

A fresh local Uvicorn server backed by persisted synthetic rows returned HTTP 200 from
`/health/failures`. Two reads were byte-identical. The exact response was:

```json
{"visible_failure_ids":["source_503_stale","scan_pdf_ocr_required","conflicting_deadlines","incomplete_profile_needs_review"],"hidden_failures":["attachment_parse:encrypted_pdf","field_conflict:organization","rule_assessment:unsupported_rule_kind","source_run:bizinfo:rate_limited"]}
```

A second persisted database containing only the recognized scenarios returned the same four
visible IDs and an empty `hidden_failures` array. A fresh empty database returned both arrays
empty. This proves the live mixed, visible-only, and clean production surfaces.

The browser page `/programs/failure-scenario` showed the four visible IDs and
`hidden_failures=4`. The fresh commit-C capture is
[failure-scenarios.png](../assets/failure-scenarios.png), 1036 × 815 pixels, SHA-256
`9bfe0fddea442d81c4984d544673aad4bd9644200ec5e95dcfacc9af6b10cc97`.

### Final C institution browser QA

A real Chromium session opened two synthetic programs, verified the official URL and p.1
`eligibility` evidence, ran all-company reverse matching as `합성 C 기관담당자` for
`합성 C 전체기업 재검토`, saved a `conditional` override by `합성 C 기관담당자` for
`합성 C 증빙 재확인 필요`, and moved the case to `contacted` as `합성 C 상담담당자` for
`합성 C 상담 완료`. The resulting case displayed the effective conditional decision and both
immutable attributed audit reasons.

The fresh commit-C capture is [institution-workspace.png](../assets/institution-workspace.png),
1020 × 1415 pixels, SHA-256
`6324809afae4953dc23ca2bc9ed201e7073d8ee39e3632b750062d1761d254cd`.

### Final C automated and artifact gates

- TDD fix set: RED `4 failed, 9 passed, 1 skipped`; GREEN `13 passed, 1 skipped`.
- Focused Task 14 gate: 29 passed, 1 recognized native-loader skip.
- Full suite/JUnit: 561 passed, 1 skipped in 138.74 seconds; 562 tests, zero failures,
  zero errors, one recognized native-loader skip.
- Benchmarks: 6 passed in 14.60 seconds; exactly 30 document and 100 assessment cases.
- Ruff lint passed; Ruff format reported 208 files already formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- `uv lock --check`: 71 packages; `git diff --check`: passed.
- Wheel SHA-256: `f11223f5964031fc96416d90303c36b48a2f0c906bbc47a78765e1e80944a013`.
- Source distribution SHA-256:
  `f6de5dfd1315401f2f59544a11e72cfc270fb13ecca78e96f4828292bb12383c`.
- Direct wheel and sdist inspection found the packaged Skill `SKILL.md` and
  `agents/openai.yaml` members.

The WeasyPrint preflight now has a finite five-second production timeout. A blocked import is a
hard timeout failure; only completed stderr is eligible for recognized native-loader
classification. Tests cover the timeout and an immediate recognized-loader result.

Within the historical Task 14 record, the artifact hashes and gate counts below were superseded by
the commit-C values above. No tag was created.

## Historical build-A record (superseded)

- Functional commit A: `8ab4cb2542bc5e859932ef19917edd40d6cab561`
- Commit A tree: `7a0b1db20ad9d1a54eff8cb036185ccd58cd7190`
- Commit A subject: `fix: close GrantCompass 0.1 release review findings`
- Fix base: `1b81f48b0e6d8420238598eb89a94ea185adc7da`
- The final follow-up commit B changes only this QA record and
  `.superpowers/sdd/task-14-report.md`. All executable code, tests, package configuration,
  built-artifact inputs, and manual scenarios were tested at immutable commit A.
- Host: Windows, Python 3.12.10, uv 0.11.28.
- Data: saved official-source transport fixtures and conspicuously synthetic applicant data.
- Credentials: no live API key was used.

## Clean wheel installation

The commit-A wheel, rather than the checkout or an editable install, was installed into a fresh
`.task14-qa/fix1-A-wheel-venv`.

```powershell
$env:UV_CACHE_DIR="$env:TEMP\grantcompass-task14-clean-uv-cache"
.\.tools\uv-dist\uv.exe venv .task14-qa\fix1-A-wheel-venv `
  --python .tools\python\cpython-3.12.10-windows-x86_64-none\python.exe
.\.tools\uv-dist\uv.exe pip install `
  --python .task14-qa\fix1-A-wheel-venv\Scripts\python.exe `
  dist\grantcompass_korea-0.1.0-py3-none-any.whl
.\.task14-qa\fix1-A-wheel-venv\Scripts\grantcompass.exe --help
.\.task14-qa\fix1-A-wheel-venv\Scripts\python.exe -c `
  "from importlib.resources import files; p=files('grantcompass').joinpath('skills/grantcompass-korea/SKILL.md'); assert p.is_file(); assert 'site-packages' in str(p); print(p)"
```

Observed: 60 packages installed from the wheel and its declared dependencies; CLI help listed all
five command groups; the Skill resolved from the fresh environment's `Lib/site-packages`, not the
checkout. Result: PASS.

## Founder CLI journey

The installed `.venv\Scripts\grantcompass.exe` was exercised against a new SQLite database.
Fixture-backed transports were injected through the production Typer application for collection;
search and report used the installed executable directly.

1. `grantcompass db init` returned `database_initialized` on a fresh commit-A database.
2. Profile creation returned ID 1 for `명백한합성A창업자기업3`.
3. `sources sync --source all` recorded K-Startup and 기업마당 as fresh with zero failures.
4. `search --profile 1 --json` returned five results spanning `eligible`, `conditional`,
   `needs_review`, `ineligible`, and `missing_rules`.
5. The first evidence item retained the official K-Startup URL, block `block-1`, page 1, and
   section `신청자격`.
6. `report --profile 1 --out .task14-qa/fix1-A-reports/founder3.md --json` wrote five results; inspection
   confirmed official URL, document hash, block, page, and section coordinates.
7. Searching a missing profile returned stable `profile_not_found` with exit code 3.

Result: PASS.

## Institution browser journey

A real Chromium session was run against local Uvicorn using a fixture-seeded SQLite database.

1. `/programs` showed two synthetic programs.
2. `/programs/1` showed the official URL and page/section evidence.
3. All-company reverse matching showed the synthetic company.
4. A condition override was saved with actor `합성 A 기관담당자`, result `conditional`, and reason
   `합성 A 증빙 재확인 필요`.
5. Consultation stage was changed to `contacted` with reason `합성 A 상담 완료`.
6. The resulting case preserved current stage, effective decision, and both attributed immutable
   audit entries.

Sanitized capture: [institution-workspace.png](../assets/institution-workspace.png).
Result: PASS.

## Visible failure scenarios

Persisted source-run, retained notice, attachment, conflict, and incomplete-profile rows were
seeded. `source_503_stale` had both a prior successful run with retained data and the latest failed
503 run. The browser page `/programs/failure-scenario` displayed these stable IDs:

- `source_503_stale`
- `scan_pdf_ocr_required`
- `conflicting_deadlines`
- `incomplete_profile_needs_review`

The page reported `hidden_failures=0`. A real GET of `/health/failures` returned HTTP 200, while
tests verify positive, negative, and deliberately unmapped candidate inventories. A first-run 503
without retained successful data is not labeled stale. Sanitized capture:
[failure-scenarios.png](../assets/failure-scenarios.png). Result: PASS.

## PDF runtime limitation

The browser report request reached the real consultation PDF route and failed visibly with
`weasyprint_render_failed`. The host could not load WeasyPrint because `libgobject-2.0-0` was
missing. This is the documented optional native-runtime limitation and no PDF success is claimed.

The automated runtime gate skips only when import stderr matches a recognized WeasyPrint native
loader/library family. Missing modules, syntax errors, unrelated imports, timeout, process
failure, and invalid output remain test failures.

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
  --junitxml=.task14-qa/fix1-A-full.xml
.\.tools\uv-dist\uv.exe lock --check
```

Observed:

- Ruff lint: all checks passed.
- Ruff format: 207 files already formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- Lockfile check: resolved 71 packages without changing `uv.lock`.
- Benchmark loaders: exactly 30 document cases and 100 assessment cases.
- Benchmark tests: 6 passed in 14.40 seconds.
- Focused review-finding gate: RED `13 failed, 5 passed`; GREEN `18 passed, 1 skipped`.
- Full suite: 559 passed, 1 skipped in 135.89 seconds; JUnit records 560 tests, zero failures,
  zero errors, one skip. The skip is the recognized native WeasyPrint loader condition above.
- Changed-file size: every changed code, test, and release-document file is below 250 pure lines;
  the largest is `src/grantcompass/web/routes.py` at 219 pure lines (245 physical lines).
- `git diff --check`: passed.

`uv build` was run with approved network access after the sandboxed build-backend download was
blocked. It produced:

- `grantcompass_korea-0.1.0-py3-none-any.whl`, SHA-256
  `22a32b05bc340f3aa2bca77138d20085ac7fcac6534c6598717858f15829756e`
- `grantcompass_korea-0.1.0.tar.gz`, SHA-256
  `4dd5e624f72b3e99f3963679ccf096d927851ed966ff987e457da2e87cbb52cd`

Direct archive inspection found:

- wheel: `grantcompass/skills/grantcompass-korea/SKILL.md`
- wheel: `grantcompass/skills/grantcompass-korea/agents/openai.yaml`
- sdist: `grantcompass_korea-0.1.0/skills/grantcompass-korea/SKILL.md`
- sdist: `grantcompass_korea-0.1.0/skills/grantcompass-korea/agents/openai.yaml`

Overall release QA result: PASS with the explicitly documented host-native WeasyPrint limitation.
No tag was created. The final metadata-only commit B does not alter the tested commit-A tree.
