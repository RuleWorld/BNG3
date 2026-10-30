"""Issue #161: concentration-valued Multi sums retain compartment factors.

These source equations are independently authored. The Core oracle specifies
concentration-valued species with the same mathematical rate, not an inferred
BNG3 network. In particular, V=0.5 and V=2 give different rates.
"""

import libsbml
import numpy as np
import pytest
roadrunner = pytest.importorskip("roadrunner")
from bionetgen import BioNetGenModel, _bionetgen_cpp as cpp
from bionetgen.atomizer.modern import Atomizer

from test_multi_math_representation import (
    MULTI_WILDCARD_SUM_SOURCE,
    CORE_WILDCARD_SUM_ORACLE,
)


@pytest.mark.parametrize("volume", [0.5, 2.0])
@pytest.mark.parametrize("atomize", [False, True])
def test_multi_sum_with_concentration_coordinates(atomize, volume):
    # Both documents are authored separately in the earlier acceptance case;
    # the source-quantity and source-volume transformation is explicit.
    multi = MULTI_WILDCARD_SUM_SOURCE.replace(
        'hasOnlySubstanceUnits="true"', 'hasOnlySubstanceUnits="false"'
    ).replace('size="0.5"', f'size="{volume:g}"')
    core = CORE_WILDCARD_SUM_ORACLE.replace(
        'hasOnlySubstanceUnits="true"', 'hasOnlySubstanceUnits="false"'
    ).replace('size="0.5"', f'size="{volume:g}"')
    for source in (multi, core):
        doc = libsbml.readSBMLFromString(source)
        assert doc.getNumErrors() == 0, doc.getErrorLog().toString()
        doc.checkConsistency()
        consistency_errors = [
            doc.getError(index).getErrorId()
            for index in range(doc.getNumErrors())
            if doc.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
        ]
        assert consistency_errors == [], doc.getErrorLog().toString()
    converted = Atomizer(atomize=atomize, quiet_mode=True).atomize(multi)
    assert converted.success, converted.error
    model = BioNetGenModel(cpp.parse_string(converted.bngl))
    actual = model.simulate(method="ode", t_end=4, n_steps=40)
    oracle = roadrunner.RoadRunner(core)
    oracle.integrator.relative_tolerance = 1e-10
    oracle.integrator.absolute_tolerance = 1e-12
    expected = oracle.simulate(times=actual.time, selections=["time", "Au", "Ap"])
    for column, species in enumerate(("Au", "Ap"), start=1):
        np.testing.assert_allclose(
            actual.observables[converted.observable_map[species]],
            expected[:, column],
            rtol=1e-6,
            atol=1e-8,
        )
