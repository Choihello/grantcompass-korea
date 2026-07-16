"""Generate deterministic PDF parser fixtures.

# ─── How to run ───
# uv run python tests/fixtures/documents/generate_pdf_fixtures.py
"""

from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

FIXTURE_DIR = Path(__file__).parent
INVARIANT = 1


def _write_text_pdf(path: Path) -> None:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4, invariant=INVARIANT, pageCompression=0)
    canvas.setTitle("GrantCompass deterministic text fixture")
    canvas.drawString(72, 770, "Grant Program Overview")
    canvas.drawString(72, 740, "Category")
    canvas.drawString(240, 740, "Requirement")
    canvas.drawString(72, 715, "Region")
    canvas.drawString(240, 715, "Seoul based applicants")
    for y in (755, 730, 705):
        canvas.line(65, y, 420, y)
    for x in (65, 220, 420):
        canvas.line(x, 705, x, 755)
    canvas.showPage()
    canvas.drawString(72, 770, "Eligibility Details")
    canvas.drawString(72, 740, "Seoul based early-stage company")
    canvas.save()
    _ = path.write_bytes(output.getvalue())


def _write_scanned_pdf(path: Path) -> None:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4, invariant=INVARIANT, pageCompression=0)
    canvas.setTitle("GrantCompass deterministic scanned fixture")
    canvas.setFillGray(0.92)
    canvas.rect(72, 650, 300, 120, stroke=1, fill=1)
    canvas.setStrokeGray(0.5)
    for offset in range(10, 111, 20):
        canvas.line(90, 650 + offset, 350, 650 + offset)
    canvas.save()
    _ = path.write_bytes(output.getvalue())


def main() -> None:
    """Write byte-identical fixture PDFs at stable paths."""
    _write_text_pdf(FIXTURE_DIR / "text-layer.pdf")
    _write_scanned_pdf(FIXTURE_DIR / "scanned-page.pdf")


if __name__ == "__main__":
    main()
