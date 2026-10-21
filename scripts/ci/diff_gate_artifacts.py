#!/usr/bin/env python3
"""Diff the artifacts two gate runs produced, not only their verdicts.

A gate's verdict says whether a case passed.  It does not say whether the
*model* the gate produced changed.  A change to the Atomizer can rewrite the
generated BNGL for a case whose verdict stays exactly the same, and a verdict
comparison cannot see that: when one Atomizer change was reviewed, the
reviewer had to write a script to find the nineteen models that moved under
nine unchanged verdicts.  A harness that reported it automatically would have
caught it the first time.

This tool compares two runs' retained artifact trees case by case and reports,
for every case, which artifacts differ and by how much.  It classifies each
case into one of three outcomes, because the three mean different things:

``model changed, verdict changed``
    The ordinary case: the model moved and the gate noticed.

``model changed, verdict unchanged``
    The case this tool exists to surface.  A changed model with an unchanged
    verdict means the change did not affect the result *or* the verdict is not
    sensitive to it, and a reader cannot tell which.  Those cases need a
    human, so they are listed separately.

``model unchanged``
    A positive result.  The absence of a model difference is stated so the
    reader knows the comparison was made and found nothing, rather than
    having to assume that no report means no difference.

A fourth bucket, ``model unresolved``, is reported when an artifact cannot be
compared soundly -- see the reproducibility discussion below.  It is kept out
of the three outcomes because "the model did not change" must never be claimed
for a comparison that could not be made.

What is compared
----------------

Text artifacts (generated BNGL, exported SBML, the source SBML, the official
reference files, the worker's logs) are compared line by line, and the report
gives the *first differing line* with both texts.  That is what makes the
report actionable: a reader can go straight to the line that moved.

Numeric artifacts (the per-observable comparison numbers and the per-variable
official-reference numbers) are compared numerically, with a tolerance, and
the report gives the magnitude of the change.  A numeric difference is
reported separately and is never treated as a verdict difference or as a model
change: solver output is not bit-reproducible, and a report that cried wolf
over solver noise would teach the reader to ignore it.

Run-local provenance is not compared.  The interpreter, the working directory,
the command line and the recorded package paths say which build observed a
case, not what it observed, and a tool that reports them as differences is
worse than no tool.

Hash seed and reproducibility
-----------------------------

Per-case generated BNGL text is not bit-reproducible across processes while
the interpreter's hash seed is random, so two runs of the same code can
produce different text for the same model.  The comparison is therefore only
sound when both runs produced their artifacts under the *same pinned seed*.

The tool says so.  It reports the seed each run recorded, if the run recorded
one, and states the seed condition of the comparison.  When neither run
recorded a seed the tool says that the comparison assumes a shared pinned
seed rather than quietly implying that it verified one.

The tool can also *establish* reproducibility instead of assuming it.  With
``--probe-reproducibility`` it regenerates the artifacts of the interesting
cases three times: twice under one pinned seed and once under a contrasting
seed.  Two questions are then answered from measurements rather than
assumptions.

*An artifact whose two pinned-seed regenerations differ* is reported as

    not reproducible under a pinned seed

and is not reported as a difference: the difference cannot be attributed to
the change under test.

*An artifact that differs between the pinned seed and the contrasting seed*
is reported as

    changes with the interpreter's hash seed

and its difference is not reported as a difference either.  The Atomizer's
output is not reproducible across processes while the hash seed is random, so
two runs that used different seeds produce different text for the same model.
Reporting that as a model change would be a false difference.

When the probe cannot be run, or does not settle the question, the artifact is
reported as *unresolved* rather than silently counted as unchanged.

Usage
-----

::

    python scripts/ci/diff_gate_artifacts.py \\
        --first-artifacts /tmp/run-a/artifacts --second-artifacts /tmp/run-b/artifacts \\
        --first-report /tmp/run-a/report.json --second-report /tmp/run-b/report.json

    # one case only
    python scripts/ci/diff_gate_artifacts.py \\
        --first-artifacts ... --second-artifacts ... --case semantic/00879

The exit status is 0 when no model artifact changed and no verdict changed,
1 when something changed or could not be settled, and 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

# Artifact roles.  A file's role decides how it is compared and whether it
# counts as "the model".
ROLE_SOURCE = "source"
ROLE_MODEL = "model"
ROLE_REPORT = "report"
ROLE_LOG = "log"
ROLE_REFERENCE = "reference"

# The per-case JSON report the gate retains next to the case's artifacts.
REPORT_ARTIFACT_NAMES = ("worker-report.json", "record.json", "report.json")

# The outcomes.  ``model unchanged`` is a positive result; the other two are
# the interesting ones.
OUTCOME_CHANGED_CHANGED = "model changed, verdict changed"
OUTCOME_CHANGED_UNCHANGED = "model changed, verdict unchanged"
OUTCOME_UNCHANGED = "model unchanged"
OUTCOME_UNRESOLVED = "model unresolved"

# Probe commands.  ``{...}`` placeholders are substituted per case; see
# ``_probe_context`` for the available names.  Optional flags are passed as
# whole arguments so that an unknown value omits the flag instead of
# supplying an empty one.
SUITE_PROBE_COMMAND = (
    "{python} {gate} {lock_arg} --suite-dir {suite_dir} "
    "--categories {category} --only-case {case} --worker "
    "--artifacts-dir {artifacts_dir} --json {json} "
    "--simulation-t-end {t_end} --simulation-n-steps {n_steps} "
    "--simulation-rtol {rtol} --simulation-atol {atol}"
)
CORPUS_PROBE_COMMAND = (
    "{python} {gate} {manifest_arg} {cache_dir_arg} "
    "--json {json} --mode {mode} --offline --only-id {id} --worker "
    "--artifacts-dir {artifacts_dir} "
    "--simulation-t-end {t_end} --simulation-n-steps {n_steps} "
    "--simulation-rtol {rtol} --simulation-atol {atol}"
)

# Seed values that mean "the run did not pin the seed".
UNPINNED_SEEDS = {"", "random", "unset", "none", "unknown"}


def artifact_role(name: str) -> str:
    """Return the role of a retained artifact file name."""

    if name in REPORT_ARTIFACT_NAMES:
        return ROLE_REPORT
    if name == "source.xml":
        return ROLE_SOURCE
    if name.endswith(".bngl"):
        return ROLE_MODEL
    if name.endswith(".xml"):
        return ROLE_MODEL
    if name.endswith(".log"):
        return ROLE_LOG
    return ROLE_REFERENCE


def is_model_artifact(name: str) -> bool:
    """Return whether a retained artifact is part of the generated model."""

    return artifact_role(name) == ROLE_MODEL


def _runtime_identity(payload: Any) -> dict[str, Any]:
    """Return the identity of the build a run observed the corpus with.

    The report says which package tree and which native extension produced
    the artifacts.  A reader has to be able to see it, because a run that
    measured a stale installed package measures the wrong code.
    """

    if not isinstance(payload, dict):
        return {}
    provenance = payload.get("runtime_provenance")
    if not isinstance(provenance, dict):
        return {}
    return {
        "bionetgen_package_path": provenance.get("bionetgen_package_path"),
        "native_extension_resolved_path": provenance.get(
            "native_extension_resolved_path"
        ),
        "bionetgen_version": provenance.get("bionetgen_version"),
    }


def discover_cases(root: Path) -> dict[str, Path]:
    """Return the per-case artifact directories under an artifacts root.

    A directory is a case when it directly holds at least one source, model
    or report artifact.  The case key is the directory's path relative to the
    artifacts root, which is what makes the same tool work for the SBML Test
    Suite layout (``semantic/00879``) and for the curated BioModels layout
    (``BIOMD0000000174``) without either being special-cased.
    """

    cases: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_dir():
            continue
        names = [child.name for child in path.iterdir() if child.is_file()]
        if not any(
            artifact_role(name) in {ROLE_SOURCE, ROLE_MODEL, ROLE_REPORT}
            for name in names
        ):
            continue
        key = path.relative_to(root).as_posix()
        cases[key] = path
    return cases


def case_key_from_record(record: dict[str, Any]) -> str:
    """Return the case key a report record belongs to.

    The SBML Test Suite records carry a category and an id and live at
    ``<category>/<id>`` in the artifacts tree.  The curated corpus records
    carry only an id and live at ``<id>``.
    """

    category = record.get("category")
    case_id = record.get("id")
    if category and case_id:
        return f"{category}/{case_id}"
    return str(case_id)


def verdict_signature(record: dict[str, Any]) -> dict[str, Any]:
    """Return the gate's decision for a record.

    Only the gate's decision is a verdict.  Prose reasons, solver numbers and
    run-local provenance are not: they are compared separately, and a
    difference in them never turns into a verdict difference.
    """

    official = record.get("official_conformance")
    modes = record.get("modes")
    return {
        "status": record.get("status"),
        "core_passed": record.get("core_passed"),
        "roundtrip_passed": record.get("roundtrip_passed"),
        "official_status": (
            official.get("status") if isinstance(official, dict) else None
        ),
        "mode_statuses": (
            [
                [mode.get("mode"), mode.get("status")]
                for mode in modes
                if isinstance(mode, dict)
            ]
            if isinstance(modes, list)
            else None
        ),
    }


def _numeric_leaves(value: Any, prefix: str = "") -> dict[str, float]:
    """Return the numeric leaves of a JSON-compatible value, keyed by path."""

    leaves: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_numeric_leaves(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaves.update(_numeric_leaves(item, f"{prefix}[{index}]"))
    elif isinstance(value, bool):
        pass
    elif isinstance(value, (int, float)):
        leaves[prefix] = float(value)
    return leaves


def comparison_numbers(record: dict[str, Any]) -> dict[str, float]:
    """Return the comparison numbers of a record, keyed by path.

    These are the numbers the gate computed when it compared the simulated
    trajectories: the per-observable differences against libRoadRunner and
    the per-variable differences against the official reference.
    """

    numbers: dict[str, float] = {}
    simulation = record.get("simulation_comparison")
    if isinstance(simulation, dict):
        numbers.update(_numeric_leaves(simulation, "simulation_comparison"))
    official = record.get("official_conformance")
    if isinstance(official, dict):
        comparison = official.get("comparison")
        if isinstance(comparison, dict):
            numbers.update(
                _numeric_leaves(comparison, "official_conformance.comparison")
            )
    modes = record.get("modes")
    if isinstance(modes, list):
        for mode in modes:
            if not isinstance(mode, dict):
                continue
            name = mode.get("mode", "?")
            simulation = mode.get("simulation_comparison")
            if isinstance(simulation, dict):
                numbers.update(
                    _numeric_leaves(simulation, f"modes.{name}.simulation_comparison")
                )
    return numbers


def compare_text(first: str, second: str) -> dict[str, Any]:
    """Compare two texts line by line and report the first differing line."""

    first_lines = first.splitlines()
    second_lines = second.splitlines()
    differing = 0
    first_difference: dict[str, Any] | None = None
    for index in range(max(len(first_lines), len(second_lines))):
        left = first_lines[index] if index < len(first_lines) else None
        right = second_lines[index] if index < len(second_lines) else None
        if left == right:
            continue
        differing += 1
        if first_difference is None:
            first_difference = {"line": index + 1, "first": left, "second": right}
    result: dict[str, Any] = {
        "status": "identical" if differing == 0 else "differs",
        "differing_lines": differing,
        "first_line_count": len(first_lines),
        "second_line_count": len(second_lines),
    }
    if first_difference is not None:
        result["first_differing_line"] = first_difference
    return result


def compare_numeric(
    first: dict[str, float],
    second: dict[str, float],
    *,
    rtol: float,
    atol: float,
) -> dict[str, Any]:
    """Compare two sets of numbers with a tolerance and report the deltas."""

    changed: list[dict[str, Any]] = []
    for path in sorted(set(first) | set(second)):
        left = first.get(path)
        right = second.get(path)
        if left is None or right is None:
            changed.append(
                {
                    "path": path,
                    "first": left,
                    "second": right,
                    "kind": "added-or-removed",
                }
            )
            continue
        delta = abs(left - right)
        scale = max(abs(left), abs(right))
        if delta > atol + rtol * scale:
            changed.append(
                {
                    "path": path,
                    "first": left,
                    "second": right,
                    "absolute_delta": delta,
                    "relative_delta": (delta / scale) if scale else None,
                }
            )
    return {"status": "identical" if not changed else "differs", "changed": changed}


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def _load_record(payload: Any, case_key: str) -> dict[str, Any] | None:
    """Return the record for a case from a gate report or a per-case report.

    A report that holds several records must match the case exactly: falling
    back to an unrelated record would compare one case's verdict against
    another's, which is exactly the kind of false difference this tool must
    not produce.  A report that holds a single record -- the per-case worker
    report the gate retains next to the artifacts -- is unambiguous.
    """

    if not isinstance(payload, dict):
        return None
    records = payload.get("records")
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and case_key_from_record(record) == case_key:
                return record
        if len(records) == 1 and isinstance(records[0], dict):
            return records[0]
        return None
    if "status" in payload or "core_passed" in payload:
        return payload
    return None


def _seed_from_payload(payload: Any) -> str | None:
    """Return the hash seed a run recorded, if it recorded one."""

    if not isinstance(payload, dict):
        return None
    candidates = [payload, payload.get("runtime_provenance")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in (
            "python_hash_seed",
            "hash_seed",
            "pythonhashseed",
            "PYTHONHASHSEED",
        ):
            value = candidate.get(key)
            if value is not None:
                return str(value)
    return None


def _seed_condition(first_seed: str | None, second_seed: str | None) -> str:
    """Describe the seed condition of the comparison in one sentence."""

    first = (first_seed or "").strip().lower()
    second = (second_seed or "").strip().lower()
    first_pinned = first not in UNPINNED_SEEDS
    second_pinned = second not in UNPINNED_SEEDS
    if first_pinned and second_pinned:
        if first == second:
            return (
                f"both runs pinned the hash seed at {first}; the comparison is "
                "sound for bit-reproducible artifacts"
            )
        return (
            f"the runs pinned different hash seeds ({first} and {second}); "
            "artifact differences may be seed effects rather than changes"
        )
    if first_pinned != second_pinned:
        return (
            f"only one run recorded a pinned hash seed ({first or second}); "
            "artifact differences may be seed effects rather than changes"
        )
    return (
        "neither run recorded a pinned hash seed; the comparison assumes both "
        "runs produced their artifacts under the same pinned seed"
    )


def _substitute(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _probe_context(
    case_key: str,
    payload: dict[str, Any] | None,
    *,
    gate: Path,
    python: str,
    seed: int,
    artifacts_dir: Path,
    json_path: Path,
) -> dict[str, str]:
    """Return the substitution values for a probe command."""

    payload = payload if isinstance(payload, dict) else {}
    simulation = payload.get("simulation")
    if not isinstance(simulation, dict):
        simulation = {}
    lock = ""
    source_lock = payload.get("suite_source_lock")
    if isinstance(source_lock, dict):
        lock = str(source_lock.get("source_lock_path") or "")
    manifest = str(payload.get("manifest") or "")
    cache_dir = str(payload.get("cache_dir") or "")
    category, _, case_id = case_key.rpartition("/")
    if not category:
        category, case_id = "semantic", case_key
    return {
        "python": python,
        "gate": str(gate),
        "seed": str(seed),
        "case": case_key,
        "category": category,
        "id": case_id,
        "artifacts_dir": str(artifacts_dir),
        "json": str(json_path),
        "suite_dir": str(payload.get("suite_dir") or ""),
        "lock_arg": f"--lock {lock}" if lock else "",
        "manifest_arg": f"--manifest {manifest}" if manifest else "",
        "cache_dir_arg": f"--cache-dir {cache_dir}" if cache_dir else "",
        "mode": str(payload.get("mode") or "flat"),
        "t_end": str(simulation.get("t_end", 1.0)),
        "n_steps": str(simulation.get("n_steps", 10)),
        "rtol": str(simulation.get("rtol", 1e-7)),
        "atol": str(simulation.get("atol", 1e-12)),
    }


def probe_case(
    case_key: str,
    template: str,
    payload: dict[str, Any] | None,
    *,
    gate: Path,
    python: str,
    seed: int,
    contrast_seed: int,
    timeout: float,
) -> dict[str, Any]:
    """Regenerate a case's artifacts to find out how trustworthy they are.

    Three regenerations are made: two under the pinned seed and one under a
    contrasting seed.  The first two say whether the artifact is reproducible
    at all -- whether it is *not reproducible under a pinned seed*.  The third
    says whether the artifact is sensitive to the interpreter's hash seed,
    which is the documented reason a pair of runs can produce different text
    for the same model.
    """

    with tempfile.TemporaryDirectory(prefix="bng3-artifact-probe-") as temp:
        temp_root = Path(temp)
        regenerated: list[dict[str, Path]] = []
        notes: list[str] = []
        for index, run_seed in ((1, seed), (2, seed), (3, contrast_seed)):
            artifacts_dir = temp_root / f"probe{index}"
            json_path = temp_root / f"probe{index}.json"
            context = _probe_context(
                case_key,
                payload,
                gate=gate,
                python=python,
                seed=run_seed,
                artifacts_dir=artifacts_dir,
                json_path=json_path,
            )
            argv = shlex.split(_substitute(template, context))
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = str(run_seed)
            try:
                completed = subprocess.run(
                    argv,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {
                    "status": "failed",
                    "reason": f"probe could not be run: {type(exc).__name__}: {exc}",
                    "reproducible": {},
                    "seed_sensitive": {},
                }
            if completed.returncode != 0:
                # The gate's exit status reports its own verdict, which says
                # nothing about whether the probe produced artifacts.  The
                # artifacts themselves decide whether the probe worked.
                note = (
                    f"probe exited {completed.returncode}: "
                    f"{(completed.stderr or completed.stdout or '')[-200:]}"
                )
            else:
                note = ""
            if note:
                notes.append(note)
            cases = discover_cases(artifacts_dir)
            case_dir = cases.get(case_key)
            if case_dir is None:
                return {
                    "status": "failed",
                    "reason": (f"{note}; " if note else "")
                    + f"probe produced no artifacts for {case_key}",
                    "reproducible": {},
                    "seed_sensitive": {},
                }
            regenerated.append(
                {child.name: child for child in case_dir.iterdir() if child.is_file()}
            )
        first, second, contrast = regenerated
        reproducible: dict[str, bool] = {}
        seed_sensitive: dict[str, bool] = {}
        for name in sorted(set(first) & set(second) & set(contrast)):
            if artifact_role(name) == ROLE_REPORT:
                continue
            pinned = _read_text(first[name])
            pinned_again = _read_text(second[name])
            other_seed = _read_text(contrast[name])
            reproducible[name] = (
                compare_text(pinned, pinned_again)["status"] == "identical"
            )
            seed_sensitive[name] = (
                compare_text(pinned, other_seed)["status"] != "identical"
            )
    return {
        "status": "ok",
        "reason": "; ".join(notes),
        "seed": seed,
        "contrast_seed": contrast_seed,
        "reproducible": reproducible,
        "seed_sensitive": seed_sensitive,
    }


def compare_case(
    case_key: str,
    first_dir: Path,
    second_dir: Path,
    *,
    first_record: dict[str, Any] | None,
    second_record: dict[str, Any] | None,
    numeric_rtol: float,
    numeric_atol: float,
    probe_runner: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare one case's artifacts between two runs."""

    first_files = {
        child.name: child for child in first_dir.iterdir() if child.is_file()
    }
    second_files = {
        child.name: child for child in second_dir.iterdir() if child.is_file()
    }
    artifacts: dict[str, Any] = {}
    for name in sorted(set(first_files) | set(second_files)):
        role = artifact_role(name)
        if name not in first_files:
            artifacts[name] = {"role": role, "status": "missing-in-first"}
            continue
        if name not in second_files:
            artifacts[name] = {"role": role, "status": "missing-in-second"}
            continue
        if role == ROLE_REPORT:
            # The per-case report carries the verdict and the comparison
            # numbers; it is compared structurally, never as text, because its
            # text also carries run-local provenance.
            artifacts[name] = {"role": role, "status": "compared-as-report"}
            continue
        comparison = compare_text(
            _read_text(first_files[name]), _read_text(second_files[name])
        )
        comparison["role"] = role
        artifacts[name] = comparison

    model_differs = any(
        entry.get("role") == ROLE_MODEL and entry.get("status") == "differs"
        for entry in artifacts.values()
    )
    probe: dict[str, Any] | None = None
    if probe_runner is not None and model_differs:
        probe = probe_runner(case_key)
        if probe.get("status") == "ok":
            for name, entry in artifacts.items():
                if entry.get("role") != ROLE_MODEL:
                    continue
                if entry.get("status") != "differs":
                    continue
                reproducible = probe.get("reproducible", {})
                seed_sensitive = probe.get("seed_sensitive", {})
                if reproducible.get(name) is False:
                    entry["status"] = "not-reproducible"
                    entry["reason"] = (
                        "this artifact is not reproducible under a pinned seed"
                    )
                elif seed_sensitive.get(name) is True:
                    entry["status"] = "seed-sensitive"
                    entry["reason"] = (
                        "this artifact changes with the interpreter's hash seed; "
                        "the difference may be a seed effect rather than a "
                        "change under test"
                    )
                elif name not in reproducible:
                    entry["reproducibility"] = (
                        "the probe did not establish whether this artifact is "
                        "reproducible under a pinned seed"
                    )

    verdict_changes: list[str] = []
    first_signature = verdict_signature(first_record) if first_record else None
    second_signature = verdict_signature(second_record) if second_record else None
    verdict_known = first_signature is not None and second_signature is not None
    verdict_changed = False
    if verdict_known:
        for field in sorted(first_signature or {}):
            left = (first_signature or {}).get(field)
            right = (second_signature or {}).get(field)
            if left != right:
                verdict_changes.append(f"{field}: {left!r} != {right!r}")
                verdict_changed = True

    numeric_changes: list[dict[str, Any]] = []
    if first_record is not None and second_record is not None:
        numeric = compare_numeric(
            comparison_numbers(first_record),
            comparison_numbers(second_record),
            rtol=numeric_rtol,
            atol=numeric_atol,
        )
        numeric_changes = numeric["changed"]

    model_changed = False
    model_unresolved = False
    for entry in artifacts.values():
        if entry.get("role") != ROLE_MODEL:
            continue
        status = entry.get("status")
        if status == "differs":
            model_changed = True
        elif status in {"not-reproducible", "seed-sensitive"}:
            model_unresolved = True
        elif status in {"missing-in-first", "missing-in-second"}:
            model_changed = True

    if model_unresolved:
        outcome = OUTCOME_UNRESOLVED
    elif model_changed:
        outcome = (
            OUTCOME_CHANGED_UNCHANGED
            if not verdict_changed
            else OUTCOME_CHANGED_CHANGED
        )
    else:
        outcome = OUTCOME_UNCHANGED

    return {
        "case": case_key,
        "outcome": outcome,
        "model_changed": model_changed,
        "model_unresolved": model_unresolved,
        "verdict_changed": verdict_changed,
        "verdict_known": verdict_known,
        "verdict_changes": verdict_changes,
        "artifacts": artifacts,
        "numeric_changes": numeric_changes,
        "probe": probe,
    }


def _select_case(case_key: str, pattern: str) -> bool:
    if pattern == case_key:
        return True
    return case_key.rpartition("/")[2] == pattern


def _print_case(case: dict[str, Any], *, max_numeric: int) -> None:
    print(f"  {case['case']}: {case['outcome']}")
    for change in case["verdict_changes"]:
        print(f"    verdict {change}")
    for name, entry in sorted(case["artifacts"].items()):
        status = entry.get("status")
        if status in {"identical", "compared-as-report"}:
            continue
        if status == "differs":
            difference = entry.get("first_differing_line")
            if difference:
                print(
                    f"    {name}: differs at line {difference['line']} "
                    f"({entry.get('differing_lines')} line(s) differ)"
                )
                print(f"      - {difference['first']}")
                print(f"      + {difference['second']}")
            else:
                print(f"    {name}: differs")
        elif status in {"not-reproducible", "seed-sensitive"}:
            print(f"    {name}: {entry.get('reason', status)}")
        else:
            print(f"    {name}: {status}")
        if entry.get("reproducibility"):
            print(f"      note: {entry['reproducibility']}")
    numeric = case["numeric_changes"]
    if numeric:
        print(f"    comparison numbers changed ({len(numeric)}):")
        for change in numeric[:max_numeric]:
            print(
                f"      {change['path']}: {change.get('first')!r} -> "
                f"{change.get('second')!r} (delta "
                f"{change.get('absolute_delta')!r})"
            )
        if len(numeric) > max_numeric:
            print(f"      ... {len(numeric) - max_numeric} more")
    probe = case.get("probe")
    if probe:
        if probe.get("status") == "ok":
            reproducible = sorted(
                name for name, ok in probe.get("reproducible", {}).items() if ok is True
            )
            print(
                "    probe: regenerated under seed "
                f"{probe.get('seed')} and seed {probe.get('contrast_seed')}; "
                f"reproducible: {', '.join(reproducible) or 'none'}"
            )
            sensitive = sorted(
                name
                for name, is_sensitive in probe.get("seed_sensitive", {}).items()
                if is_sensitive is True
            )
            if sensitive:
                print(f"    probe: changes with the hash seed: {', '.join(sensitive)}")
        else:
            print(f"    probe: {probe.get('reason', 'could not be run')}")


def _case_record(case_dir: Path, case_key: str, payload: Any) -> dict[str, Any] | None:
    """Return the record for a case, preferring the run's own report."""

    if isinstance(payload, dict):
        record = _load_record(payload, case_key)
        if record is not None:
            return record
    for name in REPORT_ARTIFACT_NAMES:
        path = case_dir / name
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record = _load_record(document, case_key)
        if record is not None:
            return record
    return None


def _missing_case(case_key: str, missing_in: str) -> dict[str, Any]:
    return {
        "case": case_key,
        "outcome": OUTCOME_UNRESOLVED,
        "model_changed": False,
        "model_unresolved": True,
        "verdict_changed": False,
        "verdict_known": False,
        "verdict_changes": [],
        "artifacts": {
            "case": {"role": ROLE_MODEL, "status": f"missing-in-{missing_in}"}
        },
        "numeric_changes": [],
        "probe": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--first-artifacts", type=Path, required=True, help="first run's artifacts"
    )
    parser.add_argument(
        "--second-artifacts", type=Path, required=True, help="second run's artifacts"
    )
    parser.add_argument(
        "--first-report", type=Path, help="first run's gate report (JSON)"
    )
    parser.add_argument(
        "--second-report", type=Path, help="second run's gate report (JSON)"
    )
    parser.add_argument(
        "--case",
        help="compare one case only, as CATEGORY/ID or as a bare id",
    )
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    parser.add_argument(
        "--numeric-rtol",
        type=float,
        default=1e-6,
        help="relative tolerance for the comparison numbers",
    )
    parser.add_argument(
        "--numeric-atol",
        type=float,
        default=0.0,
        help="absolute tolerance for the comparison numbers",
    )
    parser.add_argument(
        "--max-numeric",
        type=int,
        default=5,
        help="how many comparison-number differences to print per case",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=40,
        help="how many differing cases to print in detail",
    )
    parser.add_argument(
        "--first-seed",
        help="the hash seed the first run used, when the run did not record one",
    )
    parser.add_argument(
        "--second-seed",
        help="the hash seed the second run used, when the run did not record one",
    )
    parser.add_argument(
        "--probe-reproducibility",
        action="store_true",
        help=(
            "regenerate the interesting cases twice under one pinned seed and "
            "report an artifact that is not reproducible as such"
        ),
    )
    parser.add_argument(
        "--probe-command",
        help=(
            "the command that regenerates one case's artifacts; "
            "'{...}' placeholders are substituted per case"
        ),
    )
    parser.add_argument(
        "--probe-gate",
        type=Path,
        help="the gate script the probe command runs",
    )
    parser.add_argument(
        "--probe-seed",
        type=int,
        default=0,
        help="the pinned hash seed the probe uses",
    )
    parser.add_argument(
        "--probe-contrast-seed",
        type=int,
        default=1,
        help=(
            "the contrasting hash seed the probe uses to find out whether an "
            "artifact changes with the seed"
        ),
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=300.0,
        help="seconds allowed for one probe regeneration",
    )
    args = parser.parse_args()

    for root in (args.first_artifacts, args.second_artifacts):
        if not root.is_dir():
            print(f"error: artifacts directory does not exist: {root}", file=sys.stderr)
            return 2

    first_payload: Any = None
    second_payload: Any = None
    if args.first_report is not None:
        first_payload = json.loads(args.first_report.read_text(encoding="utf-8"))
    if args.second_report is not None:
        second_payload = json.loads(args.second_report.read_text(encoding="utf-8"))

    first_seed = args.first_seed or _seed_from_payload(first_payload)
    second_seed = args.second_seed or _seed_from_payload(second_payload)
    seed_condition = _seed_condition(first_seed, second_seed)
    first_identity = _runtime_identity(first_payload)
    second_identity = _runtime_identity(second_payload)

    first_cases = discover_cases(args.first_artifacts)
    second_cases = discover_cases(args.second_artifacts)
    if args.case:
        first_cases = {
            key: path
            for key, path in first_cases.items()
            if _select_case(key, args.case)
        }
        second_cases = {
            key: path
            for key, path in second_cases.items()
            if _select_case(key, args.case)
        }
        if not first_cases and not second_cases:
            print(f"error: no case matches {args.case}", file=sys.stderr)
            return 2

    probe_template = args.probe_command
    probe_gate = args.probe_gate
    if args.probe_reproducibility and probe_template is None:
        payload = second_payload if isinstance(second_payload, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        if not payload and isinstance(first_payload, dict):
            payload = first_payload
        if "suite_dir" in payload:
            probe_template = SUITE_PROBE_COMMAND
            probe_gate = probe_gate or Path(__file__).with_name(
                "validate_sbml_test_suite.py"
            )
        elif "cache_dir" in payload:
            probe_template = CORPUS_PROBE_COMMAND
            probe_gate = probe_gate or Path(__file__).with_name(
                "validate_published_biomodels.py"
            )
        else:
            print(
                "error: --probe-reproducibility needs --probe-command when the "
                "run's layout cannot be recognised",
                file=sys.stderr,
            )
            return 2
    if probe_template is not None and probe_gate is None:
        print("error: --probe-gate is required with --probe-command", file=sys.stderr)
        return 2

    probe_runner: Callable[[str], dict[str, Any]] | None = None
    if probe_template is not None:

        def probe_runner(case_key: str) -> dict[str, Any]:  # noqa: F811
            payload = second_payload if isinstance(second_payload, dict) else {}
            if not payload and isinstance(first_payload, dict):
                payload = first_payload
            return probe_case(
                case_key,
                probe_template,
                payload,
                gate=probe_gate,
                python=sys.executable,
                seed=args.probe_seed,
                contrast_seed=args.probe_contrast_seed,
                timeout=args.probe_timeout,
            )

    cases: list[dict[str, Any]] = []
    for key in sorted(set(first_cases) | set(second_cases)):
        first_dir = first_cases.get(key)
        second_dir = second_cases.get(key)
        if first_dir is None:
            cases.append(_missing_case(key, "first"))
            continue
        if second_dir is None:
            cases.append(_missing_case(key, "second"))
            continue
        cases.append(
            compare_case(
                key,
                first_dir,
                second_dir,
                first_record=_case_record(first_dir, key, first_payload),
                second_record=_case_record(second_dir, key, second_payload),
                numeric_rtol=args.numeric_rtol,
                numeric_atol=args.numeric_atol,
                probe_runner=probe_runner,
            )
        )

    counts = {
        OUTCOME_CHANGED_CHANGED: 0,
        OUTCOME_CHANGED_UNCHANGED: 0,
        OUTCOME_UNCHANGED: 0,
        OUTCOME_UNRESOLVED: 0,
    }
    for case in cases:
        counts[case["outcome"]] = counts.get(case["outcome"], 0) + 1

    report = {
        "tool": "diff_gate_artifacts",
        "first": {
            "artifacts": str(args.first_artifacts),
            "report": str(args.first_report) if args.first_report else None,
            "seed": first_seed,
            "runtime_identity": first_identity,
        },
        "second": {
            "artifacts": str(args.second_artifacts),
            "report": str(args.second_report) if args.second_report else None,
            "seed": second_seed,
            "runtime_identity": second_identity,
        },
        "seed_condition": seed_condition,
        "numeric_tolerance": {"rtol": args.numeric_rtol, "atol": args.numeric_atol},
        "counts": counts,
        "cases": cases,
    }
    if args.json is not None:
        args.json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    print("gate artifact diff")
    print(f"  first : {args.first_artifacts} (seed: {first_seed or 'not recorded'})")
    print(f"  second: {args.second_artifacts} (seed: {second_seed or 'not recorded'})")
    print(f"  seed condition: {seed_condition}")
    for label, identity in (("first", first_identity), ("second", second_identity)):
        package_path = identity.get("bionetgen_package_path")
        if package_path:
            print(f"  {label} package: {package_path}")
    if first_identity and second_identity and first_identity != second_identity:
        print(
            "  note: the two runs observed the corpus under different runtime "
            "identities (not a verdict)"
        )
    missing = [
        case["case"]
        for case in cases
        if case["outcome"] == OUTCOME_UNRESOLVED
        and any(
            entry.get("status", "").startswith("missing-in-")
            for entry in case["artifacts"].values()
        )
    ]
    if missing:
        print(f"  cases present in only one run: {len(missing)}")
    print(f"  cases: {len(cases)}")
    print("outcomes:")
    print(f"  {OUTCOME_CHANGED_CHANGED}: {counts[OUTCOME_CHANGED_CHANGED]}")
    print(f"  {OUTCOME_CHANGED_UNCHANGED}: {counts[OUTCOME_CHANGED_UNCHANGED]}")
    print(f"  {OUTCOME_UNCHANGED}: {counts[OUTCOME_UNCHANGED]}")
    if counts[OUTCOME_UNRESOLVED]:
        print(f"  {OUTCOME_UNRESOLVED}: {counts[OUTCOME_UNRESOLVED]}")

    interesting = [
        case
        for case in cases
        if case["outcome"] != OUTCOME_UNCHANGED or case["verdict_changed"]
    ]
    if not interesting:
        print(
            f"no model artifact changed and no verdict changed across "
            f"{len(cases)} cases"
        )
        return 0
    for case in interesting[: args.max_cases]:
        _print_case(case, max_numeric=args.max_numeric)
    if len(interesting) > args.max_cases:
        print(f"  ... {len(interesting) - args.max_cases} more cases differ")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
