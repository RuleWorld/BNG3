"""Regression tests for a rate law written on a concentration-valued species.

SBML Level 3 Version 2 Core, Sec. 4.11 ("Reactions"), states that the numeric
value of a kinetic law is the rate of change of the reaction's *extent* and
that a species' amount changes by ``stoichiometry * extent rate``.  Sec. 4.6
("Species") states that a species' *value* in an expression is its amount when
it has ``hasOnlySubstanceUnits="true"`` and its concentration
(``amount / compartmentSize``) otherwise.

A law on a concentration-valued species therefore states an extent rate in
substance/time that is ``1/V`` of the amount-based reading of the same
expression, so the BNGL constant has to carry the compartment volume to say
the same thing.  The rule the lowering implements is a single one:

    for a law with ``m`` reactant factors of which ``a`` are amount-valued,
    the BNGL constant is ``k * V**(a - 1)``

which composes with the amount-based correction of PR #319 (the case ``a = m``)
instead of double-counting it, and with a law that names the compartment's
size (one more power of ``V`` when it multiplies by it, one fewer when it
divides by it).

The official SBML Test Suite case ``stochastic/00011`` is the reference: its
mean series is ``100 * exp(-0.005 * t)``, the analytic solution of the
birth-death process whose per-capita birth and death rates are ``Lambda/V``
and ``Mu/V``.
"""

from __future__ import annotations

import math

import pytest

from bionetgen.atomizer.modern import Atomizer


def _species(species_id: str, amount: float, substance_units: bool) -> str:
    return (
        f'<species id="{species_id}" compartment="C" initialAmount="{amount}" '
        f'hasOnlySubstanceUnits="{str(substance_units).lower()}" '
        'boundaryCondition="false" constant="false"/>'
    )


def _model(
    *,
    volume: str,
    law: str,
    species: str,
    reactants: str,
    products: str = '<speciesReference species="P" stoichiometry="1" constant="true"/>',
    parameters: str = '<parameter id="k1" value="1" constant="true"/>',
) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="concentration_rate_law">
        <listOfCompartments>
          <compartment id="C" spatialDimensions="3" size="{volume}" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>{species}</listOfSpecies>
        <listOfParameters>{parameters}</listOfParameters>
        <listOfReactions>
          <reaction id="J0" reversible="false">
            <listOfReactants>{reactants}</listOfReactants>
            <listOfProducts>{products}</listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">{law}</math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def _rate_law(bngl: str, label: str = "J0:") -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            return stripped
    raise AssertionError(f"no reaction rule {label!r} emitted")


def _birth_death_00011() -> str:
    """The official ``stochastic/00011`` model.

    ``X`` carries ``hasOnlySubstanceUnits="false"``, so the laws ``Lambda * X``
    and ``Mu * X`` are concentration laws: the extent rates are
    ``Lambda * X / 2`` and ``Mu * X / 2``.
    """

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="BirthDeath11" name="Birth-death model (001), variant 11"
             substanceUnits="item" timeUnits="second" volumeUnits="litre">
        <listOfCompartments>
          <compartment id="Cell" spatialDimensions="3" size="2" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="X" compartment="Cell" initialAmount="100"
                   hasOnlySubstanceUnits="false" boundaryCondition="false"
                   constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Lambda" value="0.1" constant="true"/>
          <parameter id="Mu" value="0.11" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="Birth" reversible="false">
            <listOfReactants>
              <speciesReference species="X" stoichiometry="1" constant="false"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="X" stoichiometry="2" constant="false"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>Lambda</ci><ci>X</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="Death" reversible="false">
            <listOfReactants>
              <speciesReference species="X" stoichiometry="1" constant="false"/>
            </listOfReactants>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>Mu</ci><ci>X</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
      </model>
    </sbml>"""


def test_concentration_valued_rate_law_carries_the_compartment_volume():
    """The reproducer of the finding: the constant must be divided by ``V``.

    The law ``Lambda * X`` is a concentration law, so the extent rate is
    ``Lambda * X / 2`` and the BNGL constant is ``Lambda / 2``.  Before the
    fix the rule kept the unscaled ``Lambda``, which made the amount decay
    like ``Lambda - Mu`` instead of ``(Lambda - Mu) / 2``.
    """

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_birth_death_00011())

    assert result.success, result.error
    birth = _rate_law(result.bngl, "Birth:")
    death = _rate_law(result.bngl, "Death:")
    assert "(0.1) * (__compartment_Cell__)**-1" in birth, birth
    assert "(0.11) * (__compartment_Cell__)**-1" in death, death


def test_concentration_valued_rate_law_reproduces_the_official_reference():
    """The official mean series of ``stochastic/00011``.

    The suite's DSMTS reference reports ``X-mean`` as ``100 * exp(-0.005 t)``
    (``99.50125`` at ``t = 1``); the expectation of the birth-death process
    the model states is that series, and the ODE trajectory of the lowered
    model is exactly it.
    """

    import numpy as np

    from bionetgen import BioNetGenModel
    import bionetgen._bionetgen_cpp as cpp

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_birth_death_00011())
    assert result.success, result.error

    simulation = BioNetGenModel(cpp.parse_string(result.bngl)).simulate(
        method="ode",
        t_start=0,
        t_end=3,
        n_steps=0,
        sample_times=[0.0, 1.0, 2.0, 3.0],
        rtol=1e-10,
        atol=1e-14,
    )
    amounts = [float(value) for value in simulation.observables["X_amt"]]

    # The official reference's own numbers.
    official = {0.0: 100.0, 1.0: 99.50125, 2.0: 99.00498, 3.0: 98.5112}
    for time, amount in zip(simulation.time, amounts):
        expected = official[float(time)]
        assert math.isclose(amount, expected, rel_tol=1e-6), (time, amount, expected)


def test_concentration_valued_rate_law_ensemble_mean_matches_the_reference():
    """The stochastic reading of the same defect.

    The ensemble mean of the lowered model must be the official reference
    mean.  The reference standard deviation at ``t = 1`` is ``3.228244105``,
    so the standard error of the mean over ``n`` runs is ``3.2282 / sqrt(n)``;
    the amount-based reading would be off by ``0.496``, which the tolerance
    below separates from the reference.
    """

    import numpy as np

    import bionetgen._bionetgen_cpp as cpp

    result = Atomizer(atomize=False, quiet_mode=True).atomize(_birth_death_00011())
    assert result.success, result.error

    model = cpp.parse_string(result.bngl)
    network = cpp.generate_network(model, max_iter=100)
    runs = 20000
    metrics = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=runs,
        t_start=0.0,
        t_end=1.0,
        n_steps=1,
        base_seed=1000000,
        threads=1,
        max_sim_steps=0,
    )
    times = np.asarray(metrics["time"], dtype=float)
    means = np.asarray(metrics["observable_means"]["X_amt"], dtype=float)
    stds = np.asarray(metrics["observable_stds"]["X_amt"], dtype=float)

    index = int(np.argmin(np.abs(times - 1.0)))
    assert math.isclose(float(times[index]), 1.0, abs_tol=1e-9)
    # The official reference mean and standard deviation at t = 1.
    assert math.isclose(float(means[index]), 99.50125, rel_tol=5e-3)
    assert math.isclose(float(stds[index]), 3.228244105, rel_tol=5e-2)


@pytest.mark.parametrize(
    ("label", "volume", "law", "species", "reactants", "expected"),
    [
        # An amount-valued unimolecular law needs no volume factor: ``a = 1``.
        (
            "amount_unimolecular",
            "10",
            "<apply><times/><ci>k1</ci><ci>S1</ci></apply>",
            _species("S1", 1, True) + _species("P", 0, True),
            '<speciesReference species="S1" stoichiometry="1" constant="true"/>',
            "1",
        ),
        # A concentration-valued unimolecular law needs ``V**-1``: ``a = 0``.
        (
            "concentration_unimolecular",
            "10",
            "<apply><times/><ci>k1</ci><ci>S1</ci></apply>",
            _species("S1", 1, False) + _species("P", 0, False),
            '<speciesReference species="S1" stoichiometry="1" constant="true"/>',
            "(1) * (__compartment_C__)**-1",
        ),
        # Two amount-valued factors need ``V**(2-1)``: ``a = 2``.
        (
            "amount_bimolecular",
            "10",
            "<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>",
            _species("S1", 1, True) + _species("S2", 2, True) + _species("P", 0, True),
            (
                '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
                '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
            ),
            "(1) * (__compartment_C__)**1",
        ),
        # Two concentration-valued factors need ``V**(0-1)``: ``a = 0``.
        (
            "concentration_bimolecular",
            "10",
            "<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>",
            _species("S1", 1, False)
            + _species("S2", 2, False)
            + _species("P", 0, False),
            (
                '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
                '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
            ),
            "(1) * (__compartment_C__)**-1",
        ),
        # One amount-valued and one concentration-valued factor need ``V**0``.
        (
            "mixed_bimolecular",
            "10",
            "<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>",
            _species("S1", 1, True) + _species("S2", 2, False) + _species("P", 0, True),
            (
                '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
                '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
            ),
            "1",
        ),
        # A law that multiplies by the compartment states the opposite volume
        # dependence of one that divides by it: one more power of ``V``.
        (
            "amount_multiplicative_compartment",
            "10",
            "<apply><times/><ci>C</ci><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>",
            _species("S1", 1, True) + _species("S2", 2, True) + _species("P", 0, True),
            (
                '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
                '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
            ),
            "(1) * (__compartment_C__)**2",
        ),
        # A law that divides by the compartment carries the ``1/V`` the
        # amount-based reading needs: one fewer power of ``V``.
        (
            "amount_divisive_compartment",
            "10",
            (
                "<apply><divide/>"
                "<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>"
                "<ci>C</ci></apply>"
            ),
            _species("S1", 1, True) + _species("S2", 2, True) + _species("P", 0, True),
            (
                '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
                '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
            ),
            "1",
        ),
    ],
)
def test_rate_law_volume_exponent_follows_the_amount_operands(
    label, volume, law, species, reactants, expected
):
    """The lowering states ``k * V**(a - 1)`` for ``a`` amount-valued operands."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(
        _model(
            volume=volume,
            law=law,
            species=species,
            reactants=reactants,
        )
    )

    assert result.success, result.error
    rule = _rate_law(result.bngl)
    assert rule.endswith(expected), (label, rule)


def test_mixed_amount_and_concentration_law_matches_libroadrunner():
    """The mixed law, checked against the independent oracle.

    A law that names one amount-valued and one concentration-valued species
    states the extent rate ``k * n1 * n2 / V``, so the BNGL constant is
    ``k`` itself: the concentration reading and BNGL's own volume factor
    cancel.
    """

    import numpy as np

    roadrunner = pytest.importorskip("roadrunner")

    from bionetgen import BioNetGenModel
    import bionetgen._bionetgen_cpp as cpp

    sbml = _model(
        volume="10",
        law="<apply><times/><ci>k1</ci><ci>S1</ci><ci>S2</ci></apply>",
        species=_species("S1", 1, True)
        + _species("S2", 2, False)
        + _species("P", 0, True),
        reactants=(
            '<speciesReference species="S1" stoichiometry="1" constant="true"/>'
            '<speciesReference species="S2" stoichiometry="1" constant="true"/>'
        ),
    )
    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)
    assert result.success, result.error

    times = list(np.linspace(0.0, 2.0, 5))
    reference = roadrunner.RoadRunner(sbml)
    reference.integrator.setValue("relative_tolerance", 1e-10)
    reference.integrator.setValue("absolute_tolerance", 1e-14)
    reference.timeCourseSelections = ["time", "S1"]
    values = np.asarray(reference.simulate(times=times), dtype=float)

    simulation = BioNetGenModel(cpp.parse_string(result.bngl)).simulate(
        method="ode",
        t_start=0,
        t_end=2,
        n_steps=0,
        sample_times=times,
        rtol=1e-10,
        atol=1e-14,
    )
    amounts = np.asarray(simulation.observables["S1_amt"], dtype=float)

    for index, time in enumerate(times):
        expected = float(values[index, 1])
        assert math.isclose(float(amounts[index]), expected, rel_tol=1e-6), (
            time,
            amounts[index],
            expected,
        )


def _concentration_law_with_a_scheduled_action() -> str:
    """A concentration-valued rate law *and* a concentration-valued action.

    The reaction's law ``Lambda * X`` is a concentration law, and the event
    assigns the species' *concentration* (``X = 50``).  Both state the
    compartment's volume once: the rate law divides the extent rate by the
    volume, and the assignment multiplies the concentration by it to reach the
    species' amount.
    """

    return """<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core">
      <model id="compose" substanceUnits="item" timeUnits="second" volumeUnits="litre">
        <listOfCompartments>
          <compartment id="Cell" spatialDimensions="3" size="2" constant="true"/>
        </listOfCompartments>
        <listOfSpecies>
          <species id="X" compartment="Cell" initialAmount="100"
                   hasOnlySubstanceUnits="false" boundaryCondition="false"
                   constant="false"/>
        </listOfSpecies>
        <listOfParameters>
          <parameter id="Lambda" value="0.1" constant="true"/>
          <parameter id="Mu" value="0.11" constant="true"/>
        </listOfParameters>
        <listOfReactions>
          <reaction id="Birth" reversible="false">
            <listOfReactants>
              <speciesReference species="X" stoichiometry="1" constant="false"/>
            </listOfReactants>
            <listOfProducts>
              <speciesReference species="X" stoichiometry="2" constant="false"/>
            </listOfProducts>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>Lambda</ci><ci>X</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
          <reaction id="Death" reversible="false">
            <listOfReactants>
              <speciesReference species="X" stoichiometry="1" constant="false"/>
            </listOfReactants>
            <kineticLaw>
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply><times/><ci>Mu</ci><ci>X</ci></apply>
              </math>
            </kineticLaw>
          </reaction>
        </listOfReactions>
        <listOfEvents>
          <event id="Set" useValuesFromTriggerTime="true">
            <trigger initialValue="false" persistent="true">
              <math xmlns="http://www.w3.org/1998/Math/MathML">
                <apply>
                  <gt/>
                  <csymbol encoding="text"
                    definitionURL="http://www.sbml.org/sbml/symbols/time"> time </csymbol>
                  <cn>1</cn>
                </apply>
              </math>
            </trigger>
            <listOfEventAssignments>
              <eventAssignment variable="X">
                <math xmlns="www.w3.org/1998/Math/MathML"><cn>50</cn></math>
              </eventAssignment>
            </listOfEventAssignments>
          </event>
        </listOfEvents>
      </model>
    </sbml>"""


def test_concentration_law_and_concentration_action_each_use_the_volume_once():
    """The rate law and the action must not double-count the volume.

    The rate law is a concentration law, so the extent rate divides the
    species' amount by the compartment's volume.  The event assigns the
    species' concentration, and the species' amount is that concentration times
    the volume.  Each of the two states the volume exactly once.
    """

    result = Atomizer(atomize=False, quiet_mode=True, t_end=3.0, n_steps=30).atomize(
        _concentration_law_with_a_scheduled_action()
    )

    assert result.success, result.error
    birth = _rate_law(result.bngl, "Birth:")
    death = _rate_law(result.bngl, "Death:")
    # The rate law carries the volume once, as a divisor.
    assert "(0.1) * (__compartment_Cell__)**-1" in birth, birth
    assert "(0.11) * (__compartment_Cell__)**-1" in death, death

    # The action reaches the species' amount: the assigned concentration 50 in
    # a size-2 compartment is the amount 100.
    assignments = [
        line.strip()
        for line in result.bngl.splitlines()
        if line.strip().startswith("setConcentration(")
    ]
    assert len(assignments) == 1, result.bngl
    assert '"100"' in assignments[0], assignments[0]
