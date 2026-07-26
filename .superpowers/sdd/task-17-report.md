# Task 17: Finite dangling-evidence result

## Release candidate

- Branch: `feature/grantcompass-0.1`
- Exact baseline: `4830ea7985d8292342c4bb7af262e53dc27f46e6`
- Functional commit: `61a050d9a8aadfa19b5f8b9891e23ebad2bee998`
- This task created no tags. Existing gate tags were left unchanged.

## Narrow correction

- `src/grantcompass/cli/program_queries.py` retains the Task 16 outer-joined,
  bounded evidence load, but no longer emits a raw query-layer exception.
- A missing evidence/document/block row or document/block identity mismatch marks
  that rule ID invalid. All evidence accumulated for the affected rule is removed,
  so the existing rule boundary emits the finite `missing_evidence` result.
- Removing all evidence for the affected rule is fail-closed even when another
  evidence relation on the same rule remains valid.
- `tests/integration/test_query_count_regressions.py` now tests the real
  `ReverseMatchingService` production path rather than expecting a private
  repository exception. The company remains visible, no assessment is fabricated,
  and its input error is `CompanyInputErrorCode.MISSING_EVIDENCE`.
- Task 16 batching remains unchanged: 50-company `/companies` reads remain fixed at
  `3`, and 50 populated latest-match reads remain fixed at `4`.

## TDD evidence

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Corrupt production path, RED | `uv run pytest -q tests/integration/test_query_count_regressions.py -k dangling_evidence` after deleting the referenced document block with foreign keys temporarily disabled and then restored | Real `ReverseMatchingService.reverse_match` fails with raw `LookupError: dangling_evidence_relation`; traceback reaches the query helper | `.omo/evidence/task-17/red-finite-dangling-evidence.txt` |
| Corrupt production path, GREEN | Same invocation after the minimal rule-invalidating implementation | `1 passed`; one company result is returned, `assessment is None`, and `input_error.code is MISSING_EVIDENCE` | `.omo/evidence/task-17/green-finite-dangling-evidence.txt` |
| Bounded-query preservation | `uv run pytest -q tests/integration/test_query_count_regressions.py` | `6 passed`; exact company count `3` and populated latest-match count `4` assertions remain active | `.omo/evidence/task-17/query-regressions.txt` |

## Required verification

| Gate | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Focused query/security/release-schema suite | `uv run pytest -q tests/integration/test_query_count_regressions.py tests/e2e/test_web_security_boundary.py tests/integration/test_release_schema_migration.py` with isolated cache/temp paths | `16 passed` | `.omo/evidence/task-17/precommit/focused.txt`, `.omo/evidence/task-17/precommit/focused.xml` |
| Unfiltered full suite | `uv run pytest -q --junitxml=.omo/evidence/task-17/full-suite.xml` with isolated cache/temp paths | `598 passed, 1 skipped`; only the recognized unavailable native WeasyPrint dependency is skipped | `.omo/evidence/task-17/full-suite.txt`, `.omo/evidence/task-17/full-suite.xml` |
| Ruff format | `uv run ruff format --check src tests migrations typings` | `218 files already formatted` | `.omo/evidence/task-17/precommit/ruff-format.txt` |
| Ruff lint | `uv run ruff check src tests migrations typings` | `All checks passed!` | `.omo/evidence/task-17/precommit/ruff.txt` |
| Static typing | `uv run basedpyright` | `0 errors, 0 warnings, 0 notes` | `.omo/evidence/task-17/precommit/basedpyright.txt` |
| Diff hygiene | `git diff --check` before the functional commit | Exit `0`, no output | `.omo/evidence/task-17/precommit/diff-check.txt` |

## Packaged and runtime behavior

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Final package build | `uv build --out-dir .omo/evidence/task-17/dist` with an absolute cache outside the source tree | Wheel and sdist built successfully | `.omo/evidence/task-17/build-final.txt` |
| Build identity | SHA-256 over final archives | Wheel `525A02DB603C8ED6117DFA974BF4BB8D58B800C021AE069614003F5771E04934`; sdist `3B784B0E65E0D5E56493EFF36A5E886D617CF6F70DBFED6D7F4BD60AF5F97A8B` | `.omo/evidence/task-17/build-hashes.txt` |
| Archive inspection | Inspect final wheel/sdist members | Required skill files exist; `.omo` and the first-build cache are excluded | `.omo/evidence/task-17/archive-inspection.txt` |
| Clean wheel install | Create a fresh venv and install the final wheel | 60 packages installed, including the Task 17 `grantcompass-korea==0.1.0` wheel | `.omo/evidence/task-17/wheel-venv.txt`, `.omo/evidence/task-17/wheel-install.txt` |
| Installed-wheel corrupt CLI search | Seed a fresh database, remove its referenced document block with foreign keys temporarily disabled, restore foreign keys, then run installed `grantcompass search --profile 1 --json` | Exit `0`; result has `final_status: null`, empty conditions/evidence, and exactly `input_errors: ["missing_evidence"]` | `.omo/evidence/task-17/corrupt-cli-seed.txt`, `.omo/evidence/task-17/installed-wheel-corrupt-search.txt` |
| Real HTTP smoke | Run real Uvicorn on `127.0.0.1:8767`, GET `/companies` and `/programs/1` | Both `200`; company is visible; CSP and XFO are present | `.omo/evidence/task-17/http-smoke.txt`, `.omo/evidence/task-17/uvicorn-stdout.txt`, `.omo/evidence/task-17/uvicorn-stderr.txt` |
| Runtime cleanup | Stop exact Uvicorn parent/listener PIDs and query port 8767 | `port_8767_released=True` | `.omo/evidence/task-17/runtime-cleanup.txt` |

## Preserved scope and risks

- Migration files and package migration resources did not change. Per the controller's
  narrow-wave instruction, migration round trips were not repeated; the focused
  release-schema tests were repeated and passed.
- The one full-suite skip remains the environment's missing native WeasyPrint
  dependency.
- The ignored root `grantcompass.db`, previously upgraded during Task 15, was not
  opened, altered, downgraded, deleted, restored, or staged.
- The unrelated tracked `.superpowers/sdd/task-9-report.md`, `.omo`, browser state,
  caches, and other user artifacts were not staged.
- An initially misresolved Task 17 UV cache was moved intact from the root `tmp`
  directory into `.omo/evidence/task-17/first-build-cache`; the final build used an
  absolute external cache and archive inspection proves neither cache entered the
  artifacts.
