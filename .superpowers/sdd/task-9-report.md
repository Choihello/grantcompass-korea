# Task 9 report: reproducible eligibility assessments

## Delivered

- Added deterministic evaluators for business age, representative age, region, industry,
  performance, duplicate-benefit history, and visible unsupported natural-language rules.
- Added calendar-correct completed-month arithmetic with UTC normalization, clamped end-of-month
  anniversaries, and leap-day behavior.
- Added immutable typed evaluator outcomes, finite assessment-input errors, exact aggregate
  precedence, conditional optional rules, and review-status orchestration.
- Added conservative conflict promotion for required comparable rules from distinct source
  identities. Numeric facts compare within one fact family, performance rules compare within one
  metric key, and set rules compare only overlapping normalized members.
- Added an optional persisted `ApplicantProfile` ID while preserving frozen Pydantic behavior and
  JSON round-trip serialization.
- Added a frozen Pydantic boundary for an independently authored 100-row JSONL assessment
  benchmark. Every case runs twice and asserts exact rule status, error ID, evidence IDs, final
  status, and review status.
- Narrowed the Task 8 deterministic artifact comparison to the 31 files owned by the document
  benchmark so unrelated benchmark manifests cannot invalidate its byte-reproducibility proof.

## RED and GREEN evidence

- Unit RED before production edits:
  - Command: `.venv\Scripts\python.exe -m pytest tests/unit/test_deterministic_rules.py
    tests/unit/test_final_status.py -q`
  - Result: two collection errors for missing `grantcompass.rules.deterministic` and
    `grantcompass.rules.aggregate`; exit 1 in 0.37 seconds.
- Benchmark RED before its boundary and manifest:
  - Command: `.tools\uv-dist\uv.exe run pytest
    tests/integration/test_assessment_benchmark.py -q`
  - Result: one collection error for missing `grantcompass.rules.assessment_benchmark`; exit 1 in
    0.22 seconds.
- First unit GREEN: 38 passed in 0.13 seconds.
- First benchmark GREEN: 2 passed in 0.10 seconds.
- Final Task 9 focused suite: 46 passed in 0.25 seconds.
- First Gate B run exposed one Task 8 fixture-ownership failure: 71 passed and 1 failed. After
  restricting that comparison to `documents.jsonl` plus `documents/**`, final Gate B passed:
  73 passed in 13.27 seconds.
- Final full suite: 260 passed in 34.69 seconds.

## Benchmark composition and coverage

- Manifest size: exactly 100 JSONL rows and 52,941 bytes.
- Every case ID and substantive input signature is unique. Signatures exclude case, profile,
  rule, program, evidence, and synthetic source identities, so persistence-ID changes cannot
  inflate uniqueness.
- Rule-kind counts:
  - business age 23
  - representative age 16
  - region 24
  - industry 18
  - performance 18
  - duplicate benefit 11
  - natural language 2
- Operator counts:
  - `lte` 22
  - `lt` 7
  - `gte` 17
  - `gt` 9
  - `in` 35
  - `not_in` 16
  - unsupported `contains` 6
- Expected item statuses:
  - satisfied 49
  - unsatisfied 23
  - unknown 27
  - conditional 7
  - conflict 6
- Expected final statuses:
  - eligible 41
  - ineligible 23
  - needs review 29
  - conditional 7
- Explicit coverage tokens include 21 boundaries, 7 missing-fact classes, 7 malformed expected
  values, 3 conflicts, 1 unrelated non-conflict, 7 conditional cases, 6 review-required cases,
  1 evaluator failure, 2 leap-day cases, and 3 end-of-month cases.
- Performance inputs use `performance[metric_key] = number`; performance rules use
  `(metric_key, numeric_threshold)`. Benefit-history inputs use
  `benefit_history[*].program_id = string`.
- Expected outcomes are literal manifest values. The benchmark boundary projects inputs into
  domain objects but never invokes production evaluators to calculate an expectation.

## Verification

- Ruff format: 3 files reformatted and 108 files unchanged on the repository-wide run.
- Ruff check across `src`, `tests`, `scripts`, and `migrations`: all checks passed.
- Full configured basedpyright: 0 errors, 0 warnings, 0 notes.
- Explicit no-excuse audit: no violations in 15 changed Python files.
- `git diff --check`: clean.
- No `gate-b-evidence-assessment` tag was created during implementation.
- Pure LOC:
  - production modules: eligibility 91, aggregate 14, assessment benchmark 160, conflicts 81,
    deterministic engine 174, evaluation types 30, evaluation values 66, evaluators 164
  - test modules: fixtures 75, deterministic rules 152, engine 146, inputs 119, final status 32,
    assessment benchmark 74, document benchmark 81

## Architectural self-review

- Each production module owns one responsibility: aggregation, orchestration, outcomes, value
  parsing, evaluator logic, conflict promotion, or benchmark parsing.
- Untrusted JSONL crosses frozen Pydantic models once; internal evaluator outcomes and domain
  results are immutable typed values.
- The evaluator registry is the sole intentionally mutable seam and exists for explicit evaluator
  injection. Only `RuntimeError` is converted to a visible unknown result; other exceptions
  propagate.
- Rule-kind conflict dispatch uses a complete comparator table. Open operators and malformed
  values use strict adapters and finite unknown outcomes rather than unreachable assertions.
- No `Any`, `object`, casts, type ignores, broad exceptions, prose assertions, or files over 250
  pure LOC were introduced.
- Functions remain at three parameters or fewer, and every introduced behavior is covered by a
  focused test or the independent 100-case benchmark.
