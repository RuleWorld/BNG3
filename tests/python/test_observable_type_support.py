"""A `Concentration` observable must be refused, not silently aliased.

BNG3 does not apply the compartment volume to any observable, so a
`Concentration` observable could only ever have reported the same number as
`Molecules`.  BNG2 refuses the type outright; BNG3 accepted it and gave the
caller a molecule count under the name of a concentration, with nothing in the
output to say so.  The acceptance criterion here is the refusal and its wording:
the diagnostic has to name the offending type, say that the volume is not
applied by *any* type, and say what the number a user does get means.

The supported types must keep working.  `Species` and `Counter` are accepted by
both BNG2 and BNG3, and `Fraction` by neither's vocabulary but by BNG3's
grammar, so none of them may start failing here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        _REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    if Path(candidate).exists():
        return candidate
    pytest.skip(f"bng_cpp not available at {candidate}")


def _model(observable_type: str) -> str:
    return f"""begin model
begin compartments
  V1 3 1
  V2 3 2
end compartments
begin species
  A()@V1  100
  B()@V1  0
  A()@V2  100
  B()@V2  0
end species
begin reaction rules
  A()@V1 -> B()@V1  0.3
  A()@V2 -> B()@V2  0.3
end reaction rules
begin observables
  {observable_type}  At  A()@V1
  {observable_type}  Bt  B()@V1
end observables
end model

begin actions
  generate_network({{overwrite=>1}})
  simulate({{method=>"ode",t_end=>1,n_steps=>2,suffix=>"_ode"}})
end actions
"""


def _run(tmp_path: Path, observable_type: str) -> subprocess.CompletedProcess:
    path = tmp_path / f"obs_{observable_type}.bngl"
    path.write_text(_model(observable_type))
    return subprocess.run(
        [_bng_cpp(), path.name], cwd=tmp_path, capture_output=True, text=True
    )


@pytest.mark.parametrize("spelling", ["Concentration", "concentration"])
def test_a_concentration_observable_is_refused_with_a_named_diagnostic(
    spelling, tmp_path
):
    result = _run(tmp_path, spelling)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    # The type is named, so the user can find the offending line.
    assert "Concentration" in output, output
    # It says the volume is applied by no type, so `Molecules` is not being
    # quietly reinterpreted as a concentration either.
    assert "volume" in output, output
    # It says what the supported type actually returns, in both engines,
    # because the state unit is the engine's and not the model's.
    assert "ode" in output and "ssa" in output, output
    # And it refuses before writing a network, so nothing half-built is left.
    assert not (tmp_path / f"obs_{spelling}.net").exists()


@pytest.mark.parametrize("spelling", ["Molecules", "Species", "Counter", "Fraction"])
def test_the_other_observable_types_still_parse_and_generate(spelling, tmp_path):
    # BNG3 accepts any string here and ignores the type, so all of these
    # produce the same network.  That is a separate, reported finding; what
    # matters for this commit is that refusing `Concentration` did not take the
    # others down with it.
    result = _run(tmp_path, spelling)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert (tmp_path / f"obs_{spelling}.net").exists()


def test_a_compartment_observable_reports_the_state_value_not_a_count(
    tmp_path,
):
    # The claim the diagnostic rests on: under `ode` the state is a
    # concentration, so `Molecules A2` reads 100 in a compartment of volume 2
    # that physically holds 200 molecules.  If this ever changes, the wording
    # of the refusal has to change with it.
    result = _run(tmp_path, "Molecules")
    assert result.returncode == 0, result.stdout + result.stderr
    net = (tmp_path / "obs_Molecules.net").read_text()
    groups = net.split("begin groups")[1].split("end groups")[0]
    species = " ".join(net.split("begin species")[1].split("end species")[0].split())

    # Species 3 is A() in the volume-2 compartment, seeded at 100, and the
    # .net carries no volume factor -- that is the whole mechanism.
    assert species.split() == [
        "1",
        "@V1::A()",
        "100",
        "2",
        "@V1::B()",
        "0",
        "3",
        "@V2::A()",
        "100",
        "4",
        "@V2::B()",
        "0",
    ], species
    # Both observables are plain weight-1 groups; no volume is applied.
    assert groups.split() == ["1", "At", "1", "2", "Bt", "2"], groups
