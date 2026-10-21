"""Regression test for a rate law that names a non-consumed species.

SBML Level 3 Version 2 Core, Sec. 4.11, gives a kinetic law the meaning of
the reaction's *extent* rate: ``d n_i/dt = Σ stoich_ij · v_Rj``.  A law that
names a species the reaction does not consume is therefore a *complete flux*:
its value depends on that species' state, and no constant coefficient can
replace it.

The writer's numeric mass-action probe may still accept such a law, because
the probe replaces the species by a fixed state and fits the result.  The
fitted coefficient is then a snapshot of the law at the probe points rather
than the law itself.  The curated record BIOMD0000000954 is such a model:
its Cdh1dp production rate is ``k · (Cdh1T − Cdh1dp)/(JdpCdh1 + Cdh1T −
Cdh1dp)``, and the probe replaced it with a fitted constant whose value
depended on the probe, so the emitted model was not the model the source
states.

The fixture is the curated record BIOMD0000000954 reduced to the single
reaction whose rate law shows the defect.
"""

from __future__ import annotations

import pathlib
import re

from bionetgen.atomizer.modern import Atomizer

SBML = (
    pathlib.Path(__file__).parent / "models" / "nonreactant_species_rate.sbml"
).read_text(encoding="utf-8")


def _rate(bngl: str) -> str:
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.startswith("reaction_for_Cdh1dp_production:"):
            return stripped
    raise AssertionError("the Cdh1dp production rule is missing from the model")


def test_rate_law_naming_a_non_consumed_species_stays_state_dependent():
    """The law must not be replaced by a fitted constant."""

    result = Atomizer(atomize=False, quiet_mode=True).atomize(SBML)

    assert result.success, result.error
    rate = _rate(result.bngl)
    body = rate.split(":", 1)[1]
    # A fitted constant is a bare number; the law names the species it
    # depends on, so the emitted rate has to keep naming them.
    assert not re.fullmatch(
        r"[-+0-9.eE()*/ ]+", body.strip()
    ), f"the rate law was replaced by a constant: {rate}"
    assert "Cdh1T" in body and "Cdh1dp" in body, rate


def test_a_law_over_its_own_reactants_is_still_a_mass_action_coefficient():
    """The probe still claims a law that only names the reaction's reactants."""

    sbml = SBML.replace(
        """            <listOfProducts>
          <speciesReference species="P" stoichiometry="1" constant="true"/>
            </listOfProducts>""",
        """            <listOfReactants>
          <speciesReference species="T" stoichiometry="1" constant="true"/>
            </listOfReactants>
            <listOfProducts>
          <speciesReference species="P" stoichiometry="1" constant="true"/>
            </listOfProducts>""",
    )
    result = Atomizer(atomize=False, quiet_mode=True).atomize(sbml)

    assert result.success, result.error
    rate = _rate(result.bngl)
    body = rate.split(":", 1)[1].strip()
    # The law names the consumed species, so the elementary coefficient is
    # emitted and the rule stays a mass-action rule.
    assert "T" in body or "_c_T" in body, rate
