"""Consume artifacts produced by the writeBNGL and writeNET/writeNetwork actions.

The inventory rows are action-level, so the exports must be produced by the
BNGL actions (not only by the Python Model API) and then consumed by their
intended consumers: the BNGL parser/engine and the native bng_cpp CLI.
"""

from __future__ import annotations

import math
import subprocess

import bionetgen
import pytest

from tests.validation.export_format_tier import _net_route

MODEL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeBNGL()
writeNET({prefix=>"action_net",overwrite=>1})
writeNetwork({prefix=>"action_nw",overwrite=>1})
"""


def test_write_bngl_action_export_is_consumed(tmp_path, bng_cpp):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    result = subprocess.run(
        [str(bng_cpp), source.name], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr

    exported = tmp_path / "m_out.bngl"
    assert exported.is_file()
    simulated = bionetgen.load(str(exported)).simulate(
        method="ode", t_end=1.0, n_steps=2
    )
    assert simulated.observables["A_obs"][-1] == pytest.approx(
        10 * math.exp(-0.1), rel=1e-5
    )


@pytest.mark.parametrize("filename", ["action_net.net", "action_nw.net"])
def test_write_net_actions_export_is_consumed(tmp_path, bng_cpp, filename):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    result = subprocess.run(
        [str(bng_cpp), source.name], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    exported = tmp_path / filename
    assert exported.is_file()

    # _net_route expects the artifact as <case-id>.export.net in its work dir.
    directory = tmp_path / "consumer"
    directory.mkdir()
    (directory / "case.export.net").write_bytes(exported.read_bytes())
    values, network, error = _net_route({"id": "case"}, directory, bng_cpp)
    assert error is None
    assert network is not None
    # _net_route simulates to t_end=2, so compare the t=2 analytic value.
    assert values["A_obs"][-1] == pytest.approx(10 * math.exp(-0.2), rel=1e-4)
