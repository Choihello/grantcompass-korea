# GrantCompass Korea 0.1 release-blocker fix report

## Result

The whole-branch release blockers identified at
`c97ce0c0998b9ee077f91e344295a41c9bf5218c` are fixed. The implementation
now exercises official and institution-owned attachments through the same
parse/candidate/rule/evidence persistence seam, preserves recurrent notice
history, evaluates temporal rules against a persisted reference date, applies
one run-aware freshness policy to CLI/web/PDF surfaces, rejects non-searchable
PDF output, pins validated download destinations while retaining TLS identity,
keeps migration and ORM metadata aligned, and resolves every web request
against its own application instance.

No release tag was created. No live official credential or network endpoint
was used.

## Production changes

### Official and institution document pipeline

- `src/grantcompass/cli/sync.py` constructs the bounded production attachment
  downloader for official sync.
- `src/grantcompass/sources/collector.py` invokes attachment processing after
  canonical notice persistence.
- `src/grantcompass/storage/repositories.py` selects pending/retryable
  attachment rows, caps processing at 20 attachments per notice, downloads
  each attachment, and durably records missing/download/parse states.
- `src/grantcompass/documents/ingest.py` persists deterministic candidate
  rules, exact evidence rows, and rule/evidence links. Generated rules carry
  `source_document_id`; re-analysis deletes those rules and both sides of
  obsolete links before replacement. No-candidate analysis remains visibly
  review-required with `no_rule_candidates`.
- `src/grantcompass/storage/table_eligibility.py` adds the nullable generated
  rule/document provenance foreign key.

Both official sync and `ProgramRepository.create_manual_notice`, which is used
by the institution upload route, reach this same analysis seam. Automatically
extracted rules remain `review_required`; unsupported or ambiguous facts are
not fabricated.

### Notice history and reference dates

- `src/grantcompass/storage/table_notice_analysis.py` removes the invalid
  uniqueness assumption on `change_sets.current_version_id`, allowing a
  previously seen immutable version to become current again.
- `src/grantcompass/storage/notice_snapshots.py`,
  `src/grantcompass/storage/notice_ingest.py`,
  `src/grantcompass/storage/notice_state.py`, and
  `src/grantcompass/storage/table_programs.py` carry announcement date,
  reference date, and reference-date provenance through normalized snapshots,
  version persistence, and current program state. Missing announcement dates
  use the persisted UTC collection date and
  `collected_at_fallback`.
- `src/grantcompass/domain/programs.py` exposes the new domain fields.
- `src/grantcompass/rules/deterministic.py` evaluates business-age and
  representative-age rules against the stable reference date.
- `src/grantcompass/cli/program_queries.py`,
  `src/grantcompass/cli/search.py`, and
  `src/grantcompass/matching/reverse.py` carry the persisted date through
  founder and institution matching.

### Shared freshness, PDF, download security, and app isolation

- `src/grantcompass/web/queries.py` and
  `src/grantcompass/reports/consultation_data.py` use the same latest-source-
  run-aware freshness query as the CLI. A recent retained notice followed by
  a failed latest sync is stale on all three surfaces.
- `src/grantcompass/reports/pdf_runtime.py` opens final renderer output and
  requires a page plus meaningful searchable alphanumeric text.
  `src/grantcompass/reports/pdf.py` applies that validator to alternate
  renderers at the final report boundary as well. Existing finite process
  timeout and cleanup behavior is preserved.
- `src/grantcompass/documents/download.py` resolves and validates every HTTPS
  hop, connects to the selected public IP, sends the original hostname as
  `Host`, and passes it as `sni_hostname` for SNI and certificate verification.
  Redirects are revalidated. The installed `httpcore2` transport consumes
  `sni_hostname` when calling `start_tls`.
- `src/grantcompass/web/runtime.py`, `src/grantcompass/web/routes.py`, and
  `src/grantcompass/web/manual_routes.py` remove the mutable last-created-app
  pointer. Handlers resolve runtime from `request.app`, including read,
  mutation, health, manual upload, reverse-match, case, and PDF routes.

### Migration

`migrations/versions/0006_release_blockers.py`:

- removes `change_sets.current_version_id` uniqueness;
- converts the legacy `documents.attachment_id` unique index to the ORM-
  matching named unique constraint;
- adds/backfills/non-null-enforces program and notice-version reference fields;
- adds nullable announcement date;
- adds/indexes the generated rule/document foreign key.

Fresh upgrade through 0006 followed by Alembic autogenerate check reports
`No new upgrade operations detected`.

## Regression evidence by required outcome

The inherited RED logs were inspected, not treated as final evidence:

1. `.omo/evidence/release-blockers-20260722/red-pipeline.log`: 4 failed because
   the clean manual/official model and pipeline did not exist. Current
   `tests/integration/test_release_pipeline.py`: 4 passed, covering clean
   official sync, clean manual creation, stale-rule cleanup, and durable
   official download failure.
2. The same pipeline RED/GREEN pair proves institution and official documents
   use real parsing and generated rule/evidence persistence rather than direct
   rule-row seeding.
3. `.omo/evidence/release-blockers-20260722/red-recurrence-reference.log`
   reproduced the recurrent B-version uniqueness failure. Current
   `tests/integration/test_current_version_semantics.py`: 2 passed, including
   exact `A -> B -> A -> B` transition history.
4. That RED log also showed the assessment engine rejected
   `reference_date`. Current deterministic-rule and release-pipeline tests
   prove announcement-date and deterministic collection-date fallback
   semantics through persistence and both search directions.
5. `.omo/evidence/release-blockers-20260722/red-freshness-app.log` showed web
   freshness remained fresh after the latest failed run. Current
   `tests/integration/test_run_aware_freshness.py`: passed for CLI, web, and
   consultation report data.
6. `.omo/evidence/release-blockers-20260722/red-pdf-dns.log` showed blank and
   image-only PDFs were accepted. Current PDF focused tests pass for blank,
   image-only, malformed, valid searchable, timeout-cleanup, and alternate
   renderer boundaries.
7. The same RED log showed the downloader still connected by hostname.
   Current `tests/integration/test_attachment_download.py`: 11 passed,
   including pinned IP plus original `Host`/SNI and redirect-hop validation.
8. `.omo/evidence/release-blockers-20260722/red-migration.log` showed Alembic
   index/constraint drift. Current schema regression and a separate fresh
   upgrade/check both pass.
9. The inherited app-isolation RED was reproduced again during takeover:
   79 focused tests passed and
   `test_two_fastapi_instances_keep_routes_bound_to_their_own_runtime`
   failed because app A rendered app B data. After request-scoped resolution,
   the isolated test passed and the complete focused matrix passed 80/80.
10. `tests/integration/test_release_pipeline.py` creates notices and uploads
    document bytes through production repositories/sync, then asserts the
    resulting generated rules/evidence and founder/institution results. It
    never seeds `eligibility_rules`, `evidence`, or `rule_evidence`.

The focused command covered:

```text
tests/integration/test_release_pipeline.py
tests/integration/test_release_schema_migration.py
tests/integration/test_current_version_semantics.py
tests/integration/test_run_aware_freshness.py
tests/integration/test_attachment_download.py
tests/integration/test_document_ingest.py
tests/unit/test_deterministic_rules.py
tests/unit/test_domain_models.py
tests/unit/test_pdf_report.py
tests/unit/test_pdf_runtime_wave2.py
tests/e2e/test_web_app_isolation.py
```

Result: **80 passed in 6.95s**.

## Full verification

- Full `pytest`: **575 passed, 1 skipped in 129.55s**. The single skip is
  `tests/integration/test_real_weasyprint_runtime.py` for the already
  recognized missing native WeasyPrint dependency condition.
- `ruff check src tests`: **All checks passed**.
- `ruff format --check src tests`: **202 files already formatted**.
- `basedpyright`: **0 errors, 0 warnings, 0 notes**.
- Fresh Alembic upgrade through 0006 plus `alembic check`: exit 0,
  **No new upgrade operations detected**.
- Document and assessment benchmarks: **6 passed in 11.27s**; fixture corpus
  counts are exactly **30 documents / 100 assessments**.
- `uv lock --check`: exit 0, **Resolved 71 packages** without lock changes.
- Package build: exit 0.
  - wheel SHA-256:
    `497b17f5f281fe98cf7eac5837ae19b78e97dd62156d768dcf30ee089d5e9438`
  - sdist SHA-256:
    `acf0b696cceca92e41a2df21f24c3524dc687632dfe7783fcc16e3013ea78507`
  - direct archive inspection found
    `grantcompass/skills/grantcompass-korea/SKILL.md` and
    `grantcompass/skills/grantcompass-korea/agents/openai.yaml` in the wheel,
    and both corresponding `skills/grantcompass-korea` paths in the sdist.
- `git diff --check`: exit 0.

All pytest cache and basetemp paths for takeover verification were placed
under the operating-system temporary directory. The pre-existing protected
cache/evidence directories were not reused or modified.

## Manual clean-database QA

The offline official driver used the real `synchronize_sources` orchestration,
collector, downloader, repository, parser, candidate provider, and founder
search against a database created by `initialize_database`. A synthetic
adapter and `MockTransport` replaced only live credentials/network.

Observed official result:

```text
sync: stored=1 unchanged=0 failed=0 freshness=fresh
programs=1 versions=1 attachments=1 documents=1 blocks=7
rules=1 evidence=1 rule_evidence_links=1 source_runs=1 assessments=1
reference_date=2026-01-01 reference_source=announcement_date
founder_search_results=1 condition=satisfied evidence=1
```

The institution driver used actual ASGI HTTP requests to
`GET /programs/manual`, multipart `POST /programs/manual`, and
`POST /programs/1/reverse-match`, followed by the program-detail page and CLI
founder search. The only direct persistence setup was the applicant/company;
rules and evidence came exclusively from the uploaded HWPX.

Observed institution result:

```text
manual_form=200 upload=303 reverse_match=303 detail_has_founder=true
programs=1 versions=1 attachments=1 documents=1 blocks=7
rules=1 evidence=1 rule_evidence_links=1 source_runs=0 assessments=2
reference_date=2026-01-15 reference_source=collected_at_fallback
founder_search_results=1 condition=satisfied evidence=1
```

## Intended committed files

Production:

```text
src/grantcompass/cli/program_queries.py
src/grantcompass/cli/search.py
src/grantcompass/cli/sync.py
src/grantcompass/documents/download.py
src/grantcompass/documents/ingest.py
src/grantcompass/domain/programs.py
src/grantcompass/matching/reverse.py
src/grantcompass/reports/consultation_data.py
src/grantcompass/reports/pdf.py
src/grantcompass/reports/pdf_runtime.py
src/grantcompass/rules/deterministic.py
src/grantcompass/sources/collector.py
src/grantcompass/storage/notice_ingest.py
src/grantcompass/storage/notice_snapshots.py
src/grantcompass/storage/notice_state.py
src/grantcompass/storage/repositories.py
src/grantcompass/storage/table_eligibility.py
src/grantcompass/storage/table_notice_analysis.py
src/grantcompass/storage/table_programs.py
src/grantcompass/web/manual_routes.py
src/grantcompass/web/queries.py
src/grantcompass/web/routes.py
src/grantcompass/web/runtime.py
migrations/versions/0006_release_blockers.py
```

Tests/fixtures:

```text
tests/cli_search_fixtures.py
tests/e2e/test_institution_review_web.py
tests/e2e/test_web_app_isolation.py
tests/integration/task12_fixtures.py
tests/integration/task12_reverse_fixtures.py
tests/integration/test_attachment_download.py
tests/integration/test_current_version_semantics.py
tests/integration/test_document_ingest.py
tests/integration/test_release_pipeline.py
tests/integration/test_release_schema_migration.py
tests/integration/test_run_aware_freshness.py
tests/unit/test_deterministic_rules.py
tests/unit/test_domain_models.py
tests/unit/test_forward_match.py
tests/unit/test_markdown_impacts.py
tests/unit/test_markdown_report.py
tests/unit/test_pdf_report.py
tests/unit/test_pdf_runtime_wave2.py
tests/unit/test_roadmap.py
```

Release evidence:

```text
.superpowers/sdd/release-blocker-fix-report.md
```

## Preserved unrelated state and residual risks

The pre-existing `.superpowers/sdd/task-9-report.md` modification and all
untracked `.debug-journal.md`, `.omo/`, `.playwright-cli/`, temporary,
cache, and XML artifacts remain unstaged and uncommitted.

Residual risks are limited to explicitly excluded environment/integration
boundaries:

- no live official credential/network acceptance was performed;
- native WeasyPrint rendering remains unavailable on this host, so only the
  recognized native-loader integration test is skipped;
- DNS pinning was verified at the request/transport contract with offline
  transport tests, not against a live public TLS endpoint.

These limitations do not weaken deterministic pipeline, persistence,
freshness, PDF-output validation, migration, app-isolation, or package
verification.
