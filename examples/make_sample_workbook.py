#!/usr/bin/env python3
"""Generate the fully synthetic example workbook used by TabulaCortex docs/tests.

Uses only the Python standard library so the sample can be regenerated without
installing pandas/openpyxl. No real customer, citizen or employee data is used.
"""

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

OUT = Path(__file__).with_name("sales.xlsx")

SALES = [
    ["2025 年零售销售示例数据"],
    ["运营部", "2025-01-10"],
    ["订单号", "日期", "地区", "渠道", "产品", "销售额", "订单数"],
    ["O-1001", "2025-01-05", "华东", "线上", "产品A", 1250.50, 12],
    ["O-1002", "2025-01-07", "华南", "线下", "产品B", 980.00, 8],
    ["O-1003", "2025-02-11", "华东", "线下", "产品A", 1420.75, 15],
    ["O-1004", "2025-02-18", "华北", "线上", "产品C", 2100.00, 20],
    ["O-1005", "2025-03-02", "华南", "线上", "产品B", 760.25, 6],
    ["O-1006", "2025-03-15", "华东", "线上", "产品A", 1890.00, 18],
    ["O-1007", "2025-04-03", "华北", "线下", "产品C", 1320.00, 11],
    ["O-1008", "2025-04-20", "华南", "线下", "产品A", 1550.00, 13],
    ["备注：总订单数 103（虚构数字，仅用于演示）"],
]

REGIONS = [
    ["地区", "责任团队", "季度目标"],
    ["华东", "团队A", 50000],
    ["华南", "团队B", 45000],
    ["华北", "团队C", 40000],
]


def col_letter(idx: int) -> str:
    """0-based column index to Excel column letter."""
    result = ""
    while idx >= 0:
        result = chr(65 + idx % 26) + result
        idx = idx // 26 - 1
    return result


def sheet_xml(rows: list[list[object]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
             '<sheetData>']
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{col_letter(c_idx)}{r_idx}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        lines.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    lines.append("</sheetData></worksheet>")
    return "".join(lines)


def main() -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>
<sheet name="sales_2025" sheetId="1" r:id="rId1"/>
<sheet name="regions" sheetId="2" r:id="rId2"/>
</sheets>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""

    with ZipFile(OUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml(SALES))
        z.writestr("xl/worksheets/sheet2.xml", sheet_xml(REGIONS))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
