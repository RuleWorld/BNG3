"""Model API action text cases observed in pinned PyBioNetGen 28bf351."""

from pathlib import Path

import bionetgen
import pytest


@pytest.mark.parametrize(
    ("action", "argument", "expected"),
    (
        (
            'simulate_nf({param=>"-v -gml 1000 #tag",t_end=>2})',
            "param",
            '"-v -gml 1000 #tag"',
        ),
        (
            "simulate_ode({sample_times=>[0,2.3e-10,1]})",
            "sample_times",
            "[0,2.3e-10,1]",
        ),
    ),
)
def test_modelapi_preserves_action_values(
    tmp_path: Path, action: str, argument: str, expected: str
):
    model_path = tmp_path / "model.bngl"
    model_path.write_text(
        "begin model\n"
        "begin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        f"end model\n{action}\n",
        encoding="utf-8",
    )

    model = bionetgen.bngmodel(str(model_path))
    recorded = model.actions[0]
    assert recorded.args[argument] == expected
