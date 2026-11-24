"""Issue #178 backend/format route to test mapping.

Every required production route is mapped to an existing collected test for
each of the four evidence aspects required by ``release-backend-contract`` and
``release-interface-parity``:

* ``compiled_input`` - the route consumes the same compiled model input;
* ``result_schema`` - the route returns the declared result shape;
* ``invalid_options`` - invalid option combinations fail consistently;
* ``independent_output`` - output agrees with an independent oracle (BNG2,
  native NFsim or an analytic law), not with another BNG3 route.

This module checks that the mapping is complete (every route/aspect has a
real, existing selector). It does not itself claim execution: the recorder
still requires a consuming report whose route rows are produced by running
these selectors at an exact revision. GPU device execution is owned by #474;
the GPU row is declared compile-only and is never counted as device evidence.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ci.record_issue178_release import REQUIRED_ROUTES, ROUTE_ASPECTS

ROOT = Path(__file__).resolve().parents[5]

# Shared compiled-input gate used by every finite/network-free/native route.
_COMPILED = "tests/validation/release/cases/issue-138/test_compiled_model.py::test_release_compiled_inputs_architecture_ratchet"
_FORMAT = "tests/validation/release/cases/issue-163/test_export_format_release.py"
_BNGSIM = "tests/validation/release/cases/issue-144/test_bngsim_backend.py"

ROUTE_TESTS: dict[str, dict[str, str]] = {
    "ode:native": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/python/test_finite_backend.py::test_native_ode_returns_native_backend",
        "invalid_options": "tests/python/test_finite_backend.py::test_compartment_model_lowering_is_rejected",
        "independent_output": "tests/validation/release/cases/issue-138/test_compiled_model.py::test_release_compiled_parity_analytical_ode_simulation",
    },
    "ssa:native": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/python/test_finite_backend.py::test_native_ode_returns_native_backend",
        "invalid_options": "tests/python/test_finite_backend.py::test_explicit_bngsim_fails_closed_when_unavailable_or_unsupported",
        "independent_output": "tests/validation/test_parity_stochastic.py::test_binomial_control_accepts_a_correct_ensemble_mean",
    },
    "pla:native": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/python/test_finite_backend.py::test_native_ode_returns_native_backend",
        "invalid_options": "tests/python/test_finite_backend.py::test_explicit_bngsim_fails_closed_when_unavailable_or_unsupported",
        "independent_output": "tests/validation/release/cases/issue-138/test_compiled_model.py::test_release_compiled_parity_analytical_ode_simulation",
    },
    "psa:native": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/python/test_finite_backend.py::test_native_ode_returns_native_backend",
        "invalid_options": "tests/validation/test_simulation_contract.py::test_net_reload_ssa_rejects_time_through_nested_user_function_argument",
        "independent_output": "tests/validation/release/cases/issue-138/test_compiled_model.py::test_release_compiled_parity_analytical_ode_simulation",
    },
    "nf:nfnext": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/validation/release/cases/issue-148/test_nfnext_execution.py::test_release_nfnext_routes_production_entrypoint",
        "invalid_options": "tests/validation/release/cases/issue-148/test_nfnext_execution.py::test_release_nfnext_routes_fail_closed_unsupported_rejection",
        "independent_output": "tests/validation/release/cases/issue-148/test_nfnext_execution.py::test_release_nfnext_execution_native_nfsim_parity",
    },
    "nf:nfcore": {
        "compiled_input": _COMPILED,
        "result_schema": "tests/validation/release/cases/issue-146/test_nfcore_qualification.py::test_release_nfcore_observable_semantics",
        "invalid_options": "tests/validation/release/cases/issue-146/test_nfcore_qualification.py::test_release_nfcore_option_handling",
        "independent_output": "tests/validation/release/cases/issue-146/test_nfcore_qualification.py::test_release_nfcore_dual_route_equivalence",
    },
    "ode:bngsim": {
        "compiled_input": _COMPILED,
        "result_schema": f"{_BNGSIM}::test_release_bngsim_capabilities_structure",
        "invalid_options": f"{_BNGSIM}::test_release_bngsim_explicit_selection_and_fail_closed",
        "independent_output": f"{_BNGSIM}::test_release_bngsim_parity_lowering_acceptance",
    },
    "ssa:bngsim": {
        "compiled_input": _COMPILED,
        "result_schema": f"{_BNGSIM}::test_release_bngsim_capabilities_structure",
        "invalid_options": f"{_BNGSIM}::test_release_bngsim_explicit_selection_and_fail_closed",
        "independent_output": f"{_BNGSIM}::test_release_bngsim_parity_lowering_acceptance",
    },
    "format:bngl": {
        "compiled_input": _COMPILED,
        "result_schema": f"{_FORMAT}::test_release_formats",
        "invalid_options": f"{_FORMAT}::test_release_format_semantics",
        "independent_output": f"{_FORMAT}::test_release_format_semantics",
    },
    "format:net": {
        "compiled_input": _COMPILED,
        "result_schema": f"{_FORMAT}::test_release_formats",
        "invalid_options": f"{_FORMAT}::test_release_format_semantics",
        "independent_output": f"{_FORMAT}::test_release_format_semantics",
    },
}

# GPU is compile-only here; actual device execution and crossover are #474.
GPU_SCOPE = {
    "backend.gpu": "#474",
    "release-nf-gpu": "#474",
    "scope": "compile-only",
}


def _selector_exists(selector: str) -> bool:
    """A selector names an existing file and (optionally) an existing function."""
    path_part, _, func = selector.partition("::")
    path = ROOT / path_part
    if not path.is_file():
        return False
    if not func:
        return True
    return f"def {func}(" in path.read_text(encoding="utf-8")


def test_every_required_route_has_all_four_mapped_aspects():
    required = {name for routes in REQUIRED_ROUTES.values() for name in routes}
    assert required <= set(
        ROUTE_TESTS
    ), f"unmapped routes: {sorted(required - set(ROUTE_TESTS))}"
    for route in required:
        aspects = ROUTE_TESTS[route]
        assert set(aspects) == set(ROUTE_ASPECTS), f"{route}: {sorted(aspects)}"
        for aspect, selector in aspects.items():
            assert _selector_exists(selector), f"{route}/{aspect}: missing {selector}"


def test_gpu_is_compile_only_and_tracked_under_474():
    assert GPU_SCOPE["backend.gpu"] == "#474"
    assert GPU_SCOPE["release-nf-gpu"] == "#474"
    assert GPU_SCOPE["scope"] == "compile-only"
