"""Namespace-independent mapping from safe HWPX XML to evidence blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from grantcompass.documents.base import DocumentBlock, ParseErrorCode, parse_failure
from grantcompass.domain.documents import DocumentBlockId

if TYPE_CHECKING:
    from grantcompass.documents.archive import SectionXml

INVALID_XML: Final[ParseErrorCode] = "invalid_xml"


@dataclass(frozen=True, slots=True)
class MappedSection:
    """Blocks plus counters needed to continue deterministic global addressing."""

    blocks: tuple[DocumentBlock, ...]
    next_ordinal: int
    next_table: int


@dataclass(slots=True)
class _MappingState:
    blocks: list[DocumentBlock] = field(default_factory=list)
    ordinal: int = 0
    paragraph: int = 0
    table: int = 0


def map_section(section: SectionXml, ordinal: int, table: int) -> MappedSection:
    """Parse one section without DTDs, entities, recovery, or external resources."""
    try:
        root = DefusedET.fromstring(
            section.content,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (DefusedXmlException, ET.ParseError) as error:
        raise parse_failure(INVALID_XML, "HWPX section XML is malformed") from error
    state = _MappingState(ordinal=ordinal, table=table)
    _visit(root, state, section)
    return MappedSection(tuple(state.blocks), state.ordinal, state.table)


def _visit(element: ET.Element, state: _MappingState, section: SectionXml) -> None:
    kind = _local_name(element.tag)
    if kind == "tbl":
        _emit_table(element, state, section)
        return
    if kind == "p":
        _emit_paragraph(element, state, section)
        _visit_nested_tables(element, state, section)
        return
    for child in element:
        _visit(child, state, section)


def _visit_nested_tables(
    element: ET.Element,
    state: _MappingState,
    section: SectionXml,
) -> None:
    for child in element:
        if _local_name(child.tag) == "tbl":
            _emit_table(child, state, section)
        else:
            _visit_nested_tables(child, state, section)


def _emit_paragraph(
    element: ET.Element,
    state: _MappingState,
    section: SectionXml,
) -> None:
    text = _element_text(element)
    paragraph = state.paragraph
    state.paragraph += 1
    if not text:
        return
    block_id = f"section{section.number}:p{paragraph}"
    state.blocks.append(
        DocumentBlock(
            block_id=DocumentBlockId(block_id),
            ordinal=state.ordinal,
            kind="paragraph",
            text=text,
            page=None,
            section_path=section.path,
        )
    )
    state.ordinal += 1


def _emit_table(
    element: ET.Element,
    state: _MappingState,
    section: SectionXml,
) -> None:
    table = state.table
    state.table += 1
    for cell in _table_cells(element):
        row, column = _cell_address(cell)
        row_span, column_span = _cell_span(cell)
        reference = f"table{table}:r{row}:c{column}:rs{row_span}:cs{column_span}"
        block_id = f"section{section.number}:{reference}"
        state.blocks.append(
            DocumentBlock(
                block_id=DocumentBlockId(block_id),
                ordinal=state.ordinal,
                kind="table_cell",
                text=_element_text(cell),
                page=None,
                section_path=section.path,
                table_ref=reference,
            )
        )
        state.ordinal += 1


def _table_cells(table: ET.Element) -> tuple[ET.Element, ...]:
    cells: list[ET.Element] = []

    def collect(element: ET.Element) -> None:
        for child in element:
            kind = _local_name(child.tag)
            if kind == "tbl":
                continue
            if kind == "tc":
                cells.append(child)
            else:
                collect(child)

    collect(table)
    return tuple(cells)


def _cell_address(cell: ET.Element) -> tuple[int, int]:
    address = _first_descendant(cell, "cellAddr")
    if address is None:
        raise parse_failure(INVALID_XML, "HWPX table cell has no address")
    column = _nonnegative_integer(_attribute(address, "colAddr"), "column")
    row = _nonnegative_integer(_attribute(address, "rowAddr"), "row")
    return row, column


def _cell_span(cell: ET.Element) -> tuple[int, int]:
    span = _first_descendant(cell, "cellSpan")
    if span is None:
        return 1, 1
    column = _positive_integer(_attribute(span, "colSpan"), "column span")
    row = _positive_integer(_attribute(span, "rowSpan"), "row span")
    return row, column


def _element_text(element: ET.Element) -> str:
    fragments: list[str] = []

    def collect(current: ET.Element) -> None:
        if current is not element and _local_name(current.tag) == "tbl":
            return
        if _local_name(current.tag) == "t":
            fragments.append(_inline_text(current))
            return
        for child in current:
            collect(child)

    collect(element)
    return "".join(fragments)


def _inline_text(element: ET.Element) -> str:
    fragments = [element.text or ""]
    for child in element:
        fragments.append(_inline_text(child))
        fragments.append(child.tail or "")
    return "".join(fragments)


def _first_descendant(
    element: ET.Element,
    name: str,
) -> ET.Element | None:
    return next((item for item in element.iter() if _local_name(item.tag) == name), None)


def _attribute(element: ET.Element, name: str) -> str | None:
    return next(
        (value for key, value in element.attrib.items() if _local_name(key) == name),
        None,
    )


def _nonnegative_integer(value: str | None, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 0:
        raise parse_failure(INVALID_XML, f"HWPX {label} must not be negative")
    return parsed


def _positive_integer(value: str | None, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 1:
        raise parse_failure(INVALID_XML, f"HWPX {label} must be positive")
    return parsed


def _integer(value: str | None, label: str) -> int:
    if value is None:
        raise parse_failure(INVALID_XML, f"HWPX {label} is missing")
    try:
        return int(value)
    except ValueError as error:
        raise parse_failure(INVALID_XML, f"HWPX {label} is invalid") from error


def _local_name(qualified_name: str) -> str:
    return qualified_name.rsplit("}", maxsplit=1)[-1]
