"""Independent Core execution oracle for state-bearing Multi bond changes.

The two source files are authored separately.  The BNGL model specifies a
site with both a binding state and an internal state, including conversion of
the bound complex; the explicit Core model specifies five chemical species
and six extent-rate equations directly.
Neither the imported Multi output nor a BNG3-generated network defines the
expected trajectories.
"""

import hashlib
from pathlib import Path

import libsbml
import numpy as np
import pytest
roadrunner = pytest.importorskip("roadrunner")

import bionetgen
from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer, SBMLParser

CASES = Path(__file__).parent
SOURCE = CASES / "stateful_binding.bngl"
CORE_ORACLE = CASES / "stateful_binding_core.xml"
SOURCE_SHA256 = "617f6ebb0e333529a2447b664065e7e22ce5e15b7dc762455fed320268c7d75b"
CORE_SHA256 = "f10185b4404d2ddf261e017e87ab3255a06e4b216fc9b47d6b0a9c49a636b23b"
SPECIES_ORACLE = {
    "S1": "Au",
    "S2": "B",
    "RR1_P1": "AuB",
    "RR2_P1": "Ap",
    "RR3_P1": "ApB",
}


@pytest.mark.parametrize("atomize", [False, True])
@pytest.mark.parametrize("volume", [0.5, 2.0])
def test_stateful_binding_export_reimport_matches_explicit_core(
    atomize, volume, tmp_path
):
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    assert hashlib.sha256(CORE_ORACLE.read_bytes()).hexdigest() == CORE_SHA256
    source_text = SOURCE.read_text(encoding="utf-8")
    core_text = CORE_ORACLE.read_text(encoding="utf-8")
    assert source_text.count("cell 3 0.5") == 1
    assert core_text.count('size="0.5"') == 1
    # The second volume is a declared transformation of both locked sources,
    # not a candidate-dependent reference or a fitted kinetic parameter.
    source_text = source_text.replace("cell 3 0.5", f"cell 3 {volume:g}")
    core_text = core_text.replace('size="0.5"', f'size="{volume:g}"')
    transformed = tmp_path / "stateful_binding.bngl"
    transformed.write_text(source_text, encoding="utf-8")
    source = bionetgen.load(str(transformed))
    multi_xml = source.sbml_multi()
    candidate = libsbml.readSBMLFromString(multi_xml)
    assert candidate.getNumErrors() == 0, candidate.getErrorLog().toString()
    candidate.checkConsistency()
    candidate_errors = [
        candidate.getError(index).getErrorId()
        for index in range(candidate.getNumErrors())
        if candidate.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert candidate_errors == [], candidate.getErrorLog().toString()

    core = libsbml.readSBMLFromString(core_text)
    assert core.getNumErrors() == 0, core.getErrorLog().toString()
    core.checkConsistency()
    core_errors = [
        core.getError(index).getErrorId()
        for index in range(core.getNumErrors())
        if core.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert core_errors == [], core.getErrorLog().toString()

    parsed = SBMLParser().parse(multi_xml)
    assert parsed.multi_executable
    assert parsed.multi_species_patterns["RR1_P1"] == "A(x~u!1)@cell.B(y!1)@cell"
    assert parsed.multi_species_patterns["RR2_P1"] == "A(x~p)@cell"
    assert parsed.multi_species_patterns["RR3_P1"] == "A(x~p!1)@cell.B(y!1)@cell"

    atomized = Atomizer(atomize=atomize, quiet_mode=True).atomize(multi_xml)
    assert atomized.success, atomized.error
    native = cpp.parse_string(atomized.bngl)
    result = BioNetGenModel(native).simulate(method="ode", t_end=4, n_steps=40)

    reference_model = roadrunner.RoadRunner(core_text)
    reference_model.integrator.relative_tolerance = 1e-10
    reference_model.integrator.absolute_tolerance = 1e-12
    reference_model.timeCourseSelections = ["time", *SPECIES_ORACLE.values()]
    expected = reference_model.simulate(
        times=result.time, selections=["time", *SPECIES_ORACLE.values()]
    )
    for multi_id, core_id in SPECIES_ORACLE.items():
        observed = result.observables[atomized.observable_map[multi_id]]
        expected_column = list(SPECIES_ORACLE.values()).index(core_id) + 1
        np.testing.assert_allclose(
            observed, expected[:, expected_column], rtol=1e-6, atol=1e-8
        )

    au = result.observables[atomized.observable_map["S1"]]
    ap = result.observables[atomized.observable_map["RR2_P1"]]
    b = result.observables[atomized.observable_map["S2"]]
    aub = result.observables[atomized.observable_map["RR1_P1"]]
    apb = result.observables[atomized.observable_map["RR3_P1"]]
    np.testing.assert_allclose(au + ap + aub + apb, 20, rtol=1e-7)
    np.testing.assert_allclose(b + aub + apb, 12, rtol=1e-7)
