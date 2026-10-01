"""Check the C++ emitter's v0.2 output against the published schema and against
the key set the Python reader actually consumes."""

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

import jsonschema  # noqa: E402

import bionetgen  # noqa: E402
from bionetgen.model import _cpp  # noqa: E402

SCHEMA = json.load(
    open(
        "/Users/akutuva/Documents/BioNetGen/BNG3-ir-snapshot/provenance/schemas/bngir-0.2.schema.json"
    )
)

CASES = {
    "rate_law_with_unit": r"""
begin model
begin molecule types
  A()
end molecule types
begin parameters
  k 0.5
end parameters
begin functions
  f() k
end functions
begin reaction rules
  A() -> A() f()
end reaction rules
end model
""",
    "energy": r"""
begin model
begin molecule types
  A(s~U~P)
end molecule types
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  bind: A(s~P) 1.0
end energy patterns
begin reaction rules
  A(s~U) <-> A(s~P) 1.0, 1.0
end reaction rules
end model
""",
    "population": r"""
begin model
begin molecule types
  A()
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
  A() -> A() 1.0
end reaction rules
end model
""",
    "units": r"""
begin model
begin molecule types
  A()
end molecule types
begin compartments
  C 3 1.0
end compartments
begin seed species
  A()@C 100
end seed species
begin reaction rules
  A() -> A() 1.0
end reaction rules
end model
""",
    "filters": r"""
begin model
begin molecule types
  A(b)
  B(c)
  C(b,c)
end molecule types
begin reaction rules
  A(b) + B(c) -> C(b!1).C(c!1) 1.0 include_reactants(1,A(b))
end reaction rules
end model
""",
}

for name, src in CASES.items():
    print("=" * 70)
    print("CASE", name)
    try:
        native = _cpp.parse_string(src)
        doc = json.loads(bionetgen.BioNetGenModel(native).to_bngir(version="0.2"))
    except Exception as exc:
        print("  PARSE/EMIT FAIL:", exc)
        continue
    try:
        jsonschema.validate(doc, SCHEMA)
        print("  schema: OK")
    except jsonschema.ValidationError as exc:
        print("  schema: FAIL")
        print("   path:", list(exc.absolute_path))
        print("   msg :", exc.message[:300])
