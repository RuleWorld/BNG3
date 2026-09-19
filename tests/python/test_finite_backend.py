"""Finite-backend boundary tests (ADR 0003).

These tests lock the user-facing contract for the BNGsim canonical backend
migration: default syntax unchanged, opt-in backend selection, fail-closed
lowering, and result parity where supported.
"""

import os
import tempfile
import textwrap

import pytest

import bionetgen

SIMPLE_BNGL = textwrap.dedent("""
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
""")

COMPARTMENT_BNGL = textwrap.dedent("""
begin compartments
 CYT 3 1
end compartments
begin molecule types
 X()
end molecule types
begin seed species
 X() 1
end seed species
""")

ENERGY_BNGL = textwrap.dedent("""
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
""")


def _tmp_bngl(text: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".bngl", delete=False)
    f.write(text)
    f.close()
    return f.name


def test_native_ode_returns_native_backend():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        r = m.simulate(method="ode", t_end=1, n_steps=2)
        assert r.backend == "native"
        assert len(r.time) == 3
        assert "Xtot" in r.observables
    finally:
        os.unlink(path)


def test_auto_backend_is_native_during_migration():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        r = m.simulate(method="ode", t_end=1, n_steps=2, backend="auto")
        assert r.backend == "native"
        r2 = m.simulate(method="ssa", t_end=1, n_steps=2, backend="auto", seed=1)
        assert r2.backend == "native"
    finally:
        os.unlink(path)


def test_explicit_bngsim_fails_closed_when_unavailable_or_unsupported():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        # In this CI build BNGSIM is unavailable, so explicit bngsim must fail
        # closed with a precise unavailable message rather than silently falling back.
        import bionetgen._bionetgen_cpp as _cpp

        if not _cpp.bngsim_available():
            with pytest.raises(RuntimeError, match="unavailable"):
                m.simulate(method="ode", t_end=1, n_steps=2, backend="bngsim")
            with pytest.raises(RuntimeError, match="unavailable"):
                m.simulate(method="ssa", t_end=1, n_steps=2, backend="bngsim")
        else:
            # When BNGSIM is available, simple model should succeed via BNGSIM
            r = m.simulate(method="ode", t_end=1, n_steps=2, backend="bngsim")
            assert r.backend == "bngsim"
    finally:
        os.unlink(path)


def test_compartment_model_lowering_is_rejected():
    path = _tmp_bngl(COMPARTMENT_BNGL)
    try:
        m = bionetgen.load(path)
        m.generate_network()
        import bionetgen._bionetgen_cpp as _cpp

        chk = _cpp.check_bngsim_lowering(m._model, m._network)
        assert chk["supported"] is False
        assert any("compartments" in b for b in chk["blockers"])
        # Explicit bngsim must be fail-closed, not silently fall back.
        with pytest.raises(RuntimeError, match="compartments|unavailable"):
            m.simulate(method="ode", backend="bngsim")
    finally:
        os.unlink(path)


def test_nf_never_routes_through_bngsim():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        # NFSim path is independent; backend=bngsim must be rejected
        with pytest.raises(ValueError, match="not valid for method='nf'"):
            m.simulate(method="nf", backend="bngsim")
        # native and auto should remain NFsim
        # We don't actually run NFsim here (requires full model), just check the route exists
    finally:
        os.unlink(path)


def test_env_var_bngsim_opt_in():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        import bionetgen._bionetgen_cpp as _cpp

        os.environ["BIONETGEN_FINITE_BACKEND"] = "bngsim"
        try:
            if not _cpp.bngsim_available():
                with pytest.raises(RuntimeError, match="unavailable"):
                    m.simulate(method="ode", t_end=1, n_steps=2)
            else:
                r = m.simulate(method="ode", t_end=1, n_steps=2)
                assert r.backend == "bngsim"
        finally:
            del os.environ["BIONETGEN_FINITE_BACKEND"]
        # After clearing, back to native
        r2 = m.simulate(method="ode", t_end=1, n_steps=2)
        assert r2.backend == "native"
    finally:
        os.unlink(path)


def test_bngsim_capabilities_object():
    import bionetgen._bionetgen_cpp as _cpp

    caps = _cpp.bngsim_capabilities()
    assert "available" in caps
    assert "version" in caps
    assert "supports_ode" in caps
    assert "supports_ssa" in caps
    # When unavailable, version is "unavailable"
    if not caps["available"]:
        assert caps["version"] == "unavailable"
        assert caps["supports_ode"] is False


def test_existing_user_syntax_unchanged():
    # PyBioNetGen-compatible API must not require backend arg
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        # Original call shape without backend kw must still work
        r = m.simulate(method="ode", t_end=10, n_steps=10)
        assert r.backend == "native"
        # SSA with seed
        r2 = m.simulate(method="ssa", t_end=10, n_steps=10, seed=42)
        assert r2.backend == "native"
        # run() helper
        r3 = bionetgen.run(path, method="ode", t_end=1, n_steps=2)
        assert isinstance(r3.backend, str)
    finally:
        os.unlink(path)


def test_bngsim_pla_psa_not_yet_routed():
    path = _tmp_bngl(SIMPLE_BNGL)
    try:
        m = bionetgen.load(path)
        # PLA/PSA with backend=bngsim should fail closed rather than silently use native
        with pytest.raises(RuntimeError, match="does not yet support"):
            m.simulate(method="pla", backend="bngsim")
        with pytest.raises(RuntimeError, match="does not yet support"):
            m.simulate(method="psa", backend="bngsim")
    finally:
        os.unlink(path)
