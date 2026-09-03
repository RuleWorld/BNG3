"""Regression tests for typed .net comparison and rate normalization."""

from __future__ import annotations

import math
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


def test_net_rate_comparison_preserves_natural_log_semantics(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "ln(2)/120"))
    generated = parse_net(
        _net(tmp_path / "generated.net", repr(math.log(2) / 120))
    )
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_function_definitions_strip_call_suffix_for_rate_resolution(tmp_path):
    reference = tmp_path / "reference.net"
    reference.write_text(
        "\n".join(
            [
                "begin parameters",
                "    1 kd 0.5",
                "end parameters",
                "begin functions",
                "    1 f() 2*kd",
                "end functions",
                "begin species",
                "    1 A() 1",
                "    2 B() 0",
                "end species",
                "begin reactions",
                "    1 1 2 f",
                "end reactions",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    generated = _net(tmp_path / "generated.net", "1.0")
    parsed_reference = parse_net(reference)
    parsed_generated = parse_net(generated)
    assert parsed_reference is not None
    assert parsed_generated is not None
    assert compare_net(parsed_reference, parsed_generated).ok


def test_function_rate_normalizes_negative_product_parentheses(tmp_path):
    def write(path: Path, expression: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    "begin species",
                    "    1 A() 1",
                    "    2 B() 0",
                    "end species",
                    "begin functions",
                    f"    1 f() {expression}",
                    "end functions",
                    "begin reactions",
                    "    1 1 2 f",
                    "end reactions",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    reference = parse_net(
        write(tmp_path / "reference.net", "-((2/3)*X)")
    )
    generated = parse_net(
        write(tmp_path / "generated.net", "-(2/3)*X")
    )
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
        return path

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


def _net_with_group(
    path: Path, first: str, second: str, group: str, reaction: str = "1 2"
) -> Path:
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
                "begin groups",
                f"    1 Atot {group}",
                "end groups",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_network_comparison_maps_observable_groups_with_species(tmp_path):
    reference = parse_net(
        _net_with_group(
            tmp_path / "reference.net", "A(x!1).B(y!1)", "C()", "1,2*2"
        )
    )
    generated = parse_net(
        _net_with_group(
            tmp_path / "generated.net", "C()", "B(y!9).A(x!9)", "2*1,2", "2 1"
        )
    )
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_network_comparison_rejects_changed_observable_group_weight(tmp_path):
    reference = parse_net(
        _net_with_group(tmp_path / "reference.net", "A()", "B()", "1,2*2")
    )
    generated = parse_net(
        _net_with_group(tmp_path / "generated.net", "A()", "B()", "1,3*2")
    )
    assert reference is not None
    assert generated is not None
    assert not compare_net(reference, generated).ok
