from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle

from grantcompass.documents.base import DocumentBlock
from grantcompass.documents.pdf_tables import extract_table_blocks
from grantcompass.domain.documents import DocumentBlockId


def _table_pdf(data: list[list[str]], spans: tuple[tuple[int, int, int, int], ...] = ()) -> bytes:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4, invariant=1, pageCompression=0)
    table = Table(data, colWidths=(100, 100), rowHeights=30)
    style = TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)])
    for start_column, start_row, end_column, end_row in spans:
        style.add(
            "SPAN",
            (start_column, start_row),
            (end_column, end_row),
        )
    table.setStyle(style)
    _, height = table.wrapOn(canvas, 200, 100)
    table.drawOn(canvas, 72, 700 - height)
    canvas.save()
    return output.getvalue()


def test_table_dedupe_preserves_same_text_at_different_coordinates() -> None:
    # Given: two equal cells where only the first overlaps native text evidence.
    content = _table_pdf([["Same", "Same"]])
    native = DocumentBlock(
        block_id=DocumentBlockId("page1:text0"),
        ordinal=0,
        kind="paragraph",
        text="Same",
        page=1,
        section_path=None,
        bbox=(72.0, 141.0, 172.0, 171.0),
        provenance="pdf_text",
    )

    # When: table cells are paired to grid geometry and deduplicated.
    cells = extract_table_blocks(content, [native])

    # Then: the non-overlapping equal-text cell remains distinct evidence.
    assert tuple(cell.text for cell in cells) == ("Same",)
    assert cells[0].bbox is not None
    assert cells[0].bbox[0] >= 170


def test_table_grid_preserves_merged_placeholder_alignment() -> None:
    # Given: a merged top row followed by two ordinary cells.
    content = _table_pdf(
        [["Merged", ""], ["Left", "Right"]],
        spans=((0, 0, 1, 0),),
    )

    # When: extracted values are paired through the table grid.
    cells = extract_table_blocks(content, [])

    # Then: the placeholder consumes no geometry and lower cells stay aligned.
    assert tuple(cell.text for cell in cells) == ("Merged", "Left", "Right")
    by_text = {cell.text: cell for cell in cells}
    assert by_text["Merged"].bbox is not None
    assert by_text["Left"].bbox is not None
    assert by_text["Right"].bbox is not None
    assert by_text["Merged"].bbox[2] - by_text["Merged"].bbox[0] == 200
    assert by_text["Left"].bbox[0] < by_text["Right"].bbox[0]
