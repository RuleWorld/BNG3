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


@pytest.mark.parametrize(
    ("action", "args", "diagnostic"),
    [
        ("setParameter", {'"k"': None}, "exactly 2 positional"),
        ("setParameter", {'"k"': 2}, "is positional"),
        ("quit", {"1": None}, "exactly 0 positional"),
        ("simulate_ode", {"unknown_arg": 2}, "unknown_arg not recognized"),
    ],
)
def test_pinned_action_validation_is_shared_with_model_api(action, args, diagnostic):
    from bionetgen.core.exc import BNGParseError
    from bionetgen.core.utils.utils import ActionList
    from bionetgen.modelapi.structs import Action

    with pytest.raises(BNGParseError, match=diagnostic):
        ActionList().validate_action(action, args)
    with pytest.raises(BNGParseError, match=diagnostic):
        Action(action, args)


def test_pinned_action_validation_accepts_named_and_positional_calls():
    from bionetgen.core.utils.utils import ActionList
    from bionetgen.modelapi.structs import Action

    for name, args, rendered in [
        ("generate_network", {"check_iso": "1"}, "generate_network({check_iso=>1})"),
        ("setParameter", {'"k"': None, "2": None}, 'setParameter("k",2)'),
        ("saveParameters", {}, "saveParameters([])"),
    ]:
        assert ActionList().validate_action(name, args) is None
        assert str(Action(name, args)) == rendered
