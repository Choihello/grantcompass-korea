"""Typed canonical program, rule, and evidence queries for the CLI."""

from dataclasses import dataclass
from typing import assert_never, final

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import or_, select
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
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import AttachmentRow, ProgramRow

_EXPECTED_VALUE: TypeAdapter[ExpectedValue] = TypeAdapter(ExpectedValue)
_DANGLING_EVIDENCE_RELATION = "dangling_evidence_relation"


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
        rows = tuple(
            (await self._session.scalars(select(ProgramRow).order_by(ProgramRow.id))).all()
        )
        return await self._load_programs(rows)

    async def get_program_rules(self, program_id: ProgramId) -> ProgramRules | None:
        """Load one requested canonical program without scanning unrelated programs."""
        row = await self._session.get(ProgramRow, int(program_id))
        if row is None:
            return None
        return (await self._load_programs((row,)))[0]

    async def _load_programs(self, rows: tuple[ProgramRow, ...]) -> tuple[ProgramRules, ...]:
        if not rows:
            return ()
        program_ids = tuple(row.id for row in rows)
        rule_rows = tuple(
            (
                await self._session.scalars(
                    select(EligibilityRuleRow)
                    .outerjoin(
                        DocumentRow,
                        DocumentRow.id == EligibilityRuleRow.source_document_id,
                    )
                    .outerjoin(
                        AttachmentRow,
                        AttachmentRow.id == DocumentRow.attachment_id,
                    )
                    .outerjoin(
                        CurrentNoticeVersionRow,
                        CurrentNoticeVersionRow.version_id == AttachmentRow.notice_version_id,
                    )
                    .where(EligibilityRuleRow.program_id.in_(program_ids))
                    .where(
                        or_(
                            EligibilityRuleRow.source_document_id.is_(None),
                            CurrentNoticeVersionRow.id.is_not(None),
                        )
                    )
                    .order_by(EligibilityRuleRow.id)
                )
            ).all()
        )
        rules_by_program: dict[int, list[EligibilityRuleRow]] = {}
        for rule_row in rule_rows:
            rules_by_program.setdefault(rule_row.program_id, []).append(rule_row)
        evidence_by_rule = await self._load_evidence_for_rules(
            tuple(rule_row.id for rule_row in rule_rows)
        )
        return tuple(
            self._build_program(
                row,
                tuple(rules_by_program.get(row.id, ())),
                evidence_by_rule,
            )
            for row in rows
        )

    def _build_program(
        self,
        row: ProgramRow,
        rule_rows: tuple[EligibilityRuleRow, ...],
        evidence_by_rule: dict[int, tuple[Evidence, ...]],
    ) -> ProgramRules:
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
        if not rule_rows:
            return ProgramRules(program, (), (), ("missing_rules",))
        rules: list[EligibilityRule] = []
        evidence_items: list[Evidence] = []
        errors: list[str] = []
        for rule_row in rule_rows:
            loaded = self._load_rule(rule_row, evidence_by_rule.get(rule_row.id, ()))
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

    def _load_rule(
        self,
        row: EligibilityRuleRow,
        evidence: tuple[Evidence, ...],
    ) -> EligibilityRule | str:
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

    async def _load_evidence_for_rules(
        self,
        rule_ids: tuple[int, ...],
    ) -> dict[int, tuple[Evidence, ...]]:
        if not rule_ids:
            return {}
        result = await self._session.execute(
            select(
                EligibilityRuleRow,
                EvidenceRow,
                DocumentRow,
                DocumentBlockRow,
            )
            .join(rule_evidence, rule_evidence.c.rule_id == EligibilityRuleRow.id)
            .outerjoin(EvidenceRow, rule_evidence.c.evidence_id == EvidenceRow.id)
            .outerjoin(DocumentRow, DocumentRow.id == EvidenceRow.document_id)
            .outerjoin(DocumentBlockRow, DocumentBlockRow.id == EvidenceRow.block_id)
            .where(rule_evidence.c.rule_id.in_(rule_ids))
            .order_by(rule_evidence.c.rule_id, EvidenceRow.id)
        )
        loaded: dict[int, list[Evidence]] = {}
        for rule, row, document, block in result.tuples():
            evidence, source, part = _validated_evidence_relation(row, document, block)
            loaded.setdefault(rule.id, []).append(
                Evidence(
                    id=EvidenceId(evidence.id),
                    document_id=DocumentId(str(source.id)),
                    block_id=DocumentBlockId(part.source_block_id or str(part.id)),
                    source_url=evidence.source_url,
                    page=evidence.page,
                    section_path=evidence.section_path,
                    quote=evidence.quote,
                    content_hash=evidence.content_hash,
                )
            )
        return {rule_id: tuple(items) for rule_id, items in loaded.items()}


def _validated_evidence_relation(
    evidence: EvidenceRow | None,
    document: DocumentRow | None,
    block: DocumentBlockRow | None,
) -> tuple[EvidenceRow, DocumentRow, DocumentBlockRow]:
    if evidence is None or document is None or block is None or block.document_id != document.id:
        raise LookupError(_DANGLING_EVIDENCE_RELATION)
    return evidence, document, block


def _unique_evidence(items: list[Evidence]) -> tuple[Evidence, ...]:
    indexed: dict[EvidenceId, Evidence] = {}
    for item in items:
        if item.id is not None and item.id not in indexed:
            indexed[item.id] = item
    return tuple(indexed[key] for key in sorted(indexed, key=int))
