import pytest

import bionetgen
from bionetgen.core.exc import BNGCompileError
from bionetgen.simulator.csimulator import CSimulator


def test_unsupported_csimulator_preserves_caller_actions():
    model = bionetgen.bngmodel(
        "begin model\nbegin parameters\nk 1\nend parameters\nend model\n"
        "begin actions\ngenerate_network({overwrite=>1})\nend actions\n"
    )
    before = str(model.actions)
    assert "generate_network" in before

    with pytest.raises(BNGCompileError):
        CSimulator(model)

    assert str(model.actions) == before
