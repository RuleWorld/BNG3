"""Tests for syntax-only adaptation before the BNG2 semantic check."""

from __future__ import annotations

import unittest

from bench.check_netgen_semantics import normalize_bng2_source


class NetgenSemanticTests(unittest.TestCase):
    def test_normalizes_only_reaction_rules_block_markers(self) -> None:
        source = "begin reaction_rules\nA(x!1) -> A(x) k\nend reaction_rules\n"
        expected = "begin reaction rules\nA(x!1) -> A(x) k\nend reaction rules\n"
        self.assertEqual(normalize_bng2_source(source), expected)

    def test_leaves_standard_bngl_unchanged(self) -> None:
        source = "begin reaction rules\nA(x) -> A(y) k\nend reaction rules\n"
        self.assertEqual(normalize_bng2_source(source), source)


if __name__ == "__main__":
    unittest.main()
