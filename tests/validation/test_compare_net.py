"""Regression tests for typed .net comparison and rate normalization."""

from __future__ import annotations

from pathlib import Path

from tests.validation.compare import compare_net, parse_net


def _net(path: Path, rate: str) -> Path:
    path.write_text(
        "\n".join(
            [
                "begin parameters",
                f"    1 kd {rate} # Constant",
                "end parameters",
                "begin species",
                "    1 A() 1",
                "    2 B() 0",
                "end species",
                "begin reactions",
                "    1 1 2 kd",
                "end reactions",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_equivalent_built_in_rate_expressions_compare_equal(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "2*asin(1)"))
    generated = parse_net(_net(tmp_path / "generated.net", "3.14159265359"))
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_same_counts_with_different_rate_values_fail(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "0.5"))
    generated = parse_net(_net(tmp_path / "generated.net", "1.0"))
    assert reference is not None
    assert generated is not None
    diff = compare_net(reference, generated)
    assert not diff.ok
    assert diff.n_reactions_ref == diff.n_reactions_test == 1
    assert diff.reactions_only_test
