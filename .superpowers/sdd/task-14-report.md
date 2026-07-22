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

## Final fix wave — authoritative commit C

Functional commit C is `15879c453d7ee855c05ca3e70b99c608c1ee037d` with tree
`6c500aae8ced3903e594605a3952262a2dc9da49`. Its subject is
`fix: expose persisted hidden failure inventory`. The final commit D changes only this report,
`docs/qa/manual-qa.md`, and the two fresh browser captures under `docs/assets/`; D contains no
code, tests, package configuration, or built-artifact inputs.

### Production hidden-failure inventory

The health inventory now audits the latest persisted source run per source, review-required
attachment parse errors, all field conflicts, rule-assessment error IDs, and incomplete profiles.
Recognized states retain the fixed visible catalog order. Unrecognized persisted candidates are
deduplicated and deterministically sorted under this stable naming contract:

- `source_run:<source>:<error_code>`
- `attachment_parse:<error_code>`
- `field_conflict:<field_name>`
- `rule_assessment:<error_id>`

Safe tokens are case-folded ASCII. Unsafe values become a non-reversible
`opaque-<12-character-sha256-prefix>` token, preventing arbitrary persisted text from becoming a
health identifier.

Tests persist and retrieve a non-503 source failure, duplicate attachment errors, a non-deadline
field conflict, and a rule-assessment error. The duplicate is collapsed and the exact hidden
order is asserted. A latest 503 without retained same-source success data is hidden as
`source_run:kstartup:http_503`, never mislabeled stale.

### Finite WeasyPrint preflight

The production `probe_weasyprint_module` preflight has a five-second default hard timeout around
the blocking import. A blocked import raises `TimeoutError`; native-loader classification sees
stderr only after the probe actually completes. Tests cover both the finite timeout and an
immediate recognized native-loader diagnostic. The real-host integration check uses this same
production probe.

### Final TDD and verification

The final fix set was first captured RED:

```text
4 failed, 9 passed, 1 skipped in 2.27s
```

The failures were the first-run 503 hidden inventory, persisted hidden inventory, missing finite
timeout probe, and missing immediate probe behavior. The same set then passed GREEN:

```text
13 passed, 1 skipped in 1.93s
```

Authoritative immutable-C verification:

- Focused Task 14 gate: 29 passed, 1 skipped in 3.60 seconds.
- Full suite/JUnit: 561 passed, 1 skipped in 138.74 seconds; 562 tests, zero failures,
  zero errors, one skip.
- Sole skip: the recognized native WeasyPrint loader condition at
  `tests/integration/test_real_weasyprint_runtime.py:25`.
- Ruff lint passed; Ruff format reported 208 files already formatted.
- basedpyright: 0 errors, 0 warnings, 0 notes.
- `uv lock --check`: 71 packages without lockfile change.
- Benchmarks: 6 passed in 14.60 seconds; exactly 30 document and 100 assessment cases.
- Every changed production/test file is below 250 pure lines; `git diff --check` passed.

### Final artifacts

The single authoritative commit-C artifact hash set is:

- wheel `f11223f5964031fc96416d90303c36b48a2f0c906bbc47a78765e1e80944a013`
- sdist `f6de5dfd1315401f2f59544a11e72cfc270fb13ecca78e96f4828292bb12383c`

Direct inspection found `grantcompass/skills/grantcompass-korea/SKILL.md` and
`grantcompass/skills/grantcompass-korea/agents/openai.yaml` in the wheel and their corresponding
`grantcompass_korea-0.1.0/skills/` members in the sdist. Every earlier artifact hash in this report
— initial release hashes and commit-A hashes alike — is historical and explicitly superseded by
the commit-C pair above.

### Final manual QA

Fresh live Uvicorn reads at C produced:

```json
{"visible_failure_ids":["source_503_stale","scan_pdf_ocr_required","conflicting_deadlines","incomplete_profile_needs_review"],"hidden_failures":["attachment_parse:encrypted_pdf","field_conflict:organization","rule_assessment:unsupported_rule_kind","source_run:bizinfo:rate_limited"]}
```

Two mixed-state requests were byte-identical. A visible-only database returned the four visible
IDs with no hidden failures, and a clean database returned two empty arrays.

A real Chromium session at C ran all-company matching as `합성 C 기관담당자` for
`합성 C 전체기업 재검토`, saved a conditional review with reason
`합성 C 증빙 재확인 필요`, and transitioned the case to `contacted` as
`합성 C 상담담당자` for `합성 C 상담 완료`. The case showed p.1 eligibility evidence and both
immutable reasons. Fresh commit-C screenshots replace the stale prior captures:

- `docs/assets/institution-workspace.png`, SHA-256
  `6324809afae4953dc23ca2bc9ed201e7073d8ee39e3632b750062d1761d254cd`
- `docs/assets/failure-scenarios.png`, SHA-256
  `9bfe0fddea442d81c4984d544673aad4bd9644200ec5e95dcfacc9af6b10cc97`

No tag was created. Unrelated Task 9 and scratch artifacts remained uncommitted.
