"""Unsupported SBML construct classes: every refusal names its construct.

Issue #160 ("Disposition unsupported SBML semantics by feature class") asks for
the current unsupported cases to be grouped by dynamic rules and events,
history, algebraic constraints, stoichiometry, fast reactions and packages,
and for that grouping to be *executable* so that a newly unsupported case
becomes visible.

This module generates one SBML model per unsupported construct and requires
the Atomizer to report a diagnostic that

* identifies the construct -- its category is the construct's own identity and
  its message names the construct in words, and
* records the construct's class in the diagnostic's ``group`` field.

The expectation for every generated case is written here from the SBML
semantics of the construct.  It is never read back from the Atomizer, so a
model that is refused for an unnamed reason, or a diagnostic that stops naming
its construct, fails the check instead of quietly joining a generic bucket.

The corpus check closes the same gap from the other side: every diagnostic the
generated corpus produces that refuses or approximates a construct must carry a
named class.  A newly introduced refusal category that nobody classified fails
that check.

Scope: this is a classification boundary, not a support claim.  A passing
report says the refusal names its construct and its class; it does not say the
construct is supported, and it does not cover constructs outside the generated
corpus.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .campaign import STATUSES

try:  # The atomizer is only required when the boundary actually runs.
    from bionetgen.atomizer.modern import Atomizer
except ImportError:  # pragma: no cover - exercised by the harness guard
    Atomizer = None

ISSUES = (160,)

# The unsupported-construct classes issue #160 names.  The harness states the
# class independently of the Atomizer; the Atomizer records the same class on
# the diagnostic it emits.
GROUP_DYNAMIC_RULES = "dynamic-rules"
GROUP_EVENTS = "events"
GROUP_HISTORY = "history"
GROUP_ALGEBRAIC_CONSTRAINTS = "algebraic-constraints"
GROUP_STOICHIOMETRY = "stoichiometry"
GROUP_FAST_REACTIONS = "fast-reactions"
GROUP_PACKAGES = "packages"

# Every class the generated corpus can produce, so that a class outside the
# seven named ones is still a named class rather than an unnamed refusal.
KNOWN_GROUPS = (
    GROUP_DYNAMIC_RULES,
    GROUP_EVENTS,
    GROUP_HISTORY,
    GROUP_ALGEBRAIC_CONSTRAINTS,
    GROUP_STOICHIOMETRY,
    GROUP_FAST_REACTIONS,
    GROUP_PACKAGES,
    "conversion-factors",
    "symbol-scope",
    "identifier-collisions",
    "reaction-kinetics",
    "compartments",
    "parameters",
    "units",
    "mathml",
)

# A refusal or an approximation is a boundary the reader has to see.  An
# informational note is not, so it is not required to be classified.
REFUSAL_SEVERITIES = ("dropped", "approximated")

_MODEL_HEAD = """<?xml version="1.0"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"{namespaces}
      level="3" version="1">
  <model id="{model_id}">
    <listOfCompartments>
      <compartment id="cell" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialAmount="2" hasOnlySubstanceUnits="true"/>
      <species id="B" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.5" constant="true"/>
    </listOfParameters>
{body}
  </model>
</sbml>
"""

_REACTION = """    <listOfReactions>
      <reaction id="R1" reversible="false"{fast}>
        <listOfReactants>
          <speciesReference species="A" stoichiometry="{stoichiometry}" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
"""

# Each case is one SBML construct that BNG3 does not represent exactly.  The
# expectation is written from the SBML semantics of the construct:
#
#   category   the machine-readable identity the diagnostic must carry;
#   token      the word the diagnostic message must use to name the construct;
#   group      the unsupported-construct class the diagnostic must record.
CASES = (
    {
        "id": "species-assignment-rule",
        "group": GROUP_DYNAMIC_RULES,
        "category": "speciesAssignmentRule",
        "token": "assignment rule",
        "description": (
            "an assignment rule on a species is an algebraic state that BNGL "
            "cannot enforce"
        ),
        "body": """    <listOfRules>
      <assignmentRule variable="A">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>2</cn><ci>B</ci></apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="B">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><cn>3</cn><ci>A</ci></apply>
        </math>
      </assignmentRule>
    </listOfRules>
""",
    },
    {
        "id": "state-dependent-event",
        "group": GROUP_EVENTS,
        "category": "event",
        "token": "event",
        "description": (
            "an event whose assignment value depends on the model state has no "
            "schedule BNG3 can execute"
        ),
        "body": """    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>k</ci></math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <listOfEvents>
      <event id="E1" useValuesFromTriggerTime="true">
        <trigger initialValue="false" persistent="true">
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><gt/><csymbol definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply>
          </math>
        </trigger>
        <listOfEventAssignments>
          <eventAssignment variable="k">
            <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math>
          </eventAssignment>
        </listOfEventAssignments>
      </event>
    </listOfEvents>
""",
    },
    {
        "id": "delayed-history",
        "group": GROUP_HISTORY,
        "category": "mathml",
        "token": "delay",
        "description": (
            "an SBML delay() call needs the solution history of a state "
            "variable, which BNGL has no way to express"
        ),
        "body": """    <listOfRules>
      <rateRule variable="A">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><apply><delay/><ci>A</ci><cn>1</cn></apply></apply>
        </math>
      </rateRule>
    </listOfRules>
""",
    },
    {
        "id": "algebraic-rule",
        "group": GROUP_ALGEBRAIC_CONSTRAINTS,
        "category": "algebraicRule",
        "token": "algebraic rule",
        "description": (
            "an algebraic rule is an implicit DAE constraint with no BNGL " "equivalent"
        ),
        "body": """    <listOfRules>
      <algebraicRule>
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
      </algebraicRule>
    </listOfRules>
""",
    },
    {
        "id": "sbml-constraint",
        "group": GROUP_ALGEBRAIC_CONSTRAINTS,
        "category": "constraint",
        "token": "constraint",
        "description": ("an SBML constraint is not enforced during simulation"),
        "body": """    <listOfConstraints>
      <constraint>
        <math xmlns="http://www.w3.org/1998/Math/MathML"><cn>0</cn></math>
      </constraint>
    </listOfConstraints>
""",
    },
    {
        "id": "negative-stoichiometry",
        "group": GROUP_STOICHIOMETRY,
        "category": "stoichiometry",
        "token": "stoichiometry",
        "description": (
            "a negative stoichiometry has no BNGL pattern; the reaction is " "omitted"
        ),
        "body": _REACTION.format(fast="", stoichiometry="-1"),
    },
    {
        "id": "fast-reaction",
        "group": GROUP_FAST_REACTIONS,
        "category": "fastReaction",
        "token": "fast",
        "description": (
            "an SBML fast reaction asks for a pseudo steady-state "
            "approximation, which BNG3 does not solve"
        ),
        "body": _REACTION.format(fast=' fast="true"', stoichiometry="1"),
    },
    {
        "id": "fbc-package",
        "group": GROUP_PACKAGES,
        "category": "package:fbc",
        "token": "fbc",
        "description": (
            "the flux-balance-constraints package carries no kinetic model"
        ),
        "namespaces": (
            '\n      xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/'
            'version2"\n      fbc:required="true"'
        ),
        "body": """    <fbc:listOfFluxBounds>
      <fbc:fluxBound operation="lessEqual" value="1" reaction="R1"/>
    </fbc:listOfFluxBounds>
"""
        + _REACTION.format(fast="", stoichiometry="1"),
    },
    {
        "id": "spatial-package",
        "group": GROUP_PACKAGES,
        "category": "package:spatial",
        "token": "spatial",
        "description": (
            "the spatial package carries geometry and diffusion that the "
            "compartment model does not express"
        ),
        "namespaces": (
            '\n      xmlns:spatial="http://www.sbml.org/sbml/level3/version1/'
            'spatial/version2"\n      spatial:required="true"'
        ),
        "body": """    <spatial:listOfGeometries>
      <spatial:geometry sboTerm="SBO:0004006">
        <spatial:scaledShape spatial:scalarMultiple="1">
          <spatial:shape>
            <spatial:cylinder spatial:radius="1" spatial:height="1"/>
          </spatial:shape>
        </spatial:scaledShape>
      </spatial:geometry>
    </spatial:listOfGeometries>
"""
        + _REACTION.format(fast="", stoichiometry="1"),
    },
)


def cases():
    """Return the generated unsupported-construct cases."""
    return [dict(case) for case in CASES]


def case_sbml(case):
    """Return the SBML source of a generated case."""
    return _MODEL_HEAD.format(
        namespaces=case.get("namespaces", ""),
        model_id=case["id"].replace("-", "_"),
        body=case["body"],
    )


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    ids = [f"sbml-support-boundary:{case['id']}:named-diagnostic" for case in cases()]
    ids.append("sbml-support-boundary:corpus:every-refusal-classified")
    return ids


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def _row(check, status, detail, *, first_difference=None, artifact=None):
    row = {
        "id": check,
        "check": check.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "evidence_kind": {
            "PASS": "diagnostic-only",
            "UNSUPPORTED": "diagnostic-only",
            "FAIL": "diagnostic-only",
        }.get(status, "harness-error"),
        # A recorded refusal proves a boundary, not that the format supports
        # the construct.
        "supported_execution": False,
    }
    if artifact is not None:
        row["source_artifact"] = artifact.name
        row["source_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return row


def _failed(check, detail, difference=None, artifact=None):
    return _row(check, "FAIL", detail, first_difference=difference, artifact=artifact)


def _passed(check, detail, artifact=None):
    return _row(check, "PASS", detail, artifact=artifact)


# --------------------------------------------------------------------------- #
# The boundary itself
# --------------------------------------------------------------------------- #


def _diagnostics(case):
    """Atomize a generated case and return (diagnostics, error).

    ``error`` is set when the Atomizer refused the model instead of reporting
    a named diagnostic; that is an unnamed refusal and fails the check.
    """
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(case_sbml(case))
    if not result.success:
        return [], result.error or "the atomizer reported no BNGL output"
    model = atomizer.get_model()
    if model is None:
        return [], "the atomizer retained no source model"
    return list(model.import_warnings), None


def _named_diagnostic(case, diagnostics):
    """Return the diagnostic that names the case's construct, if there is one."""
    for warning in diagnostics:
        if str(warning.get("category")) != case["category"]:
            continue
        message = str(warning.get("message", ""))
        if case["token"].lower() in message.lower():
            return warning
    return None


def _check_case(case, directory):
    """Require a diagnostic that names the construct and records its class.

    Returns the evidence row and the diagnostics the case produced, so the
    corpus check can classify every refusal without atomizing twice.
    """
    check = f"sbml-support-boundary:{case['id']}:named-diagnostic"
    work = directory / case["id"]
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source.sbml"
    source.write_text(case_sbml(case), encoding="utf-8")
    try:
        diagnostics, error = _diagnostics(case)
    except Exception as exc:  # pragma: no cover - defensive
        return (
            _failed(
                check,
                f"the {case['id']} case could not be evaluated: "
                f"{type(exc).__name__}: {exc}",
                {"field": "evaluation", "exception": type(exc).__name__},
                source,
            ),
            [],
        )
    if error is not None:
        return (
            _failed(
                check,
                f"the {case['id']} case was refused without a named diagnostic: "
                f"{error}",
                {"field": "unnamed-refusal", "detail": error},
                source,
            ),
            diagnostics,
        )
    warning = _named_diagnostic(case, diagnostics)
    if warning is None:
        observed = sorted(
            (str(w.get("category")), str(w.get("group")), str(w.get("message")))
            for w in diagnostics
        )
        return (
            _failed(
                check,
                f"the {case['id']} case produced no diagnostic naming "
                f"{case['description']}",
                {
                    "field": "named-diagnostic",
                    "expected_category": case["category"],
                    "expected_token": case["token"],
                    "expected_group": case["group"],
                    "observed": [list(item) for item in observed],
                },
                source,
            ),
            diagnostics,
        )
    group = str(warning.get("group", ""))
    if group != case["group"]:
        return (
            _failed(
                check,
                f"the {case['id']} diagnostic named the construct but recorded the "
                f"class {group!r} instead of {case['group']!r}",
                {
                    "field": "group",
                    "expected": case["group"],
                    "observed": group,
                },
                source,
            ),
            diagnostics,
        )
    return (
        _passed(
            check,
            f"the {case['id']} diagnostic names {case['description']} and records "
            f"the class {case['group']!r}",
            source,
        ),
        diagnostics,
    )


def _check_corpus(diagnostics_by_case):
    """Require every refusal in the generated corpus to carry a named class."""
    check = "sbml-support-boundary:corpus:every-refusal-classified"
    unclassified = []
    for case_id, diagnostics in sorted(diagnostics_by_case.items()):
        for warning in diagnostics:
            severity = str(warning.get("severity", ""))
            if severity not in REFUSAL_SEVERITIES:
                continue
            group = str(warning.get("group", ""))
            if group and group in KNOWN_GROUPS:
                continue
            unclassified.append(
                {
                    "case": case_id,
                    "category": str(warning.get("category", "")),
                    "severity": severity,
                    "group": group,
                    "message": str(warning.get("message", "")),
                }
            )
    if unclassified:
        return _failed(
            check,
            "the generated corpus produced refusals that do not record a "
            "named unsupported-construct class",
            {"field": "unclassified-refusals", "refusals": unclassified},
        )
    return _passed(
        check,
        "every refusal and approximation in the generated corpus records a "
        "named unsupported-construct class",
    )


def run_worker(directory, *, bng_cpp=None):
    """Run the unsupported-construct boundary and return its evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if Atomizer is None:
        return [
            _row(
                check,
                "NOT_TESTED",
                "the bionetgen atomizer is unavailable",
            )
            for check in check_ids()
        ]

    rows = []
    diagnostics_by_case = {}
    for case in cases():
        row, diagnostics = _check_case(case, directory)
        rows.append(row)
        diagnostics_by_case[case["id"]] = diagnostics
    rows.append(_check_corpus(diagnostics_by_case))

    summary = {
        "groups": sorted({case["group"] for case in cases()}),
        "cases": [case["id"] for case in cases()],
        "refusal_severities": list(REFUSAL_SEVERITIES),
    }
    (directory / "boundary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path)
    args = parser.parse_args(argv)
    rows = run_worker(args.report_dir, bng_cpp=args.bng_cpp)
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
