"""Regression tests for typed .net comparison and rate normalization."""

from __future__ import annotations

from pathlib import Path

from tests.validation.compare import compare_net, parse_net, species_isomorphic


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


def test_species_graph_equivalence_ignores_order_and_bond_labels():
    reference = "A(x!10,y).B(z!10)"
    generated = "B(z!1).A(y,x!1)"
    assert species_isomorphic(reference, generated)


def test_species_graph_equivalence_preserves_states_and_connectivity():
    assert not species_isomorphic("A(x~p!1).B(y!1)", "A(x~u!1).B(y!1)")
    assert not species_isomorphic(
        "A(x!1,y!2).B(x!1,y!3).C(x!2,y!3)",
        "A(x!1,y!2).B(x!1,y!3).C(x!2,y)",
    )


def test_blbr_symmetric_serializations_are_graph_equivalent():
    reference = (
        "L(l!1,l!2).R(r!1,r!3).R(r!2,r!4).L(l!3,l!5)."
        "L(l!4,l!6).R(r!5,r!7).R(r!6,r!8).L(l!7,l!9)."
        "L(l,l!8).R(r!9)"
    )
    generated = (
        "L(l!1,l!2).R(r!1,r!3).R(r!2,r!4).L(l!3,l!5)."
        "L(l!4,l!6).R(r!5,r!7).R(r!6,r!8).L(l,l!7)."
        "L(l!8,l!9).R(r!9)"
    )
    assert species_isomorphic(reference, generated)


def test_network_comparison_uses_graph_identity_for_reactions(tmp_path):
    def write(path: Path, first: str, second: str, reaction: str):
        path.write_text(
            "\n".join(
                [
                    "begin parameters",
                    "    1 kd 0.5 # Constant",
                    "end parameters",
                    "begin species",
                    f"    1 {first} 1",
                    f"    2 {second} 0",
                    "end species",
                    "begin reactions",
                    f"    1 {reaction} kd",
                    "end reactions",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    reference = parse_net(
        write(
            tmp_path / "reference.net",
            "A(x!1).B(y!1)",
            "C()",
            "1 2",
        )
    )
    generated = parse_net(
        write(
            tmp_path / "generated.net",
            "C()",
            "B(y!99).A(x!99)",
            "2 1",
        )
    )
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok
