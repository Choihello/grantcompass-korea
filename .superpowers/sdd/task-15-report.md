# Task 15: Pre-release review-work blockers

## Release candidate

- Branch: `feature/grantcompass-0.1`
- Required baseline: `2a0ec72764da45f15a31d9f57fdf2de5bb930728`
- Functional commit: `cd025f1c7d14a7df6169bd9664fa6bed2c43883d`
- Scope: local HTTP trust boundary, bounded query reads, evidence-ledger wording, and
  regression coverage.
- Tags: this task created no tags. The existing gate tags were left unchanged; the
  controller remains responsible for final annotated release tags and the exact-SHA
  ledger.

## Implemented changes

### HTTP trust boundary

- `src/grantcompass/config.py` adds explicit host/origin allowlists with loopback-only
  defaults, rejects wildcard entries, and accepts a deployment CSRF signing secret.
- `src/grantcompass/web/security.py` implements signed per-browser CSRF tokens, exact
  mutation-origin checks, request-body replay, and anti-framing headers.
- `src/grantcompass/web/app.py` composes the boundary with Starlette trusted-host
  validation and the existing request-size middleware.
- `src/grantcompass/web/forms.py` and all four mutation forms in
  `src/grantcompass/web/templates/` carry the rendered CSRF token.
- `.env.example`, `README.md`, and `SECURITY.md` document loopback defaults and safe
  reverse-proxy/non-loopback deployment configuration.
- Existing E2E app factories now explicitly allow their synthetic test hosts instead
  of making `testserver` a production default.

### Bounded query reads

- `src/grantcompass/cli/program_queries.py` supports a targeted program lookup and
  batches program rules plus joined evidence/document/block data.
- `src/grantcompass/matching/reverse_inputs.py`,
  `src/grantcompass/matching/reverse.py`, and
  `src/grantcompass/cli/profiles.py` batch company/profile inputs and build profiles
  without per-company repository calls.
- `src/grantcompass/web/queries.py` batches current notices, changes, and program-detail
  evidence.
- `src/grantcompass/web/match_queries.py` batches profiles, rule conditions, and latest
  review audits.
- `tests/integration/test_query_count_regressions.py` uses 50-row fixtures and asserts
  exact, row-independent read counts.

### Evidence consistency and gate maintenance

- `docs/qa/manual-qa.md` identifies `15879c4` as historical, identifies
  `2a0ec72764da45f15a31d9f57fdf2de5bb930728` as the latest executable pre-release
  baseline, and reserves authority for the controller-created annotated tags and
  exact-SHA ledger.
- `typings/reportlab/pdfbase/pdfmetrics.pyi` retains ReportLab's external
  `registerFont` API spelling with the narrow required Ruff `N802` suppression.
- `.superpowers/sdd/task-9-report.md` and unrelated ignored/untracked artifacts were
  not staged or modified by this task.

## TDD evidence

| Scenario | Invocation | Binary observable | Captured artifact |
| --- | --- | --- | --- |
| HTTP boundary and first two query regressions, RED | `uv run pytest -q tests/e2e/test_web_security_boundary.py tests/integration/test_query_count_regressions.py` | 8 failures: hostile Host `204` instead of `400`; hostile Origin `422` instead of `403`; missing CSRF mutated with `303`; invalid CSRF reached validation with `422`; no rendered token or framing headers; reverse matching issued `103` reads for 50 companies; detail issued `54` reads for 50 rules | `.omo/evidence/task-15/red-targeted.txt` |
| Program ledger fan-out, RED | targeted ledger query-count test | 1 failure; 50 programs issued `101` reads | `.omo/evidence/task-15/red-ledger-query.txt` |
| Wildcard configuration, RED | targeted wildcard configuration test | 2 failures; both `allowed_hosts=("*",)` and `allowed_origins=("*",)` were accepted | `.omo/evidence/task-15/red-wildcard-config.txt` |
| Security and query regressions, GREEN | `uv run pytest -q tests/e2e/test_web_security_boundary.py tests/integration/test_query_count_regressions.py` with isolated cache/temp paths | `11 passed`; exact GREEN counts are reverse matching `4`, program detail `5`, and program ledger `3` for 50 rows | `.omo/evidence/task-15/targeted-green-post-wildcard2.txt` |

## Required verification

| Gate and exact scenario | Invocation | Binary observable | Captured artifact |
| --- | --- | --- | --- |
| Unfiltered full suite | `uv run pytest -q --junitxml=.omo/evidence/task-15/full-suite-final2.xml` with isolated cache/temp paths | `595 passed, 1 skipped`; only the recognized unavailable WeasyPrint native dependency skip | `.omo/evidence/task-15/full-suite-final2.txt`, `.omo/evidence/task-15/full-suite-final2.xml` |
| Ruff format | `uv run ruff format --check src tests migrations typings` | `218 files already formatted` | `.omo/evidence/task-15/ruff-format-final3.txt` |
| Ruff lint | `uv run ruff check src tests migrations typings` | `All checks passed!` | `.omo/evidence/task-15/ruff-final3.txt` |
| Static typing | `uv run basedpyright` | `0 errors, 0 warnings, 0 notes` | `.omo/evidence/task-15/pyright-final3.txt` |
| Supported migration round trip | Alembic programmatic `upgrade 0005`, `downgrade 0004`, `upgrade 0005`, `upgrade head`, `check` against a fresh explicit disposable SQLite database | `explicit_upgrade_downgrade_upgrade_check_passed`; head is `0006_release_blockers` | `.omo/evidence/task-15/migration-explicit-cycle.txt` |
| Existing benchmarks | `uv run pytest -q tests/integration/test_assessment_benchmark.py tests/integration/test_document_benchmark.py` | `6 passed` | `.omo/evidence/task-15/benchmarks-final.txt` |
| Production scenario suite | `uv run pytest -q tests/integration/test_release_pipeline.py` | `9 passed` | `.omo/evidence/task-15/production-scenario-final.txt` |
| Wheel/sdist build | `uv build --out-dir .omo/evidence/task-15/dist-final` | wheel and sdist built; SHA-256 wheel `A1B45D972331A4828EDD4102DC60457F5D366CDCCFC8A903720DAF62B19F6C89`, sdist `E412C397B711771A7C71CEA6EF677E85C15CE851CA7CB6DA77E03299C1182AFE` | `.omo/evidence/task-15/build-final.txt`, `.omo/evidence/task-15/build-hashes-final.txt` |
| Archive contents | inspect final wheel/sdist member names | both contain `SKILL.md` and `agents/openai.yaml`; neither contains `.omo` evidence | `.omo/evidence/task-15/archive-inspection-final.txt` |
| Clean installed wheel | create fresh venv and `uv pip install` the final wheel | 60 packages installed, including `grantcompass-korea==0.1.0` from the final wheel | `.omo/evidence/task-15/wheel-venv-final.txt`, `.omo/evidence/task-15/wheel-install-final.txt` |
| Installed-wheel migrations and CLI | load packaged `grantcompass/alembic.ini`, upgrade a fresh explicit database to head, run Alembic check, then run `grantcompass --help` | `wheel_migration_upgrade_check_passed`, `No new upgrade operations detected`, and CLI exits successfully with all command groups | `.omo/evidence/task-15/wheel-migration-final.txt`, `.omo/evidence/task-15/wheel-cli-help-final.txt` |
| Real HTTP boundary | run real Uvicorn on `127.0.0.1:8765`, retrieve rendered token, submit valid reverse-match, then probe hostile Origin, missing token, and hostile Host | page `200`, valid CSRF `303`, hostile Origin `403`, missing CSRF `403`, hostile Host `400`; CSP `frame-ancestors 'none'`, XFO `DENY` | `.omo/evidence/task-15/http-probes-final.txt`, `.omo/evidence/task-15/uvicorn-stdout-final.txt`, `.omo/evidence/task-15/uvicorn-stderr-final.txt` |
| Headed browser happy path | Playwright headed Chromium session fills actor/reason fields and clicks the rendered reverse-match form | redirect returns to program detail, new condition IDs render, and browser console reports 0 errors | `.omo/evidence/task-15/browser-valid-csrf.png`, `.omo/evidence/task-15/browser-session.txt` |
| Runtime cleanup | stop the exact Uvicorn parent/listener PIDs and query TCP listeners on port 8765 | `port_8765_released=True` | `.omo/evidence/task-15/port-release-final.txt` |

## Remaining risks and preserved side effect

- The unfiltered suite recognizes one environment limitation:
  `tests/integration/test_real_weasyprint_runtime.py` skips because native WeasyPrint
  dependencies are unavailable. The remaining PDF tests and package installation pass.
- Deployments with multiple workers or which must retain browser sessions across process
  restarts must set the documented 32-character-or-longer CSRF signing secret; the
  loopback development fallback is process-random and safely invalidates old cookies.
- Migration `0006_release_blockers` is intentionally irreversible. The supported
  downgrade/upgrade test therefore exercises `0005 -> 0004 -> 0005` before upgrading to
  head and checking schema drift.
- During migration verification, `uv run alembic upgrade head` was initially executed
  while assuming the environment database URL would override `alembic.ini`. It instead
  upgraded the existing ignored database
  `C:\Users\zerat\Documents\Codex\2026-07-15\new-chat\grantcompass-korea\.worktrees\grantcompass-0.1\grantcompass.db`
  from observed revision `0003_current_notice_state` to `0006_release_blockers`. No
  backup exists. The database was preserved exactly as instructed; no restore,
  downgrade, deletion, or staging was attempted.
- Evidence and disposable verification databases/venvs remain under
  `.omo/evidence/task-15/` as required proof. No QA listener remains. Other pre-existing
  untracked/cache artifacts remain untouched.
