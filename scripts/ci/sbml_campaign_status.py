#!/usr/bin/env python3
"""Report the state of the SBML Atomizer coverage campaign in one place.

The campaign's state is assembled by hand from four different tools, by one
person.  A reader cannot answer "what does the Atomizer support now, and what
changed since yesterday?" without re-deriving it from two large reports.
This tool answers that question from the reports themselves.

It reads:

* the official SBML Test Suite gate report (``validate_sbml_test_suite.py``);
* optionally the previous gate report, for the per-case diff;
* optionally the curated BioModels corpus gate report;
* optionally the pinned official suite checkout, for the failure clusters;
* optionally the committed expectation manifest, for the ratchet.

and it reports:

* the per-stage counts of the SBML suite and of the curated corpus, with the
  report's SHA-256, the commit the run executed and the native extension's
  digest;
* the remaining official-reference failures, grouped by the campaign's
  official-feature clusters;
* the unsupported cases, split by the *side* of the boundary the gap sits on:
  a **harness-side** gap is a measurement limitation, an **Atomizer-side** gap
  is a representational one.  The two are different kinds of work and are
  never counted together;
* the per-case diff against the previous report, classified as a regression,
  an improvement or a change, with the regressions listed first;
* whether the committed expectation manifest still describes reality.

The tool is a reporter.  It never changes a verdict, a tolerance, a reference
file, or the harness's own behaviour, and it never writes to the reports it
reads.

Honesty is the point of the tool.  When it cannot establish something, it says
so instead of reporting a clean result: a report whose provenance cannot be
tied to the checkout it is read against is reported as such, loudly, and the
exit status is non-zero.  A wrong result must never look like a right one.

Exit status (a bit mask, so that every condition is separately visible):

===== ==================================================================
  0   clean
  1   a regression is present (a stage that was ``passed`` and no longer is)
  2   the expectation manifest is stale against this report
  4   the report's provenance does not match the checkout it is read against
  8   the report does not account for every case it ran
===== ==================================================================

Usage::

    python scripts/ci/sbml_campaign_status.py \
        --suite-report /path/to/report.json \
        --previous-suite-report /path/to/previous.json \
        --biomodels-report /path/to/biomodels.json \
        --expectations provenance/sbml-campaign/expectations.json \
        --suite-dir /path/to/sbml-test-suite \
        --checkout-root .

    # machine-readable
    python scripts/ci/sbml_campaign_status.py \
        --suite-report /path/to/report.json --json /path/to/status.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import sbml_campaign_inventory as inventory
from scripts.ci import sbml_campaign_tables as tables
from scripts.ci import validate_sbml_test_suite as runner

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The exit status is a bit mask, so that a reader can tell which of the
#: conditions fired without parsing the text.
EXIT_REGRESSION = 1
EXIT_MANIFEST_STALE = 2
EXIT_PROVENANCE = 4
EXIT_COVERAGE = 8

#: The provenance verdicts, from best to worst.
PROVENANCE_MATCH = "match"
PROVENANCE_MISMATCH = "mismatch"
PROVENANCE_UNVERIFIABLE = "unverifiable"

#: The directory names that mark an installed copy of the package rather than
#: a source tree.
INSTALLED_PACKAGE_DIRECTORIES = ("site-packages", "dist-packages")

#: The readable name of each official-feature cluster.  The cluster itself is
#: decided by the campaign's own table (``sbml_campaign_tables``), which reads
#: the official suite's own case notes; this mapping only names it.
CLUSTER_LABELS: dict[str, str] = {
    "CSymbolDelay": "delay",
    "CSymbolRateOf": "rate of",
    "CSymbolAvogadro": "avogadro",
    "AlgebraicRule": "algebraic rule",
    "InitialAssignment": "initial assignment",
    "AssignmentRule": "assignment rule",
    "RateRule": "rate rule",
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _digest(path: Path) -> str:
    """Return the SHA-256 of a file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    """Read a JSON document."""

    return json.loads(path.read_text(encoding="utf-8"))


def _git_output(directory: Path, arguments: list[str]) -> str | None:
    """Return the output of a git command, or None when it did not succeed."""

    completed = _git_run(directory, arguments)
    if completed is None:
        return None
    value = completed.stdout.strip()
    return value or None


def _git_succeeds(directory: Path, arguments: list[str]) -> bool:
    """Return True when a git command succeeds, whatever it prints."""

    return _git_run(directory, arguments) is not None


def _is_ancestor(checkout_root: Path, ancestor: str, descendant: str) -> bool | None:
    """Return whether ``ancestor`` precedes ``descendant`` in the history.

    ``None`` means the relation could not be established: either commit is
    unknown to the checkout, or the two are on unrelated lines.
    """

    if not ancestor or not descendant:
        return None
    if _git_succeeds(
        checkout_root, ["merge-base", "--is-ancestor", ancestor, descendant]
    ):
        return True
    if _git_succeeds(
        checkout_root, ["merge-base", "--is-ancestor", descendant, ancestor]
    ):
        return False
    return None


def _git_run(
    directory: Path, arguments: list[str]
) -> subprocess.CompletedProcess[str] | None:
    """Run a git command, returning None when it could not be run."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed


def _repository_identity(path: Path) -> dict[str, str | None] | None:
    """Return the identity of the git repository that contains ``path``."""

    root = _git_output(path, ["rev-parse", "--show-toplevel"])
    if root is None:
        return None
    common = _git_output(Path(root), ["rev-parse", "--git-common-dir"])
    if common is not None and not Path(common).is_absolute():
        common = str((Path(root) / common).resolve())
    return {
        "root": root,
        "origin": _git_output(Path(root), ["remote", "get-url", "origin"]),
        "common_dir": common,
    }


def _same_repository(left: dict[str, str | None], right: dict[str, str | None]) -> bool:
    """Return True when two identities name the same repository.

    Two worktrees of one repository share a git *common* directory; two clones
    of one repository share an origin URL.  Either is enough.
    """

    if left.get("common_dir") and left.get("common_dir") == right.get("common_dir"):
        return True
    if left.get("origin") and left.get("origin") == right.get("origin"):
        return True
    return False


def repository_head(checkout_root: Path) -> str:
    """Return the commit a checkout is at, or an empty string."""

    return _git_output(checkout_root, ["rev-parse", "HEAD"]) or ""


def _worktree_root(package_path: Path) -> Path | None:
    """Return the checkout that contains an imported package, if any."""

    for candidate in [package_path.parent, *package_path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Render a markdown table."""

    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _case_list(identities: list[str], limit: int) -> str:
    """Render case identities for a table cell."""

    if len(identities) <= limit:
        return " ".join(identities)
    shown = " ".join(identities[:limit])
    return f"{shown} … (+{len(identities) - limit} more)"


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def check_provenance(report: dict[str, Any], checkout_root: Path) -> dict[str, Any]:
    """Decide whether the report can be shown to be about this checkout.

    The verdict is one of:

    ``match``
        the report measured this repository's source tree;
    ``mismatch``
        the report measured something else -- an installed copy of the
        package, a different repository, or a commit this repository does not
        know;
    ``unverifiable``
        the check could not be made, because the report records no
        provenance, or the measured tree or native build is gone.

    A report that cannot be tied to the checkout is not a report about the
    checkout, and the tool must not present its counts as if they were.
    """

    runtime = report.get("runtime_provenance") or {}
    source = report.get("source_provenance") or {}
    package_path = str(runtime.get("bionetgen_package_path") or "")
    native_path = str(
        runtime.get("native_extension_resolved_path")
        or runtime.get("native_extension_path")
        or ""
    )
    native_sha256 = str(runtime.get("native_extension_sha256") or "")
    commit = str(source.get("bng3_commit") or "")

    problems: list[str] = []
    notes: list[str] = []
    status = PROVENANCE_MATCH

    def fail(new_status: str, message: str) -> None:
        nonlocal status
        if status == PROVENANCE_MATCH or new_status == PROVENANCE_MISMATCH:
            status = new_status
        problems.append(message)

    if not package_path:
        fail(
            PROVENANCE_UNVERIFIABLE,
            "the report records no bionetgen package path, so the numbers "
            "cannot be tied to a source tree",
        )
    else:
        parts = Path(package_path).parts
        installed = [name for name in parts if name in INSTALLED_PACKAGE_DIRECTORIES]
        if installed:
            fail(
                PROVENANCE_MISMATCH,
                f"the report measured an installed copy of bionetgen "
                f"({package_path}), not a source tree",
            )
        elif not Path(package_path).exists():
            fail(
                PROVENANCE_UNVERIFIABLE,
                f"the measured package tree ({package_path}) no longer exists, "
                "so the report cannot be tied to this checkout",
            )
        else:
            worktree = _worktree_root(Path(package_path))
            if worktree is None:
                fail(
                    PROVENANCE_UNVERIFIABLE,
                    f"the measured package ({package_path}) is not inside a git "
                    "checkout, so the report cannot be traced to this "
                    "repository",
                )
            else:
                measured = _repository_identity(worktree)
                checkout = _repository_identity(checkout_root)
                if measured is None:
                    fail(
                        PROVENANCE_UNVERIFIABLE,
                        f"the measured package tree ({worktree}) is not a git "
                        "repository",
                    )
                elif checkout is None:
                    fail(
                        PROVENANCE_UNVERIFIABLE,
                        f"the checkout ({checkout_root}) is not a git "
                        "repository, so the report cannot be compared with it",
                    )
                elif not _same_repository(measured, checkout):
                    fail(
                        PROVENANCE_MISMATCH,
                        "the report measured a different repository "
                        f"({measured.get('origin') or measured.get('root')}), "
                        f"not this one ({checkout.get('origin') or checkout.get('root')})",
                    )
                elif commit and not _git_succeeds(
                    worktree, ["cat-file", "-e", f"{commit}^{{commit}}"]
                ):
                    fail(
                        PROVENANCE_MISMATCH,
                        f"the commit the report executed ({commit}) is unknown "
                        "to that repository",
                    )

    checkout_head = _git_output(checkout_root, ["rev-parse", "HEAD"])
    if commit and checkout_head and commit != checkout_head:
        notes.append(
            f"the report executed commit {commit}; this checkout is at "
            f"{checkout_head}. The counts below describe the measured commit, "
            "not this working tree."
        )
    if native_path:
        native = Path(native_path)
        if not native.exists():
            notes.append(
                f"the native extension the report measured ({native_path}) is "
                "no longer on disk, so its digest could not be re-checked"
            )
        elif native_sha256:
            actual = _digest(native)
            if actual != native_sha256:
                notes.append(
                    f"the native extension on disk ({native_path}) has digest "
                    f"{actual}, not the {native_sha256} the report measured"
                )
    elif not native_sha256:
        notes.append("the report records no native extension digest")

    return {
        "status": status,
        "problems": problems,
        "notes": notes,
        "package_path": package_path,
        "native_path": native_path,
        "native_sha256": native_sha256,
        "commit": commit,
        "checkout_head": checkout_head or "",
        "suite_revision": str(report.get("suite_commit") or ""),
        "runtime": runtime,
        "source": source,
    }


# --------------------------------------------------------------------------
# The campaign's own numbers
# --------------------------------------------------------------------------


def stage_counts(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Return the per-stage counts in the expectation manifest's vocabulary."""

    counters: dict[str, Counter] = {
        stage: Counter() for stage in inventory.EXPECTATION_STAGES
    }
    for statuses in inventory.expectation_cases(report).values():
        for stage, status in statuses.items():
            counters[stage][status] += 1
    return {stage: dict(sorted(counters[stage].items())) for stage in counters}


def coverage_problems(report: dict[str, Any]) -> list[str]:
    """Return the ways in which the report fails to account for every case.

    A case that is dropped from the report is a case whose verdict is
    unknown, and a report that silently drops one must not be presented as a
    complete measurement.
    """

    problems: list[str] = []
    records = report.get("records")
    if not isinstance(records, list):
        return ["the report has no records list"]
    total = len(records)

    selected = report.get("selected_cases")
    if isinstance(selected, int) and selected != total:
        problems.append(
            f"the report selected {selected} cases but carries {total} records"
        )

    known_statuses = set(runner.RECORD_STATUSES) | set(inventory.CONVERSION_STATUS_MAP)
    for record in records:
        status = str(record.get("status", ""))
        if status not in known_statuses:
            problems.append(
                f"case {record.get('category')}/{record.get('id')} has the "
                f"status {status!r}, which is not in the outcome vocabulary "
                f"({sorted(known_statuses)}); a new bucket has to be added to "
                "the vocabulary deliberately"
            )

    published_counts = report.get("counts")
    if isinstance(published_counts, dict):
        if sum(published_counts.values()) != total:
            problems.append(
                f"the report's counts sum to {sum(published_counts.values())}, "
                f"not to the {total} cases that ran"
            )
        recomputed = runner_record_counts(records)
        for bucket, count in published_counts.items():
            if count != recomputed.get(bucket, 0):
                problems.append(
                    f"the report's count for {bucket!r} is {count}, but the "
                    f"records say {recomputed.get(bucket, 0)}"
                )

    published_stages = report.get("stage_counts")
    if isinstance(published_stages, dict):
        for stage, counts in published_stages.items():
            if not isinstance(counts, dict):
                continue
            if sum(counts.values()) != total:
                problems.append(
                    f"the {stage} stage counts sum to {sum(counts.values())}, "
                    f"not to the {total} cases that ran"
                )

    for stage, counts in stage_counts(report).items():
        if sum(counts.values()) != total:
            problems.append(
                f"the {stage} stage counts sum to {sum(counts.values())}, not to "
                f"the {total} cases that ran"
            )
    return problems


def runner_record_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Return the harness's own counts of a report's records.

    The harness owns the outcome vocabulary; this is its counting function,
    so the status command cannot drift from the gate's own bookkeeping.
    """

    return {
        bucket: sum(record.get("status") == bucket for record in records)
        for bucket in runner.RECORD_STATUSES
    }


def official_reference_failures(
    report: dict[str, Any], suite_dir: Path | None
) -> dict[str, Any]:
    """Return the remaining official-reference failures, by cluster.

    The cluster of a failure is decided by the official suite's own case
    notes, exactly as the campaign's tables decide it.  Without a pinned
    suite checkout the grouping cannot be established, and the tool says so
    rather than inventing one.
    """

    failures = [
        record
        for record in report.get("records") or []
        if str((record.get("official_conformance") or {}).get("status")) == "failed"
    ]
    clusters: dict[str, list[str]] = {}
    unclustered: list[str] = []
    problems: list[str] = []
    identities = [f"{record.get('category')}/{record.get('id')}" for record in failures]

    for record in failures:
        identity = f"{record.get('category')}/{record.get('id')}"
        if suite_dir is None:
            unclustered.append(identity)
            continue
        try:
            tags = tables.component_tags(
                suite_dir, str(record.get("category")), str(record.get("id"))
            )
        except (OSError, ValueError) as error:
            problems.append(
                f"the official feature tags of {identity} could not be read "
                f"from the suite checkout: {error}"
            )
            unclustered.append(identity)
            continue
        cluster = tables.FAILURE_CLUSTER_OTHER
        for tag, label in tables.FAILURE_CLUSTER_TAGS:
            if tag in tags:
                cluster = label
                break
        clusters.setdefault(cluster, []).append(identity)

    ordered = sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0]))
    return {
        "total": len(failures),
        "cases": sorted(identities),
        "clusters": [
            {
                "cluster": cluster,
                "label": CLUSTER_LABELS.get(cluster, cluster),
                "count": len(identities),
                "cases": sorted(identities),
            }
            for cluster, identities in ordered
        ],
        "unclustered": sorted(unclustered),
        "problems": problems,
        "grouped": suite_dir is not None,
    }


def unsupported_by_side(report: dict[str, Any]) -> dict[str, Any]:
    """Return the unsupported cases, split by the side of the gap.

    A *harness-side* gap is a measurement limitation: the gate could not
    evaluate the case, so the case is not a claim about the Atomizer.  An
    *Atomizer-side* gap is a representational one.  A case that defines no
    official reference is neither.
    """

    gaps = inventory.expectation_gaps(report)
    sides: dict[str, dict[str, list[str]]] = {side: {} for side in inventory.GAP_SIDES}
    for identity in sorted(gaps):
        for stage, gap in sorted(gaps[identity].items()):
            side = str(gap.get("side"))
            construct = str(gap.get("construct"))
            bucket = sides.setdefault(side, {})
            bucket.setdefault(construct, []).append(f"{identity} [{stage}]")
    return {
        side: {
            "total": sum(len(cases) for cases in constructs.values()),
            "constructs": [
                {
                    "construct": construct,
                    "count": len(cases),
                    "cases": sorted(cases),
                }
                for construct, cases in sorted(
                    constructs.items(), key=lambda item: (-len(item[1]), item[0])
                )
            ],
        }
        for side, constructs in sorted(sides.items())
    }


def diff_reports(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Return the per-case differences between two reports.

    A stage that was ``passed`` and no longer is a regression; a stage that
    becomes ``passed`` is an improvement; anything else is a change.  The
    classification is the campaign's own, so the tool and the manifest agree
    about what a regression is.
    """

    before = inventory.expectation_cases(previous)
    after = inventory.expectation_cases(current)
    partial = bool(current.get("partial_run"))

    differences: list[dict[str, Any]] = []
    added: list[str] = []
    removed: list[str] = []

    for identity in sorted(set(before) | set(after)):
        if identity not in before:
            added.append(identity)
            continue
        if identity not in after:
            if not partial:
                removed.append(identity)
            continue
        for stage in inventory.EXPECTATION_STAGES:
            was = str(before[identity][stage])
            now = str(after[identity][stage])
            if was == now:
                continue
            differences.append(
                {
                    "case": identity,
                    "stage": stage,
                    "before": was,
                    "after": now,
                    "classification": inventory.classify_difference(was, now),
                }
            )

    return {
        "regressions": [
            difference
            for difference in differences
            if difference["classification"] == "regression"
        ],
        "improvements": [
            difference
            for difference in differences
            if difference["classification"] == "improvement"
        ],
        "changes": [
            difference
            for difference in differences
            if difference["classification"] == "change"
        ],
        "added": sorted(added),
        "removed": sorted(removed),
        "cases_before": len(before),
        "cases_after": len(after),
    }


def manifest_currency(
    manifest: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Return whether the committed manifest still describes this report."""

    comparison = inventory.compare_expectations(manifest, report)
    differences = comparison["differences"]
    return {
        "current": not differences and not comparison["suite_revision_mismatch"],
        "suite_revision_expected": comparison["suite_revision_expected"],
        "suite_revision_observed": comparison["suite_revision_observed"],
        "suite_revision_mismatch": comparison["suite_revision_mismatch"],
        "cases_compared": comparison["cases_compared"],
        "cases_expected": comparison["cases_expected"],
        "cases_not_executed": comparison["cases_not_executed"],
        "differences": differences,
        "regressions": [
            difference
            for difference in differences
            if difference["classification"] == "regression"
        ],
        "improvements": [
            difference
            for difference in differences
            if difference["classification"] == "improvement"
        ],
        "changes": [
            difference
            for difference in differences
            if difference["classification"] == "change"
        ],
    }


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def build_status(
    *,
    suite_report_path: Path,
    suite_report: dict[str, Any],
    previous_path: Path | None = None,
    previous_report: dict[str, Any] | None = None,
    biomodels_path: Path | None = None,
    biomodels_report: dict[str, Any] | None = None,
    corpus_inventory_path: Path | None = None,
    corpus_inventory: dict[str, Any] | None = None,
    expectations_path: Path | None = None,
    expectations: dict[str, Any] | None = None,
    suite_dir: Path | None = None,
    checkout_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Assemble the whole status from the reports the campaign produced."""

    provenance = check_provenance(suite_report, checkout_root)
    coverage = coverage_problems(suite_report)
    failures = official_reference_failures(suite_report, suite_dir)
    unsupported = unsupported_by_side(suite_report)

    diff: dict[str, Any] | None = None
    if previous_report is not None:
        diff = diff_reports(previous_report, suite_report)

    manifest: dict[str, Any] | None = None
    if expectations is not None:
        manifest = manifest_currency(expectations, suite_report)
        manifest_commit = str(
            (expectations.get("source_report") or {}).get("bng3_commit") or ""
        )
        relation = _is_ancestor(checkout_root, manifest_commit, provenance["commit"])
        if relation is True:
            manifest["direction"] = (
                "the manifest describes an older measurement than this report, "
                "so the differences are what changed since the manifest was "
                "written"
            )
        elif relation is False:
            manifest["direction"] = (
                "this report predates the manifest's own measurement, so the "
                "differences are the manifest's newer results rather than a "
                "regression of this report"
            )
        else:
            manifest["direction"] = (
                "the relationship between the manifest's measurement and this "
                "report could not be established"
            )

    corpus: dict[str, Any] | None = None
    if biomodels_report is not None:
        corpus_inventory_summary = inventory.biomodels_inventory(biomodels_report)
        corpus = {
            "path": str(biomodels_path) if biomodels_path else "",
            "sha256": _digest(biomodels_path) if biomodels_path else "",
            "mode": str(biomodels_report.get("mode") or "unknown"),
            "status_counts": corpus_inventory_summary["status_counts"],
            "cause_counts": corpus_inventory_summary["cause_counts"],
            "summary": biomodels_report.get("summary") or {},
            "runtime_provenance": biomodels_report.get("runtime_provenance") or {},
            "measurement": (
                (corpus_inventory or {}).get("measurement") or {}
                if corpus_inventory
                else {}
            ),
        }

    exit_status = 0
    reasons: list[str] = []
    if provenance["status"] != PROVENANCE_MATCH:
        exit_status |= EXIT_PROVENANCE
        reasons.append(
            "the report's provenance does not match the checkout it is read "
            f"against ({provenance['status']})"
        )
    if coverage:
        exit_status |= EXIT_COVERAGE
        reasons.append("the report does not account for every case it ran")
    if diff is not None and diff["regressions"]:
        exit_status |= EXIT_REGRESSION
        reasons.append(
            f"{len(diff['regressions'])} regression(s) against the previous report"
        )
    if manifest is not None and not manifest["current"]:
        exit_status |= EXIT_MANIFEST_STALE
        reasons.append("the expectation manifest is stale against this report")

    return {
        "schema_version": 1,
        "kind": "sbml-campaign-status",
        "generator": "scripts/ci/sbml_campaign_status.py",
        "exit_status": exit_status,
        "exit_reasons": reasons,
        "checkout_root": str(checkout_root),
        "suite": {
            "path": str(suite_report_path),
            "sha256": _digest(suite_report_path),
            "commit": provenance["commit"],
            "checkout_head": provenance["checkout_head"],
            "suite_revision": provenance["suite_revision"],
            "native_extension_path": provenance["native_path"],
            "native_extension_sha256": provenance["native_sha256"],
            "package_path": provenance["package_path"],
            "case_count": len(suite_report.get("records") or []),
            "stage_counts": stage_counts(suite_report),
        },
        "provenance": provenance,
        "coverage_problems": coverage,
        "official_reference_failures": failures,
        "unsupported": unsupported,
        "corpus": corpus,
        "diff": diff,
        "previous": (
            {"path": str(previous_path), "sha256": _digest(previous_path)}
            if previous_path
            else None
        ),
        "manifest": (
            {
                "path": str(expectations_path),
                "sha256": _digest(expectations_path),
                **manifest,
            }
            if expectations_path and manifest is not None
            else None
        ),
        "expectations_path": str(expectations_path) if expectations_path else "",
        "corpus_inventory_path": (
            str(corpus_inventory_path) if corpus_inventory_path else ""
        ),
    }


def render_text(status: dict[str, Any], max_cases: int = 40) -> str:
    """Render the status for a reader."""

    lines: list[str] = []
    suite = status["suite"]
    provenance = status["provenance"]

    lines.append("SBML Atomizer coverage campaign — status")
    lines.append("=" * 44)
    lines.append("")

    lines.append("## Provenance")
    lines.append(f"Report:           {suite['path']}")
    lines.append(f"Report SHA-256:   {suite['sha256']}")
    lines.append(f"BNG3 commit:      {suite['commit'] or '(not recorded)'}")
    lines.append(f"Suite revision:   {suite['suite_revision'] or '(not recorded)'}")
    lines.append(
        f"Native extension: {suite['native_extension_path'] or '(not recorded)'}"
    )
    lines.append(
        f"                 sha256 {suite['native_extension_sha256'] or '(not recorded)'}"
    )
    lines.append(f"Python package:   {suite['package_path'] or '(not recorded)'}")
    runtime = provenance.get("runtime") or {}
    lines.append(
        "Tool versions:    python {python}, libsbml {libsbml}, roadrunner "
        "{roadrunner}, numpy {numpy}".format(
            python=runtime.get("python_version") or "?",
            libsbml=runtime.get("libsbml_version") or "?",
            roadrunner=runtime.get("roadrunner_version") or "?",
            numpy=runtime.get("numpy_version") or "?",
        )
    )
    verdict = {
        PROVENANCE_MATCH: "MATCH — the report measured this repository's tree",
        PROVENANCE_MISMATCH: "MISMATCH — the report measured something else",
        PROVENANCE_UNVERIFIABLE: (
            "UNVERIFIABLE — the report could not be tied to this checkout"
        ),
    }[provenance["status"]]
    lines.append(f"Provenance check: {verdict}")
    for problem in provenance["problems"]:
        lines.append(f"  PROBLEM: {problem}")
    for note in provenance["notes"]:
        lines.append(f"  note: {note}")
    lines.append("")

    lines.append("## Stage counts — official SBML Test Suite")
    counts = suite["stage_counts"]
    rows = []
    for stage, label in tables.STAGE_LABELS:
        bucket = counts.get(stage, {})
        rows.append(
            [
                label,
                str(bucket.get("passed", 0)),
                str(bucket.get("unsupported", 0)),
                str(bucket.get("failed", 0)),
                str(bucket.get("not_tested", 0)),
            ]
        )
    lines.extend(
        _table(["Stage", "Passed", "Unsupported", "Failed", "Not tested"], rows)
    )
    lines.append("")
    lines.append(f"Cases run: {suite['case_count']}.")
    if status["coverage_problems"]:
        lines.append("")
        lines.append("Coverage problems:")
        for problem in status["coverage_problems"]:
            lines.append(f"  - {problem}")
    lines.append("")

    corpus = status.get("corpus")
    if corpus is not None:
        lines.append("## Stage counts — curated BioModels corpus")
        summary = corpus.get("summary") or {}
        rows = [
            [
                str(corpus["mode"]),
                str(summary.get("selected_records", "?")),
                str(corpus["status_counts"].get("passed", 0)),
                str(corpus["status_counts"].get("unsupported", 0)),
                str(corpus["status_counts"].get("unsupported_format", 0)),
                str(corpus["status_counts"].get("failed", 0)),
                str(corpus["status_counts"].get("timeout", 0)),
            ]
        ]
        lines.extend(
            _table(
                [
                    "Mode",
                    "Records",
                    "Passed",
                    "Unsupported",
                    "Unsupported format",
                    "Failed",
                    "Timed out",
                ],
                rows,
            )
        )
        lines.append("")
        lines.append(f"Report SHA-256: {corpus['sha256']}")
        measurement = corpus.get("measurement") or {}
        if measurement:
            lines.append(
                f"Measured at commit: {measurement.get('base_commit') or '(not recorded)'}"
            )
        if not corpus.get("runtime_provenance"):
            lines.append(
                "note: the corpus report records no runtime provenance, so it "
                "cannot be tied to a native build."
            )
        lines.append("")

    failures = status["official_reference_failures"]
    lines.append("## Remaining official-reference failures")
    if failures["grouped"]:
        rows = [
            [
                str(entry["cluster"]),
                str(entry["label"]),
                str(entry["count"]),
                _case_list(entry["cases"], max_cases),
            ]
            for entry in failures["clusters"]
        ]
        lines.extend(_table(["Cluster", "Feature", "n", "Cases"], rows))
    else:
        lines.append(
            "The official-feature cluster grouping needs the pinned suite "
            "checkout; pass `--suite-dir` to compute it."
        )
        lines.append("")
        lines.append(
            f"{failures['total']} failure(s): "
            + _case_list(failures["cases"], max_cases)
        )
    if failures["unclustered"]:
        lines.append("")
        lines.append(
            "Unclustered failures: " + _case_list(failures["unclustered"], max_cases)
        )
    for problem in failures["problems"]:
        lines.append(f"  PROBLEM: {problem}")
    lines.append("")
    lines.append(f"Total official-reference failures: {failures['total']}.")
    lines.append("")

    lines.append("## Unsupported cases, by the side of the gap")
    lines.append(
        "A harness-side gap is a measurement limitation; an Atomizer-side gap "
        "is a representational one."
    )
    for side, entry in status["unsupported"].items():
        lines.append("")
        lines.append(f"### {side} ({entry['total']})")
        rows = [
            [
                str(construct["construct"]),
                str(construct["count"]),
                _case_list(construct["cases"], max_cases),
            ]
            for construct in entry["constructs"]
        ]
        if rows:
            lines.extend(_table(["Construct", "n", "Cases"], rows))
        else:
            lines.append("none")
    lines.append("")

    diff = status.get("diff")
    if diff is not None:
        lines.append("## Change against the previous report")
        lines.append(f"Previous report: {status['previous']['path']}")
        lines.append(f"Previous SHA-256: {status['previous']['sha256']}")
        lines.append("")
        if diff["regressions"]:
            lines.append("### REGRESSIONS (a stage that was `passed` and no longer is)")
            lines.append("")
            for difference in diff["regressions"]:
                lines.append(
                    f"- `{difference['case']}` [{difference['stage']}]: "
                    f"{difference['before']} → {difference['after']}"
                )
        else:
            lines.append("### REGRESSIONS: none")
        lines.append("")
        lines.append(
            f"Improvements: {len(diff['improvements'])}; "
            f"changes: {len(diff['changes'])}; "
            f"cases added: {len(diff['added'])}; "
            f"cases removed: {len(diff['removed'])}."
        )
        if diff["improvements"]:
            lines.append("")
            for difference in diff["improvements"][:max_cases]:
                lines.append(
                    f"- `{difference['case']}` [{difference['stage']}]: "
                    f"{difference['before']} → {difference['after']}"
                )
        if diff["changes"]:
            lines.append("")
            for difference in diff["changes"][:max_cases]:
                lines.append(
                    f"- `{difference['case']}` [{difference['stage']}]: "
                    f"{difference['before']} → {difference['after']}"
                )
        lines.append("")

    manifest = status.get("manifest")
    lines.append("## Expectation manifest")
    if manifest is None:
        lines.append(
            "No expectation manifest was given, so its currency could not be "
            "established."
        )
    else:
        lines.append(f"Manifest: {manifest['path']}")
        lines.append(f"Manifest SHA-256: {manifest['sha256']}")
        if manifest["suite_revision_mismatch"]:
            lines.append(
                "PROBLEM: the run used a different official suite revision "
                f"({manifest['suite_revision_observed']}) than the manifest "
                f"describes ({manifest['suite_revision_expected']})."
            )
        if manifest["current"]:
            lines.append(
                f"The manifest is current: {manifest['cases_compared']} case(s) "
                "match."
            )
        else:
            lines.append(
                f"The manifest is STALE: {len(manifest['differences'])} "
                "difference(s) against this report "
                f"({manifest['cases_compared']} case(s) compared)."
            )
            lines.append(f"  note: {manifest.get('direction', '')}")
            for difference in manifest["regressions"]:
                lines.append(
                    f"  REGRESSION {difference['case']} [{difference['stage']}]: "
                    f"expected {difference['expected']}, observed "
                    f"{difference['observed']}"
                )
            for difference in manifest["improvements"]:
                lines.append(
                    f"  improvement {difference['case']} [{difference['stage']}]: "
                    f"expected {difference['expected']}, observed "
                    f"{difference['observed']}"
                )
            for difference in manifest["changes"][:max_cases]:
                lines.append(
                    f"  change {difference['case']} [{difference['stage']}]: "
                    f"expected {difference['expected']}, observed "
                    f"{difference['observed']}"
                )
    lines.append("")

    lines.append("## Exit status")
    lines.append(f"{status['exit_status']}")
    if status["exit_reasons"]:
        for reason in status["exit_reasons"]:
            lines.append(f"  - {reason}")
    else:
        lines.append("  clean")
    lines.append("")
    lines.append(
        "The exit status is a bit mask: 1 regression, 2 stale manifest, "
        "4 provenance, 8 incomplete coverage."
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite-report", type=Path, required=True, help="the gate report to read"
    )
    parser.add_argument(
        "--previous-suite-report",
        type=Path,
        help="the report the current one is compared against",
    )
    parser.add_argument(
        "--biomodels-report", type=Path, help="the curated corpus gate report"
    )
    parser.add_argument(
        "--corpus-inventory",
        type=Path,
        help="the committed curated corpus inventory, for its measurement block",
    )
    parser.add_argument(
        "--expectations",
        type=Path,
        help=(
            "the committed expectation manifest to check for currency "
            "(default: the manifest committed in the checkout)"
        ),
    )
    parser.add_argument(
        "--suite-dir",
        type=Path,
        help="the pinned official suite checkout, for the failure clusters",
    )
    parser.add_argument(
        "--checkout-root",
        type=Path,
        default=REPO_ROOT,
        help="the checkout the report is read against (default: this one)",
    )
    parser.add_argument("--json", type=Path, help="write the status as JSON")
    parser.add_argument(
        "--max-cases",
        type=int,
        default=40,
        help="how many case ids to print in a table cell",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checkout_root = args.checkout_root.resolve()

    suite_report_path = args.suite_report.resolve()
    suite_report = _load(suite_report_path)

    previous_path = None
    previous_report = None
    if args.previous_suite_report is not None:
        previous_path = args.previous_suite_report.resolve()
        previous_report = _load(previous_path)

    biomodels_path = None
    biomodels_report = None
    if args.biomodels_report is not None:
        biomodels_path = args.biomodels_report.resolve()
        biomodels_report = _load(biomodels_path)

    corpus_inventory_path = None
    corpus_inventory = None
    if args.corpus_inventory is not None:
        corpus_inventory_path = args.corpus_inventory.resolve()
        corpus_inventory = _load(corpus_inventory_path)

    expectations_path = None
    expectations = None
    if args.expectations is not None:
        expectations_path = args.expectations.resolve()
    else:
        committed = checkout_root / "provenance" / "sbml-campaign" / "expectations.json"
        if committed.is_file():
            expectations_path = committed
    if expectations_path is not None:
        expectations = _load(expectations_path)

    status = build_status(
        suite_report_path=suite_report_path,
        suite_report=suite_report,
        previous_path=previous_path,
        previous_report=previous_report,
        biomodels_path=biomodels_path,
        biomodels_report=biomodels_report,
        corpus_inventory_path=corpus_inventory_path,
        corpus_inventory=corpus_inventory,
        expectations_path=expectations_path,
        expectations=expectations,
        suite_dir=args.suite_dir.resolve() if args.suite_dir else None,
        checkout_root=checkout_root,
    )

    print(render_text(status, max_cases=args.max_cases))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.json}")
    return int(status["exit_status"])


if __name__ == "__main__":
    raise SystemExit(main())
