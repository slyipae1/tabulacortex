"""Ensure the environment template contains placeholders, not credentials."""

import re
import unittest
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


class EnvExampleTest(unittest.TestCase):
    def test_required_keys_with_placeholders(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        values = dict(
            re.findall(r"^([A-Z_]+)=(.*)$", text, flags=re.MULTILINE)
        )
        for key in ("MODEL_NAME", "BASE_URL", "API_KEY"):
            with self.subTest(key=key):
                self.assertIn(key, values)
                self.assertTrue(
                    any(mark in values[key].lower() for mark in ("your", "example", "placeholder")),
                    f"{key} should be a placeholder",
                )

    def test_no_long_secret_like_value(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for value in re.findall(r"^[A-Z_]+=(.*)$", text, flags=re.MULTILINE):
            self.assertLess(len(value.strip()), 80)


if __name__ == "__main__":
    unittest.main()
