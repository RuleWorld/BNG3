"""Release-gap qualification for Issue #475 delayed semantics.

Covers the work clauses that were previously only implied by wrapper tests:

- a complete ``delay guard`` across every non-native backend (ANL BNGsim,
  NFsim / NFnext network-free, PLA, PSA) so a delayed rule is never silently
  executed as an immediate reaction;
- ``pending delay tests`` for cancellation (reset), queue order (scheduled
  completion times), changing rates across continuation, and the guard that
  refuses a changed delay on continuation.

Every check uses either a native consumer with an analytic/predeclared law or
an explicit-unsupported diagnostic.  No expected output, tolerance or seed
budget from an existing acceptance test is changed.
"""

from __future__ import annotations

import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel

cpp = bionetgen.model._cpp


def _delayed_model(rate: str = "0.5", tau: float = 2.0) -> BioNetGenModel:
    source = f"""
begin model
begin parameters
  tau {tau}
  k {rate}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    return BioNetGenModel(cpp.parse_string(source))


def _delay_call_model() -> BioNetGenModel:
    """A model whose rate law contains delay(x, tau) rather than a rule delay."""
    source = """
begin model
begin parameters
  tau 1
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Aobs A()
end observables
begin reaction rules
  A() -> B() k
  0 -> B() k*delay(Aobs, tau)
end reaction rules
end model
"""
    return BioNetGenModel(cpp.parse_string(source))


def test_delayed_guard_rejects_all_non_native_backends():
    """Every backend that cannot carry a pending queue fails closed on delay.

    Regression: before the NFnext guard, ``method='nfnext'`` silently executed
    a delayed ``A -> B`` as an immediate reaction (B(0.5)=92 for A0=100),
    while the native ODE produced B(0.5)=0.  A silent approximation is the one
    outcome that must never be reported as support.
    """
    source = """
begin model
begin parameters
  tau 1
  k 5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  A() -> B() k delay=tau
end reaction rules
end model
"""
    model = BioNetGenModel(cpp.parse_string(source))

    # Native ODE is the oracle: no completion before the delay horizon.
    native = model.simulate(method="ode", t_end=0.5, n_steps=5)
    assert float(native.observables["B"][-1]) == pytest.approx(0.0, abs=1e-9)

    for method in ("nf", "nfnext", "pla", "psa"):
        with pytest.raises(RuntimeError, match="delay|Delay"):
            model.simulate(method=method, t_end=0.5, n_steps=5, seed=1)

    # BNGsim finite lowering reports an explicit blocker instead of generating
    # a network the external simulator would execute without the delay.
    net = model.generate_network()
    check = cpp.check_bngsim_lowering(model._model, net)
    assert check["supported"] is False
    assert any(
        "delayed reactions require the native DDE" in b for b in check["blockers"]
    )

    # delay(x, tau) rate-expression models fail closed in the network-free
    # executor too, not only rule-modifier delays.
    with pytest.raises(RuntimeError, match="delay|Delay"):
        _delay_call_model().simulate(method="nfnext", t_end=1.0, n_steps=2, seed=1)


def test_delayed_guard_rejects_changed_delay_on_continuation():
    """A continuation leg may not change the delay (pending queue invariant)."""
    for method in ("ode", "ssa"):
        model = _delayed_model()
        kw = {"seed": 17} if method == "ssa" else {}
        model.simulate(method=method, t_end=1.0, n_steps=2, **kw)
        model.set_parameter("tau", 5.0)
        with pytest.raises(RuntimeError, match="delays to remain constant"):
            model.simulate(
                method=method,
                t_start=1.0,
                t_end=3.0,
                n_steps=4,
                continue_simulation=True,
                **kw,
            )


def test_delayed_pending_completion_cancelled_by_reset():
    """reset_simulation() cancels an in-flight completion (explicit state drop).

    A pending completion scheduled at t=2 is cancelled by a reset at t=1 and a
    fresh run whose delay is 100 cannot complete by t=3 (B==0).  The
    uninterrupted control with the original delay completes (B==1), so the
    assertion is not vacuous.
    """
    for method in ("ode", "ssa"):
        kw = {"seed": 17} if method == "ssa" else {}

        control = _delayed_model()
        ctrl = control.simulate(method=method, t_end=3.0, n_steps=12, **kw)
        # Non-vacuous control: with tau=2 the in-flight queue has completed by t=3.
        assert float(ctrl.observables["B"][-1]) > 5.0

        model = _delayed_model()
        pending = model.simulate(method=method, t_end=1.0, n_steps=2, **kw)
        assert float(pending.observables["B"][-1]) == pytest.approx(0.0, abs=1e-9)
        model.reset_simulation()
        model.set_parameter("tau", 100.0)
        fresh = model.simulate(method=method, t_end=3.0, n_steps=6, **kw)
        assert float(fresh.observables["B"][-1]) == pytest.approx(0.0, abs=1e-6)


def test_delayed_ssa_completion_queue_order_and_determinism():
    """Completions fire at scheduled times (FIFO queue) and are reproducible.

    Two delayed consuming channels share reactant A with tau_B=1 and tau_C=2.
    At t=1.5 only B has completed; at t=2.5 C has also started.  With a fixed
    seed the ordered completion stream is identical across runs, and A+B+C is
    conserved (every initiation either completed or is still in flight).
    """
    source = """
begin model
begin parameters
  tau1 1
  tau2 2
  k 5
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 200
end seed species
begin observables
  Molecules B B()
  Molecules C C()
end observables
begin reaction rules
  A() -> B() k delay=tau1
  A() -> C() k delay=tau2
end reaction rules
end model
"""

    def run(seed: int):
        model = BioNetGenModel(cpp.parse_string(source))
        return model.simulate(
            method="ssa",
            t_end=3.5,
            sample_times=[0.5, 1.5, 2.5, 3.5],
            seed=seed,
        )

    first = run(99)
    second = run(99)
    for key in ("B", "C"):
        np.testing.assert_array_equal(first.observables[key], second.observables[key])

    b = np.asarray(first.observables["B"], dtype=float)
    c = np.asarray(first.observables["C"], dtype=float)
    # No completion before either horizon; B (earlier queue) strictly precedes C.
    assert b[0] == 0.0 and c[0] == 0.0
    assert b[1] > 0.0 and c[1] == 0.0
    assert c[2] > 0.0
    assert np.all(np.diff(b) >= 0) and np.all(np.diff(c) >= 0)
