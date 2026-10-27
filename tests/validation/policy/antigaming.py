"""Base-revision policy checks for public scientific acceptance tests.

This module intentionally has no pytest dependency. CI loads this exact file
from the PR base before checking the proposed tree.
"""

from __future__ import annotations

import json
import os
import hashlib
import re
import subprocess
import sys
from pathlib import Path

CHECK_IDS = (
    "release-independent-seeds",
    "release-protected-expectations",
    "release-no-product-fixture-names",
    "release-scheduled-mutation-ratchet",
)

PRODUCT_PREFIXES = ("cpp/", "python/", "bng3/", "src/", "scripts/")
PROTECTED_WORDS = ("expected", "golden", "tolerance", "exception", "skip", "exclude")
ID_RE = re.compile(
    r"""(?ix)(?:case[_ -]?id|"id"|\bid\b|\bids\b)["']?\s*[=:]\s*[\["']*([A-Za-z0-9][A-Za-z0-9_.:/-]{2,})"""
)
CASE_TOKEN_RE = re.compile(
    r"""(?i)["']((?:case|model|check)[_:/.-][A-Za-z0-9][A-Za-z0-9_.:/-]{1,})["']"""
)
GENERIC_FIXTURE_NAMES = {
    "continue",
    "strict",
    "pytest",
    "__init__",
    "models",
    "model",
    "test",
    "simple",
    "readme",
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=root, text=True, stderr=subprocess.STDOUT
    )


def changed_paths(root: Path, base: str, head: str = "HEAD") -> list[str]:
    return [
        p
        for p in git(
            root, "diff", "--name-only", "--diff-filter=ACDMRT", f"{base}...{head}"
        ).splitlines()
        if p
    ]


def _base_text(root: Path, base: str, path: str) -> str:
    try:
        raw = subprocess.check_output(
            ("git", "show", f"{base}:{path}"), cwd=root, stderr=subprocess.STDOUT
        )
        return raw.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return ""


def check_protected_changes(root: Path, base: str, head: str = "HEAD") -> list[str]:
    """Reject a PR combining product edits and public expectation/policy edits."""
    paths = changed_paths(root, base, head)
    product = [p for p in paths if p.startswith(PRODUCT_PREFIXES)]
    protected = [
        p
        for p in paths
        if any(w in p.lower() for w in PROTECTED_WORDS)
        or p.startswith(
            ("tests/", "fixtures/", "expected/", "provenance/", ".github/workflows/")
        )
        or p in {"docs/CAPABILITY_UNION_INVENTORY.md", "docs/DECISIONS.md"}
    ]
    return (
        [
            f"product changes mixed with protected acceptance data: {product} + {protected}"
        ]
        if product and protected
        else []
    )


def _manifest_ids(text: str) -> set[str]:
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return set()
    found: set[str] = set()

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"id", "case_id", "caseid"} and isinstance(
                    child, str
                ):
                    found.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(doc)
    return found


def check_case_ids(root: Path, base: str, head: str = "HEAD") -> list[str]:
    """Reject deleted/renamed manifest, parameter, and selected pytest node IDs."""
    patch = git(
        root,
        "diff",
        "--unified=0",
        f"{base}...{head}",
        "--",
        "tests/",
        "provenance/",
        "docs/CAPABILITY_UNION_INVENTORY.md",
        "docs/DECISIONS.md",
    )
    deleted: set[str] = set()
    added: set[str] = set()
    selected_files: set[str] = set()
    try:
        plan = json.loads(_base_text(root, base, "provenance/validation-plan.json"))
    except (ValueError, TypeError):
        plan = {}

    def collect_tests(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"tests", "test"}:
                    collect_tests(child)
                elif isinstance(child, (dict, list)):
                    collect_tests(child)
        elif isinstance(value, list):
            for child in value:
                collect_tests(child)
        elif isinstance(value, str) and value.startswith("tests/"):
            selected_files.add(value.split("::", 1)[0])

    collect_tests(plan)
    current_file = ""
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            current_file = line.split(" b/", 1)[-1]
        if line.startswith(("---", "+++")) or not line or line[0] not in "+-":
            continue
        target = deleted if line[0] == "-" else added
        body = line[1:]
        target.update(ID_RE.findall(body))
        target.update(CASE_TOKEN_RE.findall(body))
        if current_file in selected_files:
            match = re.match(r"\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", body)
            if match:
                target.add(f"{current_file}::{match.group(1)}")
    lost = sorted(deleted - added)
    return [f"removed or renamed stable test/case IDs: {lost}"] if lost else []


def check_product_fixture_names(root: Path, base: str, head: str = "HEAD") -> list[str]:
    """Detect newly introduced fixture names, declared case IDs, and test paths."""
    paths = changed_paths(root, base, head)
    tree_paths = git(root, "ls-tree", "-r", "--name-only", base).splitlines()
    candidate_paths = git(root, "ls-tree", "-r", "--name-only", head).splitlines()
    all_test_paths = set(tree_paths) | set(candidate_paths)
    test_paths = [p for p in all_test_paths if p.startswith(("tests/", "fixtures/"))]
    fixture_paths = [
        p
        for p in test_paths
        if p.startswith(("tests/", "fixtures/"))
        and (
            Path(p).suffix in {".bngl", ".xml"}
            or (
                Path(p).suffix in {".json", ".yaml", ".yml"}
                and ("manifest" in Path(p).name or "case" in Path(p).name)
            )
        )
    ]
    manifest_paths = [
        p
        for p in test_paths
        if p.startswith(("tests/", "fixtures/"))
        and Path(p).suffix in {".json", ".yaml", ".yml"}
        and ("manifest" in Path(p).name or "case" in Path(p).name)
    ]
    manifest_paths += [
        p
        for p in paths
        if p.startswith(("tests/", "fixtures/"))
        and Path(p).suffix in {".json", ".yaml", ".yml"}
    ]
    needles = {
        Path(p).stem
        for p in fixture_paths
        if Path(p).stem.lower() not in GENERIC_FIXTURE_NAMES and len(Path(p).stem) >= 6
    }
    needles.update(Path(p).as_posix() for p in fixture_paths)
    needles.update(Path(p).as_posix() for p in test_paths)
    for rel in set(manifest_paths):
        text = _base_text(root, base, rel)
        try:
            text += "\n" + _head_text(root, head, rel)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        needles.update(ID_RE.findall(text))
        needles.update(CASE_TOKEN_RE.findall(text))
    python_case_ids = subprocess.run(
        ("git", "grep", "-I", "-nE", r"case[_ -]?id|\bids\b", base, "--", "tests/"),
        cwd=root,
        text=True,
        capture_output=True,
    )
    for line in python_case_ids.stdout.splitlines():
        needles.update(ID_RE.findall(line))
        needles.update(CASE_TOKEN_RE.findall(line))
    for rel in paths:
        if rel.startswith(("tests/", "fixtures/")) and Path(rel).suffix in {
            ".bngl",
            ".xml",
            ".json",
            ".yaml",
            ".yml",
        }:
            try:
                text = _head_text(root, head, rel)
            except subprocess.CalledProcessError:
                continue
            needles.update(ID_RE.findall(text))
            needles.update(CASE_TOKEN_RE.findall(text))
    errors = []
    product_paths = [p for p in paths if p.startswith(PRODUCT_PREFIXES)]
    if not product_paths:
        return errors
    patch = git(root, "diff", "--unified=0", f"{base}...{head}", "--", *product_paths)
    current_file = ""
    additions: dict[str, list[str]] = {}
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and current_file:
            additions.setdefault(current_file, []).append(line[1:])
    for rel, lines in additions.items():
        text = "\n".join(lines)
        hits = sorted(needle for needle in needles if needle in text)
        if hits:
            errors.append(
                f"{rel}: newly added product text contains acceptance fixture identifiers/paths: {hits[:10]}"
            )
    return errors


def fresh_seed() -> int:
    """Return an unpredictable positive 31-bit seed accepted by native engines."""
    import secrets

    return secrets.randbelow((1 << 31) - 1) + 1


def write_seed_manifest(
    path: Path, *, seed: int, revision: str, case_ids: list[str], case_sha256: str
) -> None:
    if seed <= 0 or not revision or not case_ids:
        raise ValueError(
            "seed manifest requires a positive seed, revision, and stable case IDs"
        )
    payload = {
        "schema": 1,
        "revision": revision,
        "seed": seed,
        "case_ids": sorted(set(case_ids)),
        "case_sha256": case_sha256,
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")


def generate_seeded_case(seed: int) -> tuple[str, str]:
    """Small valid SSA source case whose parameters are generated from seed."""
    import random

    rng = random.Random(seed)
    rate = rng.uniform(0.02, 0.2)
    population = rng.randint(20, 200)
    case_id = f"generated:decay:{seed:016x}"
    source = f"""begin model
begin parameters
  k {rate:.12g}
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() {population}
end seed species
begin observables
  Molecules A_count A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
simulate({{method=>"ssa",t_end=>1,n_steps=>10,seed=>{seed}}})
"""
    return case_id, source


def verify_seed_manifest(path: Path, expected_revision: str) -> None:
    data = json.loads(path.read_text())
    if (
        data.get("schema") != 1
        or data.get("revision") != expected_revision
        or not isinstance(data.get("seed"), int)
        or data["seed"] <= 0
        or not data.get("case_ids")
        or not re.fullmatch(r"[a-f0-9]{64}", str(data.get("case_sha256", "")))
    ):
        raise ValueError(
            "seed manifest is missing a recorded fresh seed, revision, or case IDs"
        )
    case_path = path.with_suffix(".bngl")
    if (
        not case_path.is_file()
        or hashlib.sha256(case_path.read_bytes()).hexdigest() != data["case_sha256"]
    ):
        raise ValueError(
            "seeded source case is missing or its digest differs from the replay manifest"
        )


def run_product_mutations(root: Path, output: Path, *, timeout: int = 300) -> dict:
    """Run curated non-equivalent product mutations in a disposable worktree.

    Every mutant changes maintained production Python code and is judged by an
    unchanged, focused independent contract test. A timeout or setup failure is
    infrastructure_error, never a kill.
    """
    import tempfile

    revision = git(root, "rev-parse", "HEAD").strip()
    import importlib.util

    native_spec = importlib.util.find_spec("bionetgen._bionetgen_cpp")
    native_origin = (
        Path(native_spec.origin) if native_spec and native_spec.origin else None
    )
    with tempfile.TemporaryDirectory(prefix="bng3-product-mutants-") as tmp:
        checkout = Path(tmp) / "checkout"
        subprocess.check_call(
            ("git", "clone", "--shared", "--no-checkout", str(root), str(checkout)),
            cwd=root,
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ("git", "-C", str(checkout), "checkout", "--detach", revision),
            stdout=subprocess.DEVNULL,
        )
        build_dir = native_origin.parent.parent if native_origin is not None else None
        if build_dir is not None and (build_dir / "cpp").is_dir():
            (checkout / "build").symlink_to(build_dir, target_is_directory=True)
        rows = []
        source = checkout / "python/bionetgen/model.py"
        original = source.read_text()
        old = "self._model.set_parameter(name, value)"
        new = "self._model.set_parameter(name, value * 1.01)"
        mutant = {
            "id": "python.set-parameter-scale",
            "classification": "non_equivalent",
            "file": "python/bionetgen/model.py",
            "test": "tests/python/test_cpp_backend.py -k parameter_value_is_read_only_and_refreshes_dependents",
        }
        if original.count(old) != 1:
            rows.append(
                {
                    **mutant,
                    "status": "infrastructure_error",
                    "detail": f"expected exactly one mutation site, found {original.count(old)}",
                }
            )
        else:
            mutated = original.replace(old, new, 1)
            env = dict(os.environ)
            if native_origin is None:
                rows.append(
                    {
                        **mutant,
                        "status": "infrastructure_error",
                        "detail": "compiled BNG3 extension is unavailable",
                    }
                )
            else:
                extension = checkout / "python/bionetgen" / native_origin.name
                extension.symlink_to(native_origin)
                env["PYTHONPATH"] = os.pathsep.join(
                    (
                        str(checkout / "python"),
                        str(checkout / "tests"),
                        env.get("PYTHONPATH", ""),
                    )
                )
                env["BNG3_PYTHON_TEST_MODE"] = "source"
                command = (
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/python/test_cpp_backend.py",
                    "-k",
                    "parameter_value_is_read_only_and_refreshes_dependents",
                )
                try:
                    source.write_text(original)
                    baseline_run = subprocess.run(
                        command,
                        cwd=checkout,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    if (
                        baseline_run.returncode != 0
                        or " passed" not in baseline_run.stdout
                    ):
                        rows.append(
                            {
                                **mutant,
                                "status": "infrastructure_error",
                                "detail": "unchanged contract suite did not pass/collect",
                                "output": (baseline_run.stdout + baseline_run.stderr)[
                                    -4000:
                                ],
                            }
                        )
                    else:
                        source.write_text(mutated)
                        mutant_run = subprocess.run(
                            command,
                            cwd=checkout,
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                        )
                        output_text = mutant_run.stdout + mutant_run.stderr
                        if mutant_run.returncode == 0:
                            status = "survived"
                        elif (
                            " failed" in mutant_run.stdout
                            and " error" not in mutant_run.stdout
                            and "ERROR collecting" not in output_text
                        ):
                            status = "killed"
                        else:
                            status = "infrastructure_error"
                        rows.append(
                            {
                                **mutant,
                                "status": status,
                                "exit_code": mutant_run.returncode,
                                "output": output_text[-4000:],
                            }
                        )
                except subprocess.TimeoutExpired as exc:
                    rows.append(
                        {
                            **mutant,
                            "status": "infrastructure_error",
                            "detail": f"timeout after {exc.timeout}s",
                        }
                    )
    statuses = ("killed", "survived", "invalid", "equivalent", "infrastructure_error")
    result = {
        "schema": 1,
        "revision": revision,
        "mutants": rows,
        "denominator": sum(r["classification"] == "non_equivalent" for r in rows),
        "caught": sum(
            r["classification"] == "non_equivalent" and r["status"] == "killed"
            for r in rows
        ),
        "status_counts": {
            status: sum(r["status"] == status for r in rows) for status in statuses
        },
        "classification_counts": {
            kind: sum(r["classification"] == kind for r in rows)
            for kind in ("non_equivalent", "equivalent")
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def verify_mutation_ratchet(
    report_path: Path, baseline_path: Path, expected_revision: str | None = None
) -> list[str]:
    """Compare a scheduled report with its independently recorded baseline."""
    report = json.loads(report_path.read_text())
    baseline = json.loads(baseline_path.read_text())
    if (
        report.get("schema") != 1
        or not isinstance(report.get("revision"), str)
        or baseline.get("schema") != 1
    ):
        return ["mutation report or baseline schema/revision is invalid"]
    if expected_revision and report.get("revision") != expected_revision:
        return [
            f"scheduled mutation report revision mismatch: expected {expected_revision}, observed {report.get('revision')}"
        ]
    if baseline.get("status") != "verified":
        return [
            "mutation baseline is unavailable; release qualification remains blocked until an exact scheduled artifact is reviewed and recorded"
        ]
    expected_digest = baseline.get("artifact_sha256")
    if not isinstance(expected_digest, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_digest
    ):
        return ["recorded mutation baseline lacks a valid source artifact digest"]
    expected_rows = baseline.get("mutants", [])
    if not isinstance(expected_rows, list) or any(
        not isinstance(row, dict) for row in expected_rows
    ):
        return ["mutation baseline mutant rows are invalid"]
    expected_ids = [row.get("id") for row in expected_rows]
    if any(not isinstance(value, str) or not value for value in expected_ids) or len(
        set(expected_ids)
    ) != len(expected_ids):
        return ["mutation baseline IDs are missing or duplicated"]
    rows = report.get("mutants")
    if (
        not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, dict) for row in rows)
    ):
        return ["mutation report has no valid mutant rows"]
    observed_ids = [row.get("id") for row in rows]
    if any(not isinstance(value, str) or not value for value in observed_ids) or len(
        set(observed_ids)
    ) != len(observed_ids):
        return ["mutation report IDs are missing or duplicated"]
    if set(observed_ids) != set(expected_ids):
        return [
            f"curated mutant set differs from baseline: expected {sorted(expected_ids)}, observed {sorted(observed_ids)}"
        ]
    expected_classes = {row["id"]: row.get("classification") for row in expected_rows}
    valid_classes = {"non_equivalent", "equivalent"}
    valid_statuses = {
        "killed",
        "survived",
        "invalid",
        "equivalent",
        "infrastructure_error",
    }
    if any(
        row.get("classification") not in valid_classes
        or expected_classes[row["id"]] != row.get("classification")
        for row in rows
    ):
        return ["mutation report classification differs from the reviewed baseline"]
    if any(row.get("status") not in valid_statuses for row in rows):
        return ["mutation report contains an unknown status"]
    denominator = sum(row["classification"] == "non_equivalent" for row in rows)
    caught = sum(
        row["classification"] == "non_equivalent" and row["status"] == "killed"
        for row in rows
    )
    if report.get("denominator") != denominator or report.get("caught") != caught:
        return ["mutation report summary counts do not match per-mutant rows"]
    status_counts = {
        status: sum(row["status"] == status for row in rows)
        for status in (
            "killed",
            "survived",
            "invalid",
            "equivalent",
            "infrastructure_error",
        )
    }
    class_counts = {
        kind: sum(row["classification"] == kind for row in rows)
        for kind in valid_classes
    }
    if (
        report.get("status_counts") != status_counts
        or report.get("classification_counts") != class_counts
    ):
        return [
            "mutation report status/classification totals do not match per-mutant rows"
        ]
    baseline_denominator = baseline.get("denominator", 0)
    baseline_caught = baseline.get("caught", 0)
    if (
        not isinstance(baseline_denominator, int)
        or baseline_denominator
        != sum(row.get("classification") == "non_equivalent" for row in expected_rows)
        or not isinstance(baseline_caught, int)
        or not 0 <= baseline_caught <= baseline_denominator
    ):
        return [
            "recorded mutation baseline counts do not match its reviewed mutant rows"
        ]
    if (
        not denominator
        or not baseline_denominator
        or caught * baseline_denominator < baseline_caught * denominator
    ):
        return [
            f"mutation detection score dropped: {caught}/{denominator} versus recorded {baseline_caught}/{baseline_denominator}"
        ]
    if any(
        row.get("status") in {"survived", "invalid", "infrastructure_error"}
        for row in report.get("mutants", [])
    ):
        return [
            "scheduled mutation report includes a survivor, invalid mutant, or infrastructure error"
        ]
    return []


def _head_text(root: Path, head: str, path: str) -> str:
    raw = subprocess.check_output(
        ("git", "show", f"{head}:{path}"), cwd=root, stderr=subprocess.STDOUT
    )
    return raw.decode("utf-8", errors="replace")


def check_ci_wiring(root: Path, head: str = "HEAD") -> list[str]:
    """Parse candidate workflow YAML and require enabled, executable policy jobs."""
    import yaml

    def workflow(path):
        return yaml.load(_head_text(root, head, path), Loader=yaml.BaseLoader)

    def step(job, name):
        steps = job.get("steps", []) if isinstance(job, dict) else []
        return next((s for s in steps if s.get("name") == name), None)

    def executable(run):
        return "\n".join(line.split("#", 1)[0] for line in run.splitlines())

    def disabled(value):
        return (
            bool(value.get("if", ""))
            or str(value.get("continue-on-error", "false")).lower() == "true"
        )

    def command_starts(run, prefix):
        return any(
            line.strip().startswith(prefix) for line in executable(run).splitlines()
        )

    errors = []
    try:
        ci = workflow(".github/workflows/ci.yml")
        weekly = workflow(".github/workflows/weekly.yml")
        trusted = workflow(".github/workflows/release-policy.yml")
        release = workflow(".github/workflows/release.yml")
    except (subprocess.CalledProcessError, TypeError, ValueError) as exc:
        return [f"required workflow missing or invalid YAML: {exc}"]
    if not all(isinstance(doc, dict) for doc in (ci, weekly, trusted, release)):
        return ["required workflow is empty or does not contain a YAML mapping"]
    if not isinstance(ci.get("on", {}), dict) or "pull_request" not in ci.get("on", {}):
        errors.append(
            "ci.yml: protected/seeded release checks are not triggered by pull requests"
        )
    if not isinstance(weekly.get("on", {}), dict) or "schedule" not in weekly.get(
        "on", {}
    ):
        errors.append("weekly.yml: mutation ratchet is not scheduled")

    lint = ci.get("jobs", {}).get("lint", {})
    policy_step = step(lint, "Run anti-gaming checks from the PR base revision")
    policy_run = executable(policy_step.get("run", "")) if policy_step else ""
    if (
        disabled(lint)
        or not policy_step
        or not command_starts(
            policy_run, 'python "$RUNNER_TEMP/base-policy/run_antigaming.py"'
        )
        or "BASE_REVISION" not in policy_run
    ):
        errors.append(
            "ci.yml: base-revision protected-expectations and fixture checks are not executable in lint"
        )
    elif disabled(policy_step):
        errors.append("ci.yml: anti-gaming checks may be disabled or ignored")

    integration = ci.get("jobs", {}).get("python-integration", {})
    seed_step = step(integration, "Generate and execute a fresh seeded source case")
    seed_run = executable(seed_step.get("run", "")) if seed_step else ""
    if (
        disabled(integration)
        or not seed_step
        or not command_starts(
            seed_run, 'python "$RUNNER_TEMP/base-policy/run_antigaming.py"'
        )
        or "release-independent-seeds" not in seed_run
        or "seed-manifest" not in seed_run
    ):
        errors.append(
            "ci.yml: seeded generated source case is not executed and recorded"
        )
    elif disabled(seed_step):
        errors.append("ci.yml: seeded source execution may be disabled or ignored")

    mutation_job = weekly.get("jobs", {}).get("release-mutation-ratchet", {})
    mutation_step = step(mutation_job, "Run isolated curated product mutants")
    mutation_run = executable(mutation_step.get("run", "")) if mutation_step else ""
    if (
        disabled(mutation_job)
        or not mutation_step
        or not command_starts(
            mutation_run, "python tests/validation/policy/run_antigaming.py"
        )
        or "release-scheduled-mutation-ratchet" not in mutation_run
        or "mutation-output" not in mutation_run
    ):
        errors.append("weekly.yml: scheduled product mutation campaign is missing")
    elif disabled(mutation_step):
        errors.append(
            "weekly.yml: scheduled mutation campaign may be disabled or ignored"
        )

    trigger = trusted.get("on", {})
    if not isinstance(trigger, dict) or "pull_request_target" not in trigger:
        errors.append(
            "release-policy.yml: trusted pull_request_target guard is missing"
        )
    if trusted.get("permissions", {}) != {"contents": "read", "pull-requests": "read"}:
        errors.append(
            "release-policy.yml: trusted guard permissions must remain read-only"
        )
    fetch = step(
        trusted.get("jobs", {}).get("anti-gaming", {}), "Fetch PR head as data"
    )
    guard = step(
        trusted.get("jobs", {}).get("anti-gaming", {}),
        "Run trusted base policy against candidate tree",
    )
    checkout = step(
        trusted.get("jobs", {}).get("anti-gaming", {}),
        "Check out trusted base revision",
    )
    trusted_job = trusted.get("jobs", {}).get("anti-gaming", {})
    guard_run = executable(guard.get("run", "")) if guard else ""
    fetch_run = executable(fetch.get("run", "")) if fetch else ""
    if (
        not fetch
        or not guard
        or not command_starts(fetch_run, "git fetch --no-tags origin")
        or not command_starts(
            fetch_run, "fetched=$(git rev-parse refs/remotes/pull/$PR_NUMBER/head)"
        )
        or not command_starts(fetch_run, '[[ "$fetched" == "$PR_HEAD" ]]')
        or not command_starts(
            guard_run, "python tests/validation/policy/run_antigaming.py"
        )
        or '--head "$HEAD_REVISION"' not in guard_run
        or '--base "$BASE_REVISION"' not in guard_run
    ):
        errors.append(
            "release-policy.yml: PR head must be inspected as data by the base policy"
        )
    if (
        not checkout
        or checkout.get("with", {}).get("ref")
        != "${{ github.event.pull_request.base.sha }}"
        or checkout.get("with", {}).get("persist-credentials") != "false"
    ):
        errors.append(
            "release-policy.yml: guard must check out the trusted base without persisted credentials"
        )
    if disabled(trusted_job) or any(disabled(s) for s in (fetch, guard, checkout) if s):
        errors.append(
            "release-policy.yml: trusted policy steps/job may be disabled or ignored"
        )
    if trusted_job.get("permissions", {}) or trusted.get("permissions", {}) != {
        "contents": "read",
        "pull-requests": "read",
    }:
        errors.append(
            "release-policy.yml: trusted policy must retain only top-level read permissions"
        )

    release_steps = release.get("jobs", {}).get("qualify", {}).get("steps", [])
    qualify_job = release.get("jobs", {}).get("qualify", {})
    release_gate = next(
        (
            s
            for s in release_steps
            if s.get("name")
            == "Require the exact-main weekly mutation artifact and ratchet"
        ),
        None,
    )
    release_run = executable(release_gate.get("run", "")) if release_gate else ""
    if (
        not release_gate
        or not command_starts(
            release_run, "python tests/validation/policy/run_antigaming.py"
        )
        or "release-scheduled-mutation-ratchet" not in release_run
    ):
        errors.append(
            "release.yml: release qualification is not gated on the scheduled mutation ratchet"
        )
    elif disabled(release_gate) or disabled(qualify_job):
        errors.append(
            "release.yml: mutation ratchet release gate may be disabled or ignored"
        )
    if release.get("jobs", {}).get("build-binaries", {}).get(
        "needs"
    ) != "qualify" and "qualify" not in release.get("jobs", {}).get(
        "build-binaries", {}
    ).get(
        "needs", []
    ):
        errors.append("release.yml: release artifacts do not depend on qualification")
    return errors


def run_pr_checks(root: Path, base: str, head: str = "HEAD") -> dict[str, list[str]]:
    if not base:
        raise ValueError(
            "base revision is required; policy checks may not silently skip"
        )
    # Verify that the chosen base resolves before running any check.
    git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    git(root, "rev-parse", "--verify", f"{head}^{{commit}}")
    return {
        "release-protected-expectations": check_protected_changes(root, base, head)
        + check_case_ids(root, base, head)
        + check_ci_wiring(root, head),
        "release-no-product-fixture-names": check_product_fixture_names(
            root, base, head
        ),
    }
