"""Independent negative fixtures for the anti-gaming policy checker.

Run against a candidate checker with ``ANTIGAMING_POLICY_DIR`` pointing to its
policy directory. The default is the directory containing this file so CI can
run the same checks after the policy and acceptance packages merge.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BOOTSTRAP_FILES = {
    ".github/workflows/ci.yml": "name: CI\n",
    ".github/workflows/release-policy.yml": "name: Release policy\n",
    ".github/workflows/release.yml": "name: Release\n",
    ".github/workflows/weekly.yml": "name: Weekly\n",
    "tests/validation/policy/README.md": "# Anti-gaming policy\n",
    "tests/validation/policy/antigaming.py": "# checker\n",
    "tests/validation/policy/mutation-baseline.json": "{}\n",
    "tests/validation/policy/run_antigaming.py": "# runner\n",
}


def _policy_dir() -> Path:
    return Path(
        os.environ.get("ANTIGAMING_POLICY_DIR", Path(__file__).parent)
    ).resolve()


def _load_policy():
    spec = importlib.util.spec_from_file_location(
        "candidate_antigaming", _policy_dir() / "antigaming.py"
    )
    assert spec and spec.loader, f"checker not found in {_policy_dir()}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=root, text=True, stderr=subprocess.STDOUT
    )


def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "policy-fixture@example.invalid")
    _git(root, "config", "user.name", "Policy Fixture")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root, _git(root, "rev-parse", "HEAD").strip()


def _change(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", f"change {rel}")


def _mutation_report(rows: list[dict], revision: str = "candidate") -> dict:
    statuses = ("killed", "survived", "invalid", "equivalent", "infrastructure_error")
    classes = ("non_equivalent", "equivalent")
    return {
        "schema": 1,
        "revision": revision,
        "mutants": rows,
        "denominator": sum(row["classification"] == "non_equivalent" for row in rows),
        "caught": sum(
            row["classification"] == "non_equivalent" and row["status"] == "killed"
            for row in rows
        ),
        "status_counts": {
            status: sum(row["status"] == status for row in rows) for status in statuses
        },
        "classification_counts": {
            kind: sum(row["classification"] == kind for row in rows) for kind in classes
        },
    }


def _mutation_baseline(rows: list[dict]) -> dict:
    return {
        "schema": 1,
        "status": "verified",
        "revision": "scheduled-baseline",
        "artifact_sha256": "a" * 64,
        "mutants": [
            {"id": row["id"], "classification": row["classification"]} for row in rows
        ],
        "denominator": sum(row["classification"] == "non_equivalent" for row in rows),
        "caught": sum(
            row["classification"] == "non_equivalent" and row["status"] == "killed"
            for row in rows
        ),
    }


@pytest.mark.parametrize(
    ("files", "protected_path", "protected_content"),
    [
        (
            {"tests/validation/golden/expected.json": '{"value": 1}\n'},
            "tests/validation/golden/expected.json",
            '{"value": 2}\n',
        ),
        (
            {"provenance/golden/expected.json": '{"value": 1}\n'},
            "provenance/golden/expected.json",
            '{"value": 2}\n',
        ),
        (
            {
                "provenance/sbml-campaign/expectations.json": '{"value": 1}\n',
            },
            "provenance/sbml-campaign/expectations.json",
            '{"value": 2}\n',
        ),
        (
            {"tests/test_tolerance.py": "assert_close(actual, expected, atol=1e-6)\n"},
            "tests/test_tolerance.py",
            "assert_close(actual, expected, atol=1e-5)\n",
        ),
        (
            {"tests/validation/tolerance.json": '{"rtol": 1e-6}\n'},
            "tests/validation/tolerance.json",
            '{"rtol": 1e-3}\n',
        ),
        (
            {"tests/test_skip.py": "def test_case():\n    assert True\n"},
            "tests/test_skip.py",
            "import pytest\n\n@pytest.mark.skip(reason='new exclusion')\ndef test_case():\n    assert True\n",
        ),
        (
            {
                "tests/validation/reference_exclusions.json": (
                    '{"profiles": {"default": ["case_a"]}}\n'
                )
            },
            "tests/validation/reference_exclusions.json",
            '{"profiles": {"default": ["case_a", "case_b"]}}\n',
        ),
        (
            {"tests/validation/exclusions.yaml": "exclusions:\n  - case_a\n"},
            "tests/validation/exclusions.yaml",
            "exclusions:\n  - case_a\n  - case_b\n",
        ),
        (
            {"tests/test_contract.py": "def test_contract():\n    assert True\n"},
            "tests/test_contract.py",
            "import pytest\n\n@pytest.mark.xfail\ndef test_contract():\n    assert True\n",
        ),
    ],
)
def test_product_change_mixed_with_expectations_skips_or_exclusions_is_rejected(
    tmp_path, files, protected_path, protected_content
):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {"python/engine.py": "VALUE = 1\n", **files},
    )
    _change(root, "python/engine.py", "VALUE = 2\n")
    path = root / protected_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(protected_content)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "mix product and acceptance data")

    errors = checker.check_protected_changes(root, base)

    assert errors


def test_product_only_and_expectation_only_changes_are_not_mixed(tmp_path):
    checker = _load_policy()
    root, base = _repo(tmp_path, {"python/engine.py": "VALUE = 1\n"})
    _change(root, "python/engine.py", "VALUE = 2\n")
    assert checker.check_protected_changes(root, base) == []

    root2, base2 = _repo(tmp_path / "second", {"tests/data/expected.json": "{}\n"})
    _change(root2, "tests/data/expected.json", '{"expected": 2}\n')
    assert checker.check_protected_changes(root2, base2) == []


def test_product_solver_tolerance_change_is_not_protected(tmp_path):
    checker = _load_policy()
    root, base = _repo(tmp_path, {"cpp/solver.cpp": "const double rtol = 1e-6;\n"})
    _change(root, "cpp/solver.cpp", "const double rtol = 1e-8;\n")

    assert checker.check_protected_changes(root, base) == []


def test_product_skip_marker_change_is_not_protected(tmp_path):
    checker = _load_policy()
    root, base = _repo(tmp_path, {"python/runtime.py": "def run():\n    return 1\n"})
    _change(
        root,
        "python/runtime.py",
        "import pytest\n\n@pytest.mark.skip\ndef run():\n    return 1\n",
    )

    assert checker.check_protected_changes(root, base) == []


def test_changed_tolerance_in_existing_test_remains_protected(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "python/engine.py": "VALUE = 1\n",
            "tests/test_tolerance.py": "assert_close(actual, expected, rtol=1e-6)\n",
        },
    )
    _change(root, "python/engine.py", "VALUE = 2\n")
    _change(
        root,
        "tests/test_tolerance.py",
        "assert_close(actual, expected, rtol=1e-5)\n",
    )

    errors = checker.check_protected_changes(root, base)

    assert errors and "tests/test_tolerance.py" in errors[0]


def test_bootstrap_succeeds_from_any_base_revision_without_checker(tmp_path):
    checker = _load_policy()
    base_revisions = []
    for marker in ("first-base", "second-base"):
        root, base = _repo(
            tmp_path / marker,
            {
                "README.md": f"{marker}\n",
                ".github/workflows/ci.yml": "name: Old CI\n",
            },
        )
        for rel, content in BOOTSTRAP_FILES.items():
            _change(root, rel, content)

        assert checker.check_bootstrap_candidate(root, base) == []
        base_revisions.append(base)

    assert len(set(base_revisions)) == 2


def test_bootstrap_rejects_extra_changed_paths(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "README.md": "base\n",
            ".github/workflows/ci.yml": "name: Old CI\n",
        },
    )
    for rel, content in BOOTSTRAP_FILES.items():
        _change(root, rel, content)
    _change(root, "cpp/solver.cpp", "const double rtol = 1e-8;\n")

    errors = checker.check_bootstrap_candidate(root, base)

    assert errors and "cpp/solver.cpp" in errors[0]


def test_product_fix_with_new_regression_test_is_allowed(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "python/engine.py": "def solve():\n    return 1\n",
            "tests/test_engine.py": "def test_existing_behavior():\n    assert True\n",
        },
    )
    _change(root, "python/engine.py", "def solve():\n    return 2\n")
    _change(
        root,
        "tests/test_engine.py",
        "def test_existing_behavior():\n    assert True\n\ndef test_regression_case():\n    assert True\n",
    )

    assert checker.check_protected_changes(root, base) == []


def test_product_and_test_that_reads_product_source_are_not_misclassified(
    tmp_path,
):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "python/engine.py": "VALUE = 1\n",
            "tests/test_source_contract.py": (
                "from pathlib import Path\n"
                "SOURCE = Path('python/engine.py').read_text()\n"
                "def test_source_contract():\n    assert 'VALUE' in SOURCE\n"
            ),
        },
    )
    _change(root, "python/engine.py", "VALUE = 2\n")
    _change(
        root,
        "tests/test_source_contract.py",
        "from pathlib import Path\n"
        "SOURCE = Path('python/engine.py').read_text()\n"
        "def test_source_contract():\n    assert 'VALUE = 2' in SOURCE\n",
    )

    assert checker.check_protected_changes(root, base) == []


def test_product_change_with_deleted_unrelated_test_helper_is_allowed(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "python/engine.py": "VALUE = 1\n",
            "tests/test_helpers.py": "def helper():\n    return 'plain helper'\n",
        },
    )
    _change(root, "python/engine.py", "VALUE = 2\n")
    (root / "tests/test_helpers.py").unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "remove unused test helper")

    assert checker.check_protected_changes(root, base) == []


def test_provenance_lock_and_validator_change_are_allowed_together(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "provenance/upstreams.lock.yml": "schema: 1\nrevision: old\n",
            "scripts/validate_provenance.py": "def validate():\n    return True\n",
        },
    )
    _change(root, "provenance/upstreams.lock.yml", "schema: 1\nrevision: new\n")
    _change(
        root,
        "scripts/validate_provenance.py",
        "def validate():\n    return True\n\n# accepts the updated lock\n",
    )

    assert checker.check_protected_changes(root, base) == []


def test_golden_regeneration_script_and_golden_data_are_allowed_together(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            "scripts/regen_golden.py": "def regenerate():\n    return None\n",
            "tests/validation/golden/expected.json": '{"value": 1}\n',
        },
    )
    _change(
        root,
        "scripts/regen_golden.py",
        "def regenerate():\n    return {'value': 2}\n",
    )
    _change(root, "tests/validation/golden/expected.json", '{"value": 2}\n')

    assert checker.check_protected_changes(root, base) == []


@pytest.mark.parametrize(
    "script", ["scripts/regen_golden.py", "scripts/validate_golden_manifest.py"]
)
def test_golden_named_harness_script_alone_is_allowed(tmp_path, script):
    checker = _load_policy()
    root, base = _repo(tmp_path, {script: "def run():\n    return True\n"})
    _change(root, script, "def run():\n    return False\n")

    assert checker.check_protected_changes(root, base) == []


@pytest.mark.parametrize(
    ("path", "old", "new", "plan"),
    [
        (
            "tests/cases.json",
            '{"cases": [{"case_id": "case_alpha"}]}\n',
            '{"cases": [{"case_id": "case_beta"}]}\n',
            None,
        ),
        (
            "tests/cases.yaml",
            "- case_id: case_alpha\n",
            "- case_id: case_beta\n",
            None,
        ),
        (
            "tests/test_cases.py",
            'case_id = "case_alpha"\n',
            'case_id = "case_beta"\n',
            None,
        ),
        (
            "tests/test_cases.py",
            "def test_case_alpha():\n    assert True\n",
            "def test_case_beta():\n    assert True\n",
            '{"tests": ["tests/test_cases.py::test_case_alpha"]}\n',
        ),
    ],
)
def test_removed_or_renamed_case_id_in_json_yaml_or_python_is_rejected(
    tmp_path, path, old, new, plan
):
    checker = _load_policy()
    files = {path: old}
    if plan:
        files["provenance/validation-plan.json"] = plan
    root, base = _repo(tmp_path, files)
    _change(root, path, new)

    errors = checker.check_case_ids(root, base)

    assert errors and "case_alpha" in errors[0]


@pytest.mark.parametrize(
    ("fixture_rel", "fixture_content", "product_reference", "needle"),
    [
        (
            "tests/fixtures/decay_fixture.bngl",
            "# no declared ID\n",
            "tests/fixtures/decay_fixture.bngl",
            "decay_fixture",
        ),
        (
            "tests/cases.json",
            '{"case_id": "release_case_decay_42"}\n',
            "release_case_decay_42",
            "release_case_decay_42",
        ),
        (
            "tests/test_decay_contract.py",
            "case_id = 'contract_case_decay_42'\n",
            "tests/test_decay_contract.py",
            "tests/test_decay_contract.py",
        ),
    ],
)
def test_fixture_names_declared_ids_and_test_paths_are_independently_rejected(
    tmp_path, fixture_rel, fixture_content, product_reference, needle
):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            fixture_rel: fixture_content,
            "python/runtime.py": "VALUE = 1\n",
        },
    )
    _change(root, "python/runtime.py", f"# {product_reference}\nVALUE = 1\n")

    errors = checker.check_product_fixture_names(root, base)

    assert errors and "python/runtime.py" in errors[0]
    assert needle in errors[0]


def test_comment_only_workflow_policy_text_is_not_accepted_as_wiring(tmp_path):
    checker = _load_policy()
    root, base = _repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": "# Run anti-gaming checks release-independent-seeds\n",
            ".github/workflows/weekly.yml": "# release-scheduled-mutation-ratchet\n",
            ".github/workflows/release-policy.yml": "# pull_request_target --base --head\n",
            ".github/workflows/release.yml": "# release-scheduled-mutation-ratchet\n",
        },
    )

    errors = checker.check_ci_wiring(root, "HEAD")

    assert errors


def test_disabled_workflow_policy_step_is_rejected(tmp_path):
    checker = _load_policy()
    workflows = {
        ".github/workflows/ci.yml": """on:
  pull_request: {}
jobs:
  lint:
    steps:
      - name: Run anti-gaming checks from the PR base revision
        run: python "$RUNNER_TEMP/base-policy/run_antigaming.py" --base "$BASE_REVISION" --head "$HEAD_REVISION" --check release-protected-expectations
  python-integration:
    steps:
      - name: Generate and execute a fresh seeded source case
        run: python "$RUNNER_TEMP/base-policy/run_antigaming.py" --check release-independent-seeds --seed-manifest seed.json
""",
        ".github/workflows/weekly.yml": """on:
  schedule:
    - cron: '0 0 * * *'
jobs:
  release-mutation-ratchet:
    steps:
      - name: Run isolated curated product mutants
        run: python tests/validation/policy/run_antigaming.py --check release-scheduled-mutation-ratchet --mutation-output report.json
""",
        ".github/workflows/release-policy.yml": """on:
  pull_request_target: {}
permissions:
  contents: read
  pull-requests: read
jobs:
  anti-gaming:
    steps:
      - name: Fetch PR head as data
        run: |
          git fetch --no-tags origin refs/pull/$PR_NUMBER/head:refs/remotes/pull/$PR_NUMBER/head
          fetched=$(git rev-parse refs/remotes/pull/$PR_NUMBER/head)
          [[ "$fetched" == "$PR_HEAD" ]]
      - name: Run trusted base policy against candidate tree
        run: python tests/validation/policy/run_antigaming.py --base "$BASE_REVISION" --head "$HEAD_REVISION"
      - name: Check out trusted base revision
        uses: actions/checkout@v4
        with:
          ref: "${{ github.event.pull_request.base.sha }}"
          persist-credentials: "false"
""",
        ".github/workflows/release.yml": """jobs:
  qualify:
    steps:
      - name: Require the exact-main weekly mutation artifact and ratchet
        run: python tests/validation/policy/run_antigaming.py --check release-scheduled-mutation-ratchet
  build-binaries:
    needs: qualify
""",
    }
    root, _ = _repo(tmp_path, workflows)

    # Positive control: this complete CI wiring passes before a single policy
    # step is disabled.
    assert checker.check_ci_wiring(root, "HEAD") == []

    ci = root / ".github/workflows/ci.yml"
    content = ci.read_text().replace(
        "      - name: Run anti-gaming checks from the PR base revision\n",
        "      - name: Run anti-gaming checks from the PR base revision\n        if: false\n",
    )
    _change(root, ".github/workflows/ci.yml", content)

    errors = checker.check_ci_wiring(root, "HEAD")

    assert errors == ["ci.yml: anti-gaming checks may be disabled or ignored"]


def test_seeded_source_manifest_records_and_replays_the_executed_source(
    tmp_path, monkeypatch, capsys
):
    policy_dir = _policy_dir()
    runner = policy_dir / "run_antigaming.py"
    root, _ = _repo(tmp_path, {"README.md": "seed policy fixture\n"})
    manifest = tmp_path / "seed" / "manifest.json"
    executed: dict[str, str | int] = {}
    fake_extension = tmp_path / "fake-extension.so"
    fake_extension.write_bytes(b"test sentinel")
    fake_cli = tmp_path / "bng_cpp"
    fake_cli.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "source = pathlib.Path(sys.argv[1])\n"
        "pathlib.Path(os.environ['FAKE_BNG_LOG']).write_text(source.read_text())\n"
        "source.with_suffix('.gdat').write_text('time\\n0\\n')\n"
    )
    fake_cli.chmod(0o755)
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(fake_extension)),
    )
    monkeypatch.syspath_prepend(str(policy_dir))
    monkeypatch.setenv("ANTIGAMING_BOOTSTRAP", "1")
    monkeypatch.setenv("BNG_CPP", str(fake_cli))
    monkeypatch.setenv("FAKE_BNG_LOG", str(tmp_path / "executed.bngl"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(runner),
            "--root",
            str(root),
            "--base",
            _git(root, "rev-parse", "HEAD").strip(),
            "--check",
            "release-independent-seeds",
            "--seed-manifest",
            str(manifest),
        ],
    )
    spec = importlib.util.spec_from_file_location("candidate_antigaming_runner", runner)
    assert spec and spec.loader
    runner_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner_module)
    assert runner_module.main() == 0, capsys.readouterr().out

    source = (tmp_path / "executed.bngl").read_text()
    data = json.loads(manifest.read_text())
    seed = data["seed"]
    assert isinstance(seed, int) and seed > 0
    assert data["case_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert data["case_ids"] == [f"generated:decay:{seed:016x}"]
    assert "begin reaction rules" in source and "A() -> 0 k" in source
    replay_id, replay_source = _load_policy().generate_seeded_case(seed)
    assert replay_id == data["case_ids"][0]
    assert replay_source == source


def _mutation_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    model = "class BioNetGenModel:\n    def set_parameter(self, name, value):\n        self._model.set_parameter(name, value)\n"
    root, base = _repo(
        tmp_path,
        {
            "python/bionetgen/model.py": model,
            "tests/python/test_cpp_backend.py": "# contract\n",
        },
    )
    extension = tmp_path / "fake_extension.so"
    extension.write_bytes(b"not loaded by the fixture")
    return root, base, extension


def _run_mutation_campaign(
    monkeypatch, checker, root, extension, mutant_run, observed_sources
):
    original_run = subprocess.run
    pytest_calls = 0

    def fake_find_spec(name):
        return (
            SimpleNamespace(origin=str(extension))
            if name == "bionetgen._bionetgen_cpp"
            else None
        )

    def fake_run(command, *args, **kwargs):
        nonlocal pytest_calls
        if len(command) > 2 and command[1:3] == ("-m", "pytest"):
            pytest_calls += 1
            observed_sources.append(
                (Path(kwargs["cwd"]) / "python/bionetgen/model.py").read_text()
            )
            if pytest_calls == 1:
                return subprocess.CompletedProcess(
                    command, 0, stdout="1 passed in 0.01s\n", stderr=""
                )
            return mutant_run(command, pytest_calls)
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(checker.subprocess, "run", fake_run)
    return pytest_calls


def test_mutation_timeout_is_infrastructure_error_not_a_kill(tmp_path, monkeypatch):
    checker = _load_policy()
    root, _, extension = _mutation_repo(tmp_path)

    def timeout(command, _):
        raise subprocess.TimeoutExpired(command, 1)

    observed_sources = []
    _run_mutation_campaign(
        monkeypatch, checker, root, extension, timeout, observed_sources
    )
    report = checker.run_product_mutations(root, tmp_path / "report.json", timeout=1)

    assert report["denominator"] == 1
    assert report["caught"] == 0
    assert report["status_counts"]["infrastructure_error"] == 1
    assert report["mutants"][0]["status"] == "infrastructure_error"
    assert observed_sources == [
        "class BioNetGenModel:\n    def set_parameter(self, name, value):\n        self._model.set_parameter(name, value)\n",
        "class BioNetGenModel:\n    def set_parameter(self, name, value):\n        self._model.set_parameter(name, value * 1.01)\n",
    ]


def test_missing_or_uncollected_mutation_contract_is_infrastructure_error(
    tmp_path, monkeypatch
):
    checker = _load_policy()
    root, _, extension = _mutation_repo(tmp_path)

    def no_tests(command, _):
        return subprocess.CompletedProcess(
            command, 5, stdout="no tests ran\n", stderr=""
        )

    observed_sources = []
    _run_mutation_campaign(
        monkeypatch, checker, root, extension, no_tests, observed_sources
    )
    report = checker.run_product_mutations(root, tmp_path / "report.json", timeout=1)

    assert report["denominator"] == 1
    assert report["caught"] == 0
    assert report["mutants"][0]["status"] == "infrastructure_error"


def test_mutation_count_drop_fails_scheduled_ratchet(tmp_path):
    checker = _load_policy()
    baseline_rows = [
        {"id": "mutant.one", "classification": "non_equivalent", "status": "killed"},
        {"id": "mutant.two", "classification": "non_equivalent", "status": "killed"},
    ]
    baseline = _mutation_baseline(baseline_rows)
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(baseline))
    report_path.write_text(json.dumps(_mutation_report(baseline_rows)))

    assert checker.verify_mutation_ratchet(report_path, baseline_path) == []

    dropped_rows = [baseline_rows[0]]
    report_path.write_text(json.dumps(_mutation_report(dropped_rows)))

    errors = checker.verify_mutation_ratchet(report_path, baseline_path)

    assert errors and "curated mutant set differs from baseline" in errors[0]


def test_mutation_infrastructure_failure_fails_scheduled_ratchet(tmp_path):
    checker = _load_policy()
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_rows = [
        {"id": "mutant.one", "classification": "non_equivalent", "status": "killed"}
    ]
    report_rows = [
        {
            "id": "mutant.one",
            "classification": "non_equivalent",
            "status": "infrastructure_error",
        }
    ]
    baseline_path.write_text(json.dumps(_mutation_baseline(baseline_rows)))
    report_path.write_text(json.dumps(_mutation_report(report_rows)))

    errors = checker.verify_mutation_ratchet(report_path, baseline_path)

    assert errors and "score dropped" in errors[0]


@pytest.mark.parametrize(
    ("rows", "expected_message"),
    [
        (
            [
                {
                    "id": "mutant.one",
                    "classification": "non_equivalent",
                    "status": "mysterious-kill",
                }
            ],
            "unknown status",
        ),
        (
            [
                {
                    "id": "mutant.one",
                    "classification": "non_equivalentish",
                    "status": "killed",
                }
            ],
            "classification",
        ),
    ],
)
def test_unknown_mutant_status_or_classification_is_rejected(
    tmp_path, rows, expected_message
):
    checker = _load_policy()
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_rows = [
        {"id": "mutant.one", "classification": "non_equivalent", "status": "killed"}
    ]
    baseline_path.write_text(json.dumps(_mutation_baseline(baseline_rows)))
    report_path.write_text(json.dumps(_mutation_report(rows)))

    errors = checker.verify_mutation_ratchet(report_path, baseline_path)

    assert errors and expected_message in errors[0]


def test_duplicate_mutant_ids_are_rejected_even_when_unique_set_matches_baseline(
    tmp_path,
):
    checker = _load_policy()
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_rows = [
        {"id": "mutant.one", "classification": "non_equivalent", "status": "killed"},
        {"id": "mutant.two", "classification": "non_equivalent", "status": "killed"},
    ]
    report_rows = [
        baseline_rows[0],
        baseline_rows[0],
        baseline_rows[1],
    ]
    baseline_path.write_text(json.dumps(_mutation_baseline(baseline_rows)))
    report_path.write_text(json.dumps(_mutation_report(report_rows)))

    # Equal sets alone are insufficient: the duplicate candidate ID must fail.
    assert set(row["id"] for row in report_rows) == set(
        row["id"] for row in baseline_rows
    )
    errors = checker.verify_mutation_ratchet(report_path, baseline_path)

    assert errors and "duplicated" in errors[0]


def test_summary_counts_must_match_classified_mutant_records(tmp_path):
    checker = _load_policy()
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    rows = [
        {"id": "mutant.one", "classification": "non_equivalent", "status": "killed"},
        {"id": "mutant.two", "classification": "equivalent", "status": "equivalent"},
    ]
    baseline_path.write_text(json.dumps(_mutation_baseline(rows)))
    valid_report = _mutation_report(rows)
    report_path.write_text(json.dumps(valid_report))

    # Positive control establishes that the otherwise identical report is valid.
    assert checker.verify_mutation_ratchet(report_path, baseline_path) == []

    forged = dict(valid_report)
    forged["denominator"] = 2
    forged["caught"] = 2
    report_path.write_text(json.dumps(forged))
    errors = checker.verify_mutation_ratchet(report_path, baseline_path)

    assert errors and "summary counts" in errors[0]


def test_mutation_infrastructure_campaign_failure_is_reported(tmp_path):
    policy_dir = _policy_dir()
    runner = policy_dir / "run_antigaming.py"
    root, _ = _repo(
        tmp_path,
        {
            "README.md": "mutation count fixture\n",
            "python/bionetgen/model.py": "class BioNetGenModel:\n    def set_parameter(self, name, value):\n        self._model.set_parameter(name, value)\n",
        },
    )
    output = tmp_path / "mutations.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(policy_dir)
    env["ANTIGAMING_POLICY_DIR"] = str(policy_dir)
    env["ANTIGAMING_BOOTSTRAP"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--root",
            str(root),
            "--check",
            "release-scheduled-mutation-ratchet",
            "--mutation-output",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "mutation campaign/ratchet infrastructure error" in proc.stdout
