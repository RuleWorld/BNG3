"""Direct expression-vector/RHS parity over the frozen expression tier.

The documented vectors are positive synthetic species concentrations indexed
by BNG2 structural species order:

    y[i] = 0.375 + 0.125 * ((7*i + 11*case) mod 17)

They are evaluated at t = 0, 0.375, and 2.5. BNG2 .net expressions and
stoichiometry are interpreted by the independent restricted Python evaluator;
BNG3 derivatives come directly from OdeIntegrator::derivs. The 1e-9 relative
and 1e-12 absolute tolerances leave only floating-point evaluation order while
still bounding cancellation near zero. This checks derivative vectors; it does
not separately compare intermediate parameter, function, or group values.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.validation import compare, corpus, oracle_perl
from tests.validation.rhs import evaluate_rhs
from tests.validation.strict import require_oracle


RHS_TIMES = (0.0, 0.375, 2.5)
RHS_RTOL = 1e-9
RHS_ATOL = 1e-12
RHS_MODELS = tuple(corpus.tier_expr())
EXPECTED_RHS_MODELS = (
    "CaOscillate_Func",
    "isingspin_energy",
    "isingspin_localfcn",
    "localfunc",
    "michment",
)


@pytest.mark.expressions
def test_rhs_gate_covers_the_nonempty_frozen_expression_tier():
    assert RHS_MODELS == EXPECTED_RHS_MODELS
    assert RHS_TIMES


@pytest.mark.expressions
@pytest.mark.parametrize("model_name", RHS_MODELS)
def test_direct_expression_rhs_parity(model_name, api, work_dir):
    ref_path, ref_source = oracle_perl.net(
        model_name, work_dir / "perl", network_only=True
    )
    require_oracle(
        ref_path is not None,
        f"no reference .net for {model_name}: {ref_source}",
    )
    ref_net = compare.parse_net(ref_path)
    assert ref_net is not None, f"could not parse reference .net ({ref_source})"

    model = api.load(str(corpus.resolve(model_name)))
    generated = model.generate_network()
    test_path = work_dir / "bng3" / f"{model_name}.net"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    model.write_net(str(test_path))
    test_net = compare.parse_net(test_path)
    assert test_net is not None, "engine produced no parsed .net"
    network_diff = compare.compare_net(ref_net, test_net)
    assert network_diff.ok, (
        f"network prerequisite failed [{model_name}] "
        f"(ref={ref_source}): {network_diff.summary()}"
    )

    assert len(generated.species_names) == test_net.n_species
    assert ref_net.n_species > 0
    # NetWriter emits each internal species at getIndex()+1. It marks the
    # synthetic pool species with '$' only in serialization; compare the
    # remaining graph spelling with the public C++ graph labels by index.
    for index, generated_name in enumerate(generated.species_names, 1):
        serialized_name = test_net.species_by_index[index].removeprefix("$")
        assert compare.species_isomorphic(serialized_name, generated_name), (
            f"network serialization order changed at species {index} [{model_name}]"
        )
    ref_to_generated = compare._species_index_mapping(ref_net, test_net)
    assert len(ref_to_generated) == ref_net.n_species == generated.num_species

    from bionetgen import _bionetgen_cpp as cpp

    evaluated_vectors = 0
    for case, time in enumerate(RHS_TIMES):
        state = np.asarray(
            [0.375 + 0.125 * ((7 * index + 11 * case) % 17)
             for index in range(ref_net.n_species)],
            dtype=float,
        )
        assert state.size == ref_net.n_species > 0
        state_generated = np.zeros(generated.num_species, dtype=float)
        for ref_index, generated_index in ref_to_generated.items():
            state_generated[generated_index - 1] = state[ref_index - 1]

        expected = np.asarray(evaluate_rhs(ref_net, state, time), dtype=float)
        assert expected.size == ref_net.n_species > 0
        assert np.isfinite(expected).all(), (
            f"reference RHS contains a non-finite value [{model_name}] at t={time:g}"
        )
        actual_generated = np.asarray(
            cpp._validation_ode_rhs(
                model._model, generated, time, state_generated.tolist()
            ),
            dtype=float,
        )
        assert np.isfinite(actual_generated).all(), (
            f"BNG3 RHS contains a non-finite value [{model_name}] at t={time:g}"
        )
        actual = np.zeros(ref_net.n_species, dtype=float)
        for ref_index, generated_index in ref_to_generated.items():
            actual[ref_index - 1] = actual_generated[generated_index - 1]
        assert actual.size == ref_net.n_species > 0
        assert np.isfinite(actual).all(), (
            f"mapped BNG3 RHS contains a non-finite value [{model_name}] at t={time:g}"
        )

        np.testing.assert_allclose(
            actual,
            expected,
            rtol=RHS_RTOL,
            atol=RHS_ATOL,
            err_msg=(
                f"direct RHS mismatch [{model_name}] at t={time:g} "
                f"(ref={ref_source})"
            ),
        )
        evaluated_vectors += 1
    assert evaluated_vectors == len(RHS_TIMES) > 0
