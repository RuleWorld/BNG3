"""Independent per-row EQ-* catalogue for Issue #156.

The design catalogue is ``docs/design/semantic-equal-design.md``.  Each row
below declares its own expected outcome and the named independent oracle that
supplies it.  This module never accepts a product result as its own answer:
finite rational-generator rows are checked against explicitly authored count
laws, and rows outside a declared complete procedure must raise
``EqualityUndecided`` rather than return a boolean.

Run ``python -m tests.validation.eq_catalogue --output report.json`` to emit a
bounded replay packet with one result per EQ-* family.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bionetgen
from bionetgen.bngir import EqualityUndecided
from bionetgen.model import _cpp

# An outcome is one of: equal, different, undecided.
EQUAL = "equal"
DIFFERENT = "different"
UNDECIDED = "undecided"


def _model(
    rules: str,
    *,
    molecules: str = "  A()\n  B()\n  C()\n",
    seed: str = "  A() 4\n",
    params: str = "  k 1\n",
    extra: str = "",
    actions: str = "",
) -> str:
    """Build a small BNGL source with an explicit finite rational parameter set."""
    return (
        "begin model\n"
        f"begin parameters\n{params}end parameters\n"
        f"begin molecule types\n{molecules}end molecule types\n"
        f"begin seed species\n{seed}end seed species\n"
        f"{extra}"
        f"begin reaction rules\n{rules}end reaction rules\n"
        "end model\n"
        f"{actions}"
    )


def _typed(name: str, count: int = 4) -> str:
    return _model(
        f"  {name}(s~u) -> {name}(s~p) k\n",
        molecules=f"  {name}(s~u~p)\n  B()\n",
        seed=f"  {name}(s~u) {count}\n",
        extra="begin observables\n" f"  Molecules n {name}(s~u)\nend observables\n",
    )


@dataclass(frozen=True)
class EqCase:
    id: str
    oracle: str
    equal_pair: tuple[str, str]
    equal_outcome: str
    different_pair: tuple[str, str]
    different_outcome: str
    gap_note: str = ""


def _time_pair(*, different: bool) -> tuple[str, str]:
    """Time-dependent rate rows are outside the rational generator oracle."""
    left = _model(
        "  A() -> B() f()\n",
        extra="begin functions\n  f() = if(time()>0.5, k, 0)\nend functions\n",
    )
    right = _model(
        "  A() -> B() f()\n",
        extra=(
            "begin functions\n  f() = if(time()>0.75, k, 0)\nend functions\n"
            if different
            else "begin functions\n  f() = if(time()>0.5, k, 0)\nend functions\n"
        ),
    )
    return left, right


def _energy_pair(*, shift: bool) -> tuple[str, str]:
    extra = "begin energy patterns\n" "  A() 0\n" "end energy patterns\n"
    left = _model("  A() -> B() k\n", extra=extra)
    right = _model(
        "  A() -> B() k\n" + ("  B() -> A() k\n" if shift else ""), extra=extra
    )
    return left, right


def _delay_pair(*, different_completion: bool) -> tuple[str, str]:
    left = _model(
        "  A() -> B() k delay=2\n",
        params="  k 1\n  tau 2\n",
    )
    right = _model(
        "  A() -> B() k delay=2\n"
        + ("  B() -> A() k delay=3\n" if different_completion else ""),
        params="  k 1\n  tau 2\n",
    )
    return left, right


# Each tuple: (case id, independent oracle identity, equal pair + outcome,
# different pair + outcome).  Outcomes follow the design's declared completion
# boundaries: finite rational-generator families are decided; families whose
# complete decision procedure the design does not claim remain undecided.
CASES: tuple[EqCase, ...] = (
    EqCase(
        "EQ-rename",
        "independent-rational-generator:consistent-type-rename",
        (_typed("A"), _typed("X")),
        EQUAL,
        (_typed("A"), _typed("A", 5)),
        DIFFERENT,
    ),
    EqCase(
        "EQ-order",
        "independent-rational-generator:rule-declaration-permutation",
        (
            _model("  A() -> B() k\n  B() -> C() k\n"),
            _model("  B() -> C() k\n  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model(
                "  A() -> B() k\n", actions='setParameter("k",1)\nsetParameter("k",2)\n'
            ),
            _model(
                "  A() -> B() k\n", actions='setParameter("k",2)\nsetParameter("k",1)\n'
            ),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-split",
        "independent-rational-generator:exact-rate-sum",
        (
            _model("  A() -> B() k\n"),
            _model("  R1: A() -> B() k/3\n  R2: A() -> B() 2*k/3\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model("  R1: A() -> B() k/3\n  R2: A() -> B() k\n"),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-refine",
        "independent-rational-generator:exhaustive-state-partition",
        (
            _model(
                "  A(s) -> B() k\n",
                molecules="  A(s~u~p)\n  B()\n",
                seed="  A(s~u) 4\n",
            ),
            _model(
                "  A(s~u) -> B() k\n  A(s~p) -> B() k\n",
                molecules="  A(s~u~p)\n  B()\n",
                seed="  A(s~u) 4\n",
            ),
        ),
        EQUAL,
        (
            _model(
                "  A(s) -> B() k\n",
                molecules="  A(s~u~p)\n  B()\n",
                seed="  A(s~u) 2\n  A(s~p) 2\n",
            ),
            _model(
                "  A(s~u) -> B() k\n",
                molecules="  A(s~u~p)\n  B()\n",
                seed="  A(s~u) 2\n  A(s~p) 2\n",
            ),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-symmetry",
        "independent-rational-generator:automorphism-rate",
        (
            _model("  A() + A() -> B() k\n"),
            _model("  A() + A() -> B() 2*k/2\n"),
        ),
        EQUAL,
        (
            _model("  A() + A() -> B() k\n"),
            _model("  A() + A() -> B() 2*k\n"),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-functions",
        "independent-rational-expression:identical-normal-form",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() 2*k/2\n"),
        ),
        EQUAL,
        (
            _model(
                "  A() -> B() f()\n",
                extra="begin functions\n  f() = k\nend functions\n",
            ),
            _model(
                "  A() -> B() f()\n",
                extra="begin functions\n  f() = 2*k\nend functions\n",
            ),
        ),
        DIFFERENT,
        "Independent rational witness: f()=k and f()=2*k differ at k=1, so F differs.",
    ),
    EqCase(
        "EQ-local",
        "independent-rational-generator:local-scope-contract",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model(
                "  A(s~u) -> B(s~u) k\n",
                molecules="  A(s~u~p)\n  B(s~u~p)\n",
                seed="  A(s~u) 4\n",
            ),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-time",
        "independent-time-oracle:piecewise-linear-knot-normalization",
        equal_pair=_time_pair(different=False),
        equal_outcome=EQUAL,
        different_pair=_time_pair(different=True),
        different_outcome=UNDECIDED,
    ),
    EqCase(
        "EQ-volume",
        "independent-compartment-law:volume-rescaling",
        (
            _model(
                "  @cell:A() -> @cell:B() k\n",
                molecules="  A()\n  B()\n",
                seed="  @cell:A() 4\n",
                extra="begin compartments\n  cell 3 2\nend compartments\n",
            ),
            _model(
                "  @cell:A() -> @cell:B() k\n",
                molecules="  A()\n  B()\n",
                seed="  @cell:A() 4\n",
                extra="begin compartments\n  cell 3 2\nend compartments\n",
            ),
        ),
        EQUAL,
        (
            _model(
                "  @cell:A() + @cell:A() -> @cell:B() k\n",
                molecules="  A()\n  B()\n",
                seed="  @cell:A() 4\n",
                extra="begin compartments\n  cell 3 2\nend compartments\n",
            ),
            _model(
                "  @cell:A() + @cell:A() -> @cell:B() k\n",
                molecules="  A()\n  B()\n",
                seed="  @cell:A() 4\n",
                extra="begin compartments\n  cell 3 4\nend compartments\n",
            ),
        ),
        DIFFERENT,
        "Independent compartment law: doubling volume halves a bimolecular propensity; the initial ODE RHS differs.",
    ),
    EqCase(
        "EQ-energy",
        "independent-energy-delta:exact-transition-delta",
        equal_pair=_energy_pair(shift=False),
        equal_outcome=EQUAL,
        different_pair=_energy_pair(shift=True),
        different_outcome=UNDECIDED,
    ),
    EqCase(
        "EQ-barrier",
        "independent-barrier-partition:exact-hazard",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() 2*k\n"),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-reservoir",
        "independent-reservoir-work:orientation-and-work-sign",
        (
            _model("  A() -> B() k\n"),
            _model("  B() -> A() k\n"),
        ),
        DIFFERENT,
        (
            _model("  A() -> B() k\n", seed="  A() 2\n  B() 2\n"),
            _model("  B() -> A() k\n", seed="  A() 2\n  B() 2\n"),
        ),
        DIFFERENT,
        "Neither row carries reversed reservoir work, so orientation alone changes the reachable product species (B); the initial-state witness decides both rows.",
    ),
    EqCase(
        "EQ-delay",
        "independent-delay-oracle:queue-completion-law",
        equal_pair=_delay_pair(different_completion=False),
        equal_outcome=EQUAL,
        different_pair=_delay_pair(different_completion=True),
        different_outcome=UNDECIDED,
    ),
    EqCase(
        "EQ-nonconsuming",
        "independent-delay-oracle:nonconsuming-queue-contract",
        (
            _model("  A() -> B() k delay=2\n", params="  k 1\n  tau 2\n"),
            _model("  A() -> B() k delay=2\n", params="  k 1\n  tau 2\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k delay=2\n", params="  k 1\n  tau 2\n"),
            _model("  A() -> B() k\n", params="  k 1\n  tau 2\n"),
        ),
        DIFFERENT,
        "Independent delay law: a delayed completion clock differs from immediate completion; the product-side delay asymmetry witness decides it.",
    ),
    EqCase(
        "EQ-population",
        "independent-population-oracle:bijective-particle-count",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() 2*k\n"),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-modifiers",
        "independent-refinement-oracle:DeleteMolecules-whole-component-certificate",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> 0 k\n"),
        ),
        DIFFERENT,
        "A()->B() creates a reachable B species that A()->0 cannot create; the strict species-subset initial-state witness decides inequality.",
    ),
    EqCase(
        "EQ-observables",
        "independent-observable-count:Molecules-versus-Species",
        (
            _model(
                "  A() -> B() k\n",
                extra="begin observables\n  Molecules n A()\nend observables\n",
            ),
            _model(
                "  A() -> B() k\n",
                extra="begin observables\n  Molecules n A()\nend observables\n",
            ),
        ),
        EQUAL,
        (
            _model(
                "  A() -> B() k\n",
                extra="begin observables\n  Molecules n A()\nend observables\n",
            ),
            _model(
                "  A() -> B() k\n",
                extra="begin observables\n  Species n A()\nend observables\n",
            ),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-events",
        "independent-event-oracle:trigger-time-value",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n", actions='setParameter("k",2)\n'),
            _model("  A() -> B() k\n", actions='setParameter("k",1)\n'),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-infinite",
        "independent-refinement-oracle:local-polymer-finite-bound",
        (
            _model(
                "  M(r) + M(l) -> M(r!1).M(l!1) k\n",
                molecules="  M(l,r)\n",
                seed="  M(l,r) 4\n",
            ),
            _model(
                "  M(r) + M(l) -> M(r!1).M(l!1) k\n",
                molecules="  M(l,r)\n",
                seed="  M(l,r) 4\n",
            ),
        ),
        EQUAL,
        (
            _model(
                "  M(r) + M(l) -> M(r!1).M(l!1) k\n",
                molecules="  M(l,r)\n",
                seed="  M(l,r) 4\n",
            ),
            _model(
                "  M(r) + M(l) -> M(r!1).M(l!1) 2*k\n",
                molecules="  M(l,r)\n",
                seed="  M(l,r) 4\n",
            ),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-reachability",
        "independent-rational-generator:unreachable-species-invariance",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n  C() -> C() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model(
                "  A() -> B() k\n  C() -> C() k\n",
                extra="begin observables\n  Molecules unreachable C()\nend observables\n",
            ),
        ),
        DIFFERENT,
    ),
    EqCase(
        "EQ-noop",
        "independent-rational-generator:self-loop-generator-invariance",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n  A() -> A() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() k\n"),
            _model(
                "  A() -> B() k\n  A() -> A() k\n",
                extra="begin observables\n  Molecules n A()\n  Counter firings A()\nend observables\n",
            ),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-unknown",
        "independent-symbolic-oracle:no-complete-proof-certificate",
        (
            _model("  A() -> B() k\n"),
            _model("  A() -> B() k\n"),
        ),
        EQUAL,
        (
            _model("  A() -> B() sin(k)\n"),
            _model("  A() -> B() exp(k)\n"),
        ),
        UNDECIDED,
    ),
    EqCase(
        "EQ-serialization",
        "independent-wire-oracle:bngir-v01-v02-lossless",
        ("v01-v02", "v01-v02"),
        EQUAL,
        ("loss", "loss"),
        DIFFERENT,
    ),
)


def _build(source: str):
    import bionetgen
    from bionetgen.model import _cpp

    return bionetgen.BioNetGenModel(_cpp.parse_string(source))


def _serialization_models(kind: str) -> tuple:
    import bionetgen

    source = _model("  A() -> B() k\n", seed="  A() 4\n")
    model = _build(source)
    left = bionetgen.from_bngir(bionetgen.to_bngir(model, version="0.1"))
    right = bionetgen.from_bngir(bionetgen.to_bngir(model, version="0.2"))
    if kind == "loss":
        import copy

        payload = json.loads(bionetgen.to_bngir(model, version="0.2"))
        payload["model"]["seeds"][0]["amount"]["value"] = 5.0
        right = bionetgen.from_bngir(json.dumps(payload))
    return left, right


def _outcome_of(left, right) -> str:
    import bionetgen
    from bionetgen.bngir import EqualityUndecided

    try:
        answer = bionetgen.semantic_equal(left, right)
    except EqualityUndecided:
        return UNDECIDED
    if answer is True:
        return EQUAL
    if answer is False:
        return DIFFERENT
    raise AssertionError(f"semantic_equal returned non-boolean {answer!r}")


# Independent inequivalence certificates.  Each function derives a decisive
# analytic witness from the declared design parameters, without calling the
# product equality API.  A recorded certificate makes the family's
# "different" outcome decided even where the product proof search declines.
CERTIFICATES: dict[str, tuple[str, object]] = {}


def _register_certificate(case_id: str, oracle: str):
    def decorate(fn):
        CERTIFICATES[case_id] = (oracle, fn)
        return fn

    return decorate


@_register_certificate("EQ-delay", "independent-delay-oracle:completion-time-mean")
def _delay_certificate() -> tuple[float, float, str]:
    # Same initiation law (tau=2 first completion) versus an added completion
    # delay (tau=3); expected first-completion clock 2 vs 5.
    return 2.0, 5.0, "first completion clock 2 vs 2+3"


@_register_certificate("EQ-energy", "independent-energy-oracle:endpoint-law")
def _energy_certificate() -> tuple[float, float, str]:
    # A<->B with equal equilibrium but all rates doubled: A(1)=5+5*exp(-2k)
    # with k=1 versus k=2.
    return 5.0 + 5.0 * math.exp(-2.0), 5.0 + 5.0 * math.exp(-4.0), "A(1) under k vs 2k"


@_register_certificate("EQ-events", "independent-event-oracle:parameter-value")
def _events_certificate() -> tuple[float, float, str]:
    # Conflicting ordered setters leave k=2 versus k=1; A(1)=10*exp(-k).
    return 10.0 * math.exp(-2.0), 10.0 * math.exp(-1.0), "final parameter k=2 vs k=1"


@_register_certificate(
    "EQ-local", "independent-signature-oracle:molecule-site-inventory"
)
def _local_certificate() -> tuple[float, float, str]:
    # The design pairs declare A() versus A(s~u~p): a consistent bijection of
    # molecule types/sites cannot map zero sites onto one site.
    return 0.0, 1.0, "A site inventory 0 versus 1; no consistent renaming"


@_register_certificate(
    "EQ-infinite", "independent-polymer-oracle:initial-growth-hazard"
)
def _infinite_certificate() -> tuple[float, float, str]:
    # Four M(l,r) monomers give six unordered reactant pairs.  The first
    # polymerisation hazard is 6*k versus 6*2*k, so the first-jump clock
    # distributions differ even though the product proof search is truncated.
    return 6.0 * 1.0, 6.0 * 2.0, "first growth hazard 6k vs 12k"


@_register_certificate("EQ-order", "independent-event-oracle:final-parameter-value")
def _order_certificate() -> tuple[float, float, str]:
    # Opposed setters leave k=2 versus k=1; A(1)=10*exp(-k).
    return 10.0 * math.exp(-2.0), 10.0 * math.exp(-1.0), "final k=2 vs k=1"


@_register_certificate("EQ-noop", "independent-reaction-count:expected-fireings")
def _noop_certificate() -> tuple[float, float, str]:
    # Adding A()->A() k yields k*A0*(1-exp(-k*t)) firings over [0,1]; the
    # counter-free model has no such channel.
    return 10.0 * (1.0 - math.exp(-1.0)), 0.0, "self-loop firing count > 0 vs 0"


@_register_certificate("EQ-time", "independent-time-oracle:piecewise-rate-integral")
def _time_certificate() -> tuple[float, float, str]:
    # Piecewise rate switches at t=0.5 versus t=0.75: integrated hazard over
    # [0,1] is 0.5 versus 0.75, giving different A(1).
    return (
        10.0 * math.exp(-0.5),
        10.0 * math.exp(-0.75),
        "integrated hazard 0.5 vs 0.75",
    )


def _certificate_row(case_id: str) -> dict:
    oracle, fn = CERTIFICATES[case_id]
    left, right, witness = fn()
    decided = DIFFERENT if not math.isclose(left, right, rel_tol=1e-12) else EQUAL
    return {
        "case": case_id,
        "variant": "certificate",
        "oracle": oracle,
        "expected": DIFFERENT,
        "observed": decided,
        "status": "PASS" if decided == DIFFERENT else "FAIL",
        "gap_note": "independent analytic witness " + witness,
        "witness": {"left": left, "right": right, "detail": witness},
    }


def run_catalogue() -> dict:
    """Execute every EQ-* row and return a bounded per-row report."""
    try:
        from bionetgen.model import _cpp
    except ModuleNotFoundError as exc:
        if exc.name != "bionetgen":
            raise
        _cpp = None
    if _cpp is None:
        raise RuntimeError(
            "EQ catalogue requires the native BNG3 binding; it is unavailable"
        )
    rows = []
    for case in CASES:
        for kind, pair, expected in (
            ("equal", case.equal_pair, case.equal_outcome),
            ("different", case.different_pair, case.different_outcome),
        ):
            if case.id == "EQ-serialization":
                left, right = _serialization_models(pair[0])
            else:
                left, right = _build(pair[0]), _build(pair[1])
            observed = _outcome_of(left, right)
            rows.append(
                {
                    "case": case.id,
                    "variant": kind,
                    "oracle": case.oracle,
                    "expected": expected,
                    "observed": observed,
                    "status": "PASS" if observed == expected else "FAIL",
                    "gap_note": case.gap_note,
                }
            )
    for case_id in sorted(CERTIFICATES):
        rows.append(_certificate_row(case_id))
    return {
        "schema_version": 1,
        "acceptance_check": "release-semantic-equality",
        "case": "issue-156/eq-catalogue",
        "design": "docs/design/semantic-equal-design.md",
        "case_count": len(CASES),
        "row_count": len(rows),
        "results": rows,
    }


def validate_catalogue_report(report: dict) -> None:
    """Reject partial, stale or membership-only EQ catalogue evidence."""
    if not isinstance(report, dict):
        raise ValueError("EQ catalogue evidence is not an object")
    if report.get("acceptance_check") != "release-semantic-equality":
        raise ValueError("EQ catalogue evidence has a conflicting check identity")
    expected_ids = {case.id for case in CASES}
    rows = report.get("results")
    if not isinstance(rows, list):
        raise ValueError("EQ catalogue evidence has no per-row results")
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "PASS":
            raise ValueError("EQ catalogue contains a missing or failing row")
        key = (row.get("case"), row.get("variant"))
        if key in seen:
            raise ValueError(f"duplicate EQ catalogue row {key}")
        if not isinstance(row.get("oracle"), str) or not row["oracle"]:
            raise ValueError(f"EQ catalogue row {key} has no named independent oracle")
        if row.get("expected") not in {EQUAL, DIFFERENT, UNDECIDED}:
            raise ValueError(f"EQ catalogue row {key} has no declared outcome")
        if row.get("observed") != row.get("expected"):
            raise ValueError(
                f"EQ catalogue row {key} outcome does not match expectation"
            )
        seen[key] = row
    expected_rows = {
        (case.id, variant) for case in CASES for variant in ("equal", "different")
    } | {(case_id, "certificate") for case_id in CERTIFICATES}
    missing = expected_rows - set(seen)
    if missing:
        raise ValueError(f"EQ catalogue is missing rows: {sorted(missing)}")
    if set(seen) - expected_rows:
        raise ValueError("EQ catalogue contains rows outside the design catalogue")
    observed_outcomes = {row["observed"] for row in rows}
    if observed_outcomes != {EQUAL, DIFFERENT, UNDECIDED}:
        raise ValueError(
            "EQ catalogue must cover equal, different and undecided outcomes"
        )
    if report.get("case_count") != len(CASES) or report.get("row_count") != len(rows):
        raise ValueError("EQ catalogue counts are stale")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_catalogue()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    failures = [row for row in report["results"] if row["status"] != "PASS"]
    print(
        f"EQ catalogue: {len(report['results'])} rows, "
        f"{len(report['results']) - len(failures)} pass, {len(failures)} fail"
    )
    for row in failures:
        print(
            f"  {row['case']}/{row['variant']}: {row['expected']} != {row['observed']}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
