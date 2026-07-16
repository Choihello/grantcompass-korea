#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pymupdf==1.28.0",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/build_benchmark.py
# 3. Or choose an output root:
#      uv run scripts/build_benchmark.py --output-root tests/fixtures/benchmark
# ──────────────────

"""Generate the deterministic public HWPX/PDF eligibility benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

SOURCE_ROOT: Final = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from grantcompass.rules.benchmark_artifacts import manifest_row, render_case  # noqa: E402
from grantcompass.rules.benchmark_cases import CASES  # noqa: E402

DEFAULT_OUTPUT: Final = Path("tests/fixtures/benchmark")
OUTPUT_ARGUMENT_COUNT: Final = 2


def build(output_root: Path) -> None:
    """Regenerate all synthetic sources and the JSONL manifest deterministically."""
    document_root = output_root / "documents"
    document_root.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for case in CASES:
        artifact = render_case(case)
        _ = (output_root / artifact.fixture_path).write_bytes(artifact.content)
        row = manifest_row(case, artifact)
        rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    _ = (output_root / "documents.jsonl").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def main(argv: tuple[str, ...] | None = None) -> None:
    """Parse the output directory and build the benchmark."""
    arguments = tuple(sys.argv[1:]) if argv is None else argv
    if not arguments:
        build(DEFAULT_OUTPUT)
        return
    if len(arguments) == OUTPUT_ARGUMENT_COUNT and arguments[0] == "--output-root":
        build(Path(arguments[1]))
        return
    message = "usage: build_benchmark.py [--output-root PATH]"
    raise SystemExit(message)


if __name__ == "__main__":
    main()
