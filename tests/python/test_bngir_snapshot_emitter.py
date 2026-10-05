"""Semantic-roundtrip gates for the C++ BNGIR v0.2 snapshot emitter.

`cpp/bindings/bind_compile_snapshot.cpp` is the producer of the structural
wire object. These tests pin the properties the Python reader is entitled to
rely on, and the ones it is entitled to be able to refuse.

The comparison is semantic, not textual: a model is serialized, reconstructed,
and re-serialized, and the two wire objects are compared structurally. JSON
formatting and key order are irrelevant; a dropped feature is not.

Two tests below are EXPECTED TO FAIL against a build that predates a fix
owned by another lane. They are marked and annotated rather than weakened,
so the consequence of that fix being absent stays visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bionetgen

# These two imports must NOT be importorskip. This file's entire subject is
# `_cpp._compiled_snapshot`, so an unimportable extension means the file tested
# nothing while pytest exited 0. Measured on this tree after rebasing onto
# origin/main: with the PR #48 conftest guard active, `sys.path` loses the
# worktree's build/cpp and the extension is unimportable -- the file reported
# "1 skipped" and passed. jsonschema is a genuinely optional validator, so that
# one keeps importorskip.
from bionetgen.model import _cpp  # noqa: E402  (hard dependency, see above)

SCHEMA_PATH = (
    Path(__file__).parents[2] / "provenance" / "schemas" / "bngir-0.2.schema.json"
)


def build(source: str):
    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def snapshot_diff(left, right, path: str = "") -> list[str]:
    """Structural differ that names any dropped, added, or mutated feature.

    Deliberately not an equality check: comparing the two documents directly
    would report "True" and "False" without saying WHICH feature moved, which
    is the only part a reader of a failure needs.
    """
    if type(left) is not type(right):
        return [f"TYPE {path}: {left!r} vs {right!r}"]
    if isinstance(left, dict):
        out: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left:
                out.append(f"DROPPED-A {path}.{key}")
            elif key not in right:
                out.append(f"DROPPED-B {path}.{key}")
            else:
                out += snapshot_diff(left[key], right[key], f"{path}.{key}")
        return out
    if isinstance(left, list):
        out = []
        if len(left) != len(right):
            out.append(f"LEN {path}: {len(left)} vs {len(right)}")
        for index, (a, b) in enumerate(zip(left, right)):
            out += snapshot_diff(a, b, f"{path}[{index}]")
        return out
    return [] if left == right else [f"VAL {path}: {left!r} vs {right!r}"]


def assert_semantic_roundtrip(source: str, *, what: str):
    """model -> IR -> model -> IR must yield an identical wire object."""
    model = build(source)
    document = json.loads(model.to_bngir(version="0.2"))
    restored = bionetgen.from_bngir(document)
    original = json.loads(model.to_bngir(version="0.2"))
    roundtripped = json.loads(restored.to_bngir(version="0.2"))
    deltas = snapshot_diff(original, roundtripped)
    assert not deltas, f"{what} lost semantics across the roundtrip:\n  " + "\n  ".join(
        deltas
    )


# --------------------------------------------------------------------------
# Features whose roundtrip is already correct. These are the regression net:
# an emitter change that quietly breaks one of them fails here.
# --------------------------------------------------------------------------

ROUNDTRIP_FIXTURES = {
    "parameters_and_metadata": r"""
setModelName("meta_case")
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
    "state_constraints": r"""
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
    "bond_groups": r"""
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
    "compartment_suffix_form": r"""
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
    "functions_and_local_refs": r"""
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
    "bidirectional_rate_pair": r"""
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
    "population_maps": r"""
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
    "energy_patterns": r"""
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
    "table_function": r"""
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
    # EXPECTED TO FAIL: pyBngir owns this. `_pattern_v02` (bngir.py:1112-1141)
    # renders a site as component, then state, then label, then the bond marker
    # appended last. BNGL requires the bond marker BEFORE the state, so a site
    # with both a state and a bond constraint regenerates as `A(b~0.)`, which
    # the parser rejects. Verified directly: A(b~0.) FAILS, A(b.~0) PARSES.
    # Only the `.` form collides, because it is the one marker that must
    # precede the state. Reported to pyBngir; drop this marker when it lands.
    "constant_seed": r"""
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
    "protocol_and_model_actions": r"""
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
}


# Fixtures whose roundtrip is blocked by a defect owned by another lane. Each
# is listed rather than deleted so the gap stays visible and the day the fix
# lands, this suite tells us rather than sitting green over it.
KNOWN_BROKEN = {
    "constant_seed": (
        "pyBngir's _pattern_v02 renders the bond marker AFTER the state "
        "(bngir.py:1112-1141); BNGL requires it before, so `A(b~0.)` is "
        "produced and rejected by the parser. Emitter is not at fault."
    ),
}


@pytest.mark.parametrize("name", sorted(ROUNDTRIP_FIXTURES))
def test_v02_semantic_roundtrip_is_lossless(name):
    if name in KNOWN_BROKEN:
        pytest.xfail(KNOWN_BROKEN[name])
    assert_semantic_roundtrip(ROUNDTRIP_FIXTURES[name], what=name)


# --------------------------------------------------------------------------
# Gap: an expression naming a symbol kind outside the schema's enum.
#
# `symbolKindName` used to emit "barrier_pattern", "population_type" and
# "invalid" for SymbolKind::BarrierPattern / PopulationType / Count. None of
# those appear in the schema's symbol.kind enum, so any document carrying one
# failed schema validation. It now refuses with a named diagnostic instead.
#
# Correction to my own earlier report: I first claimed the reader also refused
# these kinds. It does not. `bngir.py:986-987` maps both to their sections and
# resolves the name from the label. So the defect was schema-invalidity only,
# which is why this block tests the ENUM rather than round-trippability.
# --------------------------------------------------------------------------


def collect_symbols(node):
    """Every {kind, index} pair anywhere in a wire object."""
    if isinstance(node, dict):
        if set(node) == {"kind", "index"}:
            yield node
        for value in node.values():
            yield from collect_symbols(value)
    elif isinstance(node, list):
        for value in node:
            yield from collect_symbols(value)


def test_every_emitted_symbol_kind_is_in_the_schema_enum():
    """No snapshot may carry a symbol kind outside the published enum."""
    schema = json.loads(SCHEMA_PATH.read_text())
    allowed = set(schema["$defs"]["symbol"]["properties"]["kind"]["enum"])

    for name, source in ROUNDTRIP_FIXTURES.items():
        document = json.loads(build(source).to_bngir(version="0.2"))
        for symbol in collect_symbols(document):
            assert symbol["kind"] in allowed, (
                f"{name}: symbol kind {symbol['kind']!r} is not in the schema "
                f"enum {sorted(allowed)}"
            )


def test_barrier_patterns_reach_the_snapshot_and_carry_no_illegal_symbol():
    """Direct test, replacing the dormancy precondition this used to assert.

    This was a tripwire: it asserted `barrier_patterns == []` and failed with
    "now needs a direct test" when barriers started arriving. They arrived --
    PR #66 made `do_parse()` run the same `finalizeThermodynamicMetadata()`
    step `parseModel` runs, so barrier patterns reach the AST on the Python
    path for the first time. The tripwire fired and is replaced here.

    What it asserts now, on the live path:
      1. barriers really are present (so this is not vacuous), and
      2. every symbol kind the emitter produces is inside the schema enum.

    It does NOT trigger the symbolKindName refusal for
    SymbolKind::BarrierPattern, because no expression in any fixture
    references a barrier pattern AS A SYMBOL -- the barrier energy is a
    parameter reference. So the refusal remains untriggerable today; what is
    testable is that the live path does not need it. If a model ever does
    reference one, the enum assertion below is what will fail first.
    """
    schema = json.loads(SCHEMA_PATH.read_text())
    allowed = set(schema["$defs"]["symbol"]["properties"]["kind"]["enum"])

    snapshot = _cpp._compiled_snapshot(_cpp.parse_string(BARRIER_FIXTURE))
    assert snapshot["barrier_patterns"], (
        "barrier patterns no longer reach the snapshot; PR #66 made this path "
        "live and it should not silently stop carrying barriers"
    )
    for symbol in collect_symbols(snapshot):
        assert symbol["kind"] in allowed, (
            f"live barrier path emitted symbol kind {symbol['kind']!r}, outside "
            f"the schema enum {sorted(allowed)}"
        )


def test_population_map_snapshot_carries_no_illegal_symbol():
    """A population-map model must snapshot without emitting an illegal kind."""
    schema = json.loads(SCHEMA_PATH.read_text())
    allowed = set(schema["$defs"]["symbol"]["properties"]["kind"]["enum"])
    native = _cpp.parse_string(ROUNDTRIP_FIXTURES["population_maps"])
    try:
        snapshot = _cpp._compiled_snapshot(native)
    except RuntimeError as error:
        # Fail-closed is an acceptable outcome; the message must name it.
        assert "population" in str(error).lower(), (
            f"refusal must name the construct, got: {error}"
        )
        return
    for symbol in collect_symbols(snapshot):
        assert symbol["kind"] in allowed


# --------------------------------------------------------------------------
# Gap: barrier energy was serialized as parser text.
#
# CompiledBarrierFactor carries BOTH `energyExpression` (the printable BNGL
# text) and `expression` (a ResolvedExpression). The emitter wrote the former,
# putting parser text into a document required to hold resolved semantics --
# and the reader walks `expression` as an expression tree, so a bare string is
# not readable there either.
# --------------------------------------------------------------------------


def test_barrier_energy_is_a_resolved_expression_not_source_text():
    """A barrier's energy must serialize as a resolved expression TREE.

    This is now a live assertion, not a specification. It was written as a
    dormancy note because `barrier_patterns` was always empty on the Python
    parse path -- `cpp/bindings/bind_parser.cpp` omitted the
    `finalizeThermodynamicMetadata()` call that
    `cpp/parser/BNGAstVisitor.cpp` makes. PR #66 closed that gap, so barriers
    reach the emitter and the shape is checkable.

    It is also the regression test for a real defect: the emitter used to write
    `CompiledBarrierFactor::energyExpression`, the printable BNGL text, while
    `CompiledBarrierFactor::expression` -- a ResolvedExpression -- sat unused
    beside it. A wire object required to hold resolved semantics must not carry
    parser text, and the reader walks `expression` as a tree, so a bare string
    was unusable there either.

    The non-vacuity assertion matters as much as the shape check: a loop over
    an empty `barrier_patterns` would pass on a build where barriers are
    missing again, which is precisely the regression this file had.
    """
    snapshot = _cpp._compiled_snapshot(_cpp.parse_string(BARRIER_FIXTURE))
    barriers = snapshot["barrier_patterns"]
    assert barriers, (
        "no barriers in the snapshot: the emitter must carry barrier patterns "
        "on the Python parse path now that PR #66 lowered them"
    )
    for barrier in barriers:
        assert isinstance(barrier["expression"], dict), (
            "barrier energy must serialize as a resolved expression object, "
            f"got {type(barrier['expression']).__name__}"
        )
        assert barrier["expression"].get("kind") != "unresolved"


BARRIER_FIXTURE = r"""
begin model
begin molecule types
  A(s~U~P)
end molecule types
begin parameters
  phi 0.5
  Ea 1.0
  Gb 2.0
end parameters
begin seed species
  A(s~U) 100
end seed species
begin energy patterns
  bind: A(s~P) 1.0
end energy patterns
begin barrier patterns
  brk: A(s~U) -> A(s~P) Gb
end barrier patterns
begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""


# --------------------------------------------------------------------------
# The comparison itself must have discriminating power. A test that cannot
# fail is not evidence, so this drops a feature and requires the differ to
# catch it.
# --------------------------------------------------------------------------


def test_the_semantic_comparison_detects_a_dropped_feature():
    """Guard the guard.

    If the differ could not see a removed feature, every roundtrip assertion
    above would be vacuously true. Removing a whole section must be reported.
    """
    document = json.loads(
        build(ROUNDTRIP_FIXTURES["energy_patterns"]).to_bngir(version="0.2")
    )
    assert document["model"]["energy_patterns"], "fixture must carry the feature"

    dropped = json.loads(json.dumps(document))
    dropped["model"]["energy_patterns"] = []
    deltas = snapshot_diff(document, dropped)
    assert deltas, "the differ failed to notice a dropped section"
    assert any("energy_patterns" in delta for delta in deltas)

    # And a single dropped field inside a surviving section.
    mutated = json.loads(json.dumps(document))
    del mutated["model"]["energy_patterns"][0]["expression"]
    deltas = snapshot_diff(document, mutated)
    assert any("expression" in delta for delta in deltas)


# --------------------------------------------------------------------------
# Schema conformance, with the one known-and-ruled discrepancy isolated.
# --------------------------------------------------------------------------


def test_emitter_output_conforms_to_the_published_schema():
    """Every fixture must validate against provenance/schemas/bngir-0.2.schema.json.

    `population_maps` is excluded here and covered by the strict-xfail below,
    because the schema for that section is stale by pyBngir's ruling and must
    not be allowed to fail the whole sweep.
    """
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    for name, source in ROUNDTRIP_FIXTURES.items():
        if name == "population_maps":
            continue
        document = json.loads(build(source).to_bngir(version="0.2"))
        try:
            jsonschema.validate(document, schema)
        except jsonschema.ValidationError as error:  # pragma: no cover - diagnostic
            pytest.fail(
                f"{name} is not schema-valid at {list(error.absolute_path)}: "
                f"{error.message}"
            )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "population_maps.items in bngir-0.2.schema.json still requires a 'function' "
        "string and forbids 'population'/'population_id'/'rate', i.e. it encodes the "
        "pre-canonical rate-less vocabulary. pyBngir ruled the READER authoritative "
        "and the schema stale (see PR for pyBngir's ruling); the schema rewrite is "
        "assigned to provenance/schemas' owner. The emitter deliberately keeps the "
        "canonical keys: dropping 'rate' would reintroduce the v0.1 lossy shape and "
        "would remove the population_id cross-check the reader performs against "
        "population_types. Turns green when the schema lands, with no emitter change."
    ),
)
def test_population_maps_section_is_schema_valid():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    document = json.loads(
        build(ROUNDTRIP_FIXTURES["population_maps"]).to_bngir(version="0.2")
    )
    jsonschema.validate(document, schema)
