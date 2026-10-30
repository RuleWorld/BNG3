"""Independent SBML Core oracles for issue #161 kinetic edge cases.

New source-authored BNGL examples test three-body volume scaling,
heterodimerization with identically named binding sites, repeated-site
multiplicity, and zero-order synthesis/degradation. Reference fluxes are
specified here, independently of the candidate's Multi export.
"""

from pathlib import Path

import bionetgen
import libsbml
import numpy as np
import pytest
import roadrunner
from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer, SBMLParser

MATH_NS = 'xmlns="http://www.w3.org/1998/Math/MathML"'


def _core(volume, species, rate):
    """Explicit chemical-state Core source; never enumerated from Multi."""
    declarations = "\n".join(
        f'<species id="{name}" compartment="cell" initialAmount="{amount}" '
        'hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"/>'
        for name, amount in species.items()
    )
    reactions = "\n".join(
        f'<reaction id="r_{i}" reversible="false" fast="false">'
        + (
            "<listOfReactants>"
            + "".join(
                f'<speciesReference species="{name}" stoichiometry="{stoich}" constant="true"/>'
                for name, stoich in reactants.items()
            )
            + "</listOfReactants>"
            if reactants
            else ""
        )
        + (
            "<listOfProducts>"
            + "".join(
                f'<speciesReference species="{name}" stoichiometry="{stoich}" constant="true"/>'
                for name, stoich in products.items()
            )
            + "</listOfProducts>"
            if products
            else ""
        )
        + f"<kineticLaw><math {MATH_NS}>{math}</math></kineticLaw></reaction>"
        for i, (reactants, products, math) in enumerate(rate)
    )
    return (
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">'
        '<model id="independent_multi_rate_oracle"><listOfCompartments>'
        f'<compartment id="cell" size="{volume:g}" spatialDimensions="3" constant="true"/>'
        f"</listOfCompartments><listOfSpecies>{declarations}</listOfSpecies>"
        f'<listOfParameters><parameter id="k" value="0.02" constant="true"/>'
        f'<parameter id="d" value="0.1" constant="true"/>'
        f"</listOfParameters><listOfReactions>{reactions}</listOfReactions></model></sbml>"
    )


def _mul(*args):
    return "<apply><times/>" + "".join("<ci>" + x + "</ci>" for x in args) + "</apply>"


def _div(numerator, divisor):
    return f"<apply><divide/>{numerator}<ci>{divisor}</ci></apply>"


def _source(volume, molecule_types, initial, rules):
    def rule_line(rule):
        if len(rule) == 4:
            name, lhs, rhs, rate = rule
            arrow = "->"
        else:
            name, lhs, rhs, arrow, rate = rule
        return f"  {name}: {lhs} {arrow} {rhs} {rate}\n"

    return (
        "begin model\nbegin parameters\n  k 0.02\n  d 0.1\n"
        "end parameters\nbegin compartments\n  cell 3 "
        f"{volume:g}\nend compartments\nbegin molecule types\n"
        + "".join(f"  {mol}\n" for mol in molecule_types)
        + "end molecule types\nbegin seed species\n"
        + "".join(f"  @cell:{pattern} {amount}\n" for pattern, amount in initial)
        + "end seed species\nbegin reaction rules\n"
        + "".join(rule_line(rule) for rule in rules)
        + "end reaction rules\nend model\n"
    )


def _math_value(node, values):
    """Evaluate the small arithmetic subset used by generated mass-action laws."""
    if node.isNumber():
        return node.getReal()
    if node.isName():
        return values[node.getName()]
    children = [node.getChild(i) for i in range(node.getNumChildren())]
    operands = [_math_value(child, values) for child in children]
    if node.getType() == libsbml.AST_TIMES:
        return np.prod(operands)
    if node.getType() == libsbml.AST_DIVIDE:
        return operands[0] / operands[1]
    if node.getType() == libsbml.AST_PLUS:
        return sum(operands)
    if node.getType() == libsbml.AST_MINUS:
        return operands[0] - operands[1]
    if node.getType() == libsbml.AST_POWER:
        return operands[0] ** operands[1]
    raise AssertionError(f"unsupported candidate MathML operator {node.getType()}")


def _homodimer_export_rates(xml, parsed, volume, monomer_amount, dimer_amount):
    """Evaluate writer-authored SBML laws directly, without BNG3 re-import."""
    doc = libsbml.readSBMLFromString(xml)
    model = doc.getModel()
    values = {"k": 0.02, "d": 0.1, "cell": volume}
    for species_id, pattern in parsed.multi_species_patterns.items():
        # This fixture has one unbound monomer and one two-molecule complex.
        values[species_id] = (
            dimer_amount if pattern.count("A(") == 2 else monomer_amount
        )

    observed = {}
    for reaction in model.getListOfReactions():
        reactants = [
            parsed.multi_species_patterns[ref.getSpecies()]
            for ref in reaction.getListOfReactants()
        ]
        products = [
            parsed.multi_species_patterns[ref.getSpecies()]
            for ref in reaction.getListOfProducts()
        ]
        reactant_monomers = sum(
            ref.getStoichiometry()
            for ref, pattern in zip(reaction.getListOfReactants(), reactants)
            if pattern.count("A(") == 1 and "!" not in pattern
        )
        product_dimers = sum(
            ref.getStoichiometry()
            for ref, pattern in zip(reaction.getListOfProducts(), products)
            if pattern.count("A(") == 2 and "!" in pattern
        )
        reactant_dimers = sum(
            ref.getStoichiometry()
            for ref, pattern in zip(reaction.getListOfReactants(), reactants)
            if pattern.count("A(") == 2 and "!" in pattern
        )
        product_monomers = sum(
            ref.getStoichiometry()
            for ref, pattern in zip(reaction.getListOfProducts(), products)
            if pattern.count("A(") == 1 and "!" not in pattern
        )
        if reactant_monomers == 2 and product_dimers == 1:
            direction = "association"
        elif reactant_dimers == 1 and product_monomers == 2:
            direction = "dissociation"
        else:
            continue
        observed[direction] = _math_value(reaction.getKineticLaw().getMath(), values)
    return observed


CASES = {
    "homodimer": dict(
        types=["A(b)"],
        seeds=[("A(b)", 8)],
        rules=[
            (
                "bind",
                "@cell:A(b) + @cell:A(b)",
                "@cell:A(b!1).A(b!1)",
                "<->",
                "k, d",
            ),
        ],
        species={"A": 8, "AA": 0},
        kinetics=[
            (
                {"A": 2},
                {"AA": 1},
                "<apply><times/><cn>0.5</cn><ci>k</ci><ci>A</ci><ci>A</ci></apply>",
            ),
            ({"AA": 1}, {"A": 2}, _mul("d", "AA")),
        ],
        multi_ids={"S1": "A", "RR1_P1": "AA"},
    ),
    "three_body": dict(
        types=["A()", "B()", "C()", "D()"],
        seeds=[("A()", 8), ("B()", 6), ("C()", 5)],
        rules=[("combine", "@cell:A() + @cell:B() + @cell:C()", "@cell:D()", "k")],
        species={"A": 8, "B": 6, "C": 5, "D": 0},
        kinetics=[
            (
                {"A": 1, "B": 1, "C": 1},
                {"D": 1},
                _div(_mul("k", "A", "B", "C"), "cell_squared"),
            )
        ],
        multi_ids={"S1": "A", "S2": "B", "S3": "C", "RR1_P1": "D"},
    ),
    "heterodimer_shared_b": dict(
        types=["A(b)", "B(b)"],
        seeds=[("A(b)", 8), ("B(b)", 6)],
        rules=[("bind", "@cell:A(b) + @cell:B(b)", "@cell:A(b!1).B(b!1)", "k")],
        species={"A": 8, "B": 6, "AB": 0},
        kinetics=[({"A": 1, "B": 1}, {"AB": 1}, _div(_mul("k", "A", "B"), "cell"))],
        multi_ids={"S1": "A", "S2": "B", "RR1_P1": "AB"},
    ),
    "repeated_binding_site": dict(
        types=["A(b,b)", "B(x)"],
        seeds=[("A(b,b)", 8), ("B(x)", 6)],
        rules=[("bind", "@cell:A(b,b) + @cell:B(x)", "@cell:A(b!1,b).B(x!1)", "k")],
        species={"A": 8, "B": 6, "AB": 0},
        # Two independent equivalent binding positions create multiplicity 2.
        kinetics=[
            ({"A": 1, "B": 1}, {"AB": 1}, _div(_mul("k", "A", "B", "two"), "cell"))
        ],
        multi_ids={"S1": "A", "S2": "B", "RR1_P1": "AB"},
    ),
    "zeroth_order": dict(
        types=["A()"],
        seeds=[("A()", 2)],
        rules=[("make", "0", "@cell:A()", "k"), ("decay", "@cell:A()", "0", "d")],
        species={"A": 2},
        kinetics=[({}, {"A": 1}, "<ci>k</ci>"), ({"A": 1}, {}, _mul("d", "A"))],
        multi_ids={"S1": "A"},
    ),
}


@pytest.mark.parametrize("atomize", [False, True])
@pytest.mark.parametrize("volume", [0.5, 2.0])
@pytest.mark.parametrize("case", list(CASES))
def test_multi_export_matches_independent_kinetics(case, volume, atomize, tmp_path):
    data = CASES[case]
    path = Path(tmp_path) / "source.bngl"
    path.write_text(_source(volume, data["types"], data["seeds"], data["rules"]))
    source = bionetgen.load(str(path))
    multi_xml = source.sbml_multi()
    reference_xml = _core(volume, data["species"], data["kinetics"])
    # Resolve only explicit analytic numeric constants defined by this fixture;
    # no part of the reference comes from candidate-generated output.
    reference_xml = reference_xml.replace(
        "<ci>cell_squared</ci>", "<apply><power/><ci>cell</ci><cn>2</cn></apply>"
    )
    reference_xml = reference_xml.replace("<ci>two</ci>", "<cn>2</cn>")
    for xml in (multi_xml, reference_xml):
        doc = libsbml.readSBMLFromString(xml)
        assert doc.getNumErrors() == 0, doc.getErrorLog().toString()
        doc.checkConsistency()
        consistency_errors = [
            doc.getError(index).getErrorId()
            for index in range(doc.getNumErrors())
            if doc.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
        ]
        assert consistency_errors == [], doc.getErrorLog().toString()
    parsed = SBMLParser().parse(multi_xml)
    assert parsed.multi_executable
    if case == "homodimer":
        observed = _homodimer_export_rates(
            multi_xml, parsed, volume, monomer_amount=7, dimer_amount=3
        )
        assert observed == pytest.approx(
            {
                "association": 0.5 * 0.02 * 7**2 / volume,
                "dissociation": 0.1 * 3,
            }
        )
    imported = Atomizer(atomize=atomize, quiet_mode=True).atomize(multi_xml)
    assert imported.success, imported.error
    trajectory = BioNetGenModel(cpp.parse_string(imported.bngl)).simulate(
        method="ode", t_end=3, n_steps=30
    )
    oracle = roadrunner.RoadRunner(reference_xml)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(
        times=trajectory.time, selections=["time", *data["species"]]
    )
    for i, (_, species_id) in enumerate(data["multi_ids"].items(), 1):
        multi_id = list(data["multi_ids"])[i - 1]
        np.testing.assert_allclose(
            trajectory.observables[imported.observable_map[multi_id]],
            expected[:, list(data["species"]).index(species_id) + 1],
            rtol=1e-6,
            atol=1e-8,
        )
