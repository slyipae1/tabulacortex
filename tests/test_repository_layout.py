"""Static checks for the public repository layout (no runtime dependencies)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTest(unittest.TestCase):
    def test_required_files_present(self):
        required = [
            "README.md",
            "LICENSE",
            "NOTICE.md",
            ".gitignore",
            ".env.example",
            "requirements.txt",
            "app.py",
            "UI_launch_log.py",
            "workflow_DBconstruct.py",
            "workflow_NL2SQL.py",
            "SystemState.py",
            "ProgressLogger.py",
            "examples/sales.xlsx",
            "examples/make_sample_workbook.py",
            "examples/example_queries.md",
            "docs/architecture.md",
            "docs/user-guide.md",
            "assets/TabulaCortex.png",
            "assets/TabulaCortex.pdf",
        ]
        for rel in required:
            with self.subTest(path=rel):
                self.assertTrue((ROOT / rel).is_file(), f"missing {rel}")


if __name__ == "__main__":
    unittest.main()
