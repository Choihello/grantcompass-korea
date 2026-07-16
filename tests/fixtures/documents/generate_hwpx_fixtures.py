from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

FIXTURE_DIRECTORY = Path(__file__).parent
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
MIMETYPE = b"application/hwp+zip"

ELIGIBILITY_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="urn:fictional:grantcompass:section"
        xmlns:hp="urn:fictional:grantcompass:paragraph">
  <hp:p><hp:run><hp:t>가상기업 새봄랩 지원자격</hp:t></hp:run></hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc>
        <hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p>
      </hp:tc>
      <hp:tc>
        <hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>대상</hp:t></hp:run></hp:p>
      </hp:tc>
      <hp:tc>
        <hp:cellAddr colAddr="2" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>지역</hp:t></hp:run></hp:p>
      </hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc>
        <hp:cellAddr colAddr="0" rowAddr="1"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>업력</hp:t></hp:run></hp:p>
      </hp:tc>
      <hp:tc>
        <hp:cellAddr colAddr="1" rowAddr="1"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>업력 3년 이내</hp:t></hp:run></hp:p>
      </hp:tc>
      <hp:tc>
        <hp:cellAddr colAddr="2" rowAddr="1"/><hp:cellSpan colSpan="1" rowSpan="1"/>
        <hp:p><hp:run><hp:t>가상시 은하구</hp:t></hp:run></hp:p>
      </hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
""".encode()

MERGED_SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<x:sec xmlns:x="urn:fictional:grantcompass:section"
       xmlns:p="urn:fictional:grantcompass:paragraph">
  <p:p><p:run><p:t>가상기관 별빛창업원 병합표</p:t></p:run></p:p>
  <p:tbl>
    <p:tr>
      <p:tc>
        <p:cellAddr colAddr="0" rowAddr="0"/><p:cellSpan colSpan="3" rowSpan="2"/>
        <p:p><p:run><p:t>예비 및 초기 창업자</p:t></p:run></p:p>
      </p:tc>
      <p:tc>
        <p:cellAddr colAddr="3" rowAddr="0"/><p:cellSpan colSpan="1" rowSpan="1"/>
        <p:p><p:run><p:t>확인 필요</p:t></p:run></p:p>
      </p:tc>
    </p:tr>
  </p:tbl>
</x:sec>
""".encode()


def _entry(name: str, content: bytes, compression: int) -> tuple[ZipInfo, bytes]:
    info = ZipInfo(name, FIXED_TIMESTAMP)
    info.compress_type = compression
    info.create_system = 0
    info.external_attr = 0
    return info, content


def build_hwpx(section: bytes) -> bytes:
    output = BytesIO()
    entries = (
        _entry("mimetype", MIMETYPE, ZIP_STORED),
        _entry("Contents/section0.xml", section, ZIP_DEFLATED),
    )
    with ZipFile(output, "w") as archive:
        for info, content in entries:
            _ = archive.writestr(info, content)
    return output.getvalue()


def main() -> None:
    fixtures = {
        "eligibility-table.hwpx": build_hwpx(ELIGIBILITY_SECTION),
        "merged-cells.hwpx": build_hwpx(MERGED_SECTION),
    }
    for filename, content in fixtures.items():
        _ = (FIXTURE_DIRECTORY / filename).write_bytes(content)


if __name__ == "__main__":
    main()
