"""Unit coverage for the fail-closed BNG2 .net RHS evaluator."""

from __future__ import annotations

import pytest

from tests.validation.compare import parse_net
from tests.validation import rhs
from tests.validation.rhs import UnsupportedExpressionError, evaluate_rhs


def _network(path, rate_expression="flux"):
    path.write_text(
        "\n".join(
            [
                "begin parameters",
                "    1 k 2",
                "    2 K 1",
                "end parameters",
                "begin functions",
                f"    1 flux() k/(K+A)+time",
                "end functions",
                "begin species",
                "    1 A() 1",
                "    2 B() 0",
                "end species",
                "begin reactions",
                f"    1 1 2 {rate_expression}",
                "end reactions",
                "begin groups",
                "    1 A 1",
                "end groups",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    network = parse_net(path)
    assert network is not None
    return network


def test_rhs_evaluator_resolves_parameters_groups_and_time(tmp_path):
    network = _network(tmp_path / "model.net")

    actual = evaluate_rhs(network, [0.5, 1.0], time=0.25)

    # flux = k / (K + A) + time = 2/1.5 + 0.25; mass action multiplies by A.
    assert actual == pytest.approx([-19 / 24, 19 / 24])


def test_rate_evaluator_returns_expression_values_before_mass_action(tmp_path):
    network = _network(tmp_path / "model.net")

    actual = rhs.evaluate_rate_coefficients(network, [0.5, 1.0], time=0.25)

    # flux = k / (K + A) + time = 2/1.5 + 0.25.  The reactant amount
    # 0.5 belongs to the ODE mass-action multiplier, not this expression value.
    assert actual == pytest.approx([19 / 12])


def test_rhs_evaluator_fails_closed_on_unknown_functions(tmp_path):
    network = _network(tmp_path / "model.net", rate_expression="privateFn(1)")

    with pytest.raises(UnsupportedExpressionError, match="privateFn"):
        evaluate_rhs(network, [0.5, 1.0], time=0.25)

    with pytest.raises(UnsupportedExpressionError, match="privateFn"):
        rhs.evaluate_rate_coefficients(network, [0.5, 1.0], time=0.25)


def test_rhs_evaluator_keeps_dollar_species_fixed_but_in_flux(tmp_path):
    path = tmp_path / "fixed.net"
    path.write_text(
        "\n".join(
            [
                "begin species",
                "    1 A() 1",
                "    2 $Trash() 1",
                "    3 B() 0",
                "end species",
                "begin reactions",
                "    1 1,2 2,3 2",
                "end reactions",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    network = parse_net(path)
    assert network is not None

    assert evaluate_rhs(network, [0.5, 3.0, 0.0], time=0.0) == pytest.approx(
        [-3.0, 0.0, 3.0]
    )
