from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.build_benchmark import build

from grantcompass.documents.hwpx import HwpxParser
from grantcompass.documents.pdf import PdfParser
from grantcompass.rules.benchmark import (
    BenchmarkCase,
    BenchmarkLocation,
    BenchmarkRule,
    load_benchmark_cases,
)
from grantcompass.rules.candidates import RegexRuleCandidateProvider

if TYPE_CHECKING:
    from grantcompass.domain.documents import ParsedDocument

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "benchmark"
MANIFEST_PATH = FIXTURE_ROOT / "documents.jsonl"


def _parse(case: BenchmarkCase) -> ParsedDocument:
    content = (FIXTURE_ROOT / case.fixture_path).read_bytes()
    suffix = Path(case.fixture_path).suffix.casefold()
    if suffix == ".hwpx":
        return HwpxParser().parse(case.document_id, content, case.fixture_path)
    if suffix == ".pdf":
        return PdfParser().parse(case.document_id, content, case.fixture_path)
    raise AssertionError(suffix)


def test_every_benchmark_rule_has_resolvable_location() -> None:
    # Given: the reviewed synthetic benchmark manifest.
    cases = load_benchmark_cases(MANIFEST_PATH)

    # When: every binary is parsed by its real parser and rules are extracted.
    documents = tuple((case, _parse(case)) for case in cases)
    results = tuple(
        (case, document, RegexRuleCandidateProvider().extract(document))
        for case, document in documents
    )

    # Then: all 30 unique cases exactly match their reviewed rules and evidence locations.
    assert len(results) == 30
    assert len({case.fixture_path for case, _document, _rules in results}) == 30
    assert sum(case.fixture_path.endswith(".hwpx") for case, _document, _rules in results) == 15
    assert sum(case.fixture_path.endswith(".pdf") for case, _document, _rules in results) == 15
    assert sum(not case.expected_rules for case, _document, _rules in results) == 1
    for case, document, rules in results:
        content = (FIXTURE_ROOT / case.fixture_path).read_bytes()
        assert sha256(content).hexdigest() == case.content_hash
        assert case.expected_rules == tuple(BenchmarkRule.from_rule(rule) for rule in rules)
        assert case.expected_locations == tuple(
            BenchmarkLocation.from_evidence(evidence)
            for rule in rules
            for evidence in rule.evidence
        )
        assert document.warnings == ()


def _tree_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest())
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


def test_benchmark_generation_is_byte_deterministic(tmp_path: Path) -> None:
    # Given: two empty output roots.
    first = tmp_path / "first"
    second = tmp_path / "second"

    # When: the public generator builds the benchmark independently twice.
    build(first)
    build(second)

    # Then: every relative path and byte hash is identical.
    assert _tree_hashes(first) == _tree_hashes(second)
