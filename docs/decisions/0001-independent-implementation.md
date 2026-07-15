# ADR 0001: Independent implementation

- Status: Accepted
- Date: 2026-07-15

## Context

GrantCompass Korea addresses a problem also explored by `djfksjd/ir-search`: discovering Korean public support programs and helping users interpret eligibility. That problem domain and the demonstrated user need are inspiration only.

## Decision

GrantCompass Korea is an independent implementation. Contributors must not copy or adapt code, prompts, schemas, data models, file structure, fixtures, tests, or non-public data from `djfksjd/ir-search` or another implementation. Public behavior may inform a requirement only when it is independently confirmed against an official specification or an official public service.

The initial source contracts are derived directly from official documentation and are recorded separately with their confirmation dates and planned operations:

- [K-Startup source contract](../sources/kstartup.md)
- [기업마당 source contract](../sources/bizinfo.md)

The specification URL and review date must accompany every source-contract change. Tests use independently authored synthetic fixtures and machine-consumed contract fields.

## Commit independence

Each commit must contain one reviewable behavior with its directly related tests or documentation. Commit messages must describe the behavior implemented here, not claim parity with another repository. Reviewers compare changes with this project's requirements and official contracts; they do not use another implementation as a patch source.

## License review procedure

Before adding a dependency, fixture, document, image, prompt, or other external material:

1. Identify the original source and copyright holder.
2. Record the license and exact version or retrieval date.
3. Confirm that use, modification, redistribution, and attribution obligations are compatible with this repository's MIT license.
4. Add required notices and attribution in the same commit.
5. Exclude the material when its provenance or permission is unclear; substitute independently written synthetic content when a test needs the same structure.
6. Obtain maintainer review for copyleft, source-available, custom, or ambiguous terms before inclusion.

Dependency lockfile changes are reviewed with the manifest. Public announcements and attachments are referenced by official URL; they are not redistributed as fixtures unless redistribution permission is established.

## Consequences

Independent implementation may require more specification research and synthetic fixture work. It produces an auditable history, makes provenance explicit, and reduces copyright and license risk.
