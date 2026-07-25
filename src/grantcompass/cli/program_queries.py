"""Typed canonical program, rule, and evidence queries for the CLI."""

from dataclasses import dataclass
from typing import assert_never, final

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.documents import DocumentBlockId, DocumentId, Evidence, EvidenceId
from grantcompass.domain.eligibility import (
    EligibilityRule,
    EligibilityRuleId,
    ExpectedValue,
)
from grantcompass.domain.enums import ReviewStatus, RuleKind
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.programs import Program
from grantcompass.storage.table_documents import (
    DocumentBlockRow,
    DocumentRow,
    EvidenceRow,
    rule_evidence,
)
from grantcompass.storage.table_eligibility import EligibilityRuleRow
from grantcompass.storage.table_programs import ProgramRow

_EXPECTED_VALUE: TypeAdapter[ExpectedValue] = TypeAdapter(ExpectedValue)


@dataclass(frozen=True, slots=True)
class ProgramRules:
    """One canonical program with parsed rules, evidence, and visible errors."""

    program: Program
    rules: tuple[EligibilityRule, ...]
    evidence: tuple[Evidence, ...]
    errors: tuple[str, ...]


@final
class ProgramQueryRepository:
    """Load untrusted stored program analysis into finite typed values."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind program queries to one caller-owned session."""
        self._session: AsyncSession = session

    async def list_program_rules(self) -> tuple[ProgramRules, ...]:
        """Load every canonical program in deterministic ID order."""
        rows = (await self._session.scalars(select(ProgramRow).order_by(ProgramRow.id))).all()
        return tuple([await self._load_program(row) for row in rows])

    async def _load_program(self, row: ProgramRow) -> ProgramRules:
        program = Program(
            id=ProgramId(row.id),
            canonical_key=row.canonical_key,
            title=row.title,
            organization=row.organization,
            application_start=row.application_start,
            application_end=row.application_end,
            created_at=row.created_at,
            updated_at=row.updated_at,
            reference_date=row.reference_date,
            reference_date_source=row.reference_date_source,
        )
        rule_rows = (
            await self._session.scalars(
                select(EligibilityRuleRow)
                .where(EligibilityRuleRow.program_id == row.id)
                .order_by(EligibilityRuleRow.id)
            )
        ).all()
        if not rule_rows:
            return ProgramRules(program, (), (), ("missing_rules",))
        rules: list[EligibilityRule] = []
        evidence_items: list[Evidence] = []
        errors: list[str] = []
        for rule_row in rule_rows:
            loaded = await self._load_rule(rule_row)
            match loaded:
                case str() as error:
                    errors.append(error)
                case EligibilityRule() as rule:
                    rules.append(rule)
                    evidence_items.extend(rule.evidence)
                case _:
                    assert_never(loaded)
        return ProgramRules(
            program,
            tuple(rules),
            _unique_evidence(evidence_items),
            tuple(dict.fromkeys(errors)),
        )

    async def _load_rule(self, row: EligibilityRuleRow) -> EligibilityRule | str:
        try:
            kind = RuleKind(row.kind)
        except ValueError:
            return "malformed_rule_kind"
        try:
            review_status = ReviewStatus(row.review_status)
        except ValueError:
            return "malformed_rule_review_status"
        try:
            expected_value = _EXPECTED_VALUE.validate_json(row.expected_json)
        except ValidationError:
            return "malformed_expected_value"
        evidence = await self._load_rule_evidence(row.id)
        if not evidence:
            return "missing_evidence"
        return EligibilityRule(
            id=EligibilityRuleId(row.id),
            program_id=ProgramId(row.program_id),
            kind=kind,
            operator=row.operator,
            expected_value=expected_value,
            required=row.required,
            review_status=review_status,
            rule_version=row.rule_version,
            evidence=evidence,
        )

    async def _load_rule_evidence(self, rule_id: int) -> tuple[Evidence, ...]:
        evidence_ids = (
            await self._session.scalars(
                select(EvidenceRow.id)
                .join(rule_evidence, rule_evidence.c.evidence_id == EvidenceRow.id)
                .where(rule_evidence.c.rule_id == rule_id)
                .order_by(EvidenceRow.id)
            )
        ).all()
        loaded: list[Evidence] = []
        for evidence_id in evidence_ids:
            evidence = await self._load_evidence(evidence_id)
            if evidence is None:
                return ()
            loaded.append(evidence)
        return tuple(loaded)

    async def _load_evidence(self, evidence_id: int) -> Evidence | None:
        row = await self._session.get(EvidenceRow, evidence_id)
        if row is None:
            return None
        document = await self._session.get(DocumentRow, row.document_id)
        block = await self._session.get(DocumentBlockRow, row.block_id)
        if document is None or block is None:
            return None
        return Evidence(
            id=EvidenceId(row.id),
            document_id=DocumentId(str(document.id)),
            block_id=DocumentBlockId(block.source_block_id or str(block.id)),
            source_url=row.source_url,
            page=row.page,
            section_path=row.section_path,
            quote=row.quote,
            content_hash=row.content_hash,
        )


def _unique_evidence(items: list[Evidence]) -> tuple[Evidence, ...]:
    indexed: dict[EvidenceId, Evidence] = {}
    for item in items:
        if item.id is not None and item.id not in indexed:
            indexed[item.id] = item
    return tuple(indexed[key] for key in sorted(indexed, key=int))
