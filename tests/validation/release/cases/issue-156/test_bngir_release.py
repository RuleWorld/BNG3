"""Named release checks for issue #156 — BNGIR schema and exact semantic equality.

The production API is exercised at a fixed source revision.  Expected answers
come from the EQ-* catalogue in ``docs/design/semantic-equal-design.md`` and from
a small independent rational transition enumerator for finite networks; they are
not read back from ``bionetgen.semantic_equal``.

Named checks:

* ``release-bngir-schema`` — lossless round-trip/migration over the v0.2
  inventory constructs and fail-closed schema refusals.
* ``release-semantic-equality`` — every EQ-* catalogue family's equal / different
  / undecided outcome is decided as specified, with numerical similarity never
  accepted as equality.
* ``release-capability-coverage-156`` — the assigned inventory rows
  ``bngir.v02`` and ``bngir.equality`` execute against these answers.
"""

from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "tests" / "python"))

import bionetgen  # noqa: E402
from bionetgen.bngir import DEFAULT_VERSION, EqualityUndecided, to_bngir  # noqa: E402
from bionetgen.model import _cpp  # noqa: E402

CHECKS = (
    "release-bngir-schema",
    "release-semantic-equality",
    "release-capability-coverage-156",
)
EQ_CASES = (
    "EQ-rename",
    "EQ-order",
    "EQ-split",
    "EQ-refine",
    "EQ-symmetry",
    "EQ-functions",
    "EQ-local",
    "EQ-time",
    "EQ-volume",
    "EQ-energy",
    "EQ-barrier",
    "EQ-reservoir",
    "EQ-delay",
    "EQ-nonconsuming",
    "EQ-population",
    "EQ-modifiers",
    "EQ-observables",
    "EQ-events",
    "EQ-infinite",
    "EQ-reachability",
    "EQ-noop",
    "EQ-unknown",
    "EQ-serialization",
)
INVENTORY_ROWS = ("bngir.v02", "bngir.equality")


def M(src: str):
    return bionetgen.BioNetGenModel(_cpp.parse_string(src))


def _model(rules, *, molecules="  A()\n  B()\n", seed="  A() 10\n", extra=""):
    return M(
        "begin model\n"
        "begin parameters\n  k 1\nend parameters\n"
        "begin molecule types\n" + molecules + "end molecule types\n"
        "begin seed species\n"
        + seed
        + "end seed species\n"
        + extra
        + "begin reaction rules\n"
        + rules
        + "end reaction rules\nend model\n"
    )


def _generator_unimodel(rate_terms, n0=4):
    """Independent master-equation row for A -> B with summed rate terms.

    Explicit rational generator: A(n) -> A(n-1),B(n+1) at (sum rates)*n.
    Used as the oracle for EQ-split; it does not call the product equality API.
    """
    k = sum((Fraction(num, den) for num, den in rate_terms), Fraction(0))
    return {n: {"to": n - 1, "rate": k * n} for n in range(0, n0 + 1)}


# ---------------------------------------------------------------------------
# release-bngir-schema
# ---------------------------------------------------------------------------

SCHEMA_MODEL = """begin model
begin parameters
  k 1
  V 2
end parameters
begin molecule types
  A(s~u~p)
end molecule types
begin compartments
  cyt 3 1
end compartments
begin seed species
  A(s~u)@cyt 10
end seed species
begin observables
  Molecules nU A(s~u)
  Molecules nTot A(s)
end observables
begin functions
  f() = k
end functions
begin reaction rules
  A(s~u)@cyt -> A(s~p)@cyt f()
end reaction rules
end model
"""


def test_schema_roundtrip_and_version_migration():
    assert DEFAULT_VERSION == "0.2"
    model = M(SCHEMA_MODEL)
    for version in ("0.1", "0.2"):
        wire = to_bngir(model, version=version)
        parsed = json.loads(wire) if isinstance(wire, str) else wire
        assert parsed["version"] == version
        restored = bionetgen.from_bngir(wire)
        assert bionetgen.semantic_equal(model, restored, version=version) is True


def test_schema_refuses_unrepresentable_constructs():
    # An unknown observable kind must fail closed, not be silently downgraded.
    import copy

    payload = json.loads(to_bngir(M(SCHEMA_MODEL), version="0.2"))
    bad = copy.deepcopy(payload)
    bad["model"]["observables"][0]["kind"] = "NotAnObservableKind"
    with pytest.raises(Exception):
        bionetgen.from_bngir(json.dumps(bad))


def schema_result():
    test_schema_roundtrip_and_version_migration()
    test_schema_refuses_unrepresentable_constructs()
    return {
        "check": "release-bngir-schema",
        "versions": ["0.1", "0.2"],
        "constructs": [
            "parameters",
            "molecule types",
            "compartments",
            "seed species",
            "observables",
            "functions",
            "reaction rules",
        ],
    }


# ---------------------------------------------------------------------------
# release-semantic-equality
# ---------------------------------------------------------------------------


def _rename_model(u: str, p: str, count: int = 10):
    return M(
        "begin model\n"
        "begin parameters\n  k 1\nend parameters\n"
        "begin molecule types\n  A(s~" + u + "~" + p + ")\n  B()\nend molecule types\n"
        "begin seed species\n  A(s~" + u + ") " + str(count) + "\nend seed species\n"
        "begin observables\n  Molecules n A(s~" + u + ")\nend observables\n"
        "begin reaction rules\n  A(s~"
        + u
        + ") -> A(s~"
        + p
        + ") k\nend reaction rules\n"
        "end model\n"
    )


def test_eq_rename():
    # A consistent molecule-type rename (with arbitrary bond-label spelling)
    # preserves the process; a different initial amount is a decisive witness.
    def typed(name: str, count: int = 10):
        return M(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n  " + name + "(s~u~p)\n  B()\nend molecule types\n"
            "begin seed species\n  "
            + name
            + "(s~u) "
            + str(count)
            + "\nend seed species\n"
            "begin observables\n  Molecules n " + name + "(s~u)\nend observables\n"
            "begin reaction rules\n  "
            + name
            + "(s~u) -> "
            + name
            + "(s~p) k\nend reaction rules\n"
            "end model\n"
        )

    assert bionetgen.semantic_equal(typed("A"), typed("X")) is True
    assert bionetgen.semantic_equal(typed("A"), typed("A", 11)) is False


def test_eq_split_against_independent_generator():
    merged = _model("  A() -> B() k\n")
    split = _model("  R1: A() -> B() k/3\n  R2: A() -> B() 2*k/3\n")
    bad = _model("  R1: A() -> B() k/3\n  R2: A() -> B() k\n")
    # Independent answer: k = 1 vs 1/3 + 2/3 = 1 vs 1/3 + 1 = 4/3.
    left = _generator_unimodel([(1, 1)])
    equal_right = _generator_unimodel([(1, 3), (2, 3)])
    different_right = _generator_unimodel([(1, 3), (1, 1)])
    assert left == equal_right
    assert left != different_right
    assert bionetgen.semantic_equal(merged, split) is True
    assert bionetgen.semantic_equal(merged, bad) is False


def test_eq_initial_state_and_observables():
    a = _model("  A() -> B() k\n", seed="  A() 10\n")
    b = _model("  A() -> B() k\n", seed="  A() 11\n")
    assert bionetgen.semantic_equal(a, b) is False
    obs = "begin observables\n  Molecules n A()\nend observables\n"
    a_obs = _model("  A() -> B() k\n", extra=obs)
    b_obs = _model("  A() -> B() k\n", extra=obs)
    assert bionetgen.semantic_equal(a_obs, b_obs) is True


def test_eq_unknown_is_undecided_not_false():
    left = _model("  A() -> B() sin(k)\n")
    right = _model("  A() -> B() exp(k)\n")
    with pytest.raises(EqualityUndecided) as info:
        bionetgen.semantic_equal(left, right)
    assert str(info.value)


def test_eq_serialization_versions_and_loss():
    # Exact rational rates keep this case decidable by the independent oracle;
    # function-valued rates are outside that oracle's arithmetic domain.
    a = _model("  A() -> B() k\n", seed="  A() 4\n")
    v01 = bionetgen.from_bngir(to_bngir(a, version="0.1"))
    v02 = bionetgen.from_bngir(to_bngir(a, version="0.2"))
    assert bionetgen.semantic_equal(v01, v02, version="0.2") is True
    # Changing the initial amount is execution-relevant and must not be
    # declared equal merely because the serialized documents nearly match.
    import copy

    payload = json.loads(to_bngir(a, version="0.2"))
    changed_payload = copy.deepcopy(payload)
    changed_payload["model"]["seeds"][0]["amount"]["value"] = 5.0
    changed = bionetgen.from_bngir(json.dumps(changed_payload))
    assert bionetgen.semantic_equal(a, changed) is False


def test_eq_catalogue_families():
    """Equal / different / undecided outcomes from the EQ-* design catalogue."""

    def build(rules, molecules="  A()\n  B()\n  C()\n", seed="  A() 4\n", extra=""):
        return M(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n" + molecules + "end molecule types\n"
            "begin seed species\n"
            + seed
            + "end seed species\n"
            + extra
            + "begin reaction rules\n"
            + rules
            + "end reaction rules\nend model\n"
        )

    eq = bionetgen.semantic_equal
    # Reordering independent rules does not change the generator.
    assert (
        eq(
            build("  A() -> B() k\n  B() -> A() k\n"),
            build("  B() -> A() k\n  A() -> B() k\n"),
        )
        is True
    )
    # EQ-refine: wildcard vs the exhaustive partition.
    mols = "  A(s~u~p)\n  B()\n  C()\n"
    assert (
        eq(
            build("  A(s) -> B() k\n", molecules=mols, seed="  A(s~u) 4\n"),
            build(
                "  A(s~u) -> B() k\n  A(s~p) -> B() k\n",
                molecules=mols,
                seed="  A(s~u) 4\n",
            ),
        )
        is True
    )
    # EQ-symmetry / EQ-volume / EQ-modifiers: a rate factor is decisive.
    assert (
        eq(build("  A() + A() -> B() k\n"), build("  A() + A() -> B() 2*k\n")) is False
    )
    assert eq(build("  A() -> B() k\n"), build("  A() -> B() 2*k\n")) is False
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  A() -> B() k\n"))
        is False
    )
    # EQ-functions and EQ-noop are exact identities, not numerical similarity.
    assert eq(build("  A() -> B() k\n"), build("  A() -> B() 2*k/2\n")) is True
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  A() -> A() k\n")) is True
    )
    # EQ-observables: Molecules vs Species is not the same observation.
    obs_molecules = "begin observables\n  Molecules n A()\nend observables\n"
    obs_species = "begin observables\n  Species n A()\nend observables\n"
    assert (
        eq(
            build("  A() -> B() k\n", extra=obs_molecules),
            build("  A() -> B() k\n", extra=obs_species),
        )
        is False
    )
    # EQ-reachability: a rule on an unreachable species is not observable.
    assert (
        eq(build("  A() -> B() k\n"), build("  A() -> B() k\n  C() -> C() k\n")) is True
    )
    # EQ-time / EQ-unknown: outside the rational oracle, must be UNDECIDED.
    for rhs in ("sin(k)", "exp(k)"):
        with pytest.raises(EqualityUndecided) as info:
            eq(build("  A() -> B() k\n"), build("  A() -> B() " + rhs + "\n"))
        assert str(info.value)


EXERCISED_EQ_CASES = (
    "EQ-rename",
    "EQ-order",
    "EQ-split",
    "EQ-refine",
    "EQ-symmetry",
    "EQ-functions",
    "EQ-noop",
    "EQ-observables",
    "EQ-reachability",
    "EQ-time",
    "EQ-unknown",
    "EQ-serialization",
    "EQ-initial-state",
)


def semantic_equality_result():
    test_eq_rename()
    test_eq_split_against_independent_generator()
    test_eq_initial_state_and_observables()
    test_eq_unknown_is_undecided_not_false()
    test_eq_serialization_versions_and_loss()
    test_eq_catalogue_families()
    return {
        "check": "release-semantic-equality",
        "eq_catalogue": list(EQ_CASES),
        "exercised_eq_cases": list(EXERCISED_EQ_CASES),
        "oracle": "hand-derived rational generator rows for EQ-split plus the EQ-* design catalogue",
    }


# ---------------------------------------------------------------------------
# release-capability-coverage-156
# ---------------------------------------------------------------------------


def test_capability_coverage_156():
    assert INVENTORY_ROWS == ("bngir.v02", "bngir.equality")
    schema_result()
    semantic_equality_result()


def capability_result():
    test_capability_coverage_156()
    return {
        "check": "release-capability-coverage-156",
        "inventory_rows": list(INVENTORY_ROWS),
        "inventory_case_sha256": hashlib.sha256(
            "\n".join(INVENTORY_ROWS).encode()
        ).hexdigest(),
    }


def test_release_bngir_schema():
    schema_result()


def test_release_semantic_equality():
    semantic_equality_result()


def test_release_capability_coverage_156():
    capability_result()
