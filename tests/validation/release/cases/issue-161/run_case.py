#!/usr/bin/env python3
"""Run the reduced Issue 161 authored Multi export comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import libsbml

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
from scripts.cross_validate import (  # noqa: E402
    _AUTHORED_EXPORTS,
    _run_engine,
    _stage_authored_action_model,
    run_cross_validation,
)
from tests.validation.compare import compare_net, parse_net  # noqa: E402
from scripts.ci.oracle_sources import load_lock, load_oracle_source  # noqa: E402
from tests.validation.oracle_perl import _is_locked_bng2  # noqa: E402

# Keep this acceptance process bound to the checkout under test when another
# environment installed an editable BNG3 package earlier in the interpreter.
sys.meta_path[:] = [
    finder
    for finder in sys.meta_path
    if type(finder).__name__ != "ScikitBuildRedirectingFinder"
]
from bionetgen.atomizer.modern import (  # noqa: E402
    SBMLParser,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)
from bionetgen.atomizer.modern import parser as modern_parser  # noqa: E402

MODEL_NAME = "test_write_sbml_multi"
MOLECULE_ALIASES = {"R": "M_R", "L": "M_L"}
CASES = (
    "test_write_sbml_multi.bngl",
    "state_bearing_binding_refusal.bngl",
)
LOCKED_BNG2_REVISION = load_oracle_source(load_lock(), "bionetgen")["revision"]
if not Path(modern_parser.__file__).resolve().is_relative_to(ROOT.resolve()):
    raise RuntimeError(
        "issue-161 acceptance imported the wrong atomizer source: "
        f"{modern_parser.__file__}"
    )


def _git_identity(path: Path) -> dict:
    git_path = path if path.is_dir() else path.parent
    root = subprocess.run(
        ["git", "-C", str(git_path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    revision = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"root": root, "revision": revision, "dirty": dirty}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compare_source_networks(reference, candidate, *, molecule_name_aliases=None):
    """Compare source and reconstructed networks, including initial quantities."""
    if isinstance(reference, (str, Path)):
        reference = parse_net(reference)
    if isinstance(candidate, (str, Path)):
        candidate = parse_net(candidate)
    if reference is None or candidate is None:
        raise ValueError("an issue-161 source network could not be parsed")
    return compare_net(
        reference,
        candidate,
        compare_initial_amounts=True,
        molecule_name_aliases=molecule_name_aliases,
    )


def _preserve_evidence_file(source: Path, directory: Path, name: str) -> str:
    """Copy one generated input/output into the uploaded acceptance evidence."""

    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    shutil.copy2(source, destination)
    return str(destination)


def _sbml_validity(path: Path) -> dict:
    """Record libSBML consistency errors without treating invalid XML as parity."""

    document = libsbml.readSBMLFromFile(str(path))
    if document is None:
        return {
            "status": "invalid",
            "severity_error_count": 1,
            "diagnostics": ["libSBML could not read the document"],
        }
    document.checkConsistency()
    diagnostics = []
    for index in range(document.getNumErrors()):
        error = document.getError(index)
        if error.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            diagnostics.append(
                {
                    "id": error.getErrorId(),
                    "line": error.getLine(),
                    "message": error.getMessage().strip().splitlines()[0],
                }
            )
    return {
        "status": "valid" if not diagnostics else "invalid",
        "severity_error_count": len(diagnostics),
        "diagnostics": diagnostics,
    }


def _reference_sbml_validity(path: Path) -> dict:
    """Classify invalid BNG2 output as an ineligible structural reference."""

    validity = _sbml_validity(path)
    if validity["status"] == "invalid":
        validity["classification"] = "reference-invalid"
    return validity


def _consume_and_reimport(
    xml_path: Path, bng_cpp: Path, work_dir: Path, timeout: float
) -> dict:
    """Require the emitted Multi document to reconstruct and execute in BNG3."""

    model = SBMLParser().parse(xml_path.read_text(encoding="utf-8"))
    if not model.multi_executable:
        raise RuntimeError("reimported SBML Multi model is not executable")
    if not model.multi_species_patterns or not model.multi_reaction_mappings:
        raise RuntimeError("reimported SBML Multi structures are empty")

    composition = build_species_composition_table(model)
    molecule_types = get_molecule_types(composition, model.multi_type_patterns.values())
    bngl, _ = generate_bngl(
        model, composition, molecule_types, get_seed_species(composition, model)
    )
    if "not yet fed into the simulated network" in bngl:
        raise RuntimeError(
            "reimported Multi data was dropped during BNGL reconstruction"
        )

    reconstructed = work_dir / "reimported_multi.bngl"
    reconstructed.write_text(
        bngl.rstrip()
        + "\n\n## actions ##\ngenerate_network({overwrite=>1,max_iter=>20,max_agg=>2})\n",
        encoding="utf-8",
    )
    result, error = _run_engine([str(bng_cpp), str(reconstructed)], work_dir, timeout)
    if error:
        raise RuntimeError(f"reimported BNG3 model did not execute: {error}")
    if result is None or result.returncode != 0:
        detail = "process did not return" if result is None else result.stderr.strip()
        raise RuntimeError(f"reimported BNG3 model did not execute: {detail}")
    network = work_dir / "reimported_multi.net"
    if not network.is_file() or network.stat().st_size == 0:
        raise RuntimeError("reimported BNG3 model did not produce a network")
    return {
        "species_patterns": len(model.multi_species_patterns),
        "reaction_mappings": len(model.multi_reaction_mappings),
        "network_bytes": network.stat().st_size,
    }


def _unit_compartment_source(source: Path) -> str:
    """Give each fixture an explicit unit-volume compartment for parity."""

    text = source.read_text(encoding="utf-8").split("## actions ##", 1)[0]
    marker = "begin molecule types"
    if text.count(marker) != 1 or "begin compartments" in text:
        raise RuntimeError("issue-161 source no longer has its expected header")
    text = text.replace(
        marker,
        "begin compartments\n    default 3 1\nend compartments\n" + marker,
    )

    seed_start = text.index("begin seed species")
    seed_end = text.index("end seed species", seed_start)
    seed_lines = text[seed_start:seed_end].splitlines()
    qualified_seeds = []
    for line in seed_lines:
        if not line.strip() or line.strip() == "begin seed species":
            qualified_seeds.append(line)
            continue
        match = re.fullmatch(r"(\s*)([^\s@][^\s]*)(\s+)([^\s]+)(\s*)", line)
        if match is None:
            raise RuntimeError(f"unexpected issue-161 seed species: {line!r}")
        qualified_seeds.append(
            f"{match[1]}@default:{match[2]}{match[3]}{match[4]}{match[5]}"
        )
    text = text[:seed_start] + "\n".join(qualified_seeds) + "\n" + text[seed_end:]

    start = text.index("begin reaction rules")
    end = text.index("end reaction rules", start)
    block = text[start:end]
    rendered = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "begin reaction rules":
            rendered.append(line)
            continue
        arrow = next(
            (candidate for candidate in ("<->", "->", "<-") if candidate in stripped),
            None,
        )
        if arrow is None:
            raise RuntimeError(f"unexpected issue-161 rule: {line}")

        def qualify(pattern: str) -> str:
            pattern = pattern.strip()
            return pattern if pattern.startswith("@") else f"@default:{pattern}"

        reactants, product_and_rate = stripped.split(arrow, 1)
        product, rate = product_and_rate.rsplit(None, 1)
        reactants = " + ".join(
            qualify(participant) for participant in reactants.split(" + ")
        )
        rendered.append(f"    {reactants} {arrow} {qualify(product)} {rate}")
    text = text[:start] + "\n".join(rendered) + "\n" + text[end:]
    return text


def _bounded_network(
    text: str,
    *,
    engine: str,
    bng_cpp: Path,
    bng2: Path,
    perl: str,
    work_dir: Path,
    timeout: float,
    artifact_path: Path | None = None,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    model = work_dir / "issue161_source.bngl"
    model.write_text(
        text.rstrip()
        + "\n\n## actions ##\ngenerate_network({overwrite=>1,max_iter=>20,max_agg=>2})\n",
        encoding="utf-8",
    )
    if engine == "BNG2":
        command = [perl, str(bng2.resolve()), "--outdir", str(work_dir), str(model)]
        environment = {"BNGPATH": str(bng2.resolve().parent)}
    else:
        command = [str(bng_cpp.resolve()), str(model)]
        environment = None
    result, error = _run_engine(command, work_dir, timeout, environment=environment)
    if error or result is None or result.returncode != 0:
        detail = error or (
            "process did not return" if result is None else result.stderr.strip()
        )
        raise RuntimeError(f"{engine} bounded source network failed: {detail}")
    network = work_dir / "issue161_source.net"
    if not network.is_file() or not network.stat().st_size:
        raise RuntimeError(f"{engine} bounded source network is missing")
    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(network, artifact_path)
    return network


def _first_reversible_rule(source_text: str) -> str:
    start = source_text.index("begin reaction rules")
    end = source_text.index("end reaction rules", start)
    block = source_text[start:end].splitlines()
    rules = [line for line in block[1:] if line.strip()]
    if not rules:
        raise RuntimeError("issue-161 source has no reaction rule")
    return (
        source_text[:start]
        + "\n".join([block[0], rules[0], "end reaction rules"])
        + source_text[end + len("end reaction rules") :]
    )


def _compare_bounded_source_and_reimport(
    source: Path,
    reimported_net: Path,
    *,
    bng_cpp: Path,
    bng2: Path,
    perl: str,
    work_dir: Path,
    timeout: float,
    expected_one_rule_rates: set[str],
    artifact_dir: Path | None = None,
) -> dict:
    """Compare bounded graph and rates to pinned BNG2 and direct BNG3."""

    source_text = _unit_compartment_source(source)
    bng2_net = _bounded_network(
        source_text,
        engine="BNG2",
        bng_cpp=bng_cpp,
        bng2=bng2,
        perl=perl,
        work_dir=work_dir / "bng2",
        timeout=timeout,
        artifact_path=(artifact_dir / "bng2-source.net") if artifact_dir else None,
    )
    bng3_net = _bounded_network(
        source_text,
        engine="BNG3",
        bng_cpp=bng_cpp,
        bng2=bng2,
        perl=perl,
        work_dir=work_dir / "bng3",
        timeout=timeout,
        artifact_path=(artifact_dir / "bng3-source.net") if artifact_dir else None,
    )
    oracle = parse_net(bng2_net)
    direct = parse_net(bng3_net)
    imported = parse_net(reimported_net)
    if oracle is None or direct is None or imported is None:
        raise RuntimeError("a bounded issue-161 network could not be parsed")
    direct_diff = _compare_source_networks(oracle, direct)
    if not direct_diff.ok:
        raise RuntimeError(
            f"direct BNG3 source differs from pinned BNG2: {direct_diff.summary()}"
        )

    one_rule = _first_reversible_rule(source_text)
    one_rule_bng2 = parse_net(
        _bounded_network(
            one_rule,
            engine="BNG2",
            bng_cpp=bng_cpp,
            bng2=bng2,
            perl=perl,
            work_dir=work_dir / "one-rule-bng2",
            timeout=timeout,
            artifact_path=(artifact_dir / "bng2-one-rule.net")
            if artifact_dir
            else None,
        )
    )
    one_rule_bng3 = parse_net(
        _bounded_network(
            one_rule,
            engine="BNG3",
            bng_cpp=bng_cpp,
            bng2=bng2,
            perl=perl,
            work_dir=work_dir / "one-rule-bng3",
            timeout=timeout,
            artifact_path=(artifact_dir / "bng3-one-rule.net")
            if artifact_dir
            else None,
        )
    )
    if one_rule_bng2 is None or one_rule_bng3 is None:
        raise RuntimeError("the one-rule source oracle network could not be parsed")
    one_rule_diff = _compare_source_networks(one_rule_bng2, one_rule_bng3)
    one_rule_rates = {reaction[-1] for reaction in one_rule_bng2.reaction_multiset}
    if not one_rule_diff.ok or one_rule_rates != expected_one_rule_rates:
        raise RuntimeError(
            "one-rule BNG2 parity did not preserve the expected forward and reverse rates "
            f"rates={sorted(one_rule_rates)}, diff={one_rule_diff.summary()}"
        )

    imported_diff = _compare_source_networks(
        oracle, imported, molecule_name_aliases=MOLECULE_ALIASES
    )
    topology_and_rates_match = (
        oracle.n_species == imported.n_species
        and oracle.n_reactions == imported.n_reactions
        and not imported_diff.species_only_ref
        and not imported_diff.species_only_test
        and not imported_diff.reactions_only_ref
        and not imported_diff.reactions_only_test
        and not imported_diff.initial_amounts_changed
    )
    if not topology_and_rates_match:
        raise RuntimeError(
            "reimported Multi network differs from pinned BNG2 in species, "
            f"reaction topology, or rates: {imported_diff.summary()}"
        )
    artifact_files = {}
    if artifact_dir is not None:
        artifact_files = {
            "bng2_source": str(artifact_dir / "bng2-source.net"),
            "bng3_source": str(artifact_dir / "bng3-source.net"),
            "bng2_one_rule": str(artifact_dir / "bng2-one-rule.net"),
            "bng3_one_rule": str(artifact_dir / "bng3-one-rule.net"),
            "sbml_multi_reimport": _preserve_evidence_file(
                reimported_net, artifact_dir, "sbml-multi-reimport.net"
            ),
        }
    return {
        "bounded_depth": 2,
        "network_counts": {
            "bng2_source": {
                "species": oracle.n_species,
                "reactions": oracle.n_reactions,
            },
            "bng3_source": {
                "species": direct.n_species,
                "reactions": direct.n_reactions,
            },
            "sbml_multi_reimport": {
                "species": imported.n_species,
                "reactions": imported.n_reactions,
            },
        },
        "direct_source_diff": direct_diff.summary(),
        "one_rule_rate_keys": sorted(one_rule_rates),
        "one_rule_source_diff": one_rule_diff.summary(),
        "reimport_topology_and_rates": "pass",
        "reimport_helper_observable_groups": len(imported_diff.groups_only_test),
        "network_artifacts": artifact_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--bng2", type=Path, required=True)
    parser.add_argument("--perl", default="perl")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    evidence_dir = (
        args.report.with_suffix("").with_name(args.report.stem + "_evidence")
        if args.report
        else None
    )

    for name, path in (("bng_cpp", args.bng_cpp), ("BNG2.pl", args.bng2)):
        if not path.is_file():
            parser.error(f"{name} is not a file: {path}")
    product = _git_identity(ROOT)
    oracle = _git_identity(args.bng2)
    provenance = {
        "product": product,
        "atomizer_parser": str(Path(modern_parser.__file__).resolve()),
        "bng_cpp": {
            "path": str(args.bng_cpp.resolve()),
            "sha256": _sha256(args.bng_cpp),
        },
        "bng2": {
            **oracle,
            "locked_revision": LOCKED_BNG2_REVISION,
            "revision_matches_lock": oracle["revision"] == LOCKED_BNG2_REVISION,
            "checkout_is_locked": _is_locked_bng2(args.bng2),
            "script": {"path": str(args.bng2.resolve()), "sha256": _sha256(args.bng2)},
        },
    }
    provenance["eligible"] = bool(
        not product["dirty"]
        and oracle["revision"] == LOCKED_BNG2_REVISION
        and not oracle["dirty"]
        and provenance["bng2"]["checkout_is_locked"]
    )
    case_results = []
    for case in CASES:
        source = Path(__file__).with_name(case)
        with tempfile.TemporaryDirectory(
            prefix=f"bng3-issue-161-{source.stem}-"
        ) as raw:
            root = Path(raw)
            models = root / "Validate"
            models.mkdir()
            staged = models / f"{MODEL_NAME}.bngl"
            shutil.copyfile(source, staged)
            counts, details = run_cross_validation(
                args.bng_cpp,
                args.bng2,
                models,
                perl_executable=args.perl,
                timeout=args.timeout,
                model_names=[MODEL_NAME],
                artifact_dir=(evidence_dir / "strict-authored-xml")
                if evidence_dir
                else None,
            )
            consumer = None
            candidate_artifact = None
            reference_artifact = None
            reference_validity = {
                "status": "error",
                "error": "BNG2 authored XML was not validated",
            }
            candidate_validity = {
                "status": "error",
                "error": "BNG3 authored XML was not validated",
            }
            cpp_dir = root / "consumer-cpp"
            cpp_dir.mkdir()
            cpp_model = _stage_authored_action_model(staged, models, cpp_dir)
            result, error = _run_engine(
                [str(args.bng_cpp.resolve()), str(cpp_model)],
                cpp_dir,
                args.timeout,
            )
            if error:
                consumer_error = error
            elif result is None or result.returncode != 0:
                consumer_error = (
                    "process did not return"
                    if result is None
                    else result.stderr.strip()
                )
            else:
                output = cpp_dir / f"{MODEL_NAME}_sbml_multi.xml"
                if not output.is_file() or not output.stat().st_size:
                    consumer_error = "C++ authored export output is missing or empty"
                else:
                    consumer_error = None
                    candidate_validity = _sbml_validity(output)
                    candidate_artifact = (
                        _preserve_evidence_file(
                            output,
                            evidence_dir / "authored-xml",
                            f"{Path(case).stem}.bng3.xml",
                        )
                        if evidence_dir
                        else None
                    )
                    try:
                        consumer = _consume_and_reimport(
                            output, args.bng_cpp.resolve(), cpp_dir, args.timeout
                        )
                    except Exception as exc:  # the report preserves the failing stage
                        consumer_error = str(exc)
            reference_dir = root / "authored-bng2"
            reference_dir.mkdir()
            reference_model = _stage_authored_action_model(
                staged, models, reference_dir
            )
            reference_result, reference_error = _run_engine(
                [
                    args.perl,
                    str(args.bng2.resolve()),
                    "--outdir",
                    str(reference_dir),
                    str(reference_model),
                ],
                reference_dir,
                args.timeout,
                environment={"BNGPATH": str(args.bng2.resolve().parent)},
            )
            if reference_error:
                reference_validity = {
                    "status": "error",
                    "error": reference_error,
                }
            elif reference_result is None or reference_result.returncode != 0:
                reference_validity = {
                    "status": "error",
                    "error": (
                        "BNG2 authored export process did not return"
                        if reference_result is None
                        else reference_result.stderr.strip()
                    ),
                }
            else:
                reference_xml = reference_dir / _AUTHORED_EXPORTS[MODEL_NAME][0]["perl"]
                if not reference_xml.is_file() or not reference_xml.stat().st_size:
                    reference_validity = {
                        "status": "error",
                        "error": "BNG2 authored XML is missing or empty",
                    }
                else:
                    reference_validity = _reference_sbml_validity(reference_xml)
                    reference_artifact = (
                        _preserve_evidence_file(
                            reference_xml,
                            evidence_dir / "authored-xml",
                            f"{Path(case).stem}.bng2.xml",
                        )
                        if evidence_dir
                        else None
                    )
            case_results.append(
                {
                    "source": case,
                    "source_sha256": _sha256(source),
                    "authored_export": {"counts": counts, "details": details},
                    "xml_validity": {
                        "reference_bng2": reference_validity,
                        "candidate_bng3": candidate_validity,
                        "reference_xml_artifact": reference_artifact,
                        "candidate_xml_artifact": candidate_artifact,
                    },
                    "reimport_network_smoke": {
                        "status": "pass" if consumer_error is None else "error",
                        "details": consumer,
                        "error": consumer_error,
                    },
                }
            )
            entry = case_results[-1]
            if consumer_error is None:
                try:
                    entry["bounded_source_rate_parity"] = {
                        "status": "pass",
                        "details": _compare_bounded_source_and_reimport(
                            source,
                            cpp_dir / "reimported_multi.net",
                            bng_cpp=args.bng_cpp.resolve(),
                            bng2=args.bng2.resolve(),
                            perl=args.perl,
                            work_dir=root / "bounded-source-parity",
                            timeout=args.timeout,
                            expected_one_rule_rates=(
                                {"0.006", "0.1"}
                                if case == CASES[0]
                                else {"0.01", "0.1"}
                            ),
                            artifact_dir=(evidence_dir / Path(case).stem / "networks")
                            if evidence_dir
                            else None,
                        ),
                    }
                except Exception as exc:
                    entry["bounded_source_rate_parity"] = {
                        "status": "error",
                        "details": None,
                        "error": str(exc),
                        "artifact_directory": (
                            str(evidence_dir / Path(case).stem / "networks")
                            if evidence_dir
                            else None
                        ),
                    }
            else:
                entry["bounded_source_rate_parity"] = {
                    "status": "error",
                    "details": None,
                    "error": consumer_error,
                }
    report = {
        "case": "issue-161/authored-multi-and-reimport-network-smoke",
        "evidence_directory": str(evidence_dir) if evidence_dir else None,
        "provenance": provenance,
        "cases": case_results,
        "classification": (
            "pass"
            if provenance["eligible"]
            and all(
                entry["authored_export"]["counts"] == {"pass": 1, "fail": 0, "error": 0}
                and entry["reimport_network_smoke"]["status"] == "pass"
                and entry["bounded_source_rate_parity"]["status"]
                in {"pass", "not-applicable"}
                for entry in case_results
            )
            else "failed-or-error"
        ),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["classification"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
