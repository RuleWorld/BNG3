"""Consume writeFile/writeModel exports through the BNGL parser and engine.

Both actions export a BNGL model document. Re-importing it into the public
Python API and comparing the observable to the closed-form decay law is a real
producer-consumer check, not a file-existence or syntax smoke test.
"""

from __future__ import annotations

import math
import subprocess

import bionetgen
import pytest

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
writeFile({format=>"bngl",prefix=>"wf_",overwrite=>1})
writeModel({overwrite=>1})
"""


@pytest.mark.parametrize("filename", ["wf_.bngl", "m_out.bngl"])
def test_exported_bngl_reimports_and_reproduces_source_law(tmp_path, bng_cpp, filename):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    result = subprocess.run(
        [str(bng_cpp), source.name], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr

    exported = tmp_path / filename
    assert exported.is_file()
    assert "begin model" in exported.read_text()

    model = bionetgen.load(str(exported))
    simulated = model.simulate(method="ode", t_end=1.0, n_steps=2)
    # Independent analytic law for A() -> 0 with k=0.1 and A(0)=10.
    assert simulated.observables["A_obs"][-1] == pytest.approx(
        10 * math.exp(-0.1), rel=1e-5
    )
