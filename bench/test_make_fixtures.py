"""Tests for deterministic network-generation fixture output."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.make_fixtures import build


class MakeFixturesTests(unittest.TestCase):
    def test_generated_fixture_has_no_trailing_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.bngl"
            source.write_text(
                "begin model  \n"
                "begin parameters \n"
                "  k 1   \n"
                "end parameters \n"
                "end model   \n"
            )

            generated = build("fixture", source)

        self.assertEqual(
            generated,
            (
                "begin model\n"
                "begin parameters\n"
                "  k 1\n"
                "end parameters\n"
                "end model\n"
                "\n## actions ##\n"
                "generate_network({overwrite=>1})\n"
            ),
        )


if __name__ == "__main__":
    unittest.main()
