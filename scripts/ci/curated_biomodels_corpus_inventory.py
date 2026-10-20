#!/usr/bin/env python3
"""Build the curated BioModels corpus inventory.

The inventory is a machine-readable record of one measurement of the curated
BioModels corpus: which records exist, what the Atomizer did with each of
them in the flat and the atomized mode, why a record was not supported, and
which construct a residual failure or timeout is attributed to.

The inventory is *derived* from the harness reports.  It never re-judges a
record: the harness owns the conversion, the numerical comparison and the
status vocabulary, and this script only reduces its reports to a stable
schema and adds the corpus identity (the BioModels inventory query, the
snapshot date, the report digests and the tool versions) that a reader needs
to know which measurement the numbers describe.

Usage::

    python scripts/ci/curated_biomodels_corpus_inventory.py \
        --flat-report /path/to/flat.json \
        --atomized-report /path/to/atomized.json \
        --manifest provenance/published-biomodels.json \
        --base-commit <sha> --out provenance/curated-biomodels-corpus-inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# The residual failures and timeouts of the curated corpus, classified by the
# SBML construct that causes them.  The classification is a statement about the
# *source model*, so it does not change when the Atomizer changes: a record is
# listed here because the construct it uses is the reason the record does not
# convert, not because of a particular code path.
#
# ``layer`` names the component that owns the outcome:
#
#   atomizer   the Atomizer's lowering is wrong or incomplete
#   harness    the corpus harness or its independent oracle cannot judge the
#              record; the Atomizer's own output is not the cause
#   source     the source model itself is degenerate (an undefined observable,
#              a malformed kinetic law) and the Atomizer reproduces it
FAILURE_TAXONOMY: dict[str, dict[str, Any]] = {
    "BIOMD0000000245": {
        "layer": "atomizer",
        "construct": "reaction id used as a rate inside a rule",
        "summary": (
            "The rule names seven reaction ids; the flux inlining replaced one "
            "reaction per pass and stopped after four passes, so the remaining "
            "ids reached the emitted rule as unresolved expression symbols."
        ),
    },
    "BIOMD0000000570": {
        "layer": "atomizer",
        "construct": "reaction id used as a rate inside a rate rule",
        "summary": (
            "The rate rule names seven reaction ids; the same four-pass "
            "inlining limit left three ids unresolved."
        ),
    },
    "BIOMD0000000353": {
        "layer": "atomizer",
        "construct": "compartment size set by an initialAssignment",
        "summary": (
            "A species assignment rule names a compartment whose size is set "
            "by an initial assignment; the compartment was rewritten to the "
            "constant volume parameter, producing a call to an undeclared "
            "function."
        ),
    },
    "BIOMD0000001098": {
        "layer": "atomizer",
        "construct": "MathML <apply> without an operator",
        "summary": (
            "The kinetic law of every reaction is an <apply> whose operator is "
            "a <ci> naming a parameter, which MathML reads as a call to an "
            "undeclared function.  The Atomizer translated the call faithfully "
            "and emitted a rule that does not parse."
        ),
    },
    "BIOMD0000000338": {
        "layer": "harness",
        "construct": "event-driven compartment size with a species rate rule",
        "summary": (
            "The Atomizer refuses explicitly: a species rate rule in a "
            "compartment whose size an event changes has no exact BNGL "
            "lowering.  The corpus harness does not recognise the refusal and "
            "records the record as failed instead of unsupported."
        ),
    },
    "BIOMD0000000339": {
        "layer": "harness",
        "construct": "event-driven compartment size with a species rate rule",
        "summary": (
            "The Atomizer refuses explicitly for the same reason as "
            "BIOMD0000000338; the corpus harness does not recognise the "
            "refusal."
        ),
    },
    "BIOMD0000000404": {
        "layer": "harness",
        "construct": "ill-conditioned product observable",
        "summary": (
            "The failing observable is a seven-fold product of species "
            "concentrations in a 1.41e-15 L compartment.  The comparison sits "
            "at the edge of the tolerance and does not reproduce between runs."
        ),
    },
    "BIOMD0000000451": {
        "layer": "harness",
        "construct": "stiff model rejected by the independent oracle's solver",
        "summary": (
            "libRoadRunner's CVODE fails to converge on the written SBML; "
            "BNG3's own solver produces a trajectory.  The corpus comparison "
            "needs both, so the record cannot be judged."
        ),
    },
    "BIOMD0000000601": {
        "layer": "harness",
        "construct": "stiff model rejected by a solver",
        "summary": (
            "A CVODE convergence failure on a stiff model.  The record does "
            "not reproduce on the merged tree with the rebuilt native "
            "extension."
        ),
    },
    "BIOMD0000000674": {
        "layer": "atomizer",
        "construct": "algebraic species emitted as a function",
        "summary": (
            "Species with an assignment rule are emitted as functions and "
            "removed from the reaction state; the observable values of the "
            "written SBML and of the generated model diverge."
        ),
    },
    "BIOMD0000000731": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable is ln of a quantity that is zero at t=0, so both "
            "BNG3 and libRoadRunner return -inf.  The corpus comparison "
            "requires finite values in both engines."
        ),
    },
    "BIOMD0000000803": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable is a ratio of two species that both start at "
            "zero, so both BNG3 and libRoadRunner return NaN.  The corpus "
            "comparison requires finite values in both engines."
        ),
    },
    "BIOMD0000000973": {
        "layer": "source",
        "construct": "observable that is undefined at t=0",
        "summary": (
            "The observable divides by a species that starts at zero, so both "
            "BNG3 and libRoadRunner return NaN.  The corpus comparison "
            "requires finite values in both engines."
        ),
    },
}

TIMEOUT_TAXONOMY: dict[str, dict[str, Any]] = {
    "BIOMD0000001096": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000001099": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000574": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000474": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000255": {
        "layer": "atomizer",
        "construct": "large signalling network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000235": {
        "layer": "atomizer",
        "construct": "large regulatory network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000595": {
        "layer": "atomizer",
        "construct": "large signalling network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000471": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000473": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000469": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000470": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
    "BIOMD0000000472": {
        "layer": "atomizer",
        "construct": "genome-scale metabolic network",
        "summary": "The Atomizer's expression translation does not finish inside the per-model budget.",
    },
}

# The effect of the change under review, measured record by record with the
# corpus gate's own ``--only-id`` path.  The entries are the records the
# branch changes; each one was measured on the branch and on ``main`` with the
# same native extension.
BRANCH_EFFECT: dict[str, dict[str, Any]] = {
    "BIOMD0000000245": {
        "construct": "reaction id used as a rate inside a rule",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "The rule names seven reaction ids.  The flux inlining replaced one "
            "reaction per pass and stopped after four passes, so the remaining "
            "ids reached the emitted rule as unresolved expression symbols and "
            "the model did not compile."
        ),
    },
    "BIOMD0000000570": {
        "construct": "reaction id used as a rate inside a rate rule",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "The rate rule names seven reaction ids; the same four-pass limit "
            "left three of them unresolved."
        ),
    },
    "BIOMD0000000353": {
        "construct": "compartment size set by an initialAssignment",
        "main": "failed",
        "branch": "passed",
        "cause": (
            "A species assignment rule names a compartment whose size an "
            "initial assignment sets; the compartment was rewritten to the "
            "constant volume parameter, producing a call to an undeclared "
            "function."
        ),
    },
    "BIOMD0000001098": {
        "construct": "MathML <apply> without an operator",
        "main": "failed",
        "branch": "unsupported",
        "cause": (
            "Every kinetic law is an <apply> whose operator is a <ci> naming a "
            "parameter, which MathML reads as a call to an undeclared "
            "function; the emitted rule did not parse.  The construct is now "
            "reported as a loss."
        ),
    },
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tool_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for name in ("libsbml", "roadrunner"):
        try:
            module = __import__(name)
        except ImportError:
            versions[name] = None
            continue
        versions[name] = getattr(module, "__version__", None)
    try:
        import bionetgen

        versions["bionetgen"] = getattr(bionetgen, "__version__", None)
    except ImportError:
        versions["bionetgen"] = None
    return versions


def _record_modes(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the per-mode results of one harness record."""

    modes = record.get("modes")
    if isinstance(modes, list):
        return modes
    return []


def _mode_status(record: dict[str, Any], mode: str) -> str:
    for entry in _record_modes(record):
        if entry.get("mode") == mode:
            return str(entry.get("status") or "passed")
    return str(record.get("status") or "unknown")


def _structural_atomization(bngl: str) -> dict[str, Any]:
    """Report whether a generated model carries inferred molecular structure.

    The structural trigger in the Atomizer's species-composition table is a
    bond character in a species name.  A model whose species names carry no
    bond character degrades to one molecule per species, which is the flat
    representation written with a different name.
    """

    molecules = 0
    bonded = 0
    for line in bngl.splitlines():
        stripped = line.strip()
        if not stripped.startswith("M_"):
            continue
        molecules += 1
        if "(" in stripped and ")" in stripped:
            inner = stripped[stripped.find("(") + 1 : stripped.rfind(")")]
            if re.search(r"[!\-=]", inner):
                bonded += 1
    return {
        "molecule_types": molecules,
        "molecule_types_with_bonds": bonded,
        "structurally_atomized": bonded > 0,
    }


def _summarize(report: dict[str, Any], label: str) -> dict[str, Any]:
    records = report.get("records") or []
    status_counts: Counter = Counter()
    cause_counts: Counter = Counter()
    sbml_records = 0
    for record in records:
        status = str(record.get("status", "unknown"))
        status_counts[status] += 1
        for cause in record.get("unsupported_causes") or []:
            cause_counts[str(cause)] += 1
        if str(record.get("format", "")).lower().find("sbml") >= 0:
            sbml_records += 1
    return {
        "label": label,
        "mode": report.get("mode"),
        "selected_records": len(records),
        "declared_sbml_records": sbml_records,
        "status_counts": dict(sorted(status_counts.items())),
        "unsupported_cause_counts": dict(sorted(cause_counts.items())),
        "summary": report.get("summary"),
    }


def _case_rows(
    flat: dict[str, Any],
    atomized: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    flat_records = {str(r.get("id")): r for r in (flat.get("records") or [])}
    atomized_records = (
        {str(r.get("id")): r for r in (atomized.get("records") or [])}
        if atomized
        else {}
    )
    rows: list[dict[str, Any]] = []
    for model_id, record in flat_records.items():
        other = atomized_records.get(model_id)
        flat_status = str(record.get("status", "unknown"))
        atomized_status = (
            str(other.get("status", "unknown")) if other is not None else None
        )
        row: dict[str, Any] = {
            "id": model_id,
            "name": record.get("name"),
            "format": record.get("format"),
            "flat_status": flat_status,
            "atomized_status": atomized_status,
            "flat_causes": sorted(
                set(str(c) for c in (record.get("unsupported_causes") or []))
            ),
            "atomized_causes": (
                sorted(set(str(c) for c in (other.get("unsupported_causes") or [])))
                if other is not None
                else None
            ),
            "moved_between_modes": (
                atomized_status is not None and atomized_status != flat_status
            ),
            "flat_network": _network_size(record),
            "atomized_network": _network_size(other) if other is not None else None,
        }
        if flat_status == "failed":
            row["failure_classification"] = FAILURE_TAXONOMY.get(model_id)
        if flat_status == "timeout":
            row["timeout_classification"] = TIMEOUT_TAXONOMY.get(model_id)
        rows.append(row)
    return rows


def _network_size(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the generated network size of one harness record."""

    if not record:
        return None
    for entry in _record_modes(record):
        network = entry.get("generated_network")
        if network:
            return {
                "species": network.get("species"),
                "reactions": network.get("reactions"),
            }
    return None


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flat-report", type=Path, required=True)
    parser.add_argument("--atomized-report", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo / "provenance" / "published-biomodels.json",
    )
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--measurement-date", default="")
    parser.add_argument(
        "--structural-trigger-report",
        type=Path,
        help=(
            "output of scripts/ci/measure_structural_trigger.py: the per-record "
            "count of the species whose name carries the Atomizer's structural "
            "trigger"
        ),
    )
    parser.add_argument("--label", default="corpus")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    flat = json.loads(args.flat_report.read_text(encoding="utf-8"))
    atomized = (
        json.loads(args.atomized_report.read_text(encoding="utf-8"))
        if args.atomized_report
        else None
    )
    structural = (
        json.loads(args.structural_trigger_report.read_text(encoding="utf-8"))
        if args.structural_trigger_report
        else None
    )

    inventory: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": args.label,
        "description": (
            "Inventory of the curated BioModels corpus: the corpus identity, the "
            "per-record outcome of the modern Atomizer in the flat and the "
            "atomized mode, and the classification of every residual failure "
            "and timeout.  The harness owns every status; this file only "
            "reduces its reports and adds the corpus identity."
        ),
        "corpus": {
            "source": manifest.get("source"),
            "search_api_url": manifest.get("search_api_url"),
            "inventory_query": manifest.get("curation_query"),
            "snapshot_date": manifest.get("snapshot_date"),
            "expected_total_records": manifest.get("expected_total_records"),
            "expected_sbml_records": manifest.get("expected_sbml_records"),
            "expected_non_sbml_records": manifest.get("expected_non_sbml_records"),
        },
        "measurement": {
            "base_commit": args.base_commit,
            "measurement_date": args.measurement_date,
            "tool_versions": _tool_versions(),
            "note": (
                "The per-record status is the status the reduced harness report "
                "records.  The effect of the change under review is stated "
                "separately, in residuals.branch_effect, with the records it "
                "touches and where they were measured."
            ),
            "reports": {
                "flat": {
                    "path": str(args.flat_report),
                    "sha256": _digest(args.flat_report),
                },
            },
        },
        "modes": {
            "flat": _summarize(flat, "flat"),
        },
    }
    if atomized is not None:
        inventory["measurement"]["reports"]["atomized"] = {
            "path": str(args.atomized_report),
            "sha256": _digest(args.atomized_report),
        }
        inventory["modes"]["atomized"] = _summarize(atomized, "atomized")

    rows = _case_rows(flat, atomized)
    inventory["cases"] = rows

    flat_summary = inventory["modes"]["flat"]
    failures = [row for row in rows if row["flat_status"] == "failed"]
    timeouts = [row for row in rows if row["flat_status"] == "timeout"]
    inventory["residuals"] = {
        "failed_count": len(failures),
        "timeout_count": len(timeouts),
        "failed_ids": [row["id"] for row in failures],
        "timeout_ids": [row["id"] for row in timeouts],
        "by_layer": dict(
            sorted(
                Counter(
                    (row.get("failure_classification") or {}).get(
                        "layer", "unclassified"
                    )
                    for row in failures
                ).items()
            )
        ),
        "timeout_by_layer": dict(
            sorted(
                Counter(
                    (row.get("timeout_classification") or {}).get(
                        "layer", "unclassified"
                    )
                    for row in timeouts
                ).items()
            )
        ),
    }
    if atomized is not None:
        moved = [row for row in rows if row["moved_between_modes"]]
        atomized_summary = inventory["modes"]["atomized"]
        inflations = [
            row["atomized_network"]["species"] / row["flat_network"]["species"]
            for row in rows
            if row.get("flat_network")
            and row.get("atomized_network")
            and row["flat_network"].get("species")
        ]
        inventory["mode_comparison"] = {
            "records_in_both_modes": sum(
                1 for row in rows if row["atomized_status"] is not None
            ),
            "moved_between_modes": len(moved),
            "moved_ids": [row["id"] for row in moved],
            "flat_passed": flat_summary["status_counts"].get("passed", 0),
            "atomized_passed": atomized_summary["status_counts"].get("passed", 0),
            "lost_in_atomized": sorted(
                row["id"]
                for row in rows
                if row["flat_status"] == "passed"
                and row["atomized_status"] not in (None, "passed")
            ),
            "gained_in_atomized": sorted(
                row["id"]
                for row in rows
                if row["flat_status"] != "passed" and row["atomized_status"] == "passed"
            ),
            "records_with_both_networks": len(inflations),
            "records_with_a_different_network": sum(
                1
                for row in rows
                if row.get("flat_network")
                and row.get("atomized_network")
                and row["flat_network"].get("species")
                != row["atomized_network"].get("species")
            ),
            "median_species_inflation": (
                sorted(inflations)[len(inflations) // 2] if inflations else None
            ),
            "max_species_inflation": max(inflations) if inflations else None,
        }
    if structural is not None:
        inventory["structural_atomization"] = {
            "source_report": {
                "path": str(args.structural_trigger_report),
                "sha256": _digest(args.structural_trigger_report),
            },
            "summary": structural.get("summary"),
        }
    if BRANCH_EFFECT:
        inventory["residuals"]["branch_effect"] = {
            "note": (
                "The records the change under review touches, measured record "
                "by record with the corpus gate's --only-id path on the branch "
                "and on main with the same native extension."
            ),
            "records": {
                model_id: {
                    **entry,
                    "measured_in_report": next(
                        (row["flat_status"] for row in rows if row["id"] == model_id),
                        None,
                    ),
                }
                for model_id, entry in sorted(BRANCH_EFFECT.items())
            },
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
