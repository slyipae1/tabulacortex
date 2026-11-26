"""Validate that the bundled workbook is a well-formed synthetic XLSX."""

import unittest
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

WORKBOOK = Path(__file__).resolve().parents[1] / "examples" / "sales.xlsx"


class SampleWorkbookTest(unittest.TestCase):
    def test_parts_are_valid_xml(self):
        with ZipFile(WORKBOOK) as zf:
            names = zf.namelist()
            self.assertIn("xl/workbook.xml", names)
            self.assertIn("xl/worksheets/sheet1.xml", names)
            self.assertIn("xl/worksheets/sheet2.xml", names)
            for name in names:
                with self.subTest(part=name):
                    ElementTree.fromstring(zf.read(name))

    def test_sheet_names(self):
        with ZipFile(WORKBOOK) as zf:
            root = ElementTree.fromstring(zf.read("xl/workbook.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        names = [el.get("name") for el in root.findall(".//m:sheet", ns)]
        self.assertEqual(names, ["sales_2025", "regions"])


if __name__ == "__main__":
    unittest.main()
