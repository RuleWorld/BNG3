"""Independent qualification of optional BNGsim backend and native default for #144.

Acceptance checks:
- release-bngsim: adapter-enabled and disabled installs report correct availability; native remains default.
- release-bngsim-parity: BNG2, analytic laws, and BNGsim agree on ODE/SSA cases; fail-closed diagnostics on unsupported features.
- release-capability-coverage-144: all assigned inventory cases (backend.bngsim) execute against named independent oracles.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import textwrap
import numpy as np
import pytest

import bionetgen

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]

SIMPLE_DECAY_BNGL = textwrap.dedent("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")

REVERSIBLE_BINDING_BNGL = textwrap.dedent("""
begin model
begin parameters
    kp 0.5
    km 0.2
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 10
    B(a) 10
end seed species
begin observables
    Molecules Complex A(b!1).B(a!1)
    Molecules FreeA A(b)
    Molecules FreeB B(a)
end observables
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) kp, km
end reaction rules
end model
""")

COMPARTMENT_BNGL = textwrap.dedent("""
begin model
begin compartments
    CYT 3 1.0
end compartments
begin molecule types
    X()
end molecule types
begin seed species
    @CYT:X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 0.1
end reaction rules
end model
""")

ENERGY_BNGL = textwrap.dedent("""
begin model
begin parameters
    RT 0.6
end parameters
begin molecule types
    A(x)
end molecule types
begin seed species
    A(x~u) 10
end seed species
begin energy patterns
    A(x~p) 1.0
end energy patterns
begin reaction rules
    A(x~u) -> A(x~p) 1.0
end reaction rules
end model
""")

CUSTOM_OBS_BNGL = textwrap.dedent("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Custom X_custom X()
end observables
begin reaction rules
    X() -> 0 0.1
end reaction rules
end model
""")

TFUN_BNGL = textwrap.dedent("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin functions
    rate() = TFUN('forcing.dat', time)
end functions
begin reaction rules
    X() -> 0 rate()
end reaction rules
end model
""")


def _tmp_bngl(text: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".bngl", delete=False)
    f.write(text)
    f.close()
    return f.name


# =============================================================================
# release-bngsim: Availability reporting, default solver, explicit routing
# =============================================================================


def test_release_bngsim_capabilities_structure():
    """Verify getBngsimCapabilities / bngsim_capabilities object structure."""
    import bionetgen._bionetgen_cpp as _cpp

    caps = _cpp.bngsim_capabilities()
    assert isinstance(caps, dict)
    for expected_key in (
        "available",
        "version",
        "supports_ode",
        "supports_ssa",
        "supports_psa",
        "supports_pla",
    ):
        assert expected_key in caps, f"Missing key in capabilities: {expected_key}"

    assert isinstance(caps["available"], bool)
    assert isinstance(caps["version"], str)

    if not caps["available"]:
        assert caps["version"] == "unavailable"
        assert caps["supports_ode"] is False
        assert caps["supports_ssa"] is False
        assert caps["supports_psa"] is False
        assert caps["supports_pla"] is False
    else:
        assert caps["version"] != "unavailable"
        assert len(caps["version"]) > 0


def test_release_bngsim_native_default():
    """Verify that native finite solvers remain the default when backend is omitted."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        r_ode = m.simulate(method="ode", t_end=1.0, n_steps=2)
        assert r_ode.backend == "native"
        assert len(r_ode.time) == 3
        assert "Xtot" in r_ode.observables

        r_ssa = m.simulate(method="ssa", t_end=1.0, n_steps=2, seed=123)
        assert r_ssa.backend == "native"
        assert len(r_ssa.time) == 3
        assert "Xtot" in r_ssa.observables
    finally:
        os.unlink(path)


def test_release_bngsim_auto_resolves_to_native():
    """Verify that backend='auto' resolves to native during migration (ADR 0003)."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        for auto_alias in ("auto", "automatic", "bng3", "default", "native"):
            r = m.simulate(method="ode", t_end=1.0, n_steps=2, backend=auto_alias)
            assert r.backend == "native", f"Failed for backend alias: {auto_alias}"
    finally:
        os.unlink(path)


def test_release_bngsim_explicit_selection_and_fail_closed():
    """Verify explicit backend='bngsim' fails closed when unavailable or unsupported."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        import bionetgen._bionetgen_cpp as _cpp

        if not _cpp.bngsim_available():
            with pytest.raises(RuntimeError, match="unavailable"):
                m.simulate(method="ode", t_end=1.0, n_steps=2, backend="bngsim")
            with pytest.raises(RuntimeError, match="unavailable"):
                m.simulate(method="ssa", t_end=1.0, n_steps=2, backend="bngsim")
        else:
            r = m.simulate(method="ode", t_end=1.0, n_steps=2, backend="bngsim")
            assert r.backend == "bngsim"
            assert len(r.time) == 3
    finally:
        os.unlink(path)


def test_release_bngsim_env_var_routing():
    """Verify BIONETGEN_FINITE_BACKEND environment variable routing and reversion."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        import bionetgen._bionetgen_cpp as _cpp

        os.environ["BIONETGEN_FINITE_BACKEND"] = "bngsim"
        try:
            if not _cpp.bngsim_available():
                with pytest.raises(RuntimeError, match="unavailable"):
                    m.simulate(method="ode", t_end=1.0, n_steps=2)
            else:
                r = m.simulate(method="ode", t_end=1.0, n_steps=2)
                assert r.backend == "bngsim"
        finally:
            del os.environ["BIONETGEN_FINITE_BACKEND"]

        # Clean reversion to native default
        r_revert = m.simulate(method="ode", t_end=1.0, n_steps=2)
        assert r_revert.backend == "native"
    finally:
        os.unlink(path)


def test_release_bngsim_nf_method_rejected():
    """Verify network-free simulation (NFsim) strictly refuses backend='bngsim'."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        with pytest.raises(ValueError, match="not valid for method='nf'"):
            m.simulate(method="nf", backend="bngsim")
    finally:
        os.unlink(path)


def test_release_bngsim_legacy_user_syntax_preserved():
    """Verify standard syntax without backend arguments behaves identically."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        r1 = bionetgen.run(path, method="ode", t_end=1.0, n_steps=5)
        assert r1.backend == "native"
        assert len(r1.time) == 6

        m = bionetgen.load(path)
        r2 = m.simulate(method="ode", t_end=1.0, n_steps=5)
        assert r2.backend == "native"
        np.testing.assert_allclose(r1.time, r2.time)
        np.testing.assert_allclose(r1.observables["Xtot"], r2.observables["Xtot"])
    finally:
        os.unlink(path)


# =============================================================================
# release-bngsim-parity: Lowering validation, analytic parity, fail-closed diagnostics
# =============================================================================


def test_release_bngsim_parity_lowering_acceptance():
    """Verify lowerability checks pass on elementary mass-action models."""
    import bionetgen._bionetgen_cpp as _cpp

    for bngl_source in (SIMPLE_DECAY_BNGL, REVERSIBLE_BINDING_BNGL):
        path = _tmp_bngl(bngl_source)
        try:
            m = bionetgen.load(path)
            m.generate_network()
            chk = _cpp.check_bngsim_lowering(m._model, m._network)
            assert chk["supported"] is True
            assert len(chk["blockers"]) == 0
        finally:
            os.unlink(path)


def test_release_bngsim_parity_lowering_rejection_compartments():
    """Verify compartment models fail closed with explicit diagnostic."""
    import bionetgen._bionetgen_cpp as _cpp

    path = _tmp_bngl(COMPARTMENT_BNGL)
    try:
        m = bionetgen.load(path)
        m.generate_network()
        chk = _cpp.check_bngsim_lowering(m._model, m._network)
        assert chk["supported"] is False
        assert any("compartments" in b for b in chk["blockers"])

        with pytest.raises(RuntimeError, match="compartments|unavailable"):
            m.simulate(method="ode", backend="bngsim")
    finally:
        os.unlink(path)


def test_release_bngsim_parity_lowering_rejection_energy():
    """Verify energy pattern models fail closed with explicit diagnostic."""
    import bionetgen._bionetgen_cpp as _cpp

    path = _tmp_bngl(ENERGY_BNGL)
    try:
        m = bionetgen.load(path)
        m.generate_network()
        chk = _cpp.check_bngsim_lowering(m._model, m._network)
        assert chk["supported"] is False
        assert any("energy" in b.lower() for b in chk["blockers"])

        with pytest.raises(RuntimeError, match="energy|unavailable"):
            m.simulate(method="ode", backend="bngsim")
    finally:
        os.unlink(path)


def test_release_bngsim_parity_lowering_rejection_custom_obs():
    """Verify models with Custom observable types fail closed."""
    import bionetgen._bionetgen_cpp as _cpp

    path = _tmp_bngl(CUSTOM_OBS_BNGL)
    try:
        m = bionetgen.load(path)
        m.generate_network()
        chk = _cpp.check_bngsim_lowering(m._model, m._network)
        assert chk["supported"] is False
        assert any("unsupported observable type" in b for b in chk["blockers"])

        with pytest.raises(RuntimeError, match="observable|unavailable"):
            m.simulate(method="ode", backend="bngsim")
    finally:
        os.unlink(path)


def test_release_bngsim_parity_lowering_rejection_tfun():
    """Verify models with TFUN / table functions fail closed."""
    import bionetgen._bionetgen_cpp as _cpp

    path = _tmp_bngl(TFUN_BNGL)
    try:
        m = bionetgen.load(path)
        m.generate_network()
        chk = _cpp.check_bngsim_lowering(m._model, m._network)
        assert chk["supported"] is False
        assert any("TFUN" in b for b in chk["blockers"])

        with pytest.raises(RuntimeError, match="TFUN|unavailable"):
            m.simulate(method="ode", backend="bngsim")
    finally:
        os.unlink(path)


def test_release_bngsim_parity_ode_analytic_and_native():
    """Verify ODE simulation against analytic oracle X(t) = 100*exp(-0.1*t)."""
    path = _tmp_bngl(SIMPLE_DECAY_BNGL)
    try:
        m = bionetgen.load(path)
        t_eval = np.linspace(0.0, 2.0, 11)
        r_native = m.simulate(method="ode", t_end=2.0, n_steps=10)

        # Analytic mass-action solution
        x_analytic = 100.0 * np.exp(-0.1 * r_native.time)
        np.testing.assert_allclose(
            r_native.observables["Xtot"],
            x_analytic,
            rtol=1e-5,
            atol=1e-6,
            err_msg="Native ODE deviates from analytic solution",
        )

        import bionetgen._bionetgen_cpp as _cpp

        if _cpp.bngsim_available():
            r_bngsim = m.simulate(method="ode", t_end=2.0, n_steps=10, backend="bngsim")
            assert r_bngsim.backend == "bngsim"
            np.testing.assert_allclose(
                r_bngsim.observables["Xtot"],
                x_analytic,
                rtol=1e-5,
                atol=1e-6,
                err_msg="BNGsim ODE deviates from analytic solution",
            )
            np.testing.assert_allclose(
                r_bngsim.observables["Xtot"],
                r_native.observables["Xtot"],
                rtol=1e-5,
                atol=1e-6,
                err_msg="BNGsim ODE deviates from native ODE",
            )
    finally:
        os.unlink(path)


def test_release_bngsim_parity_ssa_conservation():
    """Verify SSA mass conservation A + B = 10 and seed reproducibility."""
    path = _tmp_bngl(REVERSIBLE_BINDING_BNGL)
    try:
        m = bionetgen.load(path)
        r_native1 = m.simulate(method="ssa", t_end=5.0, n_steps=10, seed=42)
        r_native2 = m.simulate(method="ssa", t_end=5.0, n_steps=10, seed=42)

        # Bitwise identical with same seed
        np.testing.assert_array_equal(
            r_native1.observables["Complex"], r_native2.observables["Complex"]
        )

        # Mass conservation: FreeA + Complex == 10, FreeB + Complex == 10
        total_a = r_native1.observables["FreeA"] + r_native1.observables["Complex"]
        total_b = r_native1.observables["FreeB"] + r_native1.observables["Complex"]
        np.testing.assert_array_equal(total_a, np.full_like(total_a, 10))
        np.testing.assert_array_equal(total_b, np.full_like(total_b, 10))

        import bionetgen._bionetgen_cpp as _cpp

        if _cpp.bngsim_available() and _cpp.bngsim_capabilities().get(
            "supports_ssa", False
        ):
            r_bngsim = m.simulate(
                method="ssa", t_end=5.0, n_steps=10, seed=42, backend="bngsim"
            )
            assert r_bngsim.backend == "bngsim"
            total_a_bngsim = (
                r_bngsim.observables["FreeA"] + r_bngsim.observables["Complex"]
            )
            np.testing.assert_array_equal(
                total_a_bngsim, np.full_like(total_a_bngsim, 10)
            )
    finally:
        os.unlink(path)


# =============================================================================
# release-capability-coverage-144: Contract, metadata, and ADR 0003 compliance
# =============================================================================


def test_release_capability_coverage_144_contract():
    """Verify release contract schema, assigned issue, and inventory rows."""
    contract_file = CASE_DIR / "contract.json"
    assert contract_file.exists(), "contract.json must exist in release case dir"

    with open(contract_file, encoding="utf-8") as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 144
    assert "backend.bngsim" in contract["inventory_rows"]
    assert "release-bngsim" in contract["acceptance_checks"]
    assert "release-bngsim-parity" in contract["acceptance_checks"]
    assert "release-capability-coverage-144" in contract["acceptance_checks"]


def test_release_capability_coverage_144_adr_0003():
    """Verify ADR 0003 documents native default and supported optional BNGsim."""
    adr_file = REPO_ROOT / "docs" / "adr" / "0003-bngsim-canonical-finite-backend.md"
    assert adr_file.exists(), "docs/adr/0003 must exist"

    text = adr_file.read_text(encoding="utf-8")
    assert "Native BNG3 ODE/SSA/PLA/PSA solvers are the default." in text
    assert "BNGsim is a supported optional backend." in text
    assert (
        "The required architecture is one common compiled-model, capability, protocol, lifetime and result interface"
        in text
    )
