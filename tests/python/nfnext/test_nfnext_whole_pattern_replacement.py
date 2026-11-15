import math
import os
import importlib.util
from pathlib import Path

# Use freshly built extension from this worktree when available.
build_so = (
    Path(__file__).resolve().parents[3]
    / "build"
    / "cpp"
    / "_bionetgen_cpp.cpython-314-darwin.so"
)
if build_so.exists():
    spec = importlib.util.spec_from_file_location("_bionetgen_cpp", str(build_so))
    cpp = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(cpp)
else:
    import bionetgen._bionetgen_cpp as cpp


def test_nfnext_whole_pattern_replacement_and_mapping_rules_execute():
    """Hybrid-generated-style whole-pattern replacements/map rules have no orphan risk.

    Before this fix, NFnext lowering refused any unmapped-reactant + created-product
    rule as "simultaneous molecule replacement requires orphan-context semantics...",
    even when each deleted reactant molecule belonged to a reactant pattern with no
    mapped/surviving molecules in that same pattern (explicit whole-pattern deletion).
    """
    hpp = r"""begin model
begin parameters
  k_make 1
  k_map 100
  N 20
end parameters
begin molecule types
  A()
  A_pop()
  B()
end molecule types
begin seed species
  B() N
  A_pop() 0
end seed species
begin observables
  Molecules A_total A(),A_pop()
  Molecules B_total B()
end observables
begin reaction rules
  R1_v1: B() -> A_pop() k_make
  _MapRule0: A() -> A_pop() k_map
end reaction rules
end model
"""
    m = cpp.parse_string(hpp)
    times = [0.0, 0.1, 0.5, 1.0]
    res = cpp.simulate_nfnext(m, times, seed=1, max_events=500000, max_particles=500000)

    assert [float(x) for x in res["time"]] == times
    a = [float(x) for x in res["observables"]["A_total"]]
    b = [float(x) for x in res["observables"]["B_total"]]
    assert len(a) == len(times)
    assert len(b) == len(times)
    # Conservation: every B becomes A_pop in this hybrid-generated form.
    for ai, bi in zip(a, b):
        assert ai + bi == 20.0
    # Exact deterministic counts for this seed/trajectory sanity check.
    assert a == [0.0, 1.0, 7.0, 14.0]
    assert b == [20.0, 19.0, 13.0, 6.0]
