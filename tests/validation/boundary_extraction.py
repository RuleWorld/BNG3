"""The extracted total-rate capability boundary (#164).

Issue #164 asks for cohesive capability boundaries to be extracted
incrementally, without changing the supported semantics and without
introducing parallel implementations.

This family qualifies one such extraction: the *total-rate* capability.  A
rule whose rate law carries the ``TotalRate`` modifier states the complete
macroscopic reaction rate, so its reaction carries neither the reaction
centre's symmetry factor nor the reactant concentration factors.  Before the
extraction that decision lived in seven translation units - the network
writer, the SBML writer, the SBML reader, the BNG-XML writer, the ODE
integrator, the PSA simulator and the compiled model's modifier vocabulary -
and the copies did not agree: the SBML writer looked the rule up by the
reaction's origin name and therefore did not see the reverse direction of a
rule, and the PSA simulator matched the modifier's spelling case-sensitively
while the writers matched it without regard to case.

The capability now lives behind one named seam, ``bng::compile``'s total-rate
contract (``cpp/compile/TotalRate.hpp``).  The family has three checks.

``seam-ownership``
    The capability lives behind one named seam: the seam exists and declares
    the documented contract, every consumer of the decision asks the seam, no
    other translation unit defines the seam's API, and no other translation
    unit decides the question by comparing a value against the modifier's
    spelling.  The grammar owns the token of the language and the producers
    of the modifier text name the spelling without deciding anything, so
    neither is a second owner of the capability.

``caller-agreement``
    The callers that used to duplicate the decision now agree on its outcome.
    The generated family covers a forward-only TotalRate rule, an ordinary
    forward rule with repeated reactants, a reversible TotalRate rule, an
    ordinary reversible rule and a model that mixes both kinds.  The network
    writer's applied statistical factor, the SBML writer's kinetic law and the
    model source's own declaration must express the same rate for every
    reaction.  The expectation is written by the case table, not by the
    writers.

``semantics-unchanged``
    The supported semantics did not change.  The proof is the *existing*
    qualified checks that cover the affected surface - the rate-law contract
    and the network-rule execution contract - executed unchanged.  This family
    states no new expectation for them and rewrites none of their rows; it
    only records their outcome.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .campaign import STATUSES

ISSUES = (164,)
OPERATION = "boundary-extraction"

# The named checks of this operation.
CHECKS = ("seam-ownership", "caller-agreement", "semantics-unchanged")

# The obligation of issue #164 that this family closes.
OBLIGATION_CHECK = "extract-cohesive-boundaries-incrementally-without-changing-suppo"

ROOT = Path(__file__).resolve().parents[2]

# The named seam that owns the capability.
SEAM_HEADER = ROOT / "cpp" / "compile" / "TotalRate.hpp"
SEAM_SOURCE = ROOT / "cpp" / "compile" / "TotalRate.cpp"

# The contract the seam declares.
SEAM_API = (
    "isTotalRateModifier",
    "isTotalRateMarkerName",
    "hasTotalRateModifier",
    "isTotalRateRule",
    "isTotalRateReaction",
    "resolveOriginRule",
)

# The translation units that need the decision.  Each one has to ask the seam
# instead of deriving the answer itself.
CONSUMERS = (
    "cpp/compile/CompiledRule.cpp",
    "cpp/engine/OdeIntegrator.cpp",
    "cpp/engine/PsaSimulator.cpp",
    "cpp/io/NetWriter.cpp",
    "cpp/io/SbmlReader.cpp",
    "cpp/io/SbmlWriter.cpp",
    "cpp/io/XmlWriter.cpp",
)

# The translation units that may hold the modifier's spelling without owning
# the decision: the grammar defines the token, the generated parser repeats
# it, and the vendored upstream NFsim keeps its own spelling.
SPELLING_OWNERS = (
    "cpp/parser/BNGLexer.g4",
    "cpp/parser/BNGParser.g4",
)

# The vendored upstream NFsim and the generated parser are not BNG3's own
# translation units and are not scanned.
SCAN_EXCLUDED = ("cpp/nfsim/", "cpp/parser/generated/")

# The spelling of the modifier as a C++ or grammar string literal.
SPELLING_LITERAL = re.compile(r"""["'](?i:totalrate)["']""")

# A comparison against the spelling decides the capability; a mention does not.
COMPARISON = re.compile(r"(==|!=|compare\s*\(|find\s*\()\s*$")

# A definition of one of the seam's names outside the seam is a second owner.
SEAM_DEFINITION = re.compile(
    r"^\s*(?:bool|std::string|OriginRule)\s+(" + "|".join(SEAM_API) + r")\s*\(",
    re.MULTILINE,
)

# The qualified checks that cover the affected surface.  They are executed
# unchanged; the family records their outcome and states no new expectation
# for them.
COVERING_FAMILIES = ("rate_law_contract", "netrule_execution")


# --------------------------------------------------------------------------- #
# The generated family.
# --------------------------------------------------------------------------- #

# Every case states the rate of every reaction it generates.  ``total_rate``
# is the capability's outcome and ``factor`` is the statistical factor the
# network writer has to apply: a total rate carries none, an ordinary
# reaction carries the 1/n! correction of its identical reactants.
CASES = (
    {
        "id": "total-forward-3a",
        "bngl": """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  f: A() + A() + A() -> 0 k TotalRate
end reaction rules
end model
""",
        "reactions": [
            {"total_rate": True, "factor": 1.0, "reactants": [1, 1, 1], "products": []}
        ],
    },
    {
        "id": "ordinary-forward-3a",
        "bngl": """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  f: A() + A() + A() -> 0 k
end reaction rules
end model
""",
        "reactions": [
            {
                "total_rate": False,
                "factor": 1.0 / 6.0,
                "reactants": [1, 1, 1],
                "products": [],
            }
        ],
    },
    {
        "id": "total-reversible-2a",
        "bngl": """
begin model
begin parameters
  kf 0.5
  kr 0.2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  f: A() + A() <-> B() + B() kf, kr TotalRate
end reaction rules
end model
""",
        "reactions": [
            {
                "total_rate": True,
                "factor": 1.0,
                "reactants": [1, 1],
                "products": [2, 2],
            },
            {
                "total_rate": True,
                "factor": 1.0,
                "reactants": [2, 2],
                "products": [1, 1],
            },
        ],
    },
    {
        "id": "ordinary-reversible-2a",
        "bngl": """
begin model
begin parameters
  kf 0.5
  kr 0.2
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  f: A() + A() <-> B() + B() kf, kr
end reaction rules
end model
""",
        "reactions": [
            {
                "total_rate": False,
                "factor": 0.5,
                "reactants": [1, 1],
                "products": [2, 2],
            },
            {
                "total_rate": False,
                "factor": 0.5,
                "reactants": [2, 2],
                "products": [1, 1],
            },
        ],
    },
    {
        "id": "mixed-total-and-ordinary",
        "bngl": """
begin model
begin parameters
  kt 0.5
  ko 0.25
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin reaction rules
  total: A() + A() -> 0 kt TotalRate
  ordinary: B() + B() -> 0 ko
end reaction rules
end model
""",
        "reactions": [
            {"total_rate": True, "factor": 1.0, "reactants": [1, 1], "products": []},
            {
                "total_rate": False,
                "factor": 0.5,
                "reactants": [2, 2],
                "products": [],
            },
        ],
    },
)


def check_ids():
    """Stable expected check identities for the boundary-extraction operation."""
    ids = [f"{OPERATION}:{name}" for name in CHECKS]
    ids.append(f"qualification:issue:164:{OBLIGATION_CHECK}")
    return ids


def _row(check, status, detail, *, first_difference=None, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="the-extracted-capability-is-one-named-seam",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


# --------------------------------------------------------------------------- #
# The seam-ownership check.
# --------------------------------------------------------------------------- #


def _cpp_sources(root):
    """The BNG3-owned C++ translation units, in a stable order."""
    sources = []
    for path in sorted((root / "cpp").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(relative.startswith(prefix) for prefix in SCAN_EXCLUDED):
            continue
        if path.suffix not in {".cpp", ".hpp", ".h", ".g4"}:
            continue
        sources.append((relative, path))
    return sources


def seam_differences(root=None):
    """The differences between the seam's declared contract and the tree."""
    root = Path(root) if root is not None else ROOT
    header = root / "cpp" / "compile" / "TotalRate.hpp"
    source = root / "cpp" / "compile" / "TotalRate.cpp"
    differences = []
    if not header.is_file():
        differences.append(
            dict(field="seam.header", expected="cpp/compile/TotalRate.hpp", actual=None)
        )
        return differences
    if not source.is_file():
        differences.append(
            dict(field="seam.source", expected="cpp/compile/TotalRate.cpp", actual=None)
        )
    header_text = header.read_text(encoding="utf-8")
    for name in SEAM_API:
        if name not in header_text:
            differences.append(
                dict(
                    field="seam.api",
                    expected=name,
                    actual="the seam does not declare it",
                )
            )
    for relative in CONSUMERS:
        path = root / relative
        if not path.is_file():
            differences.append(
                dict(field="consumer.missing", expected=relative, actual=None)
            )
            continue
        text = path.read_text(encoding="utf-8")
        # A consumer inside the compile namespace calls the seam unqualified;
        # every other consumer has to name the namespace.  A local definition
        # that shadows the seam is refused by the definition rule below.
        if relative.startswith("cpp/compile/"):
            calls = any(name + "(" in text for name in SEAM_API)
        else:
            calls = any("compile::" + name + "(" in text for name in SEAM_API)
        if not calls:
            differences.append(
                dict(
                    field="consumer.does-not-call-the-seam",
                    expected=relative,
                    actual="the consumer does not call the total-rate seam",
                )
            )
    owners = {
        header.relative_to(root).as_posix(),
        source.relative_to(root).as_posix(),
    }
    for relative, path in _cpp_sources(root):
        if relative in owners or relative in SPELLING_OWNERS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in SEAM_DEFINITION.finditer(text):
            differences.append(
                dict(
                    field="seam.defined-twice",
                    expected="the seam owns " + match.group(1),
                    actual=relative,
                )
            )
        for match in SPELLING_LITERAL.finditer(text):
            start = match.start()
            prefix = text[max(0, start - 40) : start]
            if not COMPARISON.search(prefix):
                continue
            differences.append(
                dict(
                    field="spelling.decided-outside-the-seam",
                    expected="the seam owns the modifier's spelling",
                    actual=f"{relative}: {match.group(0)}",
                )
            )
    return differences


# --------------------------------------------------------------------------- #
# The caller-agreement check.
# --------------------------------------------------------------------------- #

NET_REACTION = re.compile(
    r"^\s*(?P<id>\d+)\s+(?P<reactants>[\d,]*)\s+(?P<products>[\d,]*)\s+(?P<rate>\S+)"
    r"(?:\s+#(?P<comment>\S+))?\s*$"
)
NET_FACTOR = re.compile(r"^(?P<factor>[-+0-9.eE]+)\*(?P<rate>.+)$")
SBML_REACTION = re.compile(r"<reaction\b.*?</reaction>", re.DOTALL)
SBML_ANNOTATION = "<bng:totalRate"
SBML_CIN = re.compile(r"<cn>\s*(?P<value>[-+0-9.eE]+)\s*</cn>")
SBML_CI = re.compile(r"<ci>\s*(?P<value>[^<]*)\s*</ci>")
SBML_SPECIES = re.compile(r"^S(?P<index>\d+)$")


def _species_list(text):
    """The species of one side of a network reaction.

    The network file writes "0" for a side that has no species: a source or a
    sink of the reaction.
    """
    if not text or text == "0":
        return []
    return [int(part) for part in text.split(",") if part]


def _net_reactions(text):
    """The reactions of a network file, with the factor the writer applied."""
    reactions = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "begin reactions":
            inside = True
            continue
        if stripped == "end reactions":
            break
        if not inside or not stripped:
            continue
        match = NET_REACTION.match(line)
        if match is None:
            continue
        rate = match.group("rate")
        factor = 1.0
        factor_match = NET_FACTOR.match(rate)
        if factor_match is not None:
            factor = float(factor_match.group("factor"))
            rate = factor_match.group("rate")
        reactions.append(
            dict(
                index=int(match.group("id")),
                reactants=_species_list(match.group("reactants")),
                products=_species_list(match.group("products")),
                rate=rate,
                factor=factor,
                rule=match.group("comment"),
            )
        )
    return reactions


def _sbml_reactions(text):
    """The reactions of an SBML document, with the total-rate marker."""
    reactions = []
    for block in SBML_REACTION.findall(text):
        law = re.search(r"<kineticLaw>.*?</kineticLaw>", block, re.DOTALL)
        law_text = law.group(0) if law else ""
        annotated = SBML_ANNOTATION in block
        constants = [float(value) for value in SBML_CIN.findall(law_text)]
        identifiers = [value.strip() for value in SBML_CI.findall(law_text)]
        # The kinetic law names the reactant species it multiplies the rate by.
        species = sorted(
            {
                int(match.group("index"))
                for value in identifiers
                for match in [SBML_SPECIES.match(value)]
                if match is not None
            }
        )
        reactions.append(
            dict(
                annotated=annotated,
                factor=constants[0] if constants else 1.0,
                identifiers=identifiers,
                species=species,
            )
        )
    return reactions


def _close(left, right):
    return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(right)))


def caller_differences(case, net_reactions, sbml_reactions):
    """The differences between the two writers and the case's own expectation."""
    differences = []
    expected = case["reactions"]
    if len(net_reactions) != len(expected) or len(sbml_reactions) != len(expected):
        differences.append(
            dict(
                field="reaction.count",
                expected=len(expected),
                actual={"net": len(net_reactions), "sbml": len(sbml_reactions)},
            )
        )
        return differences
    for index, wanted in enumerate(expected):
        net = net_reactions[index]
        sbml = sbml_reactions[index]
        if (
            net["reactants"] != wanted["reactants"]
            or net["products"] != wanted["products"]
        ):
            differences.append(
                dict(
                    field=f"reaction[{index}].participants",
                    expected={
                        "reactants": wanted["reactants"],
                        "products": wanted["products"],
                    },
                    actual={"reactants": net["reactants"], "products": net["products"]},
                )
            )
        # The SBML writer marks the capability explicitly; the marker and the
        # model's own declaration have to agree.
        if sbml["annotated"] != wanted["total_rate"]:
            differences.append(
                dict(
                    field=f"reaction[{index}].sbml.total-rate-marker",
                    expected=wanted["total_rate"],
                    actual=sbml["annotated"],
                )
            )
        # A total rate states the complete flux, so its kinetic law carries
        # neither the symmetry factor nor the reactant concentrations.  An
        # ordinary reaction carries both.
        if wanted["total_rate"]:
            if sbml["species"]:
                differences.append(
                    dict(
                        field=f"reaction[{index}].sbml.reactant-concentration",
                        expected=[],
                        actual=sbml["species"],
                    )
                )
            if not _close(sbml["factor"], 1.0):
                differences.append(
                    dict(
                        field=f"reaction[{index}].sbml.factor",
                        expected=1.0,
                        actual=sbml["factor"],
                    )
                )
        else:
            if not sbml["species"]:
                differences.append(
                    dict(
                        field=f"reaction[{index}].sbml.reactant-concentration",
                        expected="the reactant species of the reaction",
                        actual=[],
                    )
                )
            if not _close(sbml["factor"], wanted["factor"]):
                differences.append(
                    dict(
                        field=f"reaction[{index}].sbml.factor",
                        expected=wanted["factor"],
                        actual=sbml["factor"],
                    )
                )
        # The network writer applies the statistical factor; a total rate
        # carries none.
        if not _close(net["factor"], wanted["factor"]):
            differences.append(
                dict(
                    field=f"reaction[{index}].net.factor",
                    expected=wanted["factor"],
                    actual=net["factor"],
                )
            )
        # The two writers have to agree on the capability itself.
        if sbml["annotated"] and not _close(net["factor"], 1.0):
            differences.append(
                dict(
                    field=f"reaction[{index}].writers-disagree",
                    expected="a total rate carries no statistical factor",
                    actual={"net": net["factor"], "sbml": sbml["factor"]},
                )
            )
    return differences


# --------------------------------------------------------------------------- #
# The covering qualified checks.
# --------------------------------------------------------------------------- #


def covering_outcomes(directory):
    """Run the existing qualified checks and return their outcome."""
    from . import netrule_execution, rate_law_contract

    results = {}
    for name, module in (
        ("rate-law-contract", rate_law_contract),
        ("network-rule-execution", netrule_execution),
    ):
        rows = module.run_worker(Path(directory) / name)
        outcomes = {}
        for row in rows:
            outcomes[row["id"]] = row["status"]
        results[name] = dict(
            checks=len(outcomes),
            passed=sum(1 for status in outcomes.values() if status == "PASS"),
            not_passed=sorted(
                f"{key}={status}"
                for key, status in outcomes.items()
                if status != "PASS"
            ),
        )
    return results


# --------------------------------------------------------------------------- #
# The worker.
# --------------------------------------------------------------------------- #


def run_worker(directory: Path):
    """Execute the boundary-extraction qualification and return its rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []

    seam = seam_differences()
    rows.append(
        dict(
            _row(
                "seam-ownership",
                "FAIL" if seam else "PASS",
                (
                    (
                        "the total-rate capability lives behind one named seam and "
                        "every consumer asks that seam"
                    )
                    if not seam
                    else (
                        "the total-rate capability is not owned by one named seam: "
                        + ", ".join(sorted({item["field"] for item in seam}))
                    )
                ),
                first_difference=seam[0] if seam else None,
                seam=str(SEAM_HEADER.relative_to(ROOT)),
                consumers=list(CONSUMERS),
            ),
            id=f"{OPERATION}:seam-ownership",
        )
    )

    import bionetgen

    differences = []
    observed = {}
    for case in CASES:
        case_dir = directory / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "model.bngl"
        source.write_text(case["bngl"], encoding="utf-8")
        try:
            model = bionetgen.load(str(source))
            model.generate_network()
            model.write_net(str(case_dir / "model.net"))
            model.write_sbml(str(case_dir / "model.xml"))
            net_reactions = _net_reactions((case_dir / "model.net").read_text())
            sbml_reactions = _sbml_reactions((case_dir / "model.xml").read_text())
        except Exception as exc:
            differences.append(
                dict(
                    field=f"{case['id']}.execution",
                    expected="a generated network, a network file and an SBML document",
                    actual=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        observed[case["id"]] = dict(
            net=[
                dict(factor=item["factor"], rate=item["rate"]) for item in net_reactions
            ],
            sbml=[
                dict(annotated=item["annotated"], factor=item["factor"])
                for item in sbml_reactions
            ],
        )
        differences.extend(
            {**item, "field": f"{case['id']}.{item['field']}"}
            for item in caller_differences(case, net_reactions, sbml_reactions)
        )
    rows.append(
        dict(
            _row(
                "caller-agreement",
                "FAIL" if differences else "PASS",
                (
                    (
                        "the network writer and the SBML writer agree on the "
                        "total-rate decision of every reaction of the generated family"
                    )
                    if not differences
                    else (
                        "the writers that used to duplicate the decision do not agree: "
                        + ", ".join(sorted({item["field"] for item in differences}))
                    )
                ),
                first_difference=differences[0] if differences else None,
                cases=[case["id"] for case in CASES],
                observed=observed,
            ),
            id=f"{OPERATION}:caller-agreement",
        )
    )

    try:
        outcomes = covering_outcomes(directory / "covering")
    except Exception as exc:
        outcomes = {
            "error": f"{type(exc).__name__}: {exc}",
        }
    not_proven = sorted(
        f"{name}: {', '.join(entry['not_passed'])}"
        for name, entry in outcomes.items()
        if isinstance(entry, dict) and entry.get("not_passed")
    )
    failed = "error" in outcomes or bool(not_proven)
    rows.append(
        dict(
            _row(
                "semantics-unchanged",
                "FAIL" if failed else "PASS",
                (
                    (
                        "the existing qualified checks that cover the affected "
                        "surface pass unchanged"
                    )
                    if not failed
                    else (
                        "the existing qualified checks that cover the affected "
                        "surface did not pass: " + "; ".join(not_proven or ["an error"])
                    )
                ),
                first_difference=(
                    dict(
                        field="covering",
                        expected="every covering check passes",
                        actual=not_proven,
                    )
                    if not_proven
                    else (
                        dict(
                            field="covering",
                            expected="every covering check passes",
                            actual=outcomes["error"],
                        )
                        if "error" in outcomes
                        else None
                    )
                ),
                covering=outcomes,
            ),
            id=f"{OPERATION}:semantics-unchanged",
        )
    )

    failures = [row["id"] for row in rows if row["status"] == "FAIL"]
    obligation = dict(
        _row(
            OBLIGATION_CHECK,
            "FAIL" if failures else "PASS",
            (
                "the total-rate capability is extracted into one named seam, the "
                "callers that used to duplicate the decision agree on its outcome, "
                "and the existing qualified checks pass unchanged"
            ),
            failures=sorted(failures),
        ),
        id=f"qualification:issue:164:{OBLIGATION_CHECK}",
    )
    if failures:
        obligation["detail"] = "the extracted boundary is not proven: " + ", ".join(
            sorted(failures)
        )
        obligation["first_difference"] = dict(failed_checks=sorted(failures))
    rows.append(obligation)

    for row in rows:
        if row.get("status") not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the boundary-extraction adapter emitted an invalid status",
            )
    return rows


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run_worker(args.report_dir)
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
