"""A reaction participant whose value a rule owns keeps its factor in the rate.

SBML lets a boundary species with a rate rule or an assignment rule take part
in a reaction (SBML Level 3 Version 1 Core Sec. 4.9.4 and 4.11.3): the rule
determines the species' value, the reaction does not change it, and the
kinetic law still reads it.  The Atomizer removes such a species from the
BNGL reaction pattern, so its factor must stay in the rate expression.  It
used to be divided out by the mass-action conversion, so ``0.5*S2*C`` with
``C = 2`` was emitted as the constant rate ``1``.
"""

from __future__ import annotations

import re

import pytest

from bionetgen.atomizer.modern import Atomizer

TIME = (
    '<csymbol encoding="text" '
    'definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>'
)
ASSIGNMENT_RULE = (
    '<assignmentRule variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">'
    f"<apply><plus/><cn>1</cn>{TIME}</apply></math></assignmentRule>"
)
RATE_RULE = (
    '<rateRule variable="S2"><math xmlns="http://www.w3.org/1998/Math/MathML">'
    "<cn>1</cn></math></rateRule>"
)


def _source(rule: str) -> str:
    return f"""<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
<model id="m" timeUnits="time">
<listOfCompartments><compartment id="C" size="2" constant="true"/></listOfCompartments>
<listOfSpecies>
 <species id="S2" compartment="C" initialAmount="1" hasOnlySubstanceUnits="false"
          boundaryCondition="true" constant="false"/>
 <species id="S3" compartment="C" initialAmount="0" hasOnlySubstanceUnits="false"
          boundaryCondition="false" constant="false"/>
</listOfSpecies>
<listOfRules>{rule}</listOfRules>
<listOfReactions>
 <reaction id="slow" reversible="false" fast="false">
  <listOfReactants><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfReactants>
  <listOfProducts><speciesReference species="S3" stoichiometry="1" constant="true"/></listOfProducts>
  <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply><times/><cn>0.5</cn><ci>S2</ci><ci>C</ci></apply>
  </math></kineticLaw>
 </reaction>
</listOfReactions>
</model></sbml>"""


def _rule_line(bngl: str) -> str:
    match = re.search(r"^\s*slow:.*$", bngl, re.M)
    assert match, bngl
    return match.group(0).strip()


@pytest.mark.parametrize(
    "rule, operand",
    [(ASSIGNMENT_RULE, "S2()"), (RATE_RULE, "_c_S2()")],
    ids=["assignment-rule", "rate-rule"],
)
def test_rule_owned_reactant_keeps_its_factor(rule, operand):
    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(_source(rule))
    assert atomized.success, atomized.error
    line = _rule_line(atomized.bngl)
    # The species is not part of the pattern, so the rate is the whole flux.
    assert line.startswith("slow: 0 -> @C:M_S3()"), line
    assert operand in line, line
    assert line.endswith("TotalRate"), line


@pytest.mark.parametrize(
    "rule, reference",
    [
        # [S2] = 1 + t, flux 0.5*[S2]*2 = 1 + t, so n_S3 = t + t^2/2.
        (ASSIGNMENT_RULE, lambda t: t + t * t / 2),
        # [S2] = 0.5 + t, flux 0.5 + t, so n_S3 = t/2 + t^2/2.
        (RATE_RULE, lambda t: t / 2 + t * t / 2),
    ],
    ids=["assignment-rule", "rate-rule"],
)
def test_native_engine_integrates_the_rule_owned_factor(rule, reference, tmp_path):
    import bionetgen

    atomized = Atomizer(atomize=False, quiet_mode=True).atomize(_source(rule))
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    grid = ",".join(repr(time) for time in times)
    bngl = atomized.bngl + (
        "\nbegin actions\n  generate_network({overwrite=>1})\n"
        '  simulate({method=>"ode", t_start=>0, t_end=>2, '
        f"sample_times=>[{grid}], atol=>1e-12, rtol=>1e-10}})\nend actions\n"
    )
    source = tmp_path / "model.bngl"
    source.write_text(bngl, encoding="utf-8")
    bionetgen.load(str(source)).execute()
    lines = (tmp_path / "model.gdat").read_text().splitlines()
    header = lines[0].lstrip("#").split()
    rows = {
        round(float(line.split()[0]), 9): dict(zip(header, map(float, line.split())))
        for line in lines[1:]
        if line.strip() and not line.startswith("#")
    }
    for time in times:
        assert rows[round(time, 9)]["S3_amt"] == pytest.approx(
            reference(time), rel=1e-6, abs=1e-8
        )
