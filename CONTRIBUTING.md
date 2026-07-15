# Contributing

Thank you for improving GrantCompass Korea.

## Development workflow

1. Read [ADR 0001](docs/decisions/0001-independent-implementation.md).
2. Write an observable failing test before application code.
3. Keep commits focused on one independently reviewable behavior.
4. Run the complete quality gate before requesting review.

```console
uv sync --all-groups
uv lock --check
uv run pytest
uv run basedpyright
uv run ruff check .
uv run ruff format --check .
```

Python code must remain compatible with Python 3.12, pass basedpyright in `all` mode, and pass Ruff with `ALL` rules enabled. Do not use `Any`, `object`, `cast`, type-ignore comments, pyright-ignore comments, direct `asyncio` imports, or synchronous I/O at an async boundary.

## Independent implementation

Do not copy code, prompts, schemas, file layouts, fixtures, or tests from `djfksjd/ir-search` or another implementation. Derive behavior from official specifications and public source behavior, then write new tests and code in this repository. Include the official source URL and the date reviewed when updating a source contract.

## Fixtures and personal data

Fixtures must be synthetic, redistributable, and free of API keys, personal information, unpublished documents, and private business data. If redistribution rights for a public document are unclear, retain only its public URL and a content hash; reproduce the required structure with clearly synthetic content.

Synthetic organizations and people must use conspicuously fictional values that do not resemble real entities. Review staged changes for secrets and personal data before every commit.

## Dependency and license review

For every dependency or external asset, record its source, license, purpose, version constraint, and redistribution obligations. Do not merge material with an unknown or incompatible license. Update notices or attribution files when required and ask a maintainer for review when compatibility is uncertain.
