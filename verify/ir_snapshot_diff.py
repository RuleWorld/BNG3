"""Differential BNGIR roundtrip harness: find semantic losses in the v0.2 path."""

from __future__ import annotations

import json
import sys

sys.meta_path = [
    f
    for f in sys.meta_path
    if "editable" not in type(f).__module__.lower()
    and "editable" not in getattr(f, "__name__", "").lower()
]
for _path in list(sys.path):
    if "BioNetGen" in _path:
        sys.path.remove(_path)
sys.path.insert(0, "/Users/akutuva/Documents/BioNetGen/BNG3-ir-snapshot/python")
sys.path.insert(0, "/Users/akutuva/Documents/BioNetGen/BNG3-ir-snapshot/build/cpp")

import bionetgen  # noqa: E402
from bionetgen.model import _cpp  # noqa: E402

print("UNDER TEST pkg :", bionetgen.__file__)
import bionetgen._bionetgen_cpp as _C  # noqa: E402

print("UNDER TEST ext :", _C.__file__)


def diff(a, b, path=""):
    """Structural diff that reports a dropped/mutated feature."""
    out = []
    if type(a) is not type(b):
        return [f"TYPE {path}: {a!r} vs {b!r}"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"DROPPED-A {path}.{k}")
            elif k not in b:
                out.append(f"DROPPED-B {path}.{k}")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"LEN {path}: {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append(f"VAL {path}: {a!r} vs {b!r}")
    return out


CASES: dict[str, str] = {}


def case(name, src):
    CASES[name] = src


case(
    "params_and_metadata",
    """
version("2.3")
setModelName("meta_case")
setOption("max_iter", 5)
begin model
begin parameters
  k1 0.1
  k2 k1*3+1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin reaction rules
  A() -> B() k2
end reaction rules
end model
""",
)

case(
    "state_constraints",
    """
begin model
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin reaction rules
  A(s~U) -> A(s~P) 1.0
  A(s~P) -> A(s~U) 2.0
end reaction rules
end model
""",
)

case(
    "bond_alternatives",
    """
begin model
begin molecule types
  A(b,c)
  B(b)
end molecule types
begin seed species
  A(b,c) 100
  B(b) 50
end seed species
begin reaction rules
  A(b,c) + B(b) -> A(b!1,c!1).B(b!1) 1.0
end reaction rules
end model
""",
)

case(
    "compartments_suffix",
    """
begin model
begin molecule types
  A()
  B()
end molecule types
begin compartments
  CYT 3 1
  NUC 3 0.5 CYT
end compartments
begin seed species
  A()@CYT 100
  B()@NUC 50
end seed species
begin reaction rules
  A()@CYT -> B()@NUC 1.0
end reaction rules
end model
""",
)

case(
    "compartments_prefix",
    """
begin model
begin molecule types
  A()
  B()
end molecule types
begin compartments
  CYT 3 1
  NUC 3 0.5 CYT
end compartments
begin seed species
  @CYT:A() 100
  @NUC:B() 50
end seed species
begin reaction rules
  @CYT:A() -> @NUC:B() 1.0
end reaction rules
end model
""",
)

case(
    "observables_species_and_relation",
    """
begin model
begin molecule types
  A(b~0~1)
end molecule types
begin seed species
  A(b~0) 100
end seed species
begin observables
  Molecules Bound A(b~1)
  Molecules Free A(b~0)
  Species Tot A(b~0)
end observables
begin reaction rules
  A(b) -> A(b!1) 1.0
  A(b!1) -> A(b!2) 1.0
end reaction rules
end model
""",
)

case(
    "functions_with_locals",
    """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin functions
  f(x) x*2+1
  g(x,y) f(x)+y
  h() time*k
end functions
begin reaction rules
  A() -> A() g(1,2)
  A() -> A() h()
end reaction rules
end model
""",
)

case(
    "reactant_count_ref",
    """
begin model
begin molecule types
  A()
  B()
end molecule types
begin reaction rules
  A() + A() -> B() 1.0
end reaction rules
end model
""",
)

case(
    "bidirectional",
    """
begin model
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin reaction rules
  A(s~U) <-> A(s~P) 0.5, 0.25
end reaction rules
end model
""",
)

case(
    "population_maps",
    """
begin model
begin molecule types
  A()
  B()
  P(k)
end molecule types
begin seed species
  A() 100
  P(k) 10
end seed species
begin population maps
  m1: A() -> P(k) 0.2
end population maps
begin reaction rules
  A() -> B() 1.0
end reaction rules
end model
""",
)

case(
    "energy_patterns",
    """
begin model
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  bind: A(s~P) 1.0
  unbind: A(s~U) -1.0
end energy patterns
begin reaction rules
  A(s~U) <-> A(s~P) 1.0, 1.0
end reaction rules
end model
""",
)

case(
    "filters_and_modifiers",
    """
begin model
begin molecule types
  A(b)
  B(c)
  C(b,c)
end molecule types
begin reaction rules
  A(b) + B(c) -> C(b!1).C(c!1) 1.0 include_reactants(1,A(b)) exclude_products(1,C())
  A(b) -> C(b) 1.0 MoveConnected DeleteMolecules
end reaction rules
end model
""",
)

case(
    "local_scopes",
    """
begin model
begin molecule types
  A(b)
  B(c)
end molecule types
begin reaction rules
  A(b) + B(c) -> B(c!1) 1.0
end reaction rules
end model
""",
)

case(
    "table_function",
    """
begin model
begin molecule types
  A()
end molecule types
begin parameters
  k 0.3
end parameters
begin functions
  f() tfun([0,1,2],[0,1,4],k,method=>"linear")
end functions
begin reaction rules
  A() -> A() f()
end reaction rules
end model
""",
)

case(
    "constant_seed",
    """
begin model
begin molecule types
  A(b~0~1)
end molecule types
begin seed species
  A(b~0) 100
  $A(b~1) 200
end seed species
begin reaction rules
  A(b) -> A(b!1) 1.0
end reaction rules
end model
""",
)

case(
    "protocol_actions",
    """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin reaction rules
  A() -> A() 1.0
end reaction rules
begin protocol
simulate({method=>ode,t_end=>1,n_steps=>2})
end protocol
end model
begin actions
generate_network({overwrite=>1})
end actions
""",
)


def run():
    failures = []
    for name, src in CASES.items():
        print("=" * 72)
        print("CASE", name)
        try:
            native = _cpp.parse_string(src)
        except Exception as exc:
            print("  PARSE FAIL:", exc)
            failures.append((name, "parse", str(exc)))
            continue
        model = bionetgen.BioNetGenModel(native)
        try:
            doc = json.loads(model.to_bngir(version="0.2"))
        except Exception as exc:
            print("  EMIT FAIL:", type(exc).__name__, exc)
            failures.append((name, "emit", str(exc)))
            continue
        try:
            restored = bionetgen.from_bngir(doc)
        except Exception as exc:
            print("  DECODE FAIL:", type(exc).__name__, exc)
            try:
                from bionetgen.bngir import _as_bngl_v02, _load_document_v02

                print("  --- regenerated BNGL ---")
                print(_as_bngl_v02(_load_document_v02(doc)))
            except Exception as exc2:
                print("   (could not render)", type(exc2).__name__, exc2)
            failures.append((name, "decode", f"{type(exc).__name__}: {exc}"))
            continue
        left = json.loads(model.to_bngir(version="0.2"))
        right = json.loads(restored.to_bngir(version="0.2"))
        deltas = diff(left, right)
        if deltas:
            print("  SEMANTIC DRIFT:")
            for d in deltas[:20]:
                print("   ", d)
            failures.append((name, "drift", "; ".join(deltas[:5])))
        else:
            print("  OK semantic roundtrip")
    print()
    print("=" * 72)
    print(f"SUMMARY: {len(CASES) - len(failures)}/{len(CASES)} clean")
    for name, stage, msg in failures:
        print(f"  FAIL {name:32s} [{stage}] {msg}")
    return failures


if __name__ == "__main__":
    run()
