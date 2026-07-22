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

## Fix wave 1 — review findings closed

Functional commit A is `8ab4cb2542bc5e859932ef19917edd40d6cab561` with tree
`7a0b1db20ad9d1a54eff8cb036185ccd58cd7190`. All executable behavior, package inputs,
automated checks, built artifacts, and manual QA below were exercised at that immutable commit.
The final commit B changes only this report and `docs/qa/manual-qa.md`; it does not change the
tested tree.

### TDD evidence

The focused review-finding test set was captured RED before implementation:

```text
13 failed, 5 passed in 1.49s
```

Failures covered missing inventory derivation, the first-run 503 false stale label,
encoded/mixed-case credential leakage from a formatted URL argument, absent Skill packaging,
missing native-loader classification, and invalid cron redirection. The focused set after the
minimal implementations was GREEN:

```text
18 passed, 1 skipped in 1.55s
```

The skip was the real integration preflight matching the recognized missing native-library
family. Classification tests prove that missing modules, syntax errors, timeouts, and unrelated
loader errors do not qualify for the skip.

### Finding resolution

- Failure health is derived from a complete recognized-candidate inventory. Deliberately omitted
  mappings appear in `hidden_failures`; positive and empty inventories are tested. A latest 503 is
  labeled stale only when the same source has a prior successful run and retained notice data.
- Query credential names are percent-decoded only for key comparison and matched with `casefold`.
  Formatted messages and URL-object arguments lose secret values, while noncredential arguments
  remain unchanged. Logger-level/handler mutations live in a cleanup-protected fixture.
- Hatch includes the source `skills/` tree in sdist and force-includes the Skill at
  `grantcompass/skills/grantcompass-korea` in the wheel.
- The functional WeasyPrint test skips only recognized native-library loader diagnostics.
- The README cron line creates `var` before redirecting to `var/sync.log`, with a docs contract
  regression test.
- Manual QA now names immutable commit A and explains the metadata-only commit B boundary.

### Commit-A verification

- Full suite/JUnit: 559 passed, 1 skipped in 135.89 seconds; 560 tests, zero failures, zero errors.
- Focused gate: 18 passed, 1 recognized native-loader skip.
- Benchmarks: 6 passed in 14.40 seconds; exactly 30 document and 100 assessment cases.
- Ruff: all checks passed; 207 files formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- Lock: 71 packages resolved without change.
- Build: wheel and source distribution created successfully.
- Changed files: all below 250 pure lines; `git diff --check` passed.

Archive members inspected directly:

- wheel `grantcompass/skills/grantcompass-korea/SKILL.md`
- wheel `grantcompass/skills/grantcompass-korea/agents/openai.yaml`
- sdist `grantcompass_korea-0.1.0/skills/grantcompass-korea/SKILL.md`
- sdist `grantcompass_korea-0.1.0/skills/grantcompass-korea/agents/openai.yaml`

Commit-A artifact hashes:

- wheel `22a32b05bc340f3aa2bca77138d20085ac7fcac6534c6598717858f15829756e`
- sdist `4dd5e624f72b3e99f3963679ccf096d927851ed966ff987e457da2e87cbb52cd`

A fresh wheel-only environment installed 60 packages from the artifact. Its installed
`grantcompass` executable rendered all command groups, and `importlib.resources` located the Skill
under that environment's `Lib/site-packages/grantcompass/skills/grantcompass-korea/SKILL.md`.

### Commit-A manual QA

- Founder CLI: fresh database initialization and synthetic profile creation passed; both
  fixture-backed source syncs were fresh with zero failures; search returned five results across
  eligible, conditional, needs-review, ineligible, and missing-rules states; the report preserved
  URL/hash/block/page/section evidence; missing profile returned exit 3.
- Real Chrome institution flow: two programs, official source/evidence, all-company reverse match,
  attributed conditional override, contacted transition, and both immutable reasons passed.
- Failure flow: all four persisted IDs and `hidden_failures=0` were visible; the real health GET
  returned 200. Automated tests additionally prove hidden/unmapped and first-run-503 negatives.
- PDF route: reached the renderer and returned `weasyprint_render_failed` because the Windows host
  lacks the native library. No PDF render success is claimed.

No tag was created. Unrelated Task 9 and scratch artifacts remained uncommitted.
