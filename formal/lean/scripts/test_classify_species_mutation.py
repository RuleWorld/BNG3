"""Negative controls for Species mutation build attribution."""

import unittest

from classify_species_mutation import EXPECTED, MARKERS, matches


class SpeciesRejectionTest(unittest.TestCase):
    def sample(self, name):
        expected = EXPECTED[name]
        source = "\n".join(
            f"theorem {theorem} : True := by trivial" for theorem in expected
        )
        diagnostics = [
            f"error: BNG/Species.lean:{i}:1: {message}"
            for i, message in enumerate(expected.values(), 1)
        ]
        if name == "coverage-species-bond-blind":
            diagnostics.append("error: BNG/Species.lean:5:2: Invalid projection")
        output = "\n".join(
            diagnostics
            + list(MARKERS[name])
            + [
                "Some required targets logged failures:",
                "- BNG.Species",
                "error: build failed",
            ]
        )
        return source, output

    def test_expected_failures_and_invalid_controls(self):
        for name in EXPECTED:
            with self.subTest(name=name):
                source, output = self.sample(name)
                self.assertTrue(matches(name, source, output))
                for extra in (
                    "error: BNG/Species.lean:1:1: unexpected end of input",
                    "error: BNG/Other.lean:1:1: unsolved goals",
                    "error: unknown module prefix 'BNG'",
                    "- BNG.Other",
                    "error: BNG/Species.lean:1:1: Type mismatch",
                ):
                    self.assertFalse(matches(name, source, output + "\n" + extra))
                self.assertFalse(
                    matches(name, source, output.replace(MARKERS[name][0], ""))
                )
                self.assertFalse(
                    matches(
                        name,
                        source,
                        output.replace("error: BNG/Species.lean:1:1:", "warning:"),
                    )
                )
                self.assertFalse(matches("unknown", source, output))


if __name__ == "__main__":
    unittest.main()
