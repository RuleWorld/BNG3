"""The maintained engine routes of issues #149 and #150.

Issue #149 asks which engine owns each supported workload and whether
NFcore2 remains a bounded prototype, and then asks for any promoted route to
be qualified or the overlap to be contained without losing supported
behavior.  The disposition this module states is: **NFcore2 is not promoted**.
It stays a bounded prototype, so the obligation is discharged by containing
the overlap and keeping the supported behavior:

* the NFcore2 route must not be selectable from the public execution
  surface.  A selection attempt is a runtime refusal, not a silent
  substitution, and the supported production route must still execute;
* the contained prototype must still be qualified: its own parity test
  against NFcore is run and must pass, so the overlap is a tested prototype
  rather than unmaintained code;
* the disposition is reported next to the observed state, so a promotion that
  skips the qualification fails instead of being re-labelled.

Issue #150 asks to distinguish population-map storage and hybrid BNGL
generation from actual execution refinement, so a model that merely stores a
population map is not reported as executing one:

* the NFsim route must refuse a model that stores a population map, with a
  diagnostic that names the state of the population semantics;
* the hybrid model generator must produce the hybrid BNGL artifact and no
  simulation artifact;
* a requested execution of the hybrid model must be refused with a named
  diagnostic, and the actions that do not need the population semantics must
  run against the generated hybrid model rather than against the original
  model.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
from pathlib import Path

ISSUES = (149, 150)

# The recorded disposition of the NFcore2 route.  The route is not promoted:
# it is a bounded prototype, so the obligation is discharged by containment.
NF_CORE2_DISPOSITION = "contained-prototype-not-promoted"

# The public simulation methods of the product.  A route that is not named
# here is not selectable, and a selection attempt must be refused.
PUBLIC_METHODS = ("ode", "ssa", "nf", "pla", "psa")

# The action that would select the contained route.  It is not part of the
# public action surface, and a model that states it must be refused.
CONTAINED_ROUTE_ACTION = "simulate_nfcore2"

CHECKS = {
    149: (
        "nfcore2-route:containment",
        "nfcore2-route:prototype-parity",
        "nfcore2-route:disposition",
    ),
    150: (
        "population-map:storage-not-execution",
        "population-map:hybrid-generation",
        "population-map:execution-refinement-refusal",
    ),
}


def check_ids():
    """The stable check identities of the engine-route families."""
    return list(CHECKS[149]) + list(CHECKS[150])


def _row(identifier, status, detail, *, issue, **evidence):
    return dict(
        id=identifier,
        check=identifier.rsplit(":", 1)[-1],
        status=status,
        detail=detail,
        related_issues=[issue],
        evidence_kind="supported-execution",
        supported_execution=status == "PASS",
        **evidence,
    )


# --------------------------------------------------------------------------- #
# The generated population-map model
# --------------------------------------------------------------------------- #

POPULATION_MAP_MODEL = """begin model
begin parameters
  k 0.4
  k_gather 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 20
  B() 0
end seed species
begin observables
  Molecules A A()
  Molecules B B()
end observables
begin reaction rules
  r1: A() -> B() k
end reaction rules
begin population maps
  A() -> A_pop() k_gather
end population maps
end model
"""


def _run_cli(binary, source, directory, *, timeout=120):
    """Run the CLI on a model and return (returncode, stdout, stderr)."""
    work = Path(directory)
    work.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [str(binary), str(source)],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "", "the CLI run timed out"
    return completed.returncode, completed.stdout, completed.stderr


# --------------------------------------------------------------------------- #
# Issue #149: the maintained engine routes
# --------------------------------------------------------------------------- #


def _nfcore2_containment(directory):
    """The contained route must not be selectable, and the production route
    must still execute."""
    import bionetgen

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "containment.bngl"
    source.write_text(
        "begin model\n"
        "begin parameters\n  k 0.4\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 20\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A A()\nend observables\n"
        "begin reaction rules\n  r1: A() -> B() k\nend reaction rules\n"
        "end model\n",
        encoding="utf-8",
    )
    problems = []
    # The public method set must not name the contained route.
    if any("nfcore" in method.lower() for method in PUBLIC_METHODS):
        problems.append("the public method set names the contained route")
    # A selection attempt must be refused, not silently substituted.
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bionetgen.load(str(source)).simulate(
                method="nfcore2", t_end=1, n_steps=2, seed=1
            )
        problems.append("the contained route was selected by the public API")
    except Exception as exc:  # noqa: BLE001 - the refusal is the observation
        refusal = f"{type(exc).__name__}: {exc}"
        if "nfcore2" not in refusal:
            problems.append("the refusal of the contained route does not name it")
    # The supported production route must still execute.
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = bionetgen.load(str(source)).simulate(
                method="nf", t_end=1, n_steps=2, seed=1
            )
        if result.construction_path != "direct":
            problems.append(
                "the supported production route no longer runs on the direct path: "
                + str(result.construction_path)
            )
    except Exception as exc:  # noqa: BLE001 - the failure is the observation
        problems.append(f"the supported production route failed: {exc}")
    return problems


def _nfcore2_prototype_parity(directory, binary):
    """The contained prototype must still be qualified by its own parity test."""
    if binary is None or not Path(binary).is_file():
        return (
            "NOT_TESTED",
            "the contained prototype's parity qualification is unavailable: "
            f"{binary}",
            dict(applicability="nfcore2-parity-binary-unavailable"),
        )
    work = Path(directory)
    work.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [str(binary)],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", "the contained prototype's parity qualification timed out", {}
    if completed.returncode != 0:
        return (
            "FAIL",
            "the contained prototype's parity qualification failed: "
            + (completed.stdout + completed.stderr).strip()[-400:],
            dict(returncode=completed.returncode),
        )
    return (
        "PASS",
        "the contained prototype still passes its own parity qualification "
        "against NFcore",
        dict(returncode=completed.returncode),
    )


# --------------------------------------------------------------------------- #
# Issue #150: population-map storage, hybrid generation, execution refinement
# --------------------------------------------------------------------------- #


def _population_map_refusal(directory):
    """A model that stores a population map must not be executed by NFsim."""
    import bionetgen

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "population-map.bngl"
    source.write_text(POPULATION_MAP_MODEL, encoding="utf-8")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bionetgen.load(str(source)).simulate(
                method="nf", t_end=1, n_steps=2, seed=1
            )
    except Exception as exc:  # noqa: BLE001 - the refusal is the observation
        message = str(exc)
        problems = []
        if "population map" not in message:
            problems.append("the refusal does not name the population map")
        if "not implemented" not in message and "cannot execute" not in message:
            problems.append("the refusal does not state the population semantics")
        return problems, message
    return ["the model that stores a population map was executed"], ""


def _hybrid_generation(directory, binary):
    """The hybrid generator must produce the hybrid model and no simulation."""
    if binary is None or not Path(binary).is_file():
        return (
            "NOT_TESTED",
            "the hybrid model generator is unavailable: " + str(binary),
            dict(applicability="bng-cpp-unavailable"),
        )
    work = Path(directory)
    work.mkdir(parents=True, exist_ok=True)
    source = work / "hybrid.bngl"
    source.write_text(
        POPULATION_MAP_MODEL
        + "\ngenerate_hybrid_model({overwrite=>1, execute=>0, verbose=>0})\n",
        encoding="utf-8",
    )
    code, stdout, stderr = _run_cli(binary, source, work)
    if code != 0:
        return (
            "FAIL",
            "the hybrid model generation failed: " + (stdout + stderr).strip()[-400:],
            dict(returncode=code),
        )
    generated = work / "hybrid_hpp.bngl"
    problems = []
    if not generated.is_file():
        problems.append("the hybrid model was not generated")
    else:
        text = generated.read_text(encoding="utf-8")
        if "begin population maps" in text:
            problems.append("the generated hybrid model still stores a population map")
        if "A_pop" not in text:
            problems.append("the generated hybrid model declares no population type")
        if "_map_" not in text:
            problems.append("the generated hybrid model declares no mapping rule")
    for artefact in ("hybrid_hpp.gdat", "hybrid_hpp.cdat"):
        if (work / artefact).is_file():
            problems.append(
                "the hybrid model generation produced the simulation artefact "
                + artefact
            )
    return (
        "FAIL" if problems else "PASS",
        (
            "; ".join(problems)
            if problems
            else "the hybrid model generator produced the hybrid model and no "
            "simulation artefact"
        ),
        dict(generated=str(generated)),
    )


def _hybrid_execution_refusal(directory, binary):
    """A requested hybrid execution must be refused; the other actions must
    run against the hybrid model."""
    if binary is None or not Path(binary).is_file():
        return (
            "NOT_TESTED",
            "the hybrid model generator is unavailable: " + str(binary),
            dict(applicability="bng-cpp-unavailable"),
        )
    work = Path(directory)
    work.mkdir(parents=True, exist_ok=True)
    problems = []

    # A simulation of the hybrid model needs the population execution
    # refinement, which is not implemented: it must be refused by name.
    source = work / "hybrid-simulate.bngl"
    source.write_text(
        POPULATION_MAP_MODEL
        + "\ngenerate_hybrid_model({overwrite=>1, execute=>1, verbose=>0, "
        'actions=>["simulate({t_end=>1})"]})\n',
        encoding="utf-8",
    )
    code, stdout, stderr = _run_cli(binary, source, work)
    message = (stdout + stderr).strip()
    if code == 0:
        problems.append("the requested hybrid simulation was not refused")
    if "population execution refinement is not supported" not in message:
        problems.append("the refusal does not name the unsupported refinement")
    if (work / "hybrid-simulate_hpp.gdat").is_file():
        problems.append("the refused hybrid simulation produced a trajectory")

    # The actions that do not need the population semantics must run against
    # the generated hybrid model, not against the original model.
    source = work / "hybrid-write.bngl"
    source.write_text(
        POPULATION_MAP_MODEL
        + "\ngenerate_hybrid_model({overwrite=>1, execute=>1, verbose=>0, "
        'actions=>["writeXML()"]})\n',
        encoding="utf-8",
    )
    code, stdout, stderr = _run_cli(binary, source, work)
    if code != 0:
        problems.append(
            "the requested action on the hybrid model failed: "
            + (stdout + stderr).strip()[-400:]
        )
    hybrid_xml = work / "hybrid-write_hpp.xml"
    if not hybrid_xml.is_file():
        problems.append("the requested action did not run against the hybrid model")
    else:
        text = hybrid_xml.read_text(encoding="utf-8")
        if "A_pop" not in text:
            problems.append(
                "the written artifact does not describe the generated hybrid model"
            )
    for artefact in ("hybrid-write_hpp.gdat", "hybrid-write_hpp.cdat"):
        if (work / artefact).is_file():
            problems.append(
                "the hybrid model action produced the simulation artefact " + artefact
            )
    return (
        "FAIL" if problems else "PASS",
        (
            "; ".join(problems)
            if problems
            else "the requested hybrid execution was refused and the remaining "
            "actions ran against the generated hybrid model"
        ),
        dict(),
    )


def run(directory, *, bng_cpp=None, nfcore2_parity=None, prototype_root=None):
    """Execute the engine-route qualifications of issues #149 and #150."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []

    # --- #149 -------------------------------------------------------------
    problems = _nfcore2_containment(directory / "nfcore2")
    rows.append(
        _row(
            "nfcore2-route:containment",
            "FAIL" if problems else "PASS",
            (
                "; ".join(problems)
                if problems
                else "the NFcore2 route is not selectable from the public "
                "execution surface and the supported production route still "
                "executes"
            ),
            issue=149,
            first_difference=dict(problems=problems) if problems else None,
            public_methods=list(PUBLIC_METHODS),
            disposition=NF_CORE2_DISPOSITION,
        )
    )
    status, detail, evidence = _nfcore2_prototype_parity(
        directory / "nfcore2", nfcore2_parity
    )
    rows.append(
        _row(
            "nfcore2-route:prototype-parity",
            status,
            detail,
            issue=149,
            first_difference=None,
            **evidence,
        )
    )
    containment = rows[0]
    rows.append(
        _row(
            "nfcore2-route:disposition",
            "PASS" if containment["status"] == "PASS" else "FAIL",
            (
                "the NFcore2 route is recorded as a contained prototype that is "
                "not promoted, and the product state matches that disposition"
                if containment["status"] == "PASS"
                else "the product state does not match the recorded disposition: "
                "the route became reachable without a qualification"
            ),
            issue=149,
            first_difference=None,
            disposition=NF_CORE2_DISPOSITION,
            promotion="not promoted",
        )
    )

    # --- #150 -------------------------------------------------------------
    problems, message = _population_map_refusal(directory / "population-map")
    rows.append(
        _row(
            "population-map:storage-not-execution",
            "FAIL" if problems else "PASS",
            (
                "; ".join(problems)
                if problems
                else "the model that stores a population map is refused by the "
                "NFsim route, so a stored population map is not reported as an "
                "executed one"
            ),
            issue=150,
            first_difference=dict(problems=problems) if problems else None,
            refusal=message,
        )
    )
    status, detail, evidence = _hybrid_generation(directory / "hybrid", bng_cpp)
    rows.append(
        _row(
            "population-map:hybrid-generation",
            status,
            detail,
            issue=150,
            first_difference=None,
            **evidence,
        )
    )
    status, detail, evidence = _hybrid_execution_refusal(directory / "hybrid", bng_cpp)
    rows.append(
        _row(
            "population-map:execution-refinement-refusal",
            status,
            detail,
            issue=150,
            first_difference=None,
            **evidence,
        )
    )
    return rows
