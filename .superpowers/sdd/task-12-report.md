# Task 12 implementation report

## Outcome

Shipped auditable institution reverse matching, support-case transitions, and attributed assessment reviews without changing the existing database schema.

Reverse matching reuses the canonical Task 11 program/rule/evidence and profile readers, evaluates every active or inactive managed company exactly once, keeps invalid stored inputs visible as finite per-company errors, records every successful run as a new immutable assessment, and returns deterministic status/ID ordering with every current official source/version/hash identity.

Case transitions enforce the complete forward-only workflow graph with optimistic updates. Each successful transition appends compact canonical before/after JSON with actor, reason, and injected UTC time in the same transaction. Assessment review preserves all automatic fields, validates persisted rule-assessment identities, derives a separate effective result, advances review progress optimistically, and appends exact prior/effective audit snapshots atomically.

No migration was necessary: the existing `managed_companies`, `cases`, `assessments`, `rule_assessments`, and append-only `audit_events` schema already represents the required immutable automatic state, review progress, and attributed history. Task 12 only adds typed domain and repository behavior over those tables.

## Verification

- Initial RED: `.omo/evidence/task12/red-behavior.txt` (three missing-boundary collection errors).
- Expanded reverse RED/GREEN: `.omo/evidence/task12/reverse-errors-red.txt` and `.omo/evidence/task12/reverse-errors-green.txt`.
- Expanded review RED/GREEN: `.omo/evidence/task12/review-expanded-red2.txt` and `.omo/evidence/task12/review-expanded-green2.txt` (`18 passed`).
- Corruption boundaries: `.omo/evidence/task12/corruption-green.txt` (`5 passed`).
- Task 12 aggregate: `.omo/evidence/task12/aggregate-green-final.txt` (`115 passed in 64.80s`).
- Full suite final: `.omo/evidence/task12/full-pytest-final.txt` (`445 passed in 127.37s`).
- Ruff: `.omo/evidence/task12/ruff-check.txt` (`All checks passed!`).
- Ruff format: `.omo/evidence/task12/ruff-format.txt` (`155 files already formatted`).
- basedpyright all: `.omo/evidence/task12/basedpyright.txt` (`0 errors, 0 warnings, 0 notes`).
- No-excuse changed Python: `.omo/evidence/task12/no-excuse.txt` (`no violations in 21 file(s)`).
- Pure LOC: `.omo/evidence/task12/pure-loc.txt` (largest changed file 209 pure LOC; hard limit 250).
- Whitespace: `.omo/evidence/task12/git-diff-check.txt` (`GIT_DIFF_CHECK_PASS`).

## Handoff

The Task 12 institutional workflows and their regression evidence are complete. This task does not add Task 13 web UI behavior or create a release tag.
