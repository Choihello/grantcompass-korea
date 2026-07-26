# Task 16: Final query-quality blocker

## Release candidate

- Branch: `feature/grantcompass-0.1`
- Exact baseline: `7001e63aaca635daf85ed262f99a717a43339c89`
- Functional commit: `3c495cdb6c9c85163d203665feab3640ceb35773`
- This task created no tags. Existing gate tags were left unchanged.

## Implemented scope

- `src/grantcompass/web/company_queries.py` now loads the managed-company ledger in
  three bounded reads: companies, referenced profiles, and the highest-ID case per
  company. The highest-ID rule preserves the previous `ORDER BY cases.id DESC`
  definition of latest.
- `src/grantcompass/cli/program_queries.py` now uses outer joins at the stored
  evidence-integrity boundary. Missing evidence, document, or block rows and
  document/block identity mismatches raise the stable fail-closed
  `LookupError("dangling_evidence_relation")` instead of disappearing from an inner
  join and degrading to `missing_evidence`.
- `tests/integration/test_query_count_regressions.py` adds real 50-row regressions
  for the company ledger and populated latest-match detail path, plus a real
  foreign-key-disabled legacy-corruption regression for dangling evidence.

## TDD evidence

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| 50-company ledger, RED | `uv run pytest -q tests/integration/test_query_count_regressions.py -k "company_ledger or latest_matches_batches or dangling_evidence"` against the baseline implementation | Company ledger executed `101` reads (`1 + 2N`) instead of the required `3` | `.omo/evidence/task-16/red-query-and-integrity.txt` |
| Populated latest-match detail | Same invocation with 50 profiles, managed companies, assessments, conditions, and review audits | Existing batched path passed at exactly `4` reads and returned 50 populated matches | `.omo/evidence/task-16/red-query-and-integrity.txt` |
| Dangling evidence, RED | Same invocation after deleting the referenced document block with foreign keys temporarily disabled and then restored | `DID NOT RAISE LookupError`; the inner join silently omitted the corrupt relation | `.omo/evidence/task-16/red-query-and-integrity.txt` |
| Query and integrity regressions, GREEN | Same targeted invocation after the minimal implementation | `3 passed`; company ledger is exactly `3` reads, latest matches exactly `4`, and dangling evidence raises exactly `dangling_evidence_relation` | `.omo/evidence/task-16/green-query-and-integrity.txt` |

## Automated verification

| Gate | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Focused query/security/release-schema suite | `uv run pytest -q tests/integration/test_query_count_regressions.py tests/e2e/test_web_security_boundary.py tests/integration/test_release_schema_migration.py` with isolated cache/temp paths | `16 passed` | `.omo/evidence/task-16/focused-final2.txt` |
| Unfiltered full suite | `uv run pytest -q --junitxml=.omo/evidence/task-16/full-suite.xml` with isolated cache/temp paths | `598 passed, 1 skipped`; the only skip is the recognized unavailable WeasyPrint native dependency | `.omo/evidence/task-16/full-suite.txt`, `.omo/evidence/task-16/full-suite.xml` |
| Ruff format | `uv run ruff format --check src tests migrations typings` | `218 files already formatted` | `.omo/evidence/task-16/ruff-format-commit.txt` |
| Ruff lint | `uv run ruff check src tests migrations typings` | `All checks passed!` | `.omo/evidence/task-16/ruff-commit.txt` |
| Static typing | `uv run basedpyright` | `0 errors, 0 warnings, 0 notes` | `.omo/evidence/task-16/basedpyright-commit.txt` |
| Diff hygiene | `git diff --check` before the functional commit | Exit `0`, no output | `.omo/evidence/task-16/diff-check.txt` |
| Supported migration round trip | Explicit fresh SQLite database: Alembic `upgrade 0005`, `downgrade 0004`, `upgrade 0005`, `upgrade head`, then `check` | `task16_migration_upgrade_downgrade_upgrade_check_passed`; no new upgrade operations | `.omo/evidence/task-16/migration-cycle-final.txt` |
| Assessment/document benchmarks | `uv run pytest -q tests/integration/test_assessment_benchmark.py tests/integration/test_document_benchmark.py` | `6 passed` | `.omo/evidence/task-16/benchmarks.txt` |
| Production release scenarios | `uv run pytest -q tests/integration/test_release_pipeline.py` | `9 passed` | `.omo/evidence/task-16/production-scenarios.txt` |
| Wheel and sdist build | `uv build --out-dir .omo/evidence/task-16/dist` | Both artifacts built successfully | `.omo/evidence/task-16/build.txt` |
| Build identities | SHA-256 over final archives | Wheel `E58A912FB2226FF9CBB352B462856C3F9EBD88743BEBC9DE6A8C6492F9127098`; sdist `0881287CC596884C79F503021BCAB2959CAFF6543613E253507674093E3CBABE` | `.omo/evidence/task-16/build-hashes.txt` |
| Archive inspection | Inspect wheel/sdist member names | Both contain `SKILL.md` and `agents/openai.yaml`; neither contains `.omo` evidence | `.omo/evidence/task-16/archive-inspection.txt` |
| Clean installed wheel | Create a fresh venv and install the final wheel | 60 packages installed, including `grantcompass-korea==0.1.0` from the Task 16 wheel | `.omo/evidence/task-16/wheel-venv.txt`, `.omo/evidence/task-16/wheel-install.txt` |
| Installed-wheel migration and CLI | Load packaged `grantcompass/alembic.ini`, upgrade a fresh explicit database to head, run Alembic check, then `grantcompass --help` | `task16_installed_wheel_upgrade_check_passed`, no schema drift, CLI lists all command groups | `.omo/evidence/task-16/wheel-migration.txt`, `.omo/evidence/task-16/wheel-cli-help.txt` |

## Hands-on HTTP and browser QA

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Real HTTP boundary | Real Uvicorn on `127.0.0.1:8766`; GET companies/program, submit rendered CSRF token, probe hostile Origin, missing token, and hostile Host | `/companies` `200`, program `200`, valid CSRF `303`, hostile Origin `403`, missing CSRF `403`, hostile Host `400`; CSP `frame-ancestors 'none'`, XFO `DENY` | `.omo/evidence/task-16/http-probes.txt`, `.omo/evidence/task-16/uvicorn-stdout.txt`, `.omo/evidence/task-16/uvicorn-stderr.txt` |
| Headed `/companies` smoke | Playwright CLI headed Chromium open and snapshot | Title `관리기업 · GrantCompass`; visible company `합성기업`, owner, active state, and `CASE 1 · recommended` | `.omo/evidence/task-16/browser-companies.png` |
| Headed rendered-CSRF reverse match | Fill actor/reason using snapshot refs and click `전체 기업 역매칭` | Browser records POST `303` followed by GET `200`; condition result IDs advance from `#3/#4` to `#5/#6`; console has 0 errors and 0 warnings | `.omo/evidence/task-16/browser-reverse-csrf.png`, `.omo/evidence/task-16/browser-session.txt` |
| QA cleanup | Close named browser session, stop exact Uvicorn parent/listener PIDs, query the port, and remove only Task 16 temporary `output/playwright` copies | `no browsers`; `port_8766_released=True`; evidence screenshot copies preserved | `.omo/evidence/task-16/runtime-cleanup.txt`, `.omo/evidence/task-16/qa-output-cleanup.txt` |

## Preserved risks and side effects

- The one full-suite skip remains the environment's missing native WeasyPrint runtime
  dependency. Other PDF, benchmark, package, and installed-wheel checks pass.
- Migration `0006_release_blockers` remains intentionally irreversible; the supported
  round trip is `0005 -> 0004 -> 0005` before upgrading to head.
- The ignored root `grantcompass.db`, previously upgraded from revision `0003` to head
  during Task 15, was not opened, altered, downgraded, deleted, restored, or staged.
  No backup exists, as already recorded by Task 15.
- Unrelated `.superpowers/sdd/task-9-report.md`, `.omo`, caches, browser state, and
  other user artifacts were not staged. The Task 16 evidence under
  `.omo/evidence/task-16/` is intentionally preserved.
