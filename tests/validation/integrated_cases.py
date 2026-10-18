"""Generated SBML cases and independent trajectories for integration checks.

Each family has a deterministic six-row pairwise sample for pull requests and
all sixteen combinations for the scheduled/full campaign. The ``reverse``
factor preserves the original decay species-order permutation; in the
reversible family it selects which side receives the initial amount.
"""

from __future__ import annotations

import itertools

import numpy as np

TIMES = np.linspace(0, 2, 11)
RATE = 0.4
REVERSE_RATE = 0.2
PAIRWISE_INDICES = (0, 3, 5, 10, 12, 15)
PERTURBATION_PR_INDICES = (0, 5, 12)
FAMILIES = ("decay", "reversible", "dimerization")


def source_law_cases(full=False):
    """Small count-law models covering rate order, units, volume and basis.

    Physical cases record the SBML-style units represented by the descriptor;
    their generated BNGL coefficient is explicitly converted to the standard
    count convention. Bare cases retain the supplied BNGL count coefficient.
    """
    volumes = (1, 3) if full else (3,)
    cases = []
    axes = (
        ("zero-order", "physical_source_law", "amount"),
        ("zero-order", "bngl_count", "amount"),
        ("first-order", "physical_source_law", "amount"),
        ("first-order", "bngl_count", "concentration"),
        ("second-order", "physical_source_law", "amount"),
        ("second-order", "bngl_count", "amount"),
    )
    for law, convention, basis in axes:
        for volume in volumes:
            initial = (
                0 if law == "zero-order" else (12 if law == "second-order" else 40)
            )
            case = dict(
                id=f"quantity-{law}-{convention}-{basis}-v{volume}",
                law=law,
                family=law,
                rate_convention=convention,
                quantity_basis=basis,
                initial=initial,
                initial_coordinate_value=(
                    initial / volume if basis == "concentration" else initial
                ),
                rate=0.4,
                volume=volume,
                times=tuple(float(t) for t in TIMES),
                observable="A",
                source_units=(
                    {
                        "zero-order": "item/second",
                        "first-order": "1/second",
                        "second-order": "litre/item/second",
                    }[law]
                    if convention == "physical_source_law"
                    else "unannotated BNGL count-rate convention"
                ),
            )
            # A bounded pairwise source-law slice with one representative per
            # molecularity and convention; scheduled/full mode adds V=1.
            cases.append(case)
    return cases


def source_law_bngl(case):
    """Return a parameter-backed BNGL fixture for a source-law descriptor."""
    law = case["law"]
    if case["rate_convention"] == "physical_source_law":
        rate = {
            "zero-order": "k/V",
            "first-order": "k",
            "second-order": "2*k",
        }[law]
    else:
        rate = "k"
    if law == "zero-order":
        reactants, products = "0", "@cell:A()"
    elif law == "first-order":
        reactants, products = "@cell:A()", "@cell:B()"
    elif law == "second-order":
        reactants, products = "@cell:A() + @cell:A()", "@cell:D()"
    else:
        raise ValueError(f"unknown source-law family: {law!r}")
    initial_b = case["initial"] if case.get("initial_side") == "B" else 0
    initial_a = case["initial"] - initial_b
    source_coordinate_comment = (
        f"# SBML initialConcentration={case['initial_coordinate_value']:.17g}; "
        f"amount count={case['initial']} after multiplying by V\n"
        if case["quantity_basis"] == "concentration"
        else ""
    )
    return f"""# Source-law basis: {case['rate_convention']} ({case['source_units']}); physical rates are prelowered to BNGL count units.
{source_coordinate_comment}begin model
begin parameters
  k {case['rate']:.17g}
  V {case['volume']:.17g}
end parameters
begin compartments
  cell 3 V
end compartments
begin molecule types
  A()
  B()
  D()
end molecule types
begin seed species
  @cell:A() {initial_a}
  @cell:B() {initial_b}
  @cell:D() 0
end seed species
begin observables
  Molecules A @cell:A()
end observables
begin reaction rules
  source: {reactants} -> {products} {rate}
end reaction rules
end model
"""


def generated_cases(full=False):
    """Return baseline cases plus bounded semantic source perturbations."""
    cases = []
    decay_bases = {}
    for family in FAMILIES:
        for index, (volume, initial, reverse, atomize) in enumerate(
            itertools.product((1, 3), (20, 80), (False, True), (False, True))
        ):
            if not full and index not in PAIRWISE_INDICES:
                continue
            legacy_id = f"v{volume}-n{initial}-r{int(reverse)}-a{int(atomize)}"
            case = dict(
                id=(legacy_id if family == "decay" else f"{family}-{legacy_id}"),
                family=family,
                volume=volume,
                initial=initial,
                reverse=reverse,
                atomize=atomize,
                exact_nf=family != "reversible",
            )
            if family == "decay":
                decay_bases[index] = case
            if family == "reversible":
                # Atomizer may emit the forward and reverse channels as two
                # rules. Seeded paths then depend on rule construction order.
                case["nf_comparison"] = (
                    "Use equal-seed comparison only when both routes preserve "
                    "reaction ordering; otherwise compare ensemble means and "
                    "the conserved A+B total."
                )
            else:
                case["nf_comparison"] = "Equal-seed native/embedded NFsim comparison."
            cases.append(case)
    perturbation_indices = PAIRWISE_INDICES if full else PERTURBATION_PR_INDICES
    for transform in ("function-shadowing", "concentration-coordinate"):
        for index in perturbation_indices:
            base = decay_bases[index]
            cases.append(
                dict(
                    base,
                    id=f"{transform}-{base['id']}",
                    base_case_id=base["id"],
                    transform=transform,
                    quantity_basis=(
                        "initialConcentration=N0/V; kinetic law k*cell*A"
                        if transform == "concentration-coordinate"
                        else "item amount; function formal shadows global rate"
                    ),
                )
            )
    # Keep one distinct, deliberately misleading global-rate declaration in
    # the PR sample. The local function formal still binds k; a reference that
    # accidentally resolves the global `rate` must therefore diverge sharply.
    shadow = dict(decay_bases[0])
    shadow.update(
        id=f"shadow-global-decoy-{decay_bases[0]['id']}",
        base_case_id=decay_bases[0]["id"],
        transform="shadow-global-decoy",
        shadow_global_rate=13.0,
        quantity_basis="amount; function formal rate shadows adversarial global rate=13",
    )
    cases.append(shadow)
    return cases


def _species(name, initial):
    return (
        f'<species id="{name}" compartment="cell" initialAmount="{initial}" '
        'substanceUnits="item" hasOnlySubstanceUnits="true" '
        'boundaryCondition="false" constant="false"/>'
    )


def _concentration_species(name, initial, volume):
    concentration = initial / volume
    return (
        f'<species id="{name}" compartment="cell" '
        f'initialConcentration="{concentration:.17g}" '
        'substanceUnits="item" hasOnlySubstanceUnits="false" '
        'boundaryCondition="false" constant="false"/>'
    )


def _math(expression):
    return '<math xmlns="http://www.w3.org/1998/Math/MathML">' f"{expression}</math>"


def sbml_text(case):
    """Return a valid SBML L3V2 source model for a generated case."""
    family = case["family"]
    if family == "decay":
        initial_states = (("A", case["initial"]), ("B", 0))
        if case["reverse"]:
            initial_states = tuple(reversed(initial_states))
        if case.get("transform") == "concentration-coordinate":
            species = "".join(
                _concentration_species(name, amount, case["volume"])
                for name, amount in initial_states
            )
        else:
            species = "".join(_species(name, amount) for name, amount in initial_states)
        parameter_units = (
            '<parameter id="k" value="0.4" units="per_second" constant="true"/>'
        )
        if case.get("transform") in ("function-shadowing", "shadow-global-decoy"):
            parameter_units += (
                f'<parameter id="rate" value="{case.get("shadow_global_rate", 7)}" '
                'units="per_second" constant="true"/>'
            )
            function_definitions = """<listOfFunctionDefinitions>
<functionDefinition id="rateLaw"><math xmlns="http://www.w3.org/1998/Math/MathML">
<lambda><bvar><ci>rate</ci></bvar><bvar><ci>amount</ci></bvar>
<apply><times/><ci>rate</ci><ci>amount</ci></apply></lambda>
</math></functionDefinition></listOfFunctionDefinitions>"""
            rate_expression = "<apply><ci>rateLaw</ci><ci>k</ci><ci>A</ci></apply>"
        elif case.get("transform") == "concentration-coordinate":
            function_definitions = ""
            rate_expression = "<apply><times/><ci>k</ci><ci>cell</ci><ci>A</ci></apply>"
        else:
            function_definitions = ""
            rate_expression = "<apply><times/><ci>k</ci><ci>A</ci></apply>"
        reactions = f"""<reaction id="convert" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
<kineticLaw>{_math(rate_expression)}</kineticLaw>
</reaction>"""
    elif family == "reversible":
        a_initial, b_initial = (
            (0, case["initial"]) if case["reverse"] else (case["initial"], 0)
        )
        species = _species("A", a_initial) + _species("B", b_initial)
        parameter_units = (
            '<parameter id="k" value="0.4" units="per_second" constant="true"/>'
            '<parameter id="kr" value="0.2" units="per_second" constant="true"/>'
        )
        reactions = f"""<reaction id="forward" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
<kineticLaw>{_math('<apply><times/><ci>k</ci><ci>A</ci></apply>')}</kineticLaw>
</reaction>
<reaction id="backward" reversible="false">
<listOfReactants><speciesReference species="B" stoichiometry="1" constant="true"/></listOfReactants>
<listOfProducts><speciesReference species="A" stoichiometry="1" constant="true"/></listOfProducts>
<kineticLaw>{_math('<apply><times/><ci>kr</ci><ci>B</ci></apply>')}</kineticLaw>
</reaction>"""
    elif family == "dimerization":
        amounts = (("A", case["initial"]), ("D", 0))
        if case["reverse"]:
            amounts = tuple(reversed(amounts))
        species = "".join(_species(name, amount) for name, amount in amounts)
        parameter_units = '<parameter id="k" value="0.4" units="litre_per_item_second" constant="true"/>'
        # k [L/(item s)] * A^2 [item^2] / V [L] gives extent/time [item/s].
        reactions = f"""<reaction id="dimerize" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="2" constant="true"/></listOfReactants>
<listOfProducts><speciesReference species="D" stoichiometry="1" constant="true"/></listOfProducts>
<kineticLaw>{_math('<apply><divide/><apply><times/><ci>k</ci><ci>A</ci><ci>A</ci></apply><ci>cell</ci></apply>')}</kineticLaw>
</reaction>"""
    else:
        raise ValueError(f"unknown generated model family: {family!r}")
    if family != "decay":
        function_definitions = ""

    definitions = """<unitDefinition id="per_second"><listOfUnits>
<unit kind="second" exponent="-1" scale="0" multiplier="1"/>
</listOfUnits></unitDefinition>
<unitDefinition id="litre_per_item_second"><listOfUnits>
<unit kind="litre" exponent="1" scale="0" multiplier="1"/>
<unit kind="item" exponent="-1" scale="0" multiplier="1"/>
<unit kind="second" exponent="-1" scale="0" multiplier="1"/>
</listOfUnits></unitDefinition>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="{family}" timeUnits="second" substanceUnits="item" extentUnits="item">
{function_definitions}
<listOfUnitDefinitions>{definitions}</listOfUnitDefinitions>
<listOfCompartments><compartment id="cell" spatialDimensions="3" units="litre" size="{case['volume']}" constant="true"/></listOfCompartments>
<listOfSpecies>{species}</listOfSpecies>
<listOfParameters>{parameter_units}</listOfParameters>
<listOfReactions>{reactions}</listOfReactions>
</model></sbml>
"""


def expected_trajectory(case):
    """Return columns (including time) and exact amount trajectories.

    All species use item amounts and ``hasOnlySubstanceUnits=true``, so both
    generated Atomizer observable views have the same item values. The dimer
    rate law explicitly divides by compartment volume; its amount dynamics
    therefore vary with volume while first-order rates do not.
    """
    times = TIMES
    family = case["family"]
    initial = case["initial"]
    if family == "decay":
        a0 = initial
        a = a0 * np.exp(-RATE * times)
        b = initial - a
        names = ("A", "B")
    elif family == "reversible":
        a0 = 0 if case["reverse"] else initial
        b0 = initial - a0
        total = initial
        equilibrium_a = total * REVERSE_RATE / (RATE + REVERSE_RATE)
        a = equilibrium_a + (a0 - equilibrium_a) * np.exp(
            -(RATE + REVERSE_RATE) * times
        )
        b = total - a
        names = ("A", "B")
    elif family == "dimerization":
        # The reverse dimension permutes species declarations only. The
        # initial amount remains on A as in the legacy generated family.
        a0, d0 = initial, 0
        a = a0 / (1 + 2 * RATE * a0 * times / case["volume"])
        d = d0 + (a0 - a) / 2
        b = None
        names = ("A", "D")
    else:
        raise ValueError(f"unknown generated model family: {family!r}")

    values = [times]
    columns = ["time"]
    for name, trajectory in zip(names, (a, b if family != "dimerization" else d)):
        values.extend((trajectory, trajectory))
        columns.extend((f"{name}_amt", name))
    return np.column_stack(values), columns


def expected_source_species(case):
    """Return source-coordinate trajectories for species named by the model."""
    values, columns = expected_trajectory(case)
    species = [name for name in columns if name != "time" and not name.endswith("_amt")]
    factor = (
        case["volume"] if case.get("transform") == "concentration-coordinate" else 1
    )
    return (
        np.column_stack([values[:, columns.index(name)] / factor for name in species]),
        species,
    )


def reuse_bngl(case, *, rate=RATE):
    """Native source control with named rate, seed and volume dependencies.

    This companion is deliberately separate from Atomizer's legal static
    folding. Fresh references replace source literals rather than calling the
    same set_parameter path as the instance under test.
    """
    family = case["family"]
    a_initial, b_initial = "N", "0"
    if family == "reversible" and case["reverse"]:
        a_initial, b_initial = "0", "N"
    second = "D" if family == "dimerization" else "B"
    reactants = "@cell:A() + @cell:A()" if family == "dimerization" else "@cell:A()"
    rate_expression = "2*k" if family == "dimerization" else "k"
    backward = (
        "\n  backward: @cell:B() -> @cell:A() kr" if family == "reversible" else ""
    )
    return f"""begin model
begin parameters
  k {rate:.17g}
  kr {REVERSE_RATE:.17g}
  N {case['initial']}
  V {case['volume']}
end parameters
begin compartments
  cell 3 V
end compartments
begin molecule types
  A()
  {second}()
end molecule types
begin seed species
  @cell:A() {a_initial}
  @cell:{second}() {b_initial}
end seed species
begin observables
  Molecules A @cell:A()
  Molecules {second} @cell:{second}()
end observables
begin functions
  rate() = {rate_expression}
end functions
begin reaction rules
  forward: {reactants} -> @cell:{second}() rate(){backward}
end reaction rules
end model
"""
