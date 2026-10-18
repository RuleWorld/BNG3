"""Compartment conversion must retain precision before reaching the solver."""

import numpy as np
import pytest
import bionetgen
from _extdep import require_extension

require_extension()


@pytest.mark.parametrize("volume", [3, 7, 11])
def test_dimer_ode_matches_source_law_after_nonterminating_volume_conversion(
    tmp_path, volume
):
    source = tmp_path / "dimer.bngl"
    source.write_text(f"""begin model
begin parameters
  k 0.4
end parameters
begin compartments
  cell 3 {volume}
end compartments
begin molecule types
  A()
  D()
end molecule types
begin seed species
  @cell:A() 20
end seed species
begin observables
  Molecules A @cell:A()
end observables
begin reaction rules
  @cell:A() + @cell:A() -> @cell:D() 2*k
end reaction rules
end model
""")
    result = bionetgen.load(source).simulate(
        method="ode", t_end=2, n_steps=10, rtol=1e-11, atol=1e-13
    )
    expected = 20 / (1 + 2 * 0.4 * 20 * result.time / volume)
    np.testing.assert_allclose(result.observables["A"], expected, rtol=1e-9, atol=1e-10)
