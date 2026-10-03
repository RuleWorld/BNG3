"""Focused checks for the netgen benchmark's correctness gates."""

from __future__ import annotations

import unittest

from bench.netgen_bench import raw_identity_mismatches, ru_maxrss_bytes


class NetgenBenchTests(unittest.TestCase):
    def test_raw_identity_gate_catches_tlbr_variants(self) -> None:
        hashes = {
            "tlbr_gen.bngl": [
                {"a" * 64: 2},
                {"b" * 64: 1, "a" * 64: 1},
            ]
        }
        self.assertEqual(raw_identity_mismatches(hashes), ["tlbr_gen.bngl"])

    def test_raw_identity_gate_accepts_one_hash_across_runs_and_arms(self) -> None:
        digest = "a" * 64
        hashes = {"stable_gen.bngl": [{digest: 3}, {digest: 3}]}
        self.assertEqual(raw_identity_mismatches(hashes), [])

    def test_ru_maxrss_is_normalized_by_platform(self) -> None:
        self.assertEqual(ru_maxrss_bytes(4096, "darwin"), 4096)
        self.assertEqual(ru_maxrss_bytes(4, "linux"), 4096)


if __name__ == "__main__":
    unittest.main()
