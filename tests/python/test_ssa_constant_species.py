"""A constant species keeps its amount in every stochastic reading.

BNGL's ``$`` seed-species marker - the spelling of SBML's
``boundaryCondition="true"`` - says that a species' *amount* is not determined
by the reactions.  The SBML Level 3 Version 2 Core, section 4.6.6 ("The
constant and boundaryCondition attributes on Species") says the same:

    "In practice, a boundaryCondition value of 'true' means a differential
    equation derived from the reaction definitions should not be generated for
    the species."

so the amount is constant *by the model*, not by the solver.

BNG3's engines have to agree on that.  The deterministic reading honours it by
zeroing the species' derivative, the partitioned simulators honour it by
skipping the species in their state update, and the direct method honours it
too - after the defect this file pins.  Before the fix the direct method
consumed and produced the constant species like any other, so the *same
converted model* meant two different things depending on which engine simulated
it: the boundary species that the published reference keeps at 0 reached 437
molecules in the stochastic reading, and the sweep's own consistency check
reported 15 converted models whose deterministic and stochastic readings
disagreed for this reason alone
(``semantic/01537 01541 01555 01556 01557 01638 01639 01640 01730 01731
01752 01795`` and ``stochastic/00006 00024 00026``).

The property under test is the one the campaign's stochastic-consistency sweep
measures: **the stochastic reading must agree with the deterministic reading**
of the same converted model.  A test that only exercised the ODE path would
have passed on the broken engine, so every assertion below is on a stochastic
sample.

What the fix does *not* change is the propensity.  A constant species still
contributes its amount to the rate law it appears in - only the state update
skips it.  That is what keeps the two readings equal: the deterministic
reading integrates ``dB/dt = k*A`` with ``A`` held at its initial value, and
the discrete reading fires the reaction at the same constant rate.

Tolerances are Monte-Carlo error.  For ``B`` i.i.d. trajectories the ensemble
mean has standard error ``sd/sqrt(B)``, so a point is compared at
``k_sigma`` standard errors, the same criterion the sweep uses
(``scripts/ci/check_stochastic_consistency.py``).  The seed is fixed, so each
threshold is compared against one deterministic number rather than a
repeated-sampling probability.
"""

import math

import numpy as np
import pytest

from _extdep import require_extension

_cpp = require_extension()

# A deviation beyond this many ensemble standard errors is a 5.7e-7 two-sided
# normal tail.  The models below are exactly the shapes the defect produced, so
# the unfixed engine misses them by hundreds of standard errors; the margin is
# not a tolerance choice.
K_SIGMA = 5.0

BATCH = 2000
SEED = 20261020

# A constant reactant.  ``A`` is seeded constant, so the deterministic reading
# holds it at 100 and grows ``B`` at the constant rate ``k*100 = 50``; the
# discrete reading must fire the reaction at that same rate.
CONSTANT_REACTANT = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  $A()  100
  B()  0
end seed species
begin observables
  Molecules nA A()
  Molecules nB B()
end observables
begin reaction rules
  A() -> B()  k
end reaction rules
end model
"""

# A constant product.  ``B`` is seeded constant, so the deterministic reading
# holds it at 0 while ``A`` decays; the discrete reading must consume ``A`` at
# the same rate and leave ``B`` alone.
CONSTANT_PRODUCT = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A()  100
  $B()  0
end seed species
begin observables
  Molecules nA A()
  Molecules nB B()
end observables
begin reaction rules
  A() -> B()  k
end reaction rules
end model
"""

# The SBML shape the sweep reported: a boundary species that a reaction
# consumes, a second species the reaction produces, and a compartment of unit
# size.  ``S1`` is a boundary species, so the published reference keeps it at 2
# and grows ``S2`` at the reaction's rate.
SBML_BOUNDARY_SPECIES = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
  <model id="boundary">
    <listOfCompartments>
      <compartment id="C" spatialDimensions="3" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialAmount="2" hasOnlySubstanceUnits="false" boundaryCondition="true" constant="false"/>
      <species id="S2" compartment="C" initialAmount="3" hasOnlySubstanceUnits="false" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="J0" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <cn type="integer"> 1 </cn>
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


def _batch(bngl, t_end=10.0, n_steps=10, batch=BATCH, seed=SEED):
    """One batched direct-SSA ensemble on the single-worker CPU pool.

    The CPU pool runs one trajectory per call against the shared integrator's
    direct-method path, so this is the same code path the single-trajectory
    simulator uses; the batch is the campaign's instrument because the
    comparison is against an ensemble mean.
    """

    model, network = _network(bngl)
    result = _cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=batch,
        t_end=t_end,
        n_steps=n_steps,
        t_start=0.0,
        base_seed=seed,
        max_sim_steps=0,
        threads=1,
    )
    return result


def _deterministic(bngl, times):
    """The model's own CVODE trace on the given grid."""

    from bionetgen import BioNetGenModel

    model, _network_object = _network(bngl)
    result = BioNetGenModel(model).simulate(
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
        for name, values in result.observables.items()
    }


def _assert_agrees(mean, sd, reference, batch):
    """The sweep's criterion: the reference lies inside the ensemble band."""

    mean = np.asarray(mean, dtype=float)
    sd = np.asarray(sd, dtype=float)
    reference = np.asarray(reference, dtype=float)
    assert mean.shape == reference.shape
    standard_error = sd / math.sqrt(batch)
    deviation = np.abs(mean - reference)
    band = K_SIGMA * standard_error
    worst = float(np.max(deviation - band)) if deviation.size else 0.0
    assert worst <= 0.0, (
        f"the stochastic reading departs from the deterministic one by "
        f"{worst:.4g} beyond {K_SIGMA} ensemble standard errors"
    )


def _gpu_backend():
    """The name of an available accelerator backend, or None."""

    for entry in _cpp.gpu_backends():
        if entry.get("available"):
            return str(entry["name"])
    return None


def test_the_gpu_batch_keeps_a_constant_species_unchanged():
    """The batched accelerator path applies the same restriction.

    The GPU kernels consume the flattened network's state-change lists, so the
    constant species has to be absent from them: otherwise the accelerator and
    the CPU pool would disagree about the same converted model, which is the
    defect this file pins, in the other direction.  Skipped where no
    accelerator is available.
    """

    backend = _gpu_backend()
    if backend is None:
        pytest.skip("no accelerator backend is available")

    model, network = _network(CONSTANT_REACTANT)
    result = _cpp.simulate_batch_ssa_gpu(
        model,
        network,
        batch_size=BATCH,
        t_end=10.0,
        n_steps=10,
        t_start=0.0,
        base_seed=SEED,
        max_sim_steps=0,
        backend=backend,
    )
    final = np.asarray(result["final_species"], dtype=np.int64)
    assert np.all(
        final[:, 0] == 100
    ), "the batched GPU path changed a constant species on some trajectories"

    times = np.asarray(result["time"], dtype=float)
    deterministic = _deterministic(CONSTANT_REACTANT, times)
    mean = np.asarray(result["observable_means"]["nB"], dtype=float)
    sd = np.asarray(result["observable_stds"]["nB"], dtype=float)
    # The GPU accumulates the ensemble in float32, so the band carries the
    # float32 representation error of the reported mean.
    reference = deterministic["nB"]
    standard_error = sd / math.sqrt(BATCH)
    tolerance = 1.19e-7 * np.maximum(np.abs(mean), np.abs(reference))
    assert np.all(np.abs(mean - reference) <= K_SIGMA * standard_error + tolerance)


def test_a_constant_reactant_keeps_its_amount_in_the_direct_ssa():
    """The direct method must not consume a constant species.

    The state update is the whole difference between the two readings, so this
    is an exact assertion on the recorded samples, not a statistical one: on
    the unfixed engine ``nA`` falls from 100 to 0 over the run.
    """

    model, network = _network(CONSTANT_REACTANT)
    result = _cpp.simulate_ssa(
        model,
        network,
        t_end=10.0,
        n_steps=10,
        t_start=0.0,
        seed=SEED,
    )
    observed = np.asarray(result["observables"]["nA"], dtype=float)
    assert observed.size > 1
    assert np.all(
        observed == 100.0
    ), f"the direct SSA changed a constant species: {observed}"


def test_a_constant_product_keeps_its_amount_in_the_direct_ssa():
    """The direct method must not produce into a constant species."""

    model, network = _network(CONSTANT_PRODUCT)
    result = _cpp.simulate_ssa(
        model,
        network,
        t_end=10.0,
        n_steps=10,
        t_start=0.0,
        seed=SEED,
    )
    observed = np.asarray(result["observables"]["nB"], dtype=float)
    assert observed.size > 1
    assert np.all(
        observed == 0.0
    ), f"the direct SSA produced into a constant species: {observed}"


def test_the_batch_pool_keeps_a_constant_species_unchanged():
    """Every trajectory of the batched pool keeps the constant species.

    ``final_species`` carries the final state of every trajectory, so this is
    an exact per-trajectory statement: on the unfixed engine the constant
    species ends at 0 on every trajectory that fired the reaction.
    """

    for bngl, index, initial in (
        (CONSTANT_REACTANT, 0, 100),
        (CONSTANT_PRODUCT, 1, 0),
    ):
        result = _batch(bngl)
        final = np.asarray(result["final_species"], dtype=np.int64)
        assert final.shape[1] == 2
        assert np.all(
            final[:, index] == initial
        ), "the batched SSA changed a constant species on some trajectories"


@pytest.mark.parametrize(
    "bngl,constant",
    [(CONSTANT_REACTANT, "nA"), (CONSTANT_PRODUCT, "nB")],
)
def test_the_stochastic_reading_agrees_with_the_deterministic_reading(bngl, constant):
    """The campaign's form: the ensemble mean tracks the CVODE trace.

    A test that only exercised the ODE path would pass on the broken engine,
    so the comparison is between the batched stochastic ensemble and the
    model's own deterministic reading, at every time point.
    """

    result = _batch(bngl)
    times = np.asarray(result["time"], dtype=float)
    deterministic = _deterministic(bngl, times)
    for name in result["observable_names"]:
        mean = np.asarray(result["observable_means"][name], dtype=float)
        sd = np.asarray(result["observable_stds"][name], dtype=float)
        _assert_agrees(mean, sd, deterministic[name], BATCH)
    # The constant species has no spread at all: it never moved.
    spread = np.asarray(result["observable_stds"][constant], dtype=float)
    assert np.all(spread == 0.0)


def test_the_converted_boundary_species_agrees_with_its_deterministic_reading(tmp_path):
    """End to end: an SBML boundary species, converted, then simulated.

    This is the shape the sweep reported (``semantic/01537`` and its
    companions): a boundary species that a reaction consumes.  The Atomizer
    marks the species constant, and the converted model must then read the
    same in both engines.
    """

    from bionetgen.atomizer.modern import Atomizer

    source = tmp_path / "boundary.xml"
    source.write_text(SBML_BOUNDARY_SPECIES, encoding="utf-8")
    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(
        SBML_BOUNDARY_SPECIES, source_path=source
    )
    assert atomized.success, atomized.error

    model = _cpp.parse_string(atomized.bngl)
    network = _cpp.generate_network(model, max_iter=100)
    result = _cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=BATCH,
        t_end=10.0,
        n_steps=10,
        t_start=0.0,
        base_seed=SEED,
        max_sim_steps=0,
        threads=1,
    )
    times = np.asarray(result["time"], dtype=float)

    from bionetgen import BioNetGenModel

    trace = BioNetGenModel(model).simulate(
        method="ode",
        t_start=0.0,
        t_end=10.0,
        n_steps=0,
        sample_times=[float(value) for value in times],
        rtol=1e-9,
        atol=1e-14,
    )
    deterministic = {
        name: np.asarray(values, dtype=float)
        for name, values in trace.observables.items()
    }

    boundary = "S1_amt"
    assert boundary in result["observable_names"]
    # The published reference keeps the boundary species at 2 for the whole
    # run; the deterministic reading keeps it there too.
    assert np.allclose(deterministic[boundary], 2.0, rtol=0.0, atol=1e-9)
    # The stochastic reading must agree with it, to Monte-Carlo error.
    _assert_agrees(
        np.asarray(result["observable_means"][boundary], dtype=float),
        np.asarray(result["observable_stds"][boundary], dtype=float),
        deterministic[boundary],
        BATCH,
    )
    # The species the reaction produces grows at the reaction's rate, so the
    # stochastic reading must track the deterministic one there as well.
    produced = "S2_amt"
    assert produced in result["observable_names"]
    _assert_agrees(
        np.asarray(result["observable_means"][produced], dtype=float),
        np.asarray(result["observable_stds"][produced], dtype=float),
        deterministic[produced],
        BATCH,
    )
