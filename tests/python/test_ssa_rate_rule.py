"""A rate rule's rate is applied in the stochastic reading too.

SBML Level 3 Version 2 Core, section 4.9.4 ("RateRule"), makes a rate rule the
defining derivative of its variable for the whole simulation:

> "The value of the RateRule object's math attribute is the rate of change of
> the variable ... The rate rule is applied at every point in time."

A stochastic simulation has to honour that too, or the same converted model
means two different things depending on which engine simulates it.

**How BNG3 represents it.**  The Atomizer lowers a rate rule into a *state
species* whose amount **is** the rule variable's value, plus a ``TotalRate``
source rule that applies the rule's own rate:

    __rate_rule_p1: 0 -> M___rate_rule_state__p1() __rate_rule__p1() TotalRate

The deterministic reading integrates that rule, so the state species holds the
variable's value.  The direct method fires the rule's rate as a propensity,
so the state species grows at the rule's rate in expectation.  The two
readings therefore agree in the mean, which is the property this file pins.

**The campaign's recorded disagreement was not this.**  The stochastic
consistency sweep once reported ``semantic/00990`` as inconsistent with the
mechanism ``ssa-does-not-apply-rate-rules``.  That attribution was a guess:
the sweep labels *any* disagreement in a model that has a rate rule that way.
The disagreement was a data race in the multi-worker CPU batch pool - the
shared observable scratch that pull request #362 (``b4171576``) moved to
per-worker storage - and it is fixed on ``main``.  On ``main`` the sweep
reports ``semantic/00990`` as ``consistent`` with a maximum |z| of 2.1253,
which is the number #362 recorded after its fix.

The assertions below are in the campaign's form: the **stochastic** reading
must agree with the **deterministic** reading of the same converted model, at
every time point.  A test that only exercised the ODE path would pass on an
engine that ignored the rule entirely.
"""

import math

import numpy as np
import pytest

from _extdep import require_extension

_cpp = require_extension()

# A deviation beyond this many ensemble standard errors is a 5.7e-7 two-sided
# normal tail.  The models below carry the rule's rate into a second species,
# so an engine that ignored the rule would miss by hundreds of standard
# errors; the margin is not a tolerance choice.
K_SIGMA = 5.0

BATCH = 2000
SEED = 20261020

# The shape the Atomizer lowers a rate rule into: a state species that carries
# the rule variable's value, driven by the rule's rate, and a second species
# whose production rate reads the rule variable.
RATE_RULE_SHAPE = """begin model
begin parameters
  rate 1
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S()  1
  P()  0
end seed species
begin observables
  Molecules nS S()
  Molecules nP P()
end observables
begin reaction rules
  0 -> S()  rate  TotalRate
  0 -> P()  nS    TotalRate
end reaction rules
end model
"""

# The same shape as an SBML source: a parameter that carries a rate rule, and
# a reaction whose kinetic law reads the parameter.
SBML_RATE_RULE = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="rate_rule">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="X" compartment="C" initialAmount="1" hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="p1" value="1" constant="false"/>
      <parameter id="k1" value="1" constant="true"/>
    </listOfParameters>
    <listOfRules>
      <rateRule variable="p1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <cn type="integer"> 1 </cn>
        </math>
      </rateRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfProducts>
          <speciesReference species="X" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> k1 </ci>
              <ci> p1 </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


def _network(bngl):
    model = _cpp.parse_string(bngl)
    return model, _cpp.generate_network(model)


def _batch(model, network, t_end=10.0, n_steps=10, batch=BATCH, seed=SEED, threads=1):
    return _cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=batch,
        t_end=t_end,
        n_steps=n_steps,
        t_start=0.0,
        base_seed=seed,
        max_sim_steps=0,
        threads=threads,
    )


def _deterministic(model, times):
    from bionetgen import BioNetGenModel

    trace = BioNetGenModel(model).simulate(
        method="ode",
        t_start=float(times[0]),
        t_end=float(times[-1]),
        n_steps=0,
        sample_times=[float(value) for value in times],
        rtol=1e-9,
        atol=1e-14,
    )
    return {
        name: np.asarray(values, dtype=float)
        for name, values in trace.observables.items()
    }


def _assert_agrees(mean, sd, reference, batch):
    mean = np.asarray(mean, dtype=float)
    sd = np.asarray(sd, dtype=float)
    reference = np.asarray(reference, dtype=float)
    assert mean.shape == reference.shape
    standard_error = sd / math.sqrt(batch)
    deviation = np.abs(mean - reference)
    worst = (
        float(np.max(deviation - K_SIGMA * standard_error)) if deviation.size else 0.0
    )
    assert worst <= 0.0, (
        f"the stochastic reading departs from the deterministic one by "
        f"{worst:.4g} beyond {K_SIGMA} ensemble standard errors"
    )


def test_the_rate_rule_shape_agrees_with_the_deterministic_reading():
    """The rule's rate reaches the species that reads it.

    ``S`` carries the rule variable: its deterministic reading is ``1 + t``.
    ``P``'s production rate reads ``S``, so its deterministic reading is
    ``t + t^2/2``.  Both have to agree with the stochastic ensemble; an engine
    that did not apply the rule would leave ``P`` at zero.
    """

    model, network = _network(RATE_RULE_SHAPE)
    result = _batch(model, network)
    times = np.asarray(result["time"], dtype=float)
    deterministic = _deterministic(model, times)

    for name in ("nS", "nP"):
        assert name in result["observable_names"]
        _assert_agrees(
            np.asarray(result["observable_means"][name], dtype=float),
            np.asarray(result["observable_stds"][name], dtype=float),
            deterministic[name],
            BATCH,
        )

    # The deterministic readings are the ones the model claims: the rule
    # integrates to 1 + t and the dependent species to t + t^2/2.
    assert deterministic["nS"][-1] == pytest.approx(11.0, rel=1e-6)
    assert deterministic["nP"][-1] == pytest.approx(60.0, rel=1e-6)


def test_the_converted_rate_rule_agrees_with_the_deterministic_reading(tmp_path):
    """End to end: an SBML rate rule, converted, then simulated.

    The parameter ``p1`` carries the rule ``dp1/dt = 1`` and the reaction's
    kinetic law reads it, so the reaction's rate is ``k1 * p1`` and the
    species grows at ``1 + t``.  The converted model's stochastic reading has
    to agree with its deterministic reading.
    """

    from bionetgen.atomizer.modern import Atomizer

    source = tmp_path / "rate_rule.xml"
    source.write_text(SBML_RATE_RULE, encoding="utf-8")
    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(
        SBML_RATE_RULE, source_path=source
    )
    assert atomized.success, atomized.error

    model = _cpp.parse_string(atomized.bngl)
    network = _cpp.generate_network(model, max_iter=100)
    result = _batch(model, network)
    times = np.asarray(result["time"], dtype=float)
    deterministic = _deterministic(model, times)

    # The rate-ruled variable's own reading: the state species that carries
    # it grows at the rule's rate in both readings.
    assert "p1_amt" in result["observable_names"]
    _assert_agrees(
        np.asarray(result["observable_means"]["p1_amt"], dtype=float),
        np.asarray(result["observable_stds"]["p1_amt"], dtype=float),
        deterministic["p1_amt"],
        BATCH,
    )

    # The species whose production rate reads the rule variable.
    assert "X_amt" in result["observable_names"]
    _assert_agrees(
        np.asarray(result["observable_means"]["X_amt"], dtype=float),
        np.asarray(result["observable_stds"]["X_amt"], dtype=float),
        deterministic["X_amt"],
        BATCH,
    )
    assert deterministic["X_amt"][-1] == pytest.approx(61.0, rel=1e-6)


def test_the_multi_worker_pool_agrees_with_the_single_worker_pool():
    """The pool's worker count is a throughput choice, not a correctness one.

    The recorded disagreement this file's docstring describes was a data race
    in the shared observable scratch: a rate law that reads an observable was
    resolved against another worker's trajectory state.  The pool is
    reproducible at any worker count now, and the rate rule's reading is the
    sharpest instrument for that, because the rule's state species is read by
    the reaction's rate law.
    """

    model, network = _network(RATE_RULE_SHAPE)
    single = _batch(model, network, threads=1)
    multi = _batch(model, network, threads=0)
    for name in single["observable_names"]:
        assert np.array_equal(
            np.asarray(single["observable_means"][name], dtype=float),
            np.asarray(multi["observable_means"][name], dtype=float),
        ), f"{name} differs between the single-worker and multi-worker pools"
