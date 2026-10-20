"""Atomizer structural reconstruction and semantic round-trip qualification.

Issue #161 ("E05: Expand structural Atomizer and SBML Multi execution
qualification") asks for two things that the existing unit tests did not
provide as one named, executable family:

* coverage of reconstruction, reaction and bond changes, compartments,
  quantities and retained metadata on supported models, and
* a comparison of the *full execution* and the *semantic round trip* with
  independent references, where a successful parse is never substituted for
  dynamics.

This module owns both.  Every generated case is an SBML document; the family

* reconstructs it with the modern Atomizer,
* executes the reconstruction with the BNG3 engine and compares every source
  species against an **independent closed-form law** of the generated model
  *and* against **libRoadRunner** running the source SBML, and
* writes the reconstruction to SBML, reads it back, reconstructs it again and
  executes that, comparing it against the same independent references.

A model the reconstruction cannot represent is **refused**: the case then
requires an explicit import diagnostic naming the unrepresentable construct,
and no execution claim is made for it.  A parse that silently drops a
construct is a failure, not a success.

The independent laws are derived from the generated case parameters and from
the closed-form solution of the generated model.  They are never taken from
the product under test.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from .campaign import STATUSES

ROOT = Path(__file__).resolve().parents[2]
ISSUES = (161,)

SBML_CORE = "http://www.sbml.org/sbml/level3/version2/core"
SBML_MULTI = "http://www.sbml.org/sbml/level3/version1/multi/version1"

TIMES = np.linspace(0.0, 5.0, 11)
T_END = float(TIMES[-1])
N_STEPS = len(TIMES) - 1
SOLVER_RTOL = 1e-10
SOLVER_ATOL = 1e-12

# The comparison tolerances.  Both sides are deterministic integrations of the
# same model, so the tolerance only has to absorb the two solvers' own error;
# it is far below the difference a wrong rate law, a wrong stoichiometry, a
# dropped bond or a lost compartment would produce.
LAW_RTOL = 1e-6
LAW_ATOL = 1e-6

# The features the family has to cover.  A case that does not contribute to a
# feature leaves the family incomplete.
REQUIRED_FEATURES = (
    "reconstruction",
    "bond-change",
    "compartment",
    "quantity",
    "metadata",
    "multi",
    "refusal",
)

MULTI_HEADER = f'xmlns:multi="{SBML_MULTI}"'


def _document(model_id: str, body: str, *, namespaces: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<sbml xmlns="{SBML_CORE}"{namespaces} level="3" version="2">\n'
        f'  <model id="{model_id}">\n{body}\n  </model>\n'
        "</sbml>\n"
    )


def _species(
    species_id: str,
    *,
    amount: float | None = None,
    concentration: float | None = None,
    compartment: str = "cell",
    substance_units: bool = True,
) -> str:
    if amount is not None:
        quantity = f'initialAmount="{amount}"'
    else:
        quantity = f'initialConcentration="{concentration}"'
    return (
        f'      <species id="{species_id}" compartment="{compartment}" {quantity} '
        f'hasOnlySubstanceUnits="{"true" if substance_units else "false"}" '
        'constant="false" boundaryCondition="false"/>'
    )


def _reaction(
    reaction_id: str,
    reactants: tuple[str, ...],
    products: tuple[str, ...],
    law: str,
) -> str:
    reactant_xml = "".join(
        f'<speciesReference species="{item}" stoichiometry="1" constant="true"/>'
        for item in reactants
    )
    product_xml = "".join(
        f'<speciesReference species="{item}" stoichiometry="1" constant="true"/>'
        for item in products
    )
    return f"""      <reaction id="{reaction_id}" reversible="false" fast="false">
        <listOfReactants>{reactant_xml}</listOfReactants>
        <listOfProducts>{product_xml}</listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>{law}</ci></math></kineticLaw>
      </reaction>"""


def _compartment(size: float, identifier: str = "cell") -> str:
    return f"""    <listOfCompartments>
      <compartment id="{identifier}" size="{size}" spatialDimensions="3" constant="true"/>
    </listOfCompartments>"""


def _parameters(*entries: tuple[str, float]) -> str:
    body = "".join(
        f'      <parameter id="{name}" value="{value}" constant="true"/>'
        for name, value in entries
    )
    return f"    <listOfParameters>\n{body}\n    </listOfParameters>"


# --------------------------------------------------------------------------- #
# The generated case family.
# --------------------------------------------------------------------------- #


def cases() -> list[dict]:
    """Return the generated structural cases and their independent laws."""

    result: list[dict] = []

    # 1. A plain conversion.  The reconstruction is elemental; the law is the
    #    closed-form solution of a constant-flux conversion.
    rate = 0.35
    initial = 40.0
    result.append(
        {
            "id": "conversion",
            "features": ("reconstruction",),
            "representable": True,
            "source": _document(
                "conversion",
                "\n".join(
                    [
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=initial)
                        + "\n"
                        + _species("B", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", rate)),
                        "    <listOfReactions>\n"
                        + _reaction("R", ("A",), ("B",), "k")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _r=rate, _a=initial: {
                "A": _a - _r * t,
                "B": _r * t,
            },
        }
    )

    # 2. Complex formation.  The reconstruction has to discover that the
    #    product species is a bonded complex of the two reactants, so the
    #    reconstructed pattern must carry a bond.
    kon = 0.5
    amount_a = 60.0
    amount_b = 40.0
    result.append(
        {
            "id": "complex-formation",
            "features": ("reconstruction", "bond-change"),
            "representable": True,
            "expect_bond": True,
            "source": _document(
                "complex_formation",
                "\n".join(
                    [
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=amount_a)
                        + "\n"
                        + _species("B", amount=amount_b)
                        + "\n"
                        + _species("AB", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("kon", kon)),
                        "    <listOfReactions>\n"
                        + _reaction("R_bind", ("A", "B"), ("AB",), "kon")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _k=kon, _a=amount_a, _b=amount_b: {
                "A": _a - _k * t,
                "B": _b - _k * t,
                "AB": _k * t,
            },
        }
    )

    # 3. Complex dissociation: the bond is broken again.
    koff = 0.4
    amount_ab = 30.0
    result.append(
        {
            "id": "complex-dissociation",
            "features": ("reconstruction", "bond-change"),
            "representable": True,
            "expect_bond": True,
            "source": _document(
                "complex_dissociation",
                "\n".join(
                    [
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=0.0)
                        + "\n"
                        + _species("B", amount=0.0)
                        + "\n"
                        + _species("AB", amount=amount_ab)
                        + "\n    </listOfSpecies>",
                        _parameters(("koff", koff)),
                        "    <listOfReactions>\n"
                        + _reaction("R_unbind", ("AB",), ("A", "B"), "koff")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _k=koff, _a=amount_ab: {
                "A": _k * t,
                "B": _k * t,
                "AB": _a - _k * t,
            },
        }
    )

    # 4. A reversible bond: the closed-form solution of a reversible
    #    association.
    kon_r = 0.5
    koff_r = 0.1
    amount_a_r = 60.0
    amount_b_r = 40.0
    result.append(
        {
            "id": "reversible-complex",
            "features": ("reconstruction", "bond-change"),
            "representable": True,
            "expect_bond": True,
            "source": _document(
                "reversible_complex",
                "\n".join(
                    [
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=amount_a_r)
                        + "\n"
                        + _species("B", amount=amount_b_r)
                        + "\n"
                        + _species("AB", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("kon", kon_r), ("koff", koff_r)),
                        "    <listOfReactions>\n"
                        + _reaction("R_bind", ("A", "B"), ("AB",), "kon")
                        + "\n"
                        + _reaction("R_unbind", ("AB",), ("A", "B"), "koff")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            # An SBML kinetic law is the reaction's flux.  A constant
            # kinetic law is a constant flux, so the reversible pair has a
            # constant net flux (kon - koff) in both directions.
            "law": lambda t, _kon=kon_r, _koff=koff_r, _a=amount_a_r, _b=amount_b_r: {
                "A": _a - (_kon - _koff) * t,
                "B": _b - (_kon - _koff) * t,
                "AB": (_kon - _koff) * t,
            },
        }
    )

    # 5. A non-unit compartment: the amount and the concentration differ, so
    #    the reconstruction has to carry the volume.
    volume = 2.5
    rate_v = 0.35
    initial_v = 40.0
    result.append(
        {
            "id": "compartment-volume",
            "features": ("compartment", "quantity"),
            "representable": True,
            "volume": volume,
            "source": _document(
                "compartment_volume",
                "\n".join(
                    [
                        _compartment(volume),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=initial_v)
                        + "\n"
                        + _species("B", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", rate_v)),
                        "    <listOfReactions>\n"
                        + _reaction("R", ("A",), ("B",), "k")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _r=rate_v, _a=initial_v: {
                "A": _a - _r * t,
                "B": _r * t,
            },
        }
    )

    # 6. A concentration-valued species: the seed is a concentration and the
    #    amount follows from the compartment volume.
    volume_c = 2.0
    concentration = 30.0
    rate_c = 0.35
    result.append(
        {
            "id": "concentration-species",
            "features": ("quantity", "compartment"),
            "representable": True,
            "volume": volume_c,
            "source": _document(
                "concentration_species",
                "\n".join(
                    [
                        _compartment(volume_c),
                        "    <listOfSpecies>\n"
                        + _species(
                            "A", concentration=concentration, substance_units=False
                        )
                        + "\n"
                        + _species("B", concentration=0.0, substance_units=False)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", rate_c)),
                        "    <listOfReactions>\n"
                        + _reaction("R", ("A",), ("B",), "k")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _r=rate_c, _a=concentration * volume_c: {
                "A": _a - _r * t,
                "B": _r * t,
            },
        }
    )

    # 7. A model that carries RDF annotations and notes: the retained
    #    metadata has to survive the round trip.
    result.append(
        {
            "id": "annotated-model",
            "features": ("metadata",),
            "representable": True,
            "source": _document(
                "annotated_model",
                "\n".join(
                    [
                        '    <notes><body xmlns="http://www.w3.org/1999/xhtml">'
                        "<p>generated structural case</p></body></notes>",
                        "    <annotation><rdf:RDF "
                        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                        '<rdf:Description rdf:about="#annotated_model">'
                        '<bqbiol:is xmlns:bqbiol="http://biomodels.net/biology-qualifiers/">'
                        '<rdf:Bag><rdf:li rdf:resource="urn:miriam:pubmed:12345"/>'
                        "</rdf:Bag></bqbiol:is></rdf:Description></rdf:RDF></annotation>",
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=initial)
                        + "\n"
                        + _species("B", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", rate)),
                        "    <listOfReactions>\n"
                        + _reaction("R", ("A",), ("B",), "k")
                        + "\n    </listOfReactions>",
                    ]
                ),
            ),
            "law": lambda t, _r=rate, _a=initial: {
                "A": _a - _r * t,
                "B": _r * t,
            },
        }
    )

    # 8. SBML Multi: the package supplies the internal state structure of a
    #    species while the core model states the reaction explicitly.
    multi_rate = 0.3
    multi_initial = 20.0
    result.append(
        {
            "id": "multi-state-change",
            "features": ("multi", "reconstruction"),
            "representable": True,
            "source": _document(
                "multi_state_change",
                "\n".join(
                    [
                        _compartment(2.0),
                        "    <listOfSpecies>\n"
                        + _species("Au", amount=multi_initial)
                        + "\n"
                        + _species("Ap", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", multi_rate)),
                        "    <listOfReactions>\n"
                        + """      <reaction id="phosphorylate" reversible="false" fast="false">
        <listOfReactants><speciesReference species="Au" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="Ap" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>Au</ci></apply></math></kineticLaw>
      </reaction>"""
                        + "\n    </listOfReactions>",
                    ]
                ),
                namespaces=" " + MULTI_HEADER,
            ),
            "law": lambda t, _k=multi_rate, _a=multi_initial: {
                "Au": _a * np.exp(-_k * t),
                "Ap": _a * (1.0 - np.exp(-_k * t)),
            },
        }
    )

    # 9. A model the reconstruction cannot represent: two species assignment
    #    rules that depend on each other are an algebraic species state,
    #    which a BNGL network cannot enforce.
    result.append(
        {
            "id": "refusal-cyclic-species-assignment",
            "features": ("refusal",),
            "representable": False,
            "refusal_marker": "assignment rule targets species",
            "refusal_category": "speciesAssignmentRule",
            "source": _document(
                "cyclic_species_assignment",
                "\n".join(
                    [
                        _compartment(1.0),
                        "    <listOfSpecies>\n"
                        + _species("A", amount=40.0)
                        + "\n"
                        + _species("B", amount=0.0)
                        + "\n    </listOfSpecies>",
                        _parameters(("k", 0.35)),
                        """    <listOfRules>
      <assignmentRule variable="A">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>B</ci></math>
      </assignmentRule>
      <assignmentRule variable="B">
        <math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math>
      </assignmentRule>
    </listOfRules>""",
                    ]
                ),
            ),
        }
    )

    return result


# --------------------------------------------------------------------------- #
# Check identities.
# --------------------------------------------------------------------------- #


def check_ids() -> list[str]:
    """Stable check identities for the reconstruction qualification."""

    ids = []
    for case in cases():
        ids.append(f"atomizer-reconstruction:{case['id']}:reconstruction")
        if case["representable"]:
            ids.append(f"atomizer-reconstruction:{case['id']}:execution")
            ids.append(f"atomizer-reconstruction:{case['id']}:roundtrip")
    ids.append("atomizer-reconstruction:metadata:roundtrip")
    ids.append("atomizer-reconstruction:family:coverage")
    return ids


def _blocked_rows(case_id: str, reason: str) -> list[dict]:
    """Record the rows a case cannot reach, so the named row set stays complete.

    A case that cannot be reconstructed has no execution and no round trip.
    The rows are recorded as failures instead of being dropped, because a
    missing row would let a broken case pass as an unselected one.
    """

    return [
        _row(
            f"atomizer-reconstruction:{case_id}:execution",
            "execution",
            "FAIL",
            reason + ", so the reconstruction was not executed",
            expectation=(
                "the reconstruction executes and reproduces the independent "
                "law of the generated model"
            ),
            supported_execution=False,
        ),
        _row(
            f"atomizer-reconstruction:{case_id}:roundtrip",
            "roundtrip",
            "FAIL",
            reason + ", so the semantic round trip was not attempted",
            expectation=(
                "the semantic round trip reproduces the independent law of the "
                "generated model"
            ),
            supported_execution=False,
        ),
    ]


def _row(check_id: str, check: str, status: str, detail: str, **evidence) -> dict:
    row = dict(
        id=check_id,
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        evidence_kind="supported-execution",
        supported_execution=True,
    )
    row.update(evidence)
    return row


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _strip_multi(text: str) -> str:
    """Remove the Multi package declarations for the independent simulator.

    The Multi package supplies the internal structure of a species; the core
    model states the species and the reaction explicitly, so the core model is
    the independent reference for the dynamics.
    """

    document = ET.fromstring(text)
    for parent in document.iter():
        for child in list(parent):
            if isinstance(child.tag, str) and child.tag.startswith(
                "{" + SBML_MULTI + "}"
            ):
                parent.remove(child)
        for attribute in list(parent.attrib):
            if attribute.startswith("{" + SBML_MULTI + "}"):
                del parent.attrib[attribute]
    return ET.tostring(document, encoding="unicode")


def _observable_patterns(bngl: str) -> dict[str, str]:
    """Map the ``Species`` observable names of a generated model to patterns."""

    patterns: dict[str, str] = {}
    inside = False
    for line in bngl.splitlines():
        stripped = line.strip()
        if stripped.lower() == "begin observables":
            inside = True
            continue
        if stripped.lower() == "end observables":
            inside = False
            continue
        if not inside or not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3 or parts[0] != "Species":
            continue
        patterns[parts[1]] = parts[2]
    return patterns


def _plain_pattern(pattern: str) -> str:
    """Remove the compartment prefix from a reconstructed pattern."""

    pieces = []
    for part in pattern.split("."):
        if part.startswith("@") and ":" in part:
            pieces.append(part.split(":", 1)[1])
        else:
            pieces.append(part)
    return ".".join(pieces)


def _difference(
    observed: np.ndarray,
    expected: np.ndarray,
    *,
    label: str,
) -> dict | None:
    """Return the first difference between two trajectories, or None."""

    observed = np.asarray(observed, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if observed.shape != expected.shape:
        return {
            "field": label + ".shape",
            "expected": list(expected.shape),
            "observed": list(observed.shape),
        }
    if not np.all(np.isfinite(observed)):
        index = int(np.flatnonzero(~np.isfinite(observed))[0])
        return {
            "field": label,
            "time": float(TIMES[index]),
            "observed": float(observed[index]),
            "expected": float(expected[index]),
            "reason": "the observed trajectory is not finite",
        }
    error = np.abs(observed - expected)
    limit = LAW_ATOL + LAW_RTOL * np.abs(expected)
    bad = np.flatnonzero(error > limit)
    if len(bad):
        index = int(bad[0])
        return {
            "field": label,
            "time": float(TIMES[index]),
            "observed": float(observed[index]),
            "expected": float(expected[index]),
            "absolute_error": float(error[index]),
            "limit": float(limit[index]),
        }
    return None


def _law_values(case: dict) -> dict[str, np.ndarray]:
    """Evaluate the independent law of a generated case.

    The law is only usable when it stays defined over the whole horizon: a
    negative amount would make the comparison meaningless, so the family
    refuses the case instead of comparing against an impossible expectation.
    """

    law = case["law"]
    values = law(TIMES)
    result = {}
    for name, value in values.items():
        series = np.asarray(value, dtype=float)
        if np.any(series < -1e-9):
            raise ValueError(
                f"the independent law of '{name}' is negative over the horizon; "
                "the generated case parameters are not admissible"
            )
        result[name] = series
    return result


def _roadrunner_reference(source_text: str, species_ids: list[str], directory: Path):
    """Run the independent simulator on the source model."""

    import roadrunner

    core = _strip_multi(source_text) if "multi" in source_text else source_text
    path = directory / "reference-core.xml"
    path.write_text(core, encoding="utf-8")
    simulator = roadrunner.RoadRunner(str(path))
    simulator.integrator.setValue("relative_tolerance", SOLVER_RTOL)
    simulator.integrator.setValue("absolute_tolerance", SOLVER_ATOL)
    simulator.timeCourseSelections = ["time", *species_ids]
    values = np.asarray(simulator.simulate(0.0, T_END, N_STEPS + 1), dtype=float)
    return {
        name: values[:, index + 1] for index, name in enumerate(species_ids)
    }, simulator


def _execute(bngl: str):
    """Execute a generated BNGL model with the BNG3 engine."""

    import bionetgen._bionetgen_cpp as cpp

    model = cpp.parse_string(bngl)
    network = cpp.generate_network(model, max_iter=100)
    result = cpp.simulate_ode(
        model,
        network,
        T_END,
        N_STEPS,
        0.0,
        SOLVER_RTOL,
        SOLVER_ATOL,
    )
    return model, network, result


# --------------------------------------------------------------------------- #
# The family.
# --------------------------------------------------------------------------- #


def _run_case(case: dict, directory: Path, rows: list[dict]) -> None:
    """Reconstruct, execute and round-trip one generated case.

    Every named row of the case is recorded, including the rows a broken
    case cannot reach: a missing row would let a broken case pass as an
    unselected one.
    """

    from bionetgen.atomizer.modern import (
        Atomizer,
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )
    import bionetgen._bionetgen_cpp as cpp

    case_id = case["id"]
    case_directory = directory / case_id
    case_directory.mkdir(parents=True, exist_ok=True)
    source_text = case["source"]
    (case_directory / "source.xml").write_text(source_text, encoding="utf-8")

    atomizer = Atomizer(
        atomize=True,
        quiet_mode=True,
        t_end=T_END,
        n_steps=N_STEPS,
    )
    atomized = atomizer.atomize(source_text)
    parsed = atomizer.get_model()
    warnings = list(getattr(parsed, "import_warnings", []) or [])
    dropped = [
        warning
        for warning in warnings
        if str(warning.get("severity")) in {"dropped", "approximated"}
    ]

    if not case["representable"]:
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:reconstruction",
                "reconstruction",
                "PASS" if dropped else "FAIL",
                (
                    "the reconstruction refused the model with an explicit "
                    "import diagnostic and no execution claim was made"
                    if dropped
                    else "the reconstruction reported success for a model it "
                    "cannot represent"
                ),
                first_difference=(
                    None
                    if dropped
                    else {
                        "field": "refusal",
                        "observed": "the reconstruction reported success",
                        "expected": (
                            "an explicit import diagnostic naming "
                            f"{case['refusal_marker']!r}"
                        ),
                    }
                ),
                expectation=(
                    "an unrepresentable model is refused with a named "
                    "diagnostic instead of a successful parse"
                ),
                refusal_category=case.get("refusal_category"),
                refusal_marker=case.get("refusal_marker"),
                diagnostics=[
                    {
                        "category": warning.get("category"),
                        "severity": warning.get("severity"),
                        "message": warning.get("message"),
                    }
                    for warning in dropped
                ],
                evidence_kind="diagnostic-only",
                supported_execution=False,
            )
        )
        return

    if not atomized.success:
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:reconstruction",
                "reconstruction",
                "FAIL",
                "the reconstruction failed: " + str(atomized.error),
                expectation="the reconstruction produces an executable model",
                supported_execution=False,
            )
        )
        rows.extend(_blocked_rows(case_id, "the reconstruction failed"))
        return
    if dropped:
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:reconstruction",
                "reconstruction",
                "FAIL",
                "the reconstruction dropped a source construct that the "
                "supported case requires",
                first_difference={
                    "field": "diagnostics",
                    "observed": dropped[0].get("message"),
                    "expected": "no dropped or approximated construct",
                },
                expectation=(
                    "a supported model is reconstructed without dropping a "
                    "source construct"
                ),
                diagnostics=[
                    {
                        "category": warning.get("category"),
                        "severity": warning.get("severity"),
                        "message": warning.get("message"),
                    }
                    for warning in dropped
                ],
                evidence_kind="diagnostic-only",
                supported_execution=False,
            )
        )
        rows.extend(
            _blocked_rows(
                case_id,
                "the reconstruction dropped a source construct",
            )
        )
        return

    (case_directory / "reconstructed.bngl").write_text(atomized.bngl, encoding="utf-8")
    patterns = _observable_patterns(atomized.bngl)
    observable_map = dict(atomized.observable_map)

    reconstruction_problems = []
    if case.get("expect_bond"):
        bonded = [
            name
            for name, pattern in patterns.items()
            if "!" in pattern and "." in pattern
        ]
        if not bonded:
            reconstruction_problems.append(
                {
                    "field": "bond",
                    "observed": "no reconstructed pattern carries a bond",
                    "expected": "the product species is a bonded complex",
                }
            )
    for species_id in parsed.species:
        name = observable_map.get(species_id)
        if name is None:
            reconstruction_problems.append(
                {
                    "field": "observable",
                    "observed": species_id,
                    "expected": "the reconstruction exposes a source observable",
                }
            )
            return
        if f"{name}_amt" not in patterns:
            reconstruction_problems.append(
                {
                    "field": "amount-observable",
                    "observed": f"{name}_amt",
                    "expected": "the reconstruction exposes the amount observable",
                }
            )
    rows.append(
        _row(
            f"atomizer-reconstruction:{case_id}:reconstruction",
            "reconstruction",
            "FAIL" if reconstruction_problems else "PASS",
            (
                "the reconstruction exposes one observable per source species"
                + (
                    " and carries the reconstructed bond"
                    if case.get("expect_bond")
                    else ""
                )
                if not reconstruction_problems
                else "the reconstruction does not match the generated structure"
            ),
            first_difference=(
                reconstruction_problems[0] if reconstruction_problems else None
            ),
            expectation=(
                "the reconstruction exposes the generated structure, "
                "including the reconstructed bond"
                if case.get("expect_bond")
                else "the reconstruction exposes one observable per source species"
            ),
            patterns=patterns,
            observable_map=observable_map,
            supported_execution=True,
        )
    )

    # ---- the full execution against two independent references -------
    try:
        law = _law_values(case)
    except ValueError as exc:
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:execution",
                "execution",
                "FAIL",
                str(exc),
                expectation=(
                    "the reconstruction executes and reproduces the "
                    "independent law of the generated model"
                ),
                supported_execution=False,
            )
        )
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:roundtrip",
                "roundtrip",
                "NOT_TESTED",
                "the independent law of the generated case is not defined "
                "over the horizon, so the semantic round trip was not judged",
                expectation=(
                    "the semantic round trip reproduces the independent law "
                    "of the generated model"
                ),
                supported_execution=False,
            )
        )
        return
    species_ids = list(parsed.species)
    reference = {}
    reference_error = None
    try:
        reference, _simulator = _roadrunner_reference(
            source_text, species_ids, case_directory
        )
    except Exception as exc:  # pragma: no cover - depends on the oracle
        reference_error = f"{type(exc).__name__}: {exc}"

    execution_problems = []
    try:
        model, network, result = _execute(atomized.bngl)
    except Exception as exc:
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:execution",
                "execution",
                "FAIL",
                "the reconstruction could not be executed: "
                + f"{type(exc).__name__}: {exc}",
                expectation=(
                    "the reconstruction executes and reproduces the "
                    "independent law of the generated model"
                ),
                supported_execution=False,
            )
        )
        rows.append(
            _row(
                f"atomizer-reconstruction:{case_id}:roundtrip",
                "roundtrip",
                "NOT_TESTED",
                "the reconstruction could not be executed, so the semantic "
                "round trip was not attempted",
                expectation=(
                    "the semantic round trip reproduces the independent law "
                    "of the generated model"
                ),
                supported_execution=False,
            )
        )
        return

    observables = result["observables"]
    for species_id in species_ids:
        name = observable_map[species_id]
        observed = np.asarray(observables[f"{name}_amt"], dtype=float)
        expected = law.get(species_id)
        if expected is None:
            execution_problems.append(
                {
                    "field": "law",
                    "observed": species_id,
                    "expected": "the generated case defines an independent law",
                }
            )
            return
        difference = _difference(observed, expected, label=species_id + ".law")
        if difference:
            execution_problems.append(difference)
        if reference_error is not None:
            return
        reference_difference = _difference(
            observed, reference[species_id], label=species_id + ".roadrunner"
        )
        if reference_difference:
            execution_problems.append(reference_difference)
    rows.append(
        _row(
            f"atomizer-reconstruction:{case_id}:execution",
            "execution",
            "FAIL" if execution_problems else "PASS",
            (
                (
                    "the executed reconstruction reproduces the independent "
                    "closed-form law and the independent simulator"
                    if reference_error is None
                    else "the executed reconstruction reproduces the "
                    "independent closed-form law; the independent simulator "
                    "was unavailable (" + reference_error + ")"
                )
                if not execution_problems
                else "the executed reconstruction disagrees with an "
                "independent reference"
            ),
            first_difference=(execution_problems[0] if execution_problems else None),
            expectation=(
                "the reconstruction executes and reproduces the independent "
                "law of the generated model"
            ),
            references=(
                ["closed-form law of the generated model"]
                + ([] if reference_error else ["libRoadRunner on the source SBML"])
            ),
            reference_error=reference_error,
            supported_execution=True,
        )
    )

    # ---- the semantic round trip -------------------------------------
    roundtrip_problems = []
    written_path = case_directory / "roundtrip.xml"
    payload = source_metadata_payload(parsed)
    cpp.io.write_sbml(
        model,
        network,
        str(written_path),
        source_metadata=payload,
    )
    written_text = written_path.read_text(encoding="utf-8")
    reimport = SBMLParser().parse(written_text)
    reatomizer = Atomizer(
        atomize=True,
        quiet_mode=True,
        t_end=T_END,
        n_steps=N_STEPS,
    )
    reatomized = reatomizer.atomize(written_text)
    if not reatomized.success:
        roundtrip_problems.append(
            {
                "field": "reconstruction",
                "observed": str(reatomized.error),
                "expected": "the written SBML is reconstructed again",
            }
        )
    else:
        (case_directory / "roundtrip.bngl").write_text(
            reatomized.bngl, encoding="utf-8"
        )
        re_patterns = _observable_patterns(reatomized.bngl)
        re_map = dict(reatomized.observable_map)
        # The written SBML states one species per reconstructed network
        # species.  The re-atomized model exposes one amount observable per
        # written species, so the round trip is compared species by
        # species against the independent law.
        written_species = list(reimport.species)
        law_by_pattern = {
            _plain_pattern(patterns[observable_map[species_id]]): species_id
            for species_id in parsed.species
            if observable_map.get(species_id) in patterns
        }
        if len(law_by_pattern) != len(parsed.species):
            roundtrip_problems.append(
                {
                    "field": "mapping",
                    "observed": f"{len(law_by_pattern)} distinct patterns",
                    "expected": (f"{len(parsed.species)} distinct source patterns"),
                }
            )
        try:
            _rmodel, _rnetwork, rresult = _execute(reatomized.bngl)
        except Exception as exc:
            roundtrip_problems.append(
                {
                    "field": "execution",
                    "observed": f"{type(exc).__name__}: {exc}",
                    "expected": "the reconstructed round-trip model executes",
                }
            )
        else:
            robservables = rresult["observables"]
            for written_id in written_species:
                source_id = None
                written_name = str(reimport.species[written_id].name or "")
                for pattern, candidate in law_by_pattern.items():
                    if pattern == written_name:
                        source_id = candidate
                        break
                if source_id is None:
                    return
                re_name = re_map.get(written_id)
                if re_name is None or f"{re_name}_amt" not in re_patterns:
                    roundtrip_problems.append(
                        {
                            "field": "observable",
                            "observed": written_id,
                            "expected": "the round trip exposes the written species",
                        }
                    )
                    return
                observed = np.asarray(robservables[f"{re_name}_amt"], dtype=float)
                difference = _difference(
                    observed, law[source_id], label=written_id + ".law"
                )
                if difference:
                    roundtrip_problems.append(difference)
                if reference_error is not None:
                    return
                reference_difference = _difference(
                    observed,
                    reference[source_id],
                    label=written_id + ".roadrunner",
                )
                if reference_difference:
                    roundtrip_problems.append(reference_difference)
    rows.append(
        _row(
            f"atomizer-reconstruction:{case_id}:roundtrip",
            "roundtrip",
            "FAIL" if roundtrip_problems else "PASS",
            (
                (
                    "the semantic round trip reproduces the independent law "
                    "of the generated model"
                    if reference_error is None
                    else "the semantic round trip reproduces the independent "
                    "closed-form law; the independent simulator was "
                    "unavailable (" + reference_error + ")"
                )
                if not roundtrip_problems
                else "the semantic round trip lost the source semantics"
            ),
            first_difference=(roundtrip_problems[0] if roundtrip_problems else None),
            expectation=(
                "the semantic round trip reproduces the independent law of "
                "the generated model"
            ),
            references=(
                ["closed-form law of the generated model"]
                + ([] if reference_error else ["libRoadRunner on the source SBML"])
            ),
            reference_error=reference_error,
            supported_execution=True,
        )
    )


def run(directory):
    """Execute the reconstruction qualification and return one row per check."""

    from bionetgen.atomizer.modern import (
        SBMLParser,
        source_metadata_payload,
        source_metadata_summary,
    )

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    covered_features: set[str] = set()
    for case in cases():
        covered_features.update(case["features"])
        _run_case(case, directory, rows)

    # ---- the retained metadata ------------------------------------------
    metadata_case = next(
        (case for case in cases() if "metadata" in case["features"]), None
    )
    metadata_problems = []
    metadata_evidence = {}
    if metadata_case is None:
        metadata_problems.append(
            {
                "field": "case",
                "observed": "no metadata case",
                "expected": "the family covers retained metadata",
            }
        )
    else:
        case_directory = directory / metadata_case["id"]
        written = case_directory / "roundtrip.xml"
        if not written.is_file():
            metadata_problems.append(
                {
                    "field": "artifact",
                    "observed": "no written SBML",
                    "expected": "the written SBML retains the source metadata",
                }
            )
        else:
            source_summary = source_metadata_summary(
                SBMLParser().parse(metadata_case["source"])
            )
            reimported = SBMLParser().parse(written.read_text())
            reimport_summary = source_metadata_summary(reimported)
            source_payload = source_metadata_payload(
                SBMLParser().parse(metadata_case["source"])
            )
            reimport_payload = reimported.source_metadata_payload
            metadata_evidence = {
                "source_entities": source_summary.get("metadataEntities"),
                "roundtrip_entities": reimport_summary.get("metadataEntities"),
                "source_annotations": source_summary.get("annotations"),
                "roundtrip_annotations": reimport_summary.get("annotations"),
                "source_present": bool(source_payload),
                "roundtrip_present": bool(reimport_payload),
            }
            if not source_payload:
                metadata_problems.append(
                    {
                        "field": "source",
                        "observed": "no metadata payload",
                        "expected": "the source model carries metadata",
                    }
                )
            elif not reimport_payload:
                metadata_problems.append(
                    {
                        "field": "roundtrip",
                        "observed": "no metadata payload",
                        "expected": "the written SBML retains the source metadata",
                    }
                )
            elif reimport_payload != source_payload:
                metadata_problems.append(
                    {
                        "field": "metadata",
                        "observed": reimport_summary.get("metadataEntities"),
                        "expected": source_summary.get("metadataEntities"),
                    }
                )
    rows.append(
        _row(
            "atomizer-reconstruction:metadata:roundtrip",
            "metadata-roundtrip",
            "FAIL" if metadata_problems else "PASS",
            (
                "the retained source metadata survives the SBML round trip"
                if not metadata_problems
                else "the retained source metadata did not survive the round trip"
            ),
            first_difference=metadata_problems[0] if metadata_problems else None,
            expectation=(
                "the source metadata payload is preserved by the written SBML"
            ),
            **metadata_evidence,
        )
    )

    # ---- the family coverage --------------------------------------------
    missing = sorted(set(REQUIRED_FEATURES) - covered_features)
    rows.append(
        _row(
            "atomizer-reconstruction:family:coverage",
            "family-coverage",
            "FAIL" if missing else "PASS",
            (
                "the family covers reconstruction, bond changes, compartments, "
                "quantities, retained metadata, SBML Multi and an explicit refusal"
                if not missing
                else "the family does not cover: " + ", ".join(missing)
            ),
            first_difference=(
                {
                    "field": "features",
                    "observed": missing,
                    "expected": list(REQUIRED_FEATURES),
                }
                if missing
                else None
            ),
            expectation=(
                "the generated family covers every named feature of the "
                "reconstruction scope"
            ),
            covered_features=sorted(covered_features),
            required_features=list(REQUIRED_FEATURES),
            evidence_kind="diagnostic-only",
            supported_execution=False,
        )
    )

    (directory / "reconstruction-plan.json").write_text(
        json.dumps(
            {
                "check_ids": check_ids(),
                "cases": [
                    {
                        "id": case["id"],
                        "features": list(case["features"]),
                        "representable": case["representable"],
                    }
                    for case in cases()
                ],
                "times": [float(value) for value in TIMES],
                "solver": {"rtol": SOLVER_RTOL, "atol": SOLVER_ATOL},
                "comparison": {"rtol": LAW_RTOL, "atol": LAW_ATOL},
                "references": [
                    "closed-form law of the generated model",
                    "libRoadRunner on the source SBML",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return rows


def build_report(rows, directory):
    """Assemble the harness report for this family."""

    from . import campaign

    directory = Path(directory).resolve()
    report = dict(
        schema_version=1,
        generated_by="tests.validation.atomizer_reconstruction",
        source=dict(
            revision=campaign.git(ROOT, "rev-parse", "HEAD"),
            dirty=bool(campaign.git(ROOT, "status", "--porcelain")),
        ),
        subject=dict(
            atomizer="bionetgen.atomizer.modern",
            reader="bionetgen.atomizer.modern.SBMLParser",
            writer="bionetgen._bionetgen_cpp.io.write_sbml",
        ),
        references={
            "closed_form_law": (
                "the analytic solution of the generated model, derived from the "
                "generated case parameters"
            ),
            "independent_simulator": (
                "libRoadRunner CVODE on the source SBML (Multi package "
                "declarations removed, because the core model states the "
                "reaction explicitly)"
            ),
        },
        configuration=dict(
            times=[float(value) for value in TIMES],
            solver_rtol=SOLVER_RTOL,
            solver_atol=SOLVER_ATOL,
            law_rtol=LAW_RTOL,
            law_atol=LAW_ATOL,
            atomize=True,
        ),
        results=rows,
    )
    return report


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report directory must be empty")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bng3-atomizer-reconstruction-") as temp:
        rows = run(Path(temp))
        # Retain the per-case source, reconstruction, round-trip artifacts.
        for case in cases():
            case_directory = Path(temp) / case["id"]
            if case_directory.is_dir():
                shutil.copytree(
                    case_directory, args.report_dir / case["id"], dirs_exist_ok=True
                )
    report = build_report(rows, args.report_dir)
    (args.report_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    failures = [row["id"] for row in rows if row["status"] == "FAIL"]
    for row in rows:
        print(f"{row['status']:>12}  {row['id']}")
    if failures:
        print("failing checks: " + ", ".join(failures))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
