# GrantCompass Korea

GrantCompass Korea is an independent, self-hosted open-source project for matching Korean public support programs to business circumstances with traceable evidence.

## Status

Version 0.1 is under active development. The current baseline defines stable domain vocabulary and strict Python project tooling; collection, matching, CLI, and web workflows will be added incrementally.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

## Development setup

```console
uv sync --all-groups
uv run pytest
uv run basedpyright
uv run ruff check .
uv run ruff format --check .
```

Copy `.env.example` to `.env` only when local configuration is needed. Never commit `.env` or real API credentials.

## Data sources

The planned 0.1 collectors use only the official K-Startup public API and the official 기업마당 JSON endpoint. Source material is treated as external data, not as reusable project code.

## Decision limits

GrantCompass results are informational aids. They do not replace the controlling announcement, attached documents, issuing agency guidance, or professional advice. Ambiguous or conflicting conditions require human review.

## Independent implementation

This repository is implemented from official specifications and independently written tests and code. See [ADR 0001](docs/decisions/0001-independent-implementation.md) and [CONTRIBUTING.md](CONTRIBUTING.md) before contributing.

## License

MIT. See [LICENSE](LICENSE).
