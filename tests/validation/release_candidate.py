"""The release-candidate evidence that one host can decide (#184).

Issue #184 asks for the final-candidate release gates: the platform matrix,
the sanitizer and memory contract, the licences and notices, and the
reproducible-build metadata.  It also asks to retain normal CI's narrower
scope, so the release candidate needs *more* than the ordinary lane.

The arms of the obligation split into two groups, and this family keeps them
apart.

What one host decides
    The licence and notice inventory of the shipped artefacts, the memory
    contract of the artefacts, the sanitizer configuration the CI declares and
    the declared shape of the platform matrix.  All four are properties of the
    repository and of the workflows, so they are decided here and now.

What the hosted matrix has to produce
    The sanitizer runs themselves and the per-platform results.  A single host
    cannot produce them, so the family records them as *evidence to collect*:
    every arm carries the exact command and the artefact the hosted run has to
    produce, and the arms are written to ``hosted-evidence.json`` next to the
    report rows.  The rows never claim that an arm ran.

The family therefore closes the detection gap of the obligation without
claiming the hosted evidence: the single-host arms are named executable checks,
and the hosted arms are a recorded boundary with an owner.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .campaign import STATUSES

ISSUES = (184,)
OPERATION = "release-candidate"

# The named checks of this operation.
CHECKS = (
    "license-inventory",
    "notice-inventory",
    "memory-contract",
    "sanitizer-configuration",
    "platform-matrix-shape",
    "hosted-evidence",
)

# The obligation of issue #184 that this family closes.
OBLIGATION_CHECK = "verify-final-candidate-platform-sanitizer-memory-licenses-notice"

ROOT = Path(__file__).resolve().parents[2]

LICENSE = ROOT / "LICENSE"
NOTICE = ROOT / "NOTICE"
INVENTORY = ROOT / "provenance" / "third-party-notices.json"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CMAKE = ROOT / "CMakeLists.txt"

# The owner of the arms that need the hosted matrix.  The arms are collected
# by the release maintainer in the hosted release run.
HOSTED_OWNER = "release maintainer (issue #184)"


def _workflow(path):
    from tests.workflow_yaml import parse_workflow

    return parse_workflow(path)


def _normalize(text):
    """The text of a notice, without the decoration of its source block."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip().strip("*").strip()
        if stripped:
            lines.append(stripped)
    return " ".join(" ".join(lines).split())


def _same_repository(left, right):
    """Do two repository references name the same project?"""

    def canonical(value):
        return str(value or "").strip().rstrip("/").removesuffix(".git").lower()

    return canonical(left) == canonical(right) and canonical(left) != ""


def _package_steps(workflow):
    """The steps of the release workflow that package the binaries."""
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "package binaries" in str(step.get("name", "")).lower()
    ]


def _row(check, status, detail, *, first_difference=None, **evidence):
    row = dict(
        check=check,
        status=status,
        detail=detail,
        related_issues=list(ISSUES),
        question="the-release-candidate-evidence-one-host-can-decide",
        **evidence,
    )
    if status in {"PASS", "FAIL"}:
        row.setdefault("evidence_kind", "supported-execution")
        row.setdefault("supported_execution", True)
    else:
        row.setdefault("evidence_kind", "diagnostic-only")
        row.setdefault("supported_execution", False)
    return row


def check_ids():
    """Stable expected check identities for the release-candidate operation."""
    ids = [f"{OPERATION}:{name}" for name in CHECKS]
    ids.append(f"qualification:issue:184:{OBLIGATION_CHECK}")
    return ids


# --------------------------------------------------------------------------- #
# The licence inventory.
# --------------------------------------------------------------------------- #


def licence_differences(root=None):
    """The differences between the declared licence and the shipped licence."""
    root = Path(root) if root is not None else ROOT
    differences = []
    licence = root / "LICENSE"
    if not licence.is_file():
        differences.append(
            dict(
                field="licence.file",
                expected="a licence file at the repository root",
                actual=None,
            )
        )
        return differences
    text = licence.read_text(encoding="utf-8")
    if "MIT License" not in text:
        differences.append(
            dict(
                field="licence.text", expected="the MIT licence text", actual=text[:80]
            )
        )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^license\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if declared is None:
        differences.append(
            dict(
                field="licence.declared",
                expected="a declared licence in pyproject.toml",
                actual=None,
            )
        )
    elif declared.group(1).strip().upper() != "MIT":
        differences.append(
            dict(field="licence.declared", expected="MIT", actual=declared.group(1))
        )
    # The licence file must travel with the artefacts.  The binary tarball is
    # packaged by the release workflow, so the workflow has to copy it; the
    # wheel and the source distribution take the root licence files through
    # the build backend, so the metadata must not exclude them.
    workflow = _workflow(root / ".github" / "workflows" / "release.yml")
    package_steps = _package_steps(workflow)
    if not package_steps:
        differences.append(
            dict(
                field="licence.packaging",
                expected="a packaging step in the release workflow",
                actual=None,
            )
        )
    else:
        commands = "\n".join(str(step.get("run", "")) for step in package_steps)
        if "LICENSE" not in commands:
            differences.append(
                dict(
                    field="licence.packaging",
                    expected="the packaged binaries carry the licence file",
                    actual="the packaging step copies no licence file",
                )
            )
    if re.search(r"^\s*license-files\s*=", pyproject, re.MULTILINE):
        differences.append(
            dict(
                field="licence.excluded",
                expected="the root licence files are not excluded from the distribution",
                actual="pyproject.toml declares license-files",
            )
        )
    return differences


# --------------------------------------------------------------------------- #
# The notice inventory.
# --------------------------------------------------------------------------- #

FETCHCONTENT = re.compile(
    r"FetchContent_Declare\(\s*(?P<name>\w+)(?P<body>.*?)\n\s*\)", re.DOTALL
)
GIT_REPOSITORY = re.compile(r"GIT_REPOSITORY\s+(?P<value>\S+)")
GIT_TAG = re.compile(r"GIT_TAG\s+(?P<value>\S+)")


def fetched_dependencies(root=None):
    """The external projects the build fetches, with their pinned revision."""
    root = Path(root) if root is not None else ROOT
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    found = []
    for match in FETCHCONTENT.finditer(text):
        body = match.group("body")
        repository = GIT_REPOSITORY.search(body)
        tag = GIT_TAG.search(body)
        if repository is None:
            continue
        found.append(
            dict(
                name=match.group("name"),
                repository=repository.group("value").strip("\"'"),
                revision=(tag.group("value").strip("\"'") if tag else None),
            )
        )
    return found


def notice_differences(root=None):
    """The differences between the bundled components and the inventory."""
    root = Path(root) if root is not None else ROOT
    differences = []
    inventory_path = root / "provenance" / "third-party-notices.json"
    notice_path = root / "NOTICE"
    if not inventory_path.is_file():
        differences.append(
            dict(
                field="notices.inventory",
                expected="provenance/third-party-notices.json",
                actual=None,
            )
        )
        return differences
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        differences.append(
            dict(
                field="notices.inventory",
                expected="a readable inventory",
                actual=str(exc),
            )
        )
        return differences
    components = {entry["id"]: entry for entry in inventory.get("components", [])}
    notice_text = (
        _normalize(notice_path.read_text(encoding="utf-8"))
        if notice_path.is_file()
        else ""
    )
    for component in components.values():
        for path in component.get("bundled_paths", []):
            bundled = root / path
            if not bundled.is_dir():
                differences.append(
                    dict(
                        field="notices.bundled-path",
                        expected=path,
                        actual="the bundled path does not exist",
                    )
                )
        source = component.get("notice_source", "")
        if source.startswith("http"):
            continue
        source_path = root / source
        if not source_path.is_file():
            differences.append(
                dict(
                    field="notices.source",
                    expected=source,
                    actual="the file that carries the notice does not exist",
                )
            )
            continue
        text = _normalize(source_path.read_text(encoding="utf-8"))
        if _normalize(component.get("notice_text", "")) not in text:
            differences.append(
                dict(
                    field="notices.removed",
                    expected=component["id"],
                    actual=f"{source} does not carry the recorded notice any more",
                )
            )
        if _normalize(component.get("notice_text", "")) not in notice_text:
            differences.append(
                dict(
                    field="notices.not-served",
                    expected=component["id"],
                    actual="the NOTICE file does not carry the recorded notice",
                )
            )
    # Every component the build fetches and links has to be inventoried, and
    # the inventory has to record the revision the build pins.
    for dependency in fetched_dependencies(root):
        if dependency["name"] == "Catch2":
            # The test-only dependency is not part of a shipped artefact.
            continue
        matching = [
            entry
            for entry in components.values()
            if _same_repository(dependency["repository"], entry.get("upstream", ""))
        ]
        if not matching:
            differences.append(
                dict(
                    field="notices.uninventoried",
                    expected=dependency["repository"],
                    actual="the fetched dependency is not in the notice inventory",
                )
            )
            continue
        recorded = sorted({entry.get("revision") for entry in matching})
        if dependency["revision"] and recorded != [dependency["revision"]]:
            differences.append(
                dict(
                    field="notices.stale-revision",
                    expected=dependency["revision"],
                    actual=recorded,
                )
            )
    # The notice file has to travel with the packaged binaries.
    workflow = _workflow(root / ".github" / "workflows" / "release.yml")
    commands = "\n".join(str(step.get("run", "")) for step in _package_steps(workflow))
    if "NOTICE" not in commands:
        differences.append(
            dict(
                field="notices.packaging",
                expected="the packaged binaries carry the notices",
                actual="the packaging step copies no notice file",
            )
        )
    return differences


# --------------------------------------------------------------------------- #
# The memory contract and the sanitizer configuration.
# --------------------------------------------------------------------------- #

# The flags that embed a second copy of the C++ runtime into the extension.
# They are correct for a CLI executable and wrong for a module that is loaded
# into a process the packager does not own.
STATIC_RUNTIME_FLAGS = ("-static-libstdc++", "-static-libgcc")

# The sanitizer instrumentation a shipped artefact must not carry.
SANITIZER_FLAGS = ("-fsanitize=address", "-fsanitize=undefined", "-fsanitize=leak")


def memory_contract_differences(root=None):
    """The differences between the declared memory contract and the workflows."""
    root = Path(root) if root is not None else ROOT
    differences = []
    workflow = _workflow(root / ".github" / "workflows" / "release.yml")
    release_text = "\n".join(
        str(step.get("run", ""))
        + " "
        + " ".join(str(value) for value in step.get("env", {}).values())
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    )
    for flag in STATIC_RUNTIME_FLAGS:
        if flag in release_text:
            differences.append(
                dict(
                    field="memory.static-runtime",
                    expected="no static C++ runtime in a shipped extension",
                    actual=f"{flag} is declared by the release workflow",
                )
            )
    for flag in SANITIZER_FLAGS:
        if flag in release_text:
            differences.append(
                dict(
                    field="memory.sanitizer-in-release",
                    expected="no sanitizer instrumentation in a shipped artefact",
                    actual=f"{flag} is declared by the release workflow",
                )
            )
    if "CMAKE_BUILD_TYPE=Release" not in release_text:
        differences.append(
            dict(
                field="memory.build-type",
                expected="a Release build of the shipped artefacts",
                actual="the release workflow does not declare a Release build",
            )
        )
    # The sanitizer configuration belongs to the CI lane, and the leak
    # detection of the shipped artefacts has to be declared there.
    ci_text = "\n".join(
        str(step.get("run", ""))
        + " "
        + " ".join(str(value) for value in step.get("env", {}).values())
        for job in _workflow(root / ".github" / "workflows" / "ci.yml")["jobs"].values()
        for step in job.get("steps", [])
    )
    if "detect_leaks" not in ci_text:
        differences.append(
            dict(
                field="memory.leak-policy",
                expected="a declared leak-detection policy in the CI lane",
                actual="no leak-detection option is declared",
            )
        )
    return differences


def sanitizer_differences(root=None):
    """The differences between the declared sanitizer configuration and CI."""
    root = Path(root) if root is not None else ROOT
    differences = []
    workflow = _workflow(root / ".github" / "workflows" / "ci.yml")
    sanitizer_jobs = []
    for name, job in workflow["jobs"].items():
        text = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
        if any(flag in text for flag in SANITIZER_FLAGS):
            sanitizer_jobs.append(name)
    if not sanitizer_jobs:
        differences.append(
            dict(
                field="sanitizer.job",
                expected="a CI job that builds with a sanitizer",
                actual="no CI job declares sanitizer instrumentation",
            )
        )
        return differences
    for name in sanitizer_jobs:
        job = workflow["jobs"][name]
        text = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
        if "ctest" not in text:
            differences.append(
                dict(
                    field="sanitizer.tests",
                    expected=f"{name} runs the test suite under the sanitizer",
                    actual="the sanitizer job runs no test suite",
                )
            )
        if not any(flag in text for flag in SANITIZER_FLAGS):
            differences.append(
                dict(
                    field="sanitizer.flags",
                    expected=f"{name} declares the sanitizer instrumentation",
                    actual="the job was selected by another step",
                )
            )
    return differences


# --------------------------------------------------------------------------- #
# The platform matrix.
# --------------------------------------------------------------------------- #


def platform_matrix_differences(root=None):
    """The differences between the declared platform matrix and the release."""
    root = Path(root) if root is not None else ROOT
    differences = []
    workflow = _workflow(root / ".github" / "workflows" / "release.yml")
    jobs = workflow["jobs"]
    binary_job = jobs.get("build-binaries", {})
    wheel_job = jobs.get("build-wheels", {})

    def platforms(job):
        include = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
        return sorted(
            entry["os"]
            for entry in include
            if isinstance(entry, dict) and "os" in entry
        )

    binary_platforms = platforms(binary_job)
    wheel_platforms = platforms(wheel_job)
    if not binary_platforms:
        differences.append(
            dict(
                field="matrix.binaries", expected="a declared binary matrix", actual=[]
            )
        )
    if binary_platforms != wheel_platforms:
        differences.append(
            dict(
                field="matrix.agreement",
                expected=binary_platforms,
                actual={"wheels": wheel_platforms},
            )
        )
    steps = "\n".join(str(step.get("run", "")) for step in binary_job.get("steps", []))
    names = "\n".join(str(step.get("name", "")) for step in binary_job.get("steps", []))
    if "--version" not in steps:
        differences.append(
            dict(
                field="matrix.smoke-test",
                expected="a smoke test of the built binaries",
                actual="the binary job runs no smoke test",
            )
        )
    if "package binaries" not in names.lower():
        differences.append(
            dict(
                field="matrix.packaging",
                expected="a packaging step for the built binaries",
                actual="the binary job packages nothing",
            )
        )
    return differences


# --------------------------------------------------------------------------- #
# The hosted evidence.
# --------------------------------------------------------------------------- #


def hosted_arms():
    """The arms that the hosted matrix has to produce.

    Every arm names the exact command and the artefact the hosted run has to
    produce.  The arms are evidence to collect; the family never reports them
    as executed.
    """
    workflow = _workflow(RELEASE_WORKFLOW)
    binary_job = workflow["jobs"].get("build-binaries", {})
    include = ((binary_job.get("strategy") or {}).get("matrix") or {}).get(
        "include"
    ) or []
    arms = []
    for entry in include:
        if not isinstance(entry, dict) or "os" not in entry:
            continue
        platform = entry["os"]
        artefact = entry.get("artifact_name", f"bionetgen-{platform}")
        arms.append(
            dict(
                arm=f"release-binary-{platform}",
                platform=platform,
                owner=HOSTED_OWNER,
                status="PENDING",
                command=(
                    "cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release "
                    "-DBUILD_PYTHON_BINDINGS=OFF -DBUILD_CLI=ON -DBUILD_NFSIM_CLI=ON "
                    "-DBUILD_TESTS=OFF && cmake --build build --config Release && "
                    "build/cpp/bng_cpp --version && build/cpp/NFsim -help && "
                    "tar tzf dist/" + artefact + ".tar.gz"
                ),
                artifact=f"dist/{artefact}.tar.gz",
                artifact_content=("LICENSE and NOTICE inside the packaged binaries"),
            )
        )
    arms.append(
        dict(
            arm="release-wheel-licence-inventory",
            platform="hosted build matrix",
            owner=HOSTED_OWNER,
            status="PENDING",
            command=(
                "python -m zipfile -l dist/*.whl | grep -Ei '(licen[cs]e|notice)' && "
                "tar tzf dist/*.tar.gz | grep -Ei '(licen[cs]e|notice)'"
            ),
            artifact="the licence and notice entries of every packaged wheel and sdist",
        )
    )
    arms.append(
        dict(
            arm="sanitizer-address-linux",
            platform="ubuntu-22.04",
            owner=HOSTED_OWNER,
            status="PENDING",
            command=(
                "cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug "
                '-DCMAKE_CXX_FLAGS="-fsanitize=address -fno-omit-frame-pointer" '
                '-DCMAKE_C_FLAGS="-fsanitize=address -fno-omit-frame-pointer" '
                '-DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address" -DBUILD_PYTHON_BINDINGS=OFF '
                "-DBUILD_CLI=ON -DBUILD_TESTS=ON && cmake --build build && "
                "ASAN_OPTIONS=detect_leaks=0 ctest --test-dir build --output-on-failure"
            ),
            artifact="the ctest log of the sanitizer build",
        )
    )
    return arms


def hosted_evidence_differences(arms):
    """The differences between the declared arms and the obligation."""
    differences = []
    if not arms:
        differences.append(
            dict(field="hosted.arms", expected="at least one arm to collect", actual=[])
        )
    for arm in arms:
        for field in ("command", "artifact", "owner"):
            if not str(arm.get(field, "")).strip():
                differences.append(
                    dict(
                        field="hosted.arm",
                        expected=f"{arm.get('arm')} declares its {field}",
                        actual=None,
                    )
                )
    platforms = {arm["platform"] for arm in arms}
    workflow = _workflow(RELEASE_WORKFLOW)
    binary_job = workflow["jobs"].get("build-binaries", {})
    include = ((binary_job.get("strategy") or {}).get("matrix") or {}).get(
        "include"
    ) or []
    declared = {
        entry["os"] for entry in include if isinstance(entry, dict) and "os" in entry
    }
    missing = sorted(declared - platforms)
    if missing:
        differences.append(
            dict(
                field="hosted.platform-coverage",
                expected=sorted(declared),
                actual=sorted(platforms),
            )
        )
    return differences


# --------------------------------------------------------------------------- #
# The worker.
# --------------------------------------------------------------------------- #


def run_worker(directory: Path):
    """Execute the release-candidate qualification and return its rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = []

    licence = licence_differences()
    rows.append(
        dict(
            _row(
                "license-inventory",
                "FAIL" if licence else "PASS",
                (
                    (
                        "the shipped artefacts carry the licence that the package "
                        "metadata declares"
                    )
                    if not licence
                    else "the licence inventory is incomplete: "
                    + ", ".join(sorted({item["field"] for item in licence}))
                ),
                first_difference=licence[0] if licence else None,
                licence_file="LICENSE",
            ),
            id=f"{OPERATION}:license-inventory",
        )
    )

    notices = notice_differences()
    rows.append(
        dict(
            _row(
                "notice-inventory",
                "FAIL" if notices else "PASS",
                (
                    (
                        "every bundled or fetched component is inventoried and every "
                        "recorded notice travels with the artefacts"
                    )
                    if not notices
                    else "the notice inventory is incomplete: "
                    + ", ".join(sorted({item["field"] for item in notices}))
                ),
                first_difference=notices[0] if notices else None,
                inventory=str(INVENTORY.relative_to(ROOT)),
            ),
            id=f"{OPERATION}:notice-inventory",
        )
    )

    memory = memory_contract_differences()
    rows.append(
        dict(
            _row(
                "memory-contract",
                "FAIL" if memory else "PASS",
                (
                    (
                        "the shipped artefacts carry no sanitizer instrumentation and "
                        "no embedded C++ runtime, and the CI lane declares the "
                        "leak-detection policy"
                    )
                    if not memory
                    else "the memory contract is not declared: "
                    + ", ".join(sorted({item["field"] for item in memory}))
                ),
                first_difference=memory[0] if memory else None,
            ),
            id=f"{OPERATION}:memory-contract",
        )
    )

    sanitizer = sanitizer_differences()
    rows.append(
        dict(
            _row(
                "sanitizer-configuration",
                "FAIL" if sanitizer else "PASS",
                (
                    (
                        "the CI declares a sanitizer job that runs the test suite "
                        "under the sanitizer"
                    )
                    if not sanitizer
                    else "the sanitizer configuration is incomplete: "
                    + ", ".join(sorted({item["field"] for item in sanitizer}))
                ),
                first_difference=sanitizer[0] if sanitizer else None,
            ),
            id=f"{OPERATION}:sanitizer-configuration",
        )
    )

    matrix = platform_matrix_differences()
    rows.append(
        dict(
            _row(
                "platform-matrix-shape",
                "FAIL" if matrix else "PASS",
                (
                    (
                        "the release workflow declares one platform matrix for the "
                        "binaries and the wheels, and every platform is built, "
                        "smoke-tested and packaged"
                    )
                    if not matrix
                    else "the platform matrix is not declared: "
                    + ", ".join(sorted({item["field"] for item in matrix}))
                ),
                first_difference=matrix[0] if matrix else None,
            ),
            id=f"{OPERATION}:platform-matrix-shape",
        )
    )

    arms = hosted_arms()
    hosted = hosted_evidence_differences(arms)
    (directory / "hosted-evidence.json").write_text(
        json.dumps(
            dict(
                obligation=f"issue:184:{OBLIGATION_CHECK}",
                owner=HOSTED_OWNER,
                note=(
                    "These arms are evidence to collect, not executed results. "
                    "The hosted release run produces each artefact; nothing "
                    "here claims that an arm ran."
                ),
                arms=arms,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rows.append(
        dict(
            _row(
                "hosted-evidence",
                "FAIL" if hosted else "PASS",
                (
                    (
                        "the arms that need the hosted matrix are recorded with "
                        "their exact command and their expected artefact"
                    )
                    if not hosted
                    else "the hosted evidence is not declared: "
                    + ", ".join(sorted({item["field"] for item in hosted}))
                ),
                first_difference=hosted[0] if hosted else None,
                arms=[arm["arm"] for arm in arms],
                owner=HOSTED_OWNER,
                artifact="hosted-evidence.json",
            ),
            id=f"{OPERATION}:hosted-evidence",
        )
    )

    failures = [row["id"] for row in rows if row["status"] == "FAIL"]
    obligation = dict(
        _row(
            OBLIGATION_CHECK,
            "FAIL" if failures else "PASS",
            (
                "the licence and notice inventory of the shipped artefacts, the "
                "memory contract and the declared sanitizer configuration are "
                "decided here, and the arms that need the hosted matrix are "
                "recorded as evidence to collect"
            ),
            failures=sorted(failures),
            hosted_arms=[arm["arm"] for arm in arms],
        ),
        id=f"qualification:issue:184:{OBLIGATION_CHECK}",
    )
    if failures:
        obligation["detail"] = (
            "the release-candidate evidence is incomplete: "
            + ", ".join(sorted(failures))
        )
        obligation["first_difference"] = dict(failed_checks=sorted(failures))
    rows.append(obligation)

    for row in rows:
        if row.get("status") not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the release-candidate adapter emitted an invalid status",
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
