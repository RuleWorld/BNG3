"""Atomizer symbol resolution: the contract, checked against an expectation.

Issue #164 ("Split Atomizer lowering and emission by semantic responsibility")
asks for characterization tests around symbol resolution, feature checks, event
planning, units, structural mapping and text output.  This module covers the
symbol-resolution and feature-check half of that surface.

It generates SBML models in which a named symbol is declared in a given scope
and carries a given SBML feature, and requires the Atomizer to resolve it the
way SBML says it must:

* a global symbol resolves to a global BNGL declaration;
* a reaction-local symbol resolves inside its own reaction and is not exported
  globally;
* a symbol used outside the scope that declares it has no representable
  meaning, so it must be refused by name and must not leak into the emitted
  model;
* a species resolves to a state pattern and not to a parameter;
* a compartment resolves to the compartment volume symbol;
* a user function resolves to an inlined call or an emitted function;
* an SBML feature that changes a symbol's meaning -- a conversion factor, a
  rate rule -- must be applied and reported.

The expectation for every generated case is written here from the SBML
semantics of the symbol's scope.  It is never read back from the Atomizer, so
a resolver that changes its answer, or that answers differently for a
different spelling of the same name, fails the check.

Scope: this characterizes the resolution contract of a generated family of
models.  It does not claim that every SBML symbol scope is supported, and the
executable check proves only that the emitted model compiles and generates a
network -- not that its dynamics match the source.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from .campaign import STATUSES

try:  # The atomizer is only required when the resolution family actually runs.
    from bionetgen.atomizer.modern import Atomizer
except ImportError:  # pragma: no cover - exercised by the harness guard
    Atomizer = None

try:  # The engine is the independent consumer of the emitted model.
    import bionetgen
except ImportError:  # pragma: no cover - exercised by the harness guard
    bionetgen = None

ISSUES = (164,)

# The scopes the generated family covers.  Each scope says where the symbol
# is declared and therefore where it may be referenced.
SCOPE_GLOBAL_PARAMETER = "global-parameter"
SCOPE_REACTION_LOCAL_PARAMETER = "reaction-local-parameter"
SCOPE_REACTION_LOCAL_OUT_OF_SCOPE = "reaction-local-out-of-scope"
SCOPE_SPECIES = "species"
SCOPE_COMPARTMENT = "compartment"
SCOPE_FUNCTION = "function"
SCOPE_RATE_RULE = "rate-rule"
SCOPE_CONVERSION_FACTOR = "conversion-factor"

# The names the family is generated over.  They exercise the spellings the
# resolver has to standardize, without colliding with a BNGL keyword.
GLOBAL_PARAMETER_NAMES = ("k", "kf", "rate_1")
REACTION_LOCAL_NAMES = ("lr", "k_local")
SPECIES_NAMES = ("S1", "S2")
COMPARTMENT_NAMES = ("cell", "cytosol")
FUNCTION_NAMES = ("twice", "lin")
CONVERSION_FACTOR_NAMES = ("cf", "scale_2")

# --------------------------------------------------------------------------- #
# Generated SBML models
# --------------------------------------------------------------------------- #


def _model(model_id, body, *, species=None, compartments=None):
    """Return an SBML document with the given compartments, species and body."""

    if species is None:
        species = (("S1", "cell", "2", ""), ("S2", "cell", "0", ""))
    if compartments is None:
        compartments = (("cell", "1"),)
    lines = [
        '<?xml version="1.0"?>',
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
        'level="3" version="1">',
        f'  <model id="{model_id}">',
        "    <listOfCompartments>",
    ]
    for compartment_id, size in compartments:
        lines.append(
            f'      <compartment id="{compartment_id}" size="{size}" '
            'constant="true"/>'
        )
    lines.append("    </listOfCompartments>")
    lines.append("    <listOfSpecies>")
    for species_id, compartment, amount, attributes in species:
        lines.append(
            f'      <species id="{species_id}" compartment="{compartment}" '
            f'initialAmount="{amount}" hasOnlySubstanceUnits="true"'
            f"{attributes}/>"
        )
    lines.append("    </listOfSpecies>")
    lines.append(body)
    lines.append("  </model>")
    lines.append("</sbml>")
    return "\n".join(lines) + "\n"


def _parameters(*entries):
    """Return a model-level parameter block."""
    lines = ["    <listOfParameters>"]
    for parameter_id, value in entries:
        lines.append(
            f'      <parameter id="{parameter_id}" value="{value}" constant="true"/>'
        )
    lines.append("    </listOfParameters>")
    return "\n".join(lines) + "\n"


def _reactions(*reactions):
    """Return a reaction block holding the given reactions."""
    lines = ["    <listOfReactions>"]
    for reaction in reactions:
        lines.extend(reaction)
    lines.append("    </listOfReactions>")
    return "\n".join(lines) + "\n"


def _reaction(
    rate,
    *,
    reactant="S1",
    product="S2",
    local_parameters=(),
    reaction_id="R1",
):
    """Return a reaction whose kinetic law is ``rate``."""
    lines = [
        f'      <reaction id="{reaction_id}" reversible="false">',
        "        <listOfReactants>"
        f'<speciesReference species="{reactant}" stoichiometry="1" constant="true"/>'
        "</listOfReactants>",
        "        <listOfProducts>"
        f'<speciesReference species="{product}" stoichiometry="1" constant="true"/>'
        "</listOfProducts>",
        "        <kineticLaw>",
        '          <math xmlns="http://www.w3.org/1998/Math/MathML">' f"{rate}</math>",
    ]
    if local_parameters:
        lines.append("          <listOfParameters>")
        for parameter_id, value in local_parameters:
            lines.append(
                f'            <parameter id="{parameter_id}" value="{value}" '
                'constant="true"/>'
            )
        lines.append("          </listOfParameters>")
    lines.append("        </kineticLaw>")
    lines.append("      </reaction>")
    return lines


# --------------------------------------------------------------------------- #
# The generated family
# --------------------------------------------------------------------------- #


def cases():
    """Return the generated symbol-resolution cases.

    Every case states the expectation independently of the Atomizer: the
    declarations the emitted model must carry, the declarations it must not
    carry, the diagnostics it must and must not report, and whether the
    emitted model must still compile.
    """
    result = []
    for name in GLOBAL_PARAMETER_NAMES:
        body = _parameters(("k", "0.5"), (name, "2")) + _reactions(
            _reaction(f"<ci>{name}</ci>")
        )
        result.append(
            {
                "id": f"global-parameter-{name}",
                "scope": SCOPE_GLOBAL_PARAMETER,
                "name": name,
                "features": ("global-parameter",),
                "sbml": _model(f"global_parameter_{name}", body),
                "expect": {
                    "parameters": (name,),
                    "absent_parameters": (),
                    "rule_contains": (("R1", name),),
                    "diagnostics": (),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    for name in REACTION_LOCAL_NAMES:
        body = _parameters(("k", "0.5")) + _reactions(
            _reaction(f"<ci>{name}</ci>", local_parameters=((name, "2"),))
        )
        result.append(
            {
                "id": f"reaction-local-parameter-{name}",
                "scope": SCOPE_REACTION_LOCAL_PARAMETER,
                "name": name,
                "features": ("reaction-local-parameter",),
                "sbml": _model(f"reaction_local_{name}", body),
                "expect": {
                    "parameters": (),
                    "absent_parameters": (name,),
                    "rule_contains": (("R1", " 2 "),),
                    "diagnostics": (),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    for name in REACTION_LOCAL_NAMES:
        body = _parameters(("k", "0.5")) + _reactions(
            _reaction(f"<ci>{name}</ci>", local_parameters=((name, "2"),)),
            _reaction(f"<ci>{name}</ci>", reaction_id="R2"),
        )
        result.append(
            {
                "id": f"reaction-local-out-of-scope-{name}",
                "scope": SCOPE_REACTION_LOCAL_OUT_OF_SCOPE,
                "name": name,
                "features": ("reaction-local-parameter", "cross-reaction-reference"),
                "sbml": _model(f"reaction_local_scope_{name}", body),
                "expect": {
                    "parameters": (),
                    "absent_parameters": (name,),
                    "rule_contains": (("R1", " 2 "),),
                    "absent_rule_labels": ("R2",),
                    "diagnostics": (("scope", name, "symbol-scope"),),
                    "absent_diagnostics": (),
                    "executable": True,
                },
            }
        )
    for name in SPECIES_NAMES:
        other = "S2" if name == "S1" else "S1"
        body = _parameters(("k", "0.5")) + _reactions(
            _reaction("<ci>k</ci>", reactant=name, product=other)
        )
        result.append(
            {
                "id": f"species-{name}",
                "scope": SCOPE_SPECIES,
                "name": name,
                "features": ("species",),
                "sbml": _model(
                    f"species_{name}",
                    body,
                    species=((name, "cell", "2", ""), (other, "cell", "0", "")),
                ),
                "expect": {
                    "parameters": (),
                    "absent_parameters": (name,),
                    "molecule_types": (f"M_{name}()",),
                    "diagnostics": (),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    for name in COMPARTMENT_NAMES:
        body = _parameters(("k", "0.5")) + _reactions(_reaction("<ci>k</ci>"))
        result.append(
            {
                "id": f"compartment-{name}",
                "scope": SCOPE_COMPARTMENT,
                "name": name,
                "features": ("compartment",),
                "sbml": _model(
                    f"compartment_{name}",
                    body,
                    species=(("S1", name, "2", ""), ("S2", name, "0", "")),
                    compartments=((name, "2"),),
                ),
                "expect": {
                    "parameters": (f"__compartment_{name}__",),
                    "absent_parameters": (),
                    "compartments": (name,),
                    "diagnostics": (),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    for name in FUNCTION_NAMES:
        body = (
            _parameters(("k", "0.5"))
            + """    <listOfFunctionDefinitions>
      <functionDefinition id="{name}">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <lambda><bvar><ci>x</ci></bvar><apply><times/><ci>x</ci><cn>2</cn></apply></lambda>
        </math>
      </functionDefinition>
    </listOfFunctionDefinitions>
""".format(name=name)
            + _reactions(_reaction(f"<apply><ci>{name}</ci><ci>k</ci></apply>"))
        )
        result.append(
            {
                "id": f"function-{name}",
                "scope": SCOPE_FUNCTION,
                "name": name,
                "features": ("function-definition",),
                "sbml": _model(f"function_{name}", body),
                "expect": {
                    "parameters": (),
                    "absent_parameters": (),
                    # An argument-taking SBML definition is inlined at its call
                    # site, so the emitted rate carries the expanded body and
                    # no unresolved call to the definition remains.
                    "rule_contains": (("R1", "* 2"),),
                    "absent_rule_tokens": (f"{name}(",),
                    "diagnostics": (),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    body = _parameters(("k", "0.5")) + """    <listOfRules>
      <rateRule variable="S1">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k</ci><ci>S1</ci></apply>
        </math>
      </rateRule>
    </listOfRules>
"""
    result.append(
        {
            "id": "rate-rule-S1",
            "scope": SCOPE_RATE_RULE,
            "name": "S1",
            "features": ("rate-rule",),
            "sbml": _model("rate_rule_S1", body, species=(("S1", "cell", "2", ""),)),
            "expect": {
                "parameters": (),
                "absent_parameters": ("S1",),
                "molecule_types": ("M_S1()",),
                "rule_contains": (("__rate_rule_S1", "TotalRate"),),
                "diagnostics": (),
                "absent_diagnostics": ("scope",),
                "executable": True,
            },
        }
    )
    for name in CONVERSION_FACTOR_NAMES:
        body = _parameters(("k", "0.5"), (name, "2")) + _reactions(
            _reaction("<ci>k</ci>")
        )
        result.append(
            {
                "id": f"conversion-factor-{name}",
                "scope": SCOPE_CONVERSION_FACTOR,
                "name": name,
                "features": ("conversion-factor",),
                "sbml": _model(
                    f"conversion_factor_{name}",
                    body,
                    species=(
                        ("S1", "cell", "2", f' conversionFactor="{name}"'),
                        ("S2", "cell", "0", ""),
                    ),
                ),
                "expect": {
                    "parameters": (name,),
                    "absent_parameters": (),
                    "rule_contains": (("R1", "2 *"),),
                    "diagnostics": (
                        ("conversionFactor", "conversionFactors", "conversion-factors"),
                    ),
                    "absent_diagnostics": ("scope",),
                    "executable": True,
                },
            }
        )
    return result


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    return [
        f"atomizer-symbol-resolution:{case['id']}:resolution-contract"
        for case in cases()
    ]


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
            "PASS": "supported-execution",
            "FAIL": "supported-execution",
        }.get(status, "harness-error"),
        "supported_execution": status == "PASS",
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
# Reading the emitted model
# --------------------------------------------------------------------------- #


def _block(text, name):
    """Return the body of a named BNGL block."""
    match = re.search(
        r"^begin %s\n(.*?)^end %s$" % (re.escape(name), re.escape(name)),
        text,
        re.S | re.M,
    )
    return match.group(1) if match else ""


def _declared_names(block):
    """Return the names a BNGL block declares."""
    names = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.append(stripped.split()[0])
    return names


def _rule_lines(block):
    """Return the emitted reaction-rule lines."""
    return [
        line.strip()
        for line in block.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _rule_line(block, label):
    """Return the emitted rule line whose label starts with ``label``.

    A writer may split one source reaction into several labelled rules (for
    example when a conversion factor forces species-specific flux rules), so
    the label is matched by prefix.
    """
    for line in _rule_lines(block):
        if line.split(":", 1)[0].strip().startswith(label):
            return line
    return None


# --------------------------------------------------------------------------- #
# The resolution contract
# --------------------------------------------------------------------------- #


def _resolve(case):
    """Atomize a generated case; return (bngl, diagnostics, error)."""
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    result = atomizer.atomize(case["sbml"])
    if not result.success:
        return "", [], result.error or "the atomizer reported no BNGL output"
    model = atomizer.get_model()
    if model is None:
        return "", [], "the atomizer retained no source model"
    return result.bngl, list(model.import_warnings), None


def _check_executable(bngl):
    """Return None when the emitted model compiles, else the failure text."""
    if bionetgen is None:
        return "the bionetgen engine is unavailable"
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "emitted.bngl"
        source.write_text(bngl, encoding="utf-8")
        try:
            model = bionetgen.load(str(source))
            model.generate_network()
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
    return None


def _check_case(case, directory):
    """Require the resolver to satisfy the case's independent expectation."""
    check = f"atomizer-symbol-resolution:{case['id']}:resolution-contract"
    work = directory / case["id"]
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source.sbml"
    source.write_text(case["sbml"], encoding="utf-8")
    try:
        bngl, diagnostics, error = _resolve(case)
    except Exception as exc:  # pragma: no cover - defensive
        return _failed(
            check,
            f"the {case['id']} case could not be evaluated: "
            f"{type(exc).__name__}: {exc}",
            {"field": "evaluation", "exception": type(exc).__name__},
            source,
        )
    if error is not None:
        return _failed(
            check,
            f"the {case['id']} case was refused instead of resolved: {error}",
            {"field": "refusal", "detail": error},
            source,
        )
    expect = case["expect"]
    parameters = _declared_names(_block(bngl, "parameters"))
    molecule_types = _declared_names(_block(bngl, "molecule types"))
    functions = _declared_names(_block(bngl, "functions"))
    compartments = _declared_names(_block(bngl, "compartments"))
    rules = _block(bngl, "reaction rules")

    for name in expect.get("parameters", ()):
        if name not in parameters:
            return _failed(
                check,
                f"the {case['id']} symbol {name!r} did not resolve to the "
                f"declared BNGL parameter(s) {sorted(parameters)}",
                {
                    "field": "parameters",
                    "expected": sorted(set(expect.get("parameters", ()))),
                    "observed": sorted(parameters),
                },
                source,
            )
    for name in expect.get("absent_parameters", ()):
        if name in parameters:
            return _failed(
                check,
                f"the {case['id']} symbol {name!r} resolved to a global BNGL "
                "parameter even though its scope does not allow one",
                {
                    "field": "absent-parameters",
                    "expected_absent": name,
                    "observed": sorted(parameters),
                },
                source,
            )
    for name in expect.get("molecule_types", ()):
        if name not in molecule_types:
            return _failed(
                check,
                f"the {case['id']} symbol did not resolve to the molecule type "
                f"{name!r}",
                {
                    "field": "molecule-types",
                    "expected": sorted(set(expect.get("molecule_types", ()))),
                    "observed": sorted(molecule_types),
                },
                source,
            )
    for name in expect.get("functions", ()):
        if name not in functions:
            return _failed(
                check,
                f"the {case['id']} symbol did not resolve to the BNGL function "
                f"{name!r}",
                {
                    "field": "functions",
                    "expected": sorted(set(expect.get("functions", ()))),
                    "observed": sorted(functions),
                },
                source,
            )
    for name in expect.get("compartments", ()):
        if name not in compartments:
            return _failed(
                check,
                f"the {case['id']} symbol did not resolve to the BNGL "
                f"compartment {name!r}",
                {
                    "field": "compartments",
                    "expected": sorted(set(expect.get("compartments", ()))),
                    "observed": sorted(compartments),
                },
                source,
            )
    for label, token in expect.get("rule_contains", ()):
        line = _rule_line(rules, label)
        if line is None:
            return _failed(
                check,
                f"the {case['id']} model emitted no reaction rule labelled "
                f"{label!r}",
                {"field": "rule", "expected_label": label, "observed": rules},
                source,
            )
        if token not in line:
            return _failed(
                check,
                f"the {case['id']} reaction rule {label!r} does not carry the "
                f"resolved symbol {token!r}",
                {
                    "field": "rule",
                    "expected_label": label,
                    "expected_token": token,
                    "observed": line,
                },
                source,
            )
    for label in expect.get("absent_rule_labels", ()):
        if _rule_line(rules, label) is not None:
            return _failed(
                check,
                f"the {case['id']} model emitted the reaction rule {label!r} "
                "even though its rate law has no representable scope",
                {
                    "field": "absent-rule",
                    "expected_absent": label,
                    "observed": rules,
                },
                source,
            )
    for token in expect.get("absent_rule_tokens", ()):
        if token in rules:
            return _failed(
                check,
                f"the {case['id']} emitted rules still reference {token!r}",
                {"field": "absent-rule-token", "expected_absent": token},
                source,
            )
    for category, token, group in expect.get("diagnostics", ()):
        matches = [
            warning
            for warning in diagnostics
            if str(warning.get("category")) == category
            and token.lower() in str(warning.get("message", "")).lower()
        ]
        if not matches:
            return _failed(
                check,
                f"the {case['id']} case produced no {category!r} diagnostic "
                f"naming {token!r}",
                {
                    "field": "diagnostic",
                    "expected_category": category,
                    "expected_token": token,
                    "observed": [
                        [
                            str(warning.get("category")),
                            str(warning.get("group")),
                            str(warning.get("message")),
                        ]
                        for warning in diagnostics
                    ],
                },
                source,
            )
        observed_groups = sorted({str(warning.get("group", "")) for warning in matches})
        if observed_groups != [group]:
            return _failed(
                check,
                f"the {case['id']} diagnostic recorded the class "
                f"{observed_groups} instead of {[group]}",
                {
                    "field": "diagnostic-group",
                    "expected": group,
                    "observed": observed_groups,
                },
                source,
            )
    for category in expect.get("absent_diagnostics", ()):
        present = [
            str(warning.get("message", ""))
            for warning in diagnostics
            if str(warning.get("category")) == category
        ]
        if present:
            return _failed(
                check,
                f"the {case['id']} case reported a {category!r} diagnostic "
                f"although its symbols resolve: {present}",
                {
                    "field": "absent-diagnostic",
                    "expected_absent": category,
                    "observed": present,
                },
                source,
            )
    if expect.get("executable"):
        failure = _check_executable(bngl)
        if failure is not None:
            return _failed(
                check,
                f"the {case['id']} model emitted by the Atomizer does not "
                f"compile: {failure}",
                {"field": "executable", "detail": failure},
                source,
            )
    return _passed(
        check,
        f"the {case['id']} symbol resolved as the {case['scope']} scope " "requires",
        source,
    )


def run_worker(directory, *, bng_cpp=None):
    """Run the symbol-resolution family and return its evidence rows."""
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

    rows = [_check_case(case, directory) for case in cases()]

    summary = {
        "scopes": sorted({case["scope"] for case in cases()}),
        "cases": [case["id"] for case in cases()],
    }
    (directory / "resolution.json").write_text(
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
