"""Negative controls for Species mutation build attribution.

The merged #707 classifier tracked only `theorem` starts and searched semantic
markers globally. That accepted an error inside an unrelated trailing `def` as
if it were the rejection of the preceding theorem. These controls pin each
error to its own declaration body and diagnostic block and reject syntax,
module, tool, marker and extra-error confounders while keeping the two real
proof rejections accepted.
"""

import unittest

from classify_species_mutation import EXPECTED, EXPECTED_ERROR_COUNTS, matches


class SpeciesRejectionTest(unittest.TestCase):
    def sample(self, name):
        """Synthesize a source and log shaped like the real Lean build output."""
        expected = EXPECTED[name]
        source_lines = []
        diagnostics = []
        for index, (theorem, (message, marker)) in enumerate(expected.items(), 1):
            source_lines.append(f"theorem {theorem} : True := by trivial")
            diagnostics.append(f"error: BNG/Species.lean:{index}:1: {message}")
            if marker is not None:
                diagnostics.append(f"  {marker}")
        if name == "coverage-species-bond-blind":
            # isomorphicSpecies_counts reports two errors in the real log.
            diagnostics.append("error: BNG/Species.lean:6:1: Invalid projection")
        output = "\n".join(
            diagnostics
            + [
                "error: Lean exited with code 1",
                "Some required targets logged failures:",
                "- BNG.Species",
                "error: build failed",
            ]
        )
        return "\n".join(source_lines), output

    def test_expected_rejections_accepted(self):
        for name in EXPECTED:
            with self.subTest(name=name):
                source, output = self.sample(name)
                self.assertTrue(matches(name, source, output))

    def test_error_counts_are_pinned(self):
        self.assertEqual(EXPECTED_ERROR_COUNTS["coverage-species-bond-blind"], 6)
        self.assertEqual(EXPECTED_ERROR_COUNTS["coverage-network-duplicate-species"], 4)

    def test_unrelated_definition_error_is_rejected(self):
        # The reproduced merged-#707 hole: an error in the trailing def used to
        # be attributed to addSpeciesModuloIso_empty and accepted.
        source = "\n".join(
            f"theorem {theorem} : True := by trivial"
            for theorem in EXPECTED["coverage-network-duplicate-species"]
        )
        source += "\ndef unrelated : Nat := by\n  skip\n"
        output = "\n".join(
            [
                "error: BNG/Species.lean:1:1: Type mismatch",
                "error: BNG/Species.lean:2:1: unsolved goals",
                "  ⊢ candidate ∈ pool",
                "error: BNG/Species.lean:3:1: unsolved goals",
                "  ⊢ False",
                "error: BNG/Species.lean:5:1: unsolved goals",  # inside def unrelated
                "Some required targets logged failures:",
                "- BNG.Species",
                "error: build failed",
            ]
        )
        self.assertFalse(matches("coverage-network-duplicate-species", source, output))

    def test_marker_must_stay_in_its_own_diagnostic_block(self):
        source, output = self.sample("coverage-network-duplicate-species")
        # Move the contains-candidate marker out of its theorem's block to the
        # end of the log. A global marker search used to accept this.
        lines = output.splitlines()
        lines.remove("  ⊢ candidate ∈ pool")
        lines.insert(-1, "  ⊢ candidate ∈ pool")
        self.assertFalse(
            matches("coverage-network-duplicate-species", source, "\n".join(lines))
        )

    def test_invalid_controls_rejected(self):
        for name in EXPECTED:
            with self.subTest(name=name):
                source, output = self.sample(name)
                for extra in (
                    "error: BNG/Species.lean:1:1: unexpected end of input",
                    "error: BNG/Other.lean:1:1: unsolved goals",
                    "error: unknown module prefix 'BNG'",
                    "- BNG.Other",
                ):
                    self.assertFalse(matches(name, source, output + "\n" + extra))
                # A malformed message on an otherwise well-attributed error.
                malformed = output.replace(
                    next(iter(EXPECTED[name].values()))[0], "unexpected end of input", 1
                )
                self.assertFalse(matches(name, source, malformed))
                # A missing semantic marker in its own block.
                marker = next(
                    (m for _msg, m in EXPECTED[name].values() if m is not None), None
                )
                if marker is not None:
                    self.assertFalse(
                        matches(name, source, output.replace(f"  {marker}\n", "", 1))
                    )
                self.assertFalse(matches("unknown", source, output))


if __name__ == "__main__":
    unittest.main()
