"""Known wrong outputs must fail the same comparators used by real campaigns."""

import numpy as np
import pytest

from tests.validation.compare import (
    COLUMNS_EXACT,
    compare_net,
    compare_stochastic,
    compare_trajectories,
    parse_net,
)

NETWORK = """begin parameters
  1 k 0.5
end parameters
begin species
  1 A(x!1).B(y!1) 10
  2 A(x).B(y) 0
end species
begin reactions
  1 1 2 k
end reactions
begin groups
  1 bound 1
  2 free 2
end groups
"""


@pytest.mark.parametrize(
    "old,new",
    [
        ("  2 A(x).B(y) 0\n", ""),  # species count
        ("  1 1 2 k", "  1 1 2 k\n  2 1 2 k"),  # reaction multiplicity
        ("A(x!1).B(y!1)", "A(x!1).C(y!1)"),  # graph identity
        ("  1 k 0.5", "  1 k 0.6"),  # reaction rate
        ("  1 1 2 k", "  1 1 2 2*k"),  # statistical factor
        ("  1 bound 1", "  1 bound 2*1"),  # observable weight
    ],
)
def test_network_mutations_cannot_pass(tmp_path, old, new):
    reference, mutant = tmp_path / "ref.net", tmp_path / "mutant.net"
    reference.write_text(NETWORK)
    mutant.write_text(NETWORK.replace(old, new))
    ref, test = parse_net(reference), parse_net(mutant)
    assert ref is not None
    assert test is None or not compare_net(ref, test).ok


def test_bond_renumbering_is_an_accepted_metamorphism(tmp_path):
    a, b = tmp_path / "a.net", tmp_path / "b.net"
    a.write_text(NETWORK)
    b.write_text(NETWORK.replace("!1", "!72"))
    assert compare_net(parse_net(a), parse_net(b)).ok


def test_campaign_network_comparison_detects_changed_initial_amount(tmp_path):
    a, b = tmp_path / "a.net", tmp_path / "b.net"
    a.write_text(NETWORK)
    b.write_text(NETWORK.replace("B(y!1) 10", "B(y!1) 20"))
    assert not compare_net(parse_net(a), parse_net(b), compare_initial_amounts=True).ok


def test_tiny_nonzero_reaction_rate_is_not_equal_to_zero(tmp_path):
    a, b = tmp_path / "a.net", tmp_path / "b.net"
    a.write_text(NETWORK.replace("k 0.5", "k 0"))
    b.write_text(NETWORK.replace("k 0.5", "k 1e-30"))
    assert not compare_net(parse_net(a), parse_net(b)).ok


def test_initial_amount_comparison_does_not_drop_expression_tokens(tmp_path):
    a, b = tmp_path / "a.net", tmp_path / "b.net"
    a.write_text(NETWORK.replace("B(y!1) 10", "B(y!1) k + 1"))
    b.write_text(NETWORK.replace("B(y!1) 10", "B(y!1) k + 2"))
    assert not compare_net(parse_net(a), parse_net(b), compare_initial_amounts=True).ok


def test_initial_amount_mapping_is_reflexive_for_duplicate_species(tmp_path):
    path = tmp_path / "duplicate.net"
    path.write_text(
        "begin species\n1 A() 10\n2 A() 20\nend species\nbegin reactions\nend reactions\n"
    )
    network = parse_net(path)
    assert compare_net(network, network, compare_initial_amounts=True).ok


@pytest.mark.parametrize("side", ["ref", "test"])
@pytest.mark.parametrize("column", [0, 1])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_values_or_times_on_either_side_fail(side, column, value):
    a = np.asarray([[0, 10], [1, 5]], dtype=float)
    b = a.copy()
    (a if side == "ref" else b)[1, column] = value
    assert not compare_trajectories(a, ["time", "A"], b, ["time", "A"]).ok


@pytest.mark.parametrize("mutation", ["numeric", "missing", "nan", "duplicate"])
def test_trajectory_mutations_cannot_pass(mutation):
    reference = np.asarray([[0, 10, 0], [1, 5, 5]], dtype=float)
    test, columns = reference.copy(), ["time", "bound", "free"]
    if mutation == "numeric":
        test[1, 1] += 1
    elif mutation == "missing":
        test, columns = test[:, :2], columns[:2]
    elif mutation == "nan":
        test[1, 1] = np.nan
    else:
        columns[-1] = "bound"
    assert not compare_trajectories(
        reference,
        ["time", "bound", "free"],
        test,
        columns,
        rtol=1e-8,
        atol=1e-12,
        columns=COLUMNS_EXACT,
    ).ok


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_stochastic_members_cannot_pass(value):
    reference = np.asarray([[0, 10], [1, 5]], dtype=float)
    mutant = reference.copy()
    mutant[1, 1] = value
    columns = ["time", "bound"]
    diff = compare_stochastic(
        [(reference, columns)] * 2, [(mutant, columns)] * 2, columns=COLUMNS_EXACT
    )
    assert not diff.ok
    assert "non-finite" in diff.note
