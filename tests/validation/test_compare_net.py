"""Regression tests for typed .net comparison and rate normalization."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.validation.compare import (
    _canon_expr,
    compare_net,
    parse_net,
    species_isomorphic,
)


def test_canonical_rate_expression_normalizes_unary_minus_parentheses():
    left = "exp((-(35/2))*((1/2)-(x/(a+b))))"
    right = "exp(-(35/2)*((1/2)-(x/(a+b))))"
    assert _canon_expr(left) == _canon_expr(right)


def test_canonical_rate_expression_normalizes_compartment_observable_call():
    legacy = "1*(694.731*A/cell()*B/cell()/(B/cell()+6086070))"
    modern = "1*(694.731*(A/cell)()*(B/cell)()/((B/cell)()+6086070))"
    changed = modern.replace("694.731", "694.732")

    assert _canon_expr(legacy) == _canon_expr(modern)
    assert _canon_expr(legacy) != _canon_expr(changed)


def test_canonical_rate_expression_drops_leading_unit_flux_factor():
    legacy = "1*(0.75*S1/1())*S2/1()"
    modern = "0.75*S1/1()*S2/1()"

    assert _canon_expr(legacy) == _canon_expr(modern)


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


def test_parse_net_accepts_valid_empty_network_blocks(tmp_path):
    path = tmp_path / "empty.net"
    path.write_text(
        "\n".join(
            [
                "# Created by bng_cpp",
                "begin parameters",
                "    1 __Avogadro__ 1",
                "end parameters",
                "begin species",
                "end species",
                "begin reactions",
                "end reactions",
                "begin groups",
                "end groups",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    network = parse_net(path)

    assert network is not None
    assert network.n_species == 0
    assert network.n_reactions == 0


def test_parse_net_rejects_parameter_only_document(tmp_path):
    path = tmp_path / "not-a-network.net"
    path.write_text("begin parameters\n    1 k 1\nend parameters\n", encoding="utf-8")

    assert parse_net(path) is None


def test_equivalent_built_in_rate_expressions_compare_equal(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "2*asin(1)"))
    generated = parse_net(_net(tmp_path / "generated.net", "3.14159265359"))
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_dynamic_tiny_rates_do_not_collapse_to_zero(tmp_path):
    zero = parse_net(_net(tmp_path / "zero.net", "0*x"))
    scientific = parse_net(_net(tmp_path / "scientific.net", "1e-6*x"))
    decimal = parse_net(_net(tmp_path / "decimal.net", "0.000001*x"))
    tiny_rates = [
        parse_net(_net(tmp_path / "tiny-999.net", "1e-999*x")),
        parse_net(_net(tmp_path / "tiny-400.net", "1e-400*x")),
        parse_net(_net(tmp_path / "pathological-exponent.net", "1e-10000*x")),
    ]
    assert zero is not None
    assert scientific is not None
    assert decimal is not None
    assert all(rate is not None for rate in tiny_rates)

    assert all(not compare_net(rate, zero).ok for rate in tiny_rates)
    assert compare_net(scientific, decimal).ok


def test_parameter_substitution_preserves_tiny_dynamic_rate_coefficients(tmp_path):
    def write(path: Path, coefficient: str, rate_body: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    "begin parameters",
                    f"    1 k {coefficient}",
                    "end parameters",
                    "begin functions",
                    f"    1 rate() {rate_body}",
                    "end functions",
                    "begin species",
                    "    1 A() 1",
                    "    2 B() 0",
                    "end species",
                    "begin reactions",
                    "    1 1 2 rate",
                    "end reactions",
                    "begin groups",
                    "    1 x 1",
                    "end groups",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    tiny_dynamic = parse_net(write(tmp_path / "tiny-dynamic.net", "1e-999", "k*x"))
    zero_dynamic = parse_net(write(tmp_path / "zero-dynamic.net", "0", "k*x"))
    tiny_constant = parse_net(write(tmp_path / "tiny-constant.net", "1e-999", "k"))
    zero_constant = parse_net(write(tmp_path / "zero-constant.net", "0", "k"))
    tiny_math = parse_net(write(tmp_path / "tiny-math.net", "1e-999", "k*sqrt(1)"))
    zero_math = parse_net(write(tmp_path / "zero-math.net", "0", "k*sqrt(1)"))

    assert tiny_dynamic is not None
    assert zero_dynamic is not None
    assert tiny_constant is not None
    assert zero_constant is not None
    assert tiny_math is not None
    assert zero_math is not None
    assert not compare_net(tiny_dynamic, zero_dynamic).ok
    assert not compare_net(tiny_constant, zero_constant).ok
    assert not compare_net(tiny_math, zero_math).ok


def test_dynamic_if_folds_constant_boolean_conditions_lazily():
    from tests.validation.compare import _resolve_rate

    observable = _resolve_rate("x", {}, "value", rate_observables={"x"})
    conjunction = _resolve_rate(
        "if((1<2)&&(3>2),x,1/0)", {}, "value", rate_observables={"x"}
    )
    disjunction = _resolve_rate(
        "if((1<2)||(3<2),x,1/0)", {}, "value", rate_observables={"x"}
    )
    dynamic_condition = _resolve_rate(
        "if(x>0,x,1/0)", {}, "value", rate_observables={"x"}
    )

    assert conjunction == observable
    assert disjunction == observable
    assert dynamic_condition != observable


def test_net_rate_comparison_preserves_natural_log_semantics(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "ln(2)/120"))
    generated = parse_net(_net(tmp_path / "generated.net", repr(math.log(2) / 120)))
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

    reference = parse_net(write(tmp_path / "reference.net", "-((2/3)*X)"))
    generated = parse_net(write(tmp_path / "generated.net", "-(2/3)*X"))
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_function_rate_consumes_empty_call_when_resolving_definition(tmp_path):
    def write(path: Path, degradation: str) -> Path:
        path.write_text(
            "\n".join(
                [
                    "begin parameters",
                    "    1 kDegProtNuc 8",
                    "    2 Km 10",
                    "end parameters",
                    "begin species",
                    "    1 Prot(loc~NUCLEUS) 1",
                    "    2 Trash() 0",
                    "end species",
                    "begin functions",
                    f"    1 DegFunction() {degradation}",
                    "    2 _rateLaw() kDegProtNuc*DegFunction()",
                    "end functions",
                    "begin reactions",
                    "    1 1 2 _rateLaw",
                    "end reactions",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    reference = parse_net(write(tmp_path / "reference.net", "NucProt/(Km+NucProt)"))
    generated = parse_net(
        write(tmp_path / "generated.net", "(NucProt / (Km + NucProt))")
    )
    assert reference is not None
    assert generated is not None
    assert compare_net(reference, generated).ok


def test_function_rate_comparison_keeps_nonempty_calls_structural():
    from tests.validation.compare import _resolve_rate

    bng2_stub = _resolve_rate("TFUN(x,'data')", {}, "value")
    bng3_call = _resolve_rate("tfun('data',x)", {}, "value")

    assert bng2_stub != bng3_call


def test_motor_rate_comparison_accepts_equivalent_numeric_and_observable_syntax(
    tmp_path,
):
    def write(path: Path, half: str, micro: str, observable_call: str) -> Path:
        scaled_observable = f"{observable_call}/(cellVolume*_Na*{micro})"
        common = (
            "w*exp((g1/2)*("
            f"{half}-({scaled_observable})/(Kd+({scaled_observable}))"
            "))"
        )
        path.write_text(
            "\n".join(
                [
                    "begin parameters",
                    "    1 w 1.02",
                    "    2 g1 35",
                    "    3 cellVolume 1.41e-15",
                    "    4 _Na 6.02e23",
                    "    5 Kd 3.06",
                    "end parameters",
                    "begin functions",
                    f"    1 kPlus() {common}",
                    f"    2 kMinus() {common.replace('(g1/2)', '-(g1/2)')}",
                    "end functions",
                    "begin species",
                    "    1 Motor(state~CW) 10000",
                    "    2 Motor(state~CCW) 0",
                    "    3 CheY(p~PHOS) 2200",
                    "end species",
                    "begin reactions",
                    "    1 1 2 kPlus",
                    "    2 2 1 kMinus",
                    "end reactions",
                    "begin groups",
                    "    1 CheYp 3",
                    "end groups",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    reference = parse_net(write(tmp_path / "reference.net", "1/2", "10**(-6)", "CheYp"))
    generated = parse_net(write(tmp_path / "generated.net", "0.5", "1e-06", "CheYp()"))
    changed = parse_net(write(tmp_path / "changed.net", "0.6", "1e-06", "CheYp()"))
    assert reference is not None
    assert generated is not None
    assert changed is not None

    assert compare_net(reference, generated).ok
    assert not compare_net(reference, changed).ok


def test_only_net_observable_names_normalize_zero_argument_calls():
    from tests.validation.compare import _resolve_rate

    observables = {"CheYp"}
    assert _resolve_rate(
        "CheYp()", {}, "value", rate_observables=observables
    ) == _resolve_rate("CheYp", {}, "value", rate_observables=observables)
    assert _resolve_rate(
        "Unknown()", {}, "value", rate_observables=observables
    ) != _resolve_rate("Unknown", {}, "value", rate_observables=observables)


def test_same_counts_with_different_rate_values_fail(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "0.5"))
    generated = parse_net(_net(tmp_path / "generated.net", "1.0"))
    assert reference is not None
    assert generated is not None
    diff = compare_net(reference, generated)
    assert not diff.ok
    assert diff.n_reactions_ref == diff.n_reactions_test == 1
    assert diff.reactions_only_test


def test_rate_comparison_keeps_changes_near_numeric_normalization(tmp_path):
    reference = parse_net(_net(tmp_path / "reference.net", "1"))
    changed = parse_net(_net(tmp_path / "changed.net", "1.000000000006"))
    assert reference is not None
    assert changed is not None

    # The existing 12-significant-digit normalization rounds within about
    # 5e-12 near one; a 6e-12 rate change must remain distinguishable.
    assert not compare_net(reference, changed).ok


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("if((0==1),1,if((0>0),2,if((0>0),3,0)))", "0"),
        ("if(1==1,2,3)", "2"),
        ("if((1<2)&&(3>2),7,1/0)", "7"),
        ("if(-1,2,3)", "2"),
        ("2*if(0,3,if(2>1,4,5))", "8"),
        ("if(1,2,1/0)", "2"),
        ("if(0,sqrt(-1),3)", "3"),
    ],
)
def test_constant_conditional_rates_compare_by_value(tmp_path, expression, value):
    reference = parse_net(_net(tmp_path / "reference.net", expression))
    generated = parse_net(_net(tmp_path / "generated.net", value))
    changed = parse_net(_net(tmp_path / "changed.net", "9"))
    assert reference is not None and generated is not None and changed is not None
    assert compare_net(reference, generated).ok
    assert not compare_net(reference, changed).ok


@pytest.mark.parametrize(
    "expression", ["if(Obs1==1,1,2)", "if(time()>1,1,2)", "if(1,2,Obs1)"]
)
def test_dynamic_conditional_rates_do_not_compare_equal_to_initial_value(expression):
    from tests.validation.compare import _resolve_rate

    rate = _resolve_rate(expression, {}, "value")
    assert rate.startswith("expr:")
    assert rate != _resolve_rate("1", {}, "value")
    assert rate != _resolve_rate("2", {}, "value")


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


def test_explicit_molecule_name_aliases_preserve_strict_network_checks(tmp_path):
    reference_path = (
        Path(__file__).parent / "Validate" / "DAT_validate" / "test_sbml_flat.net"
    )
    aliases = {
        "A____": "A",
        "AA____": "AA",
        "B____": "B",
        "C____": "C",
        "D____": "D",
    }
    reference_text = reference_path.read_text(encoding="utf-8")
    generated_text = reference_text
    for source, generated in aliases.items():
        generated_text = generated_text.replace(source, generated)
    generated_path = tmp_path / "generated.net"
    generated_path.write_text(generated_text, encoding="utf-8")

    reference = parse_net(reference_path)
    generated = parse_net(generated_path)
    assert reference is not None
    assert generated is not None
    assert not compare_net(reference, generated).ok
    assert compare_net(reference, generated, molecule_name_aliases=aliases).ok

    changed_rate_path = tmp_path / "changed-rate.net"
    changed_rate_path.write_text(
        generated_text.replace("1*k1_f", "2*k1_f", 1), encoding="utf-8"
    )
    changed_rate = parse_net(changed_rate_path)
    assert changed_rate is not None
    assert not compare_net(reference, changed_rate, molecule_name_aliases=aliases).ok


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
        _net_with_group(tmp_path / "reference.net", "A(x!1).B(y!1)", "C()", "1,2*2")
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


def test_dynamic_rate_expansion_preserves_sum_grouping(tmp_path):
    from tests.validation.compare import _resolve_rate

    original = _resolve_rate("2*f", {"f": "A+B"}, "value", {"f"})
    changed = _resolve_rate("2*A+B", {}, "value")
    assert original != changed
    assert original == _resolve_rate("2*(A+B)", {}, "value")


@pytest.mark.parametrize(
    "original,changed", [("-(A*B+C)", "-A*B+C"), ("X/-(A*B)", "X/-A*B")]
)
def test_dynamic_rate_canonicalization_preserves_operator_precedence(original, changed):
    assert _canon_expr(original) != _canon_expr(changed)


@pytest.mark.parametrize("law", ["Sat", "MM", "Hill"])
def test_network_rate_law_arguments_are_not_discarded(tmp_path, law):
    reference = _net(tmp_path / "reference.net", "1")
    text = reference.read_text().replace("1 1 2 kd", f"1 1 2 {law} 2 3")
    reference.write_text(text)
    subject = tmp_path / "subject.net"
    subject.write_text(text.replace(f"{law} 2 3", f"{law} 200 3"))
    assert not compare_net(parse_net(reference), parse_net(subject)).ok


@pytest.mark.parametrize(
    ("reference", "generated"),
    [
        ("0.3*x", "0.29999999999999999*x"),
        ("1e-6*x", "9.9999999999999995e-7*x"),
        (
            "tfun([0.001,0.02,0.3],[150,250,350],time)",
            "tfun([0.001,0.02,0.29999999999999999],[150,250,350],time)",
        ),
    ],
)
def test_dynamic_rate_literals_compare_by_exact_binary64_value(reference, generated):
    assert _canon_expr(reference) == _canon_expr(generated)


def test_dynamic_rate_literals_keep_adjacent_binary64_values_distinct():
    assert _canon_expr("0.3*x") != _canon_expr("0.30000000000000004*x")


def test_dynamic_rate_constant_arithmetic_matches_binary64_evaluation():
    assert _canon_expr("(0.19*6.022e23)*1e-21+x") == _canon_expr("114.41799999999999+x")
    assert _canon_expr("(153.0*6.022e23)*1e-21*x") == _canon_expr("92136.59999999999*x")
