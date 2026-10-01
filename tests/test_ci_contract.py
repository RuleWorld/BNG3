"""Acceptance contracts for the Python package CI installation path."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from scripts.ci import validate_sbml_test_suite
from scripts.validate import (
    load_skip_models,
    load_validation_manifest,
    load_validation_molecule_name_aliases,
    run_validation,
    write_validation_summary,
)
from scripts.cross_validate import (
    compare_network_files,
    _network_only_text,
    run_cross_validation,
    write_cross_validation_summary,
)

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
WEEKLY_WORKFLOW = REPO / ".github" / "workflows" / "weekly.yml"
REFERENCE_EXCLUSIONS = REPO / "tests" / "validation" / "reference_exclusions.json"
VALIDATION_MANIFEST = REPO / "tests" / "validation" / "validation_manifest.json"
VALIDATE_DIR = REPO / "tests" / "validation" / "Validate"
PARITY_WORKFLOW = REPO / ".github" / "workflows" / "parity.yml"
FORMAL_WORKFLOW = REPO / ".github" / "workflows" / "formal.yml"

CPP_CMAKE = REPO / "cpp" / "CMakeLists.txt"
TOP_LEVEL_CMAKE = REPO / "CMakeLists.txt"

# The flags that embed a second copy of the C++ runtime into a binary. They are
# correct for a CLI executable, which owns its process, and wrong for the
# Python extension, which is loaded into a process someone else owns.
STATIC_RUNTIME_LINK_FLAGS = ("-static-libstdc++", "-static-libgcc")


def _python_extension_target_block() -> str:
    """The cpp/CMakeLists.txt text that declares the `_bionetgen_cpp` module."""

    cmake = CPP_CMAKE.read_text(encoding="utf-8")
    start = cmake.index("pybind11_add_module(_bionetgen_cpp")
    end = cmake.index("\nendif()", start)
    return cmake[start:end]


def _link_flags_applied_to(target: str, cmake_text: str) -> list[str]:
    """Flags CMake would append to `target`'s own link command, in any form.

    Covers the four ways a target can acquire link flags: per-target
    target_link_options, per-target target_link_libraries, the LINK_FLAGS
    target property, and the directory-level *_LINKER_FLAGS variables that
    apply to that target's library kind.
    """

    flags: list[str] = []
    # target_link_options(<target> ...) / target_link_libraries(<target> ...)
    for command_name in ("target_link_options", "target_link_libraries"):
        for call in re.finditer(
            rf"(?ms)^[ \t]*{command_name}\(\s*{re.escape(target)}\b(.*?)\)",
            cmake_text,
        ):
            flags += re.findall(r"-static[-\w+]*", call.group(1))
    # set_target_properties(<target> ... LINK_FLAGS "...")
    for properties in re.finditer(
        rf"(?ms)^[ \t]*set_target_properties\(\s*{re.escape(target)}\b(.*?)(?:\n[ \t]*\)|\))",
        cmake_text,
    ):
        for value in re.findall(r"LINK_FLAGS\s+\"?([^\"\n]+)\"?", properties.group(1)):
            flags += re.findall(r"-static[-\w+]*", value)
    return flags


def test_python_extension_never_statically_links_the_cxx_runtime():
    """The extension must resolve libstdc++ from the process, not embed one.

    A statically linked C++ runtime inside `_bionetgen_cpp` coexists with the
    `libstdc++.so.6` that the host interpreter already has mapped -- SciPy's C++
    modules map it too. Two independent runtimes in one process means two
    independent sets of locale facet tables, so `std::ostream` dispatches a
    numeric format through the wrong facet and the process segfaults inside
    `Expression::toString()` on the first `ostringstream << double`. This
    shipped green through sixteen CI runs because the crash needs a co-loaded
    C++ extension, which the build job did not have.

    CLI executables are unaffected and may keep the static runtime: they own
    their process. That asymmetry is why the check has to be about the module
    target specifically, and not about the flags existing in the build.
    """

    block = _python_extension_target_block()
    static_flags = [
        flag
        for flag in _link_flags_applied_to("_bionetgen_cpp", block)
        if flag.startswith(STATIC_RUNTIME_LINK_FLAGS)
    ]
    assert not static_flags, (
        f"`_bionetgen_cpp` is given {static_flags} by cpp/CMakeLists.txt. The "
        "Python extension runs inside a host interpreter that may already have "
        "libstdc++.so.6 mapped (SciPy's C++ modules do), so a statically linked "
        "runtime puts two C++ runtimes in one process: duplicated locale facet "
        "tables, then a segfault in std::ostream numeric formatting. Link the "
        "runtime dynamically for the module and leave CMAKE_EXE_LINKER_FLAGS "
        "alone for the CLI executables, which own their process. See PR #30."
    )

    # A SHARED module would inherit CMAKE_SHARED_LINKER_FLAGS, which does carry
    # the static runtime at the top level. pybind11_add_module defaults to
    # MODULE, so this only trips if someone reaches for the SHARED variant.
    assert "SHARED" not in block, (
        "`pybind11_add_module(_bionetgen_cpp ... SHARED ...)` makes the "
        "extension a SHARED library, and SHARED targets inherit "
        "CMAKE_SHARED_LINKER_FLAGS, which carries -static-libstdc++ at the top "
        "level. Use the MODULE default (or pass MODULE explicitly) so the "
        "extension stays out of that path."
    )


def test_cli_executables_still_may_link_the_cxx_runtime_statically():
    """The module restriction must not tempt someone into a global reversal.

    The static runtime is load-bearing for the shipped `bng_cpp` and `NFsim`
    binaries, which run on machines where a system libstdc++ may be too old.
    A well-meaning "clean up the inconsistency" edit that moves the flags out
    of CMAKE_EXE_LINKER_FLAGS would trade a documented extension crash for an
    unmeasured portability regression, so the executable path is pinned too.
    """

    top_level = TOP_LEVEL_CMAKE.read_text(encoding="utf-8")
    for flag in STATIC_RUNTIME_LINK_FLAGS:
        assert re.search(
            rf"CMAKE_EXE_LINKER_FLAGS[^\n]*{re.escape(flag)}", top_level
        ), (
            f"{flag} is no longer applied through CMAKE_EXE_LINKER_FLAGS. The "
            "module contract in "
            "test_python_extension_never_statically_links_the_cxx_runtime is "
            "about the extension target only; if the executables genuinely need "
            "to give up their static runtime, that is a separate change to "
            "justify, not a silent consequence of this one."
        )


def test_batch_ssa_cpu_reference_parity_gate_runs_in_ci():
    """The CPU batch-SSA reference gate must exist and run on every PR head.

    This is the job that would have caught the segfault: it loads the freshly
    built extension into the same interpreter that imported SciPy. It was
    never green, so the extension's runtime-linkage defect shipped behind it.
    The gate is hardware-independent by construction, which is what makes it a
    required check rather than an incidental one.
    """

    job = _workflow_job("batch-ssa-cpu-reference")
    assert "Batch SSA CPU reference parity" in job
    assert "tests/test_batch_ssa_statistical_parity.py --mode cpu" in job
    assert "-DBUILD_PYTHON_BINDINGS=ON" in job
    # The build must produce the module the gate imports; without this the job
    # would go green having tested nothing.
    assert "build/cpp/_bionetgen_cpp" in job
    assert "|| true" not in job
    assert "continue-on-error" not in job
    # --mode all would drag in the GPU comparison, which skips without a
    # backend; --mode cpu is the hardware-independent claim being made.
    assert "--mode cpu" in job
    assert "--mode all" not in job


def test_cmake_link_flag_scan_detects_each_way_a_target_can_acquire_flags():
    """Guard the guard: the static-flag scan must actually see a static flag.

    `_link_flags_applied_to` is the mechanism the extension contract rests on.
    If its extraction silently stopped matching -- a renamed command, a
    reformatted call -- it would report an empty flag list and the extension
    contract would pass no matter what the build did.
    """

    assert _link_flags_applied_to(
        "_probe_link_options",
        "target_link_options(_probe_link_options PRIVATE -static-libgcc)",
    ) == ["-static-libgcc"]
    assert _link_flags_applied_to(
        "_probe_link_flags",
        'set_target_properties(_probe_link_flags PROPERTIES LINK_FLAGS "-static-libstdc++")',
    ) == ["-static-libstdc++"]
    assert _link_flags_applied_to(
        "_probe_link_libraries",
        "target_link_libraries(_probe_link_libraries PRIVATE -static-libstdc++)",
    ) == ["-static-libstdc++"]
    # A multi-line call spanning several flags must be captured whole, not
    # just up to the first closing paren.
    assert _link_flags_applied_to(
        "_probe_multiline",
        "target_link_options(_probe_multiline PRIVATE\n    -static-libgcc\n"
        "    -static-libstdc++\n)",
    ) == ["-static-libgcc", "-static-libstdc++"]
    assert (
        _link_flags_applied_to(
            "_absent_target", TOP_LEVEL_CMAKE.read_text(encoding="utf-8")
        )
        == []
    )


def test_ssts_report_source_provenance_records_revision_and_tracked_changes(
    tmp_path: Path,
):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "SSTS provenance test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "ssts-provenance@example.invalid",
        ],
        check=True,
    )
    source = repo / "model.py"
    source.write_text("model = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "model.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    clean = validate_sbml_test_suite._repository_provenance(repo)

    assert clean == {
        "bng3_commit": revision,
        "bng3_tracked_worktree_clean": True,
    }

    source.write_text("model = False\n", encoding="utf-8")
    dirty = validate_sbml_test_suite._repository_provenance(repo)

    assert dirty == {
        "bng3_commit": revision,
        "bng3_tracked_worktree_clean": False,
    }


def test_pull_request_runs_keep_exact_head_evidence_available():
    """A later PR push must not cancel validation for the preceding SHA."""

    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.sha" in workflow
    assert re.search(r"^\s+cancel-in-progress:\s+false\s*$", workflow, re.MULTILINE)


def test_wheel_workflows_use_supported_platform_targets_and_test_dependencies():
    """Wheel builds must use toolchains compatible with current dependencies."""

    for workflow_path, job_name in (
        (CI_WORKFLOW, "wheels"),
        (RELEASE_WORKFLOW, "build-wheels"),
    ):
        job = _workflow_job_from(workflow_path, job_name)
        assert "pip install cibuildwheel==4.2.1" in job
        assert "CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28" in job
        assert "CIBW_ARCHS_MACOS: ${{ matrix.macos_arch }}" in job
        assert "MACOSX_DEPLOYMENT_TARGET=${{ matrix.macos_deployment_target }}" in job
        assert (
            "DCMAKE_OSX_DEPLOYMENT_TARGET=${{ matrix.macos_deployment_target }}" in job
        )
        assert 'macos_deployment_target: "10.13"' in job
        assert 'macos_deployment_target: "11.0"' in job
        assert "CIBW_TEST_REQUIRES: pytest numpy click" in job
        assert "cp314-*" in job

    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^\s+workflow_dispatch:\s*$", ci_workflow, re.MULTILINE)
    wheels = _workflow_job_from(CI_WORKFLOW, "wheels")
    assert "github.event_name == 'workflow_dispatch'" in wheels


def test_wheel_tests_smoke_the_installed_console_script():
    """The built wheel must expose a working user-facing CLI entry point."""

    for workflow_path, job_name in (
        (CI_WORKFLOW, "wheels"),
        (RELEASE_WORKFLOW, "build-wheels"),
    ):
        job = _workflow_job_from(workflow_path, job_name)
        assert "CIBW_TEST_COMMAND:" in job
        assert "bionetgen --version" in job
        assert "bionetgen --help" in job


def _workflow_job(name: str) -> str:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
    )
    assert match, f"CI must define a {name} job"
    return match.group("body")


def _python_test_job() -> str:
    return _workflow_job("python-test")


def _workflow_job_from(path: Path, name: str) -> str:
    workflow = path.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
    )
    assert match, f"{path.name} must define a {name} job"
    return match.group("body")


def test_external_parity_workflow_is_present_and_keeps_exact_head_evidence():
    """Cross-tool checks must be independently reproducible per PR head."""

    workflow = PARITY_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.sha" in workflow
    assert re.search(r"^\s+cancel-in-progress:\s+false\s*$", workflow, re.MULTILINE)
    assert 'BNG3_CI_STRICT_ORACLES: "1"' in workflow
    for job in ("oracle-lock", "bng2-parity", "nfsim-parity", "pybionetgen-compat"):
        assert re.search(rf"^  {job}:\n", workflow, re.MULTILINE), job


def test_external_parity_jobs_use_pinned_oracle_checkouts_and_fail_closed():
    """No parity job may silently substitute a branch head or embedded engine."""

    workflow = PARITY_WORKFLOW.read_text(encoding="utf-8")
    for source in ("bionetgen", "nfsim", "pybionetgen"):
        assert f"--name {source}" in workflow
        assert "scripts/ci/checkout_oracle.py" in workflow
    bng2 = _workflow_job_from(PARITY_WORKFLOW, "bng2-parity")
    assert "--bng-perl" in bng2
    assert "--bng-cpp" in bng2
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in bng2
    nfsim = _workflow_job_from(PARITY_WORKFLOW, "nfsim-parity")
    assert "NFSIM_BIN" in nfsim
    assert "build/NFsim" in nfsim
    assert "tests/validation/test_parity_nfsim.py" in nfsim
    assert "build/cpp/NFsim" not in nfsim


def test_formal_workflow_runs_pinned_kernel_and_nfnext_contracts():
    """The Lean reference must be kernel-checked on every PR head."""

    workflow = FORMAL_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.sha" in workflow
    assert re.search(r"^\s+cancel-in-progress:\s+false\s*$", workflow, re.MULTILINE)
    assert "leanprover/lean-action@38fbc41a8c28c4cbaec22d7f7de508ec2e7c0dd9" in workflow
    assert "lake-package-directory: formal/lean" in workflow
    assert "auto-config: false" in workflow
    assert (REPO / "formal" / "lean" / "lean-toolchain").read_text(
        encoding="utf-8"
    ).strip() == ("leanprover/lean4:v4.33.1")
    assert "scripts/static_validate.py" in workflow
    assert "scripts/run_nfnext_contract.sh" in workflow
    assert "lake build" in workflow
    assert "lake env lean tests/Smoke.lean" in workflow


def test_release_workflow_requires_exact_main_sha_qualification():
    """A version tag cannot publish unless all required main push gates passed."""

    qualify = _workflow_job_from(RELEASE_WORKFLOW, "qualify")
    for job_name in ("build-binaries", "build-wheels", "build-sdist"):
        assert "qualify" in _workflow_job_from(RELEASE_WORKFLOW, job_name)
    release = _workflow_job_from(RELEASE_WORKFLOW, "release")
    assert "qualify" in release
    assert "actions: read" in qualify
    assert "fetch-depth: 0" in qualify
    assert "git merge-base --is-ancestor" in qualify
    assert "gh api" in qualify

    qualification_script = (
        REPO / "scripts" / "ci" / "qualify_release_candidate.py"
    ).read_text(encoding="utf-8")
    for workflow_name in ("CI", "Cross-tool parity", "Lean semantic kernel", "CodeQL"):
        assert f'"{workflow_name}"' in qualification_script


def test_release_binaries_smoke_before_packaging():
    """Release archives must contain executables that start on their runner."""

    job = _workflow_job_from(RELEASE_WORKFLOW, "build-binaries")
    smoke = job.index("Smoke test release executables")
    package = job.index("Package binaries")
    assert smoke < package
    assert "bng_cpp${{ matrix.binary_ext }} --version" in job
    assert "NFsim${{ matrix.binary_ext }} -help" in job


def test_release_run_qualification_requires_success_for_each_exact_main_push():
    from scripts.ci.qualify_release_candidate import qualify_workflow_runs

    sha = "a" * 40
    names = ["CI", "Cross-tool parity", "Lean semantic kernel", "CodeQL"]
    runs = [
        {
            "name": name,
            "head_sha": sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for name in names
    ]

    assert qualify_workflow_runs({"workflow_runs": runs}, sha, names) == []
    assert qualify_workflow_runs({"workflow_runs": runs[:-1]}, sha, names) == ["CodeQL"]

    wrong_sha = [dict(run, head_sha="b" * 40) for run in runs]
    assert qualify_workflow_runs({"workflow_runs": wrong_sha}, sha, names) == names

    wrong_branch = [dict(run, head_branch="feature") for run in runs]
    assert qualify_workflow_runs({"workflow_runs": wrong_branch}, sha, names) == names

    pending = [dict(run, status="in_progress", conclusion=None) for run in runs]
    assert qualify_workflow_runs({"workflow_runs": pending}, sha, names) == names

    failed = [dict(run, conclusion="failure") for run in runs]
    assert qualify_workflow_runs({"workflow_runs": failed}, sha, names) == names


def test_oracle_source_loader_requires_full_locked_revisions(tmp_path):
    """The checkout helper must reject floating or malformed source refs."""

    from scripts.ci.oracle_sources import OracleSourceError, load_oracle_source

    lock = {
        "sources": {
            "nfsim": {
                "repository": "https://github.com/RuleWorld/NFsim.git",
                "revision": "a" * 40,
            }
        }
    }
    assert load_oracle_source(lock, "nfsim")["revision"] == "a" * 40
    with pytest.raises(OracleSourceError, match="full lowercase Git SHA"):
        load_oracle_source(
            {"sources": {"nfsim": {"repository": "x", "revision": "main"}}},
            "nfsim",
        )


def test_pull_request_exercises_clean_source_distribution_install():
    """PRs must exercise the sdist install path, not only an in-tree wheel."""

    job = _workflow_job("package-smoke")
    assert "needs: [python-test]" in job
    assert not re.search(r"^\s+if:.*github\.event_name.*push", job, re.MULTILINE)
    assert "python -m build --sdist" in job
    assert "python -m venv" in job
    assert "pip install --no-deps dist/*.tar.gz" in job
    assert "import bionetgen" in job
    assert re.search(r"/bin/bionetgen\"?\s+--version", job)


def test_project_declares_click_as_runtime_dependency():
    project = PYPROJECT.read_text(encoding="utf-8")
    dependencies = re.search(r"(?ms)^dependencies\s*=\s*\[(?P<body>.*?)^\]", project)
    assert dependencies, "pyproject.toml must declare project dependencies"
    assert re.search(r"['\"]click(?:[<>=!~].*)?['\"]", dependencies.group("body"))


def test_python_matrix_installs_runtime_dependencies_before_no_deps_wheel():
    """No-deps wheel install must run after click is installed explicitly.

    The wheel job intentionally uses ``--no-deps``.  Therefore its test
    environment must install every runtime dependency required at collection
    time; otherwise ``tests/python/test_cli.py`` cannot import ``click``.
    """

    job = _python_test_job()
    assert "--no-deps" in job
    install_lines = [
        line
        for line in job.splitlines()
        if re.search(r"(?:pip|python\s+-m\s+pip)\s+install", line)
    ]
    assert install_lines, "python-test must install package/test dependencies"
    assert any(
        re.search(r"\bclick(?:[<>=!~].*)?\b", line) for line in install_lines
    ), "python-test no-deps wheel path must install declared click dependency"


def test_python_tests_use_headless_isolated_matplotlib_cache():
    """The plotting test must not share a stale GUI/font cache on runners."""

    job = _python_test_job()
    assert "MPLBACKEND: Agg" in job
    assert "MPLCONFIGDIR: ${{ runner.temp }}/matplotlib" in job
    assert "scripts/prepare_matplotlib_cache.py" in job


def test_sbml_import_runs_as_a_real_isolated_ci_gate():
    """SBML coverage stays enabled while native XML libraries are isolated."""

    job = _python_test_job()
    assert "pytest tests/python/test_sbml_import.py -v --tb=short" in job
    assert "--ignore=tests/python/test_sbml_import.py" in job


def test_msvc_parser_headers_clear_windows_macros_before_antlr():
    """Windows SDK macros must not rewrite ANTLR enum members."""

    compat = (REPO / "cpp" / "parser" / "antlr_compat.hpp").read_text(encoding="utf-8")
    assert re.search(r"#\s*undef\s+ERROR", compat)
    assert re.search(r"#\s*undef\s+TRUE", compat)
    assert re.search(r"#\s*undef\s+FALSE", compat)
    assert re.search(r"#\s*undef\s+constant", compat)

    generated_dir = REPO / "cpp" / "parser" / "generated"
    generated_headers = sorted(generated_dir.glob("*.h"))
    assert generated_headers
    for header in generated_headers:
        source = header.read_text(encoding="utf-8")
        if '#include "antlr4-runtime.h"' not in source:
            continue
        compat_include = source.index('#include "../antlr_compat.hpp"')
        runtime_include = source.index('#include "antlr4-runtime.h"')
        assert compat_include < runtime_include, header.name


def test_corpus_parse_inventory_emits_source_and_binary_provenance():
    """Parser inventory summaries must identify the tested source and binary."""

    job = _workflow_job("corpus-parse")
    assert "set -euo pipefail" in job
    assert "BNG3_SOURCE_REVISION" in job
    assert "bng_cpp SHA-256" in job
    assert "GITHUB_STEP_SUMMARY" in job


def test_weekly_nfsim_smoke_emits_source_and_binary_provenance():
    """NFsim smoke summaries must identify the tested source and executable."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "nfsim-execution-smoke")
    assert "set -euo pipefail" in job
    assert "BNG3_SOURCE_REVISION" in job
    assert "NFsim SHA-256" in job
    assert "GITHUB_STEP_SUMMARY" in job


def test_weekly_cross_validation_fails_closed_on_engine_or_output_errors():
    """The claimed C++/Perl gate must fail through the runner, not skip."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "cross-validation")
    assert "set -euo pipefail" in job
    assert "SKIP" not in job
    assert "python scripts/cross_validate.py" in job
    assert "--bng-cpp build/cpp/bng_cpp" in job
    assert "--bng-perl legacy/perl/BNG2.pl" in job
    assert "pip install numpy" in job
    assert "|| true" not in job


def test_cross_validation_rejects_same_count_different_networks(tmp_path):
    """The independent oracle comparison must inspect reaction topology."""

    reference = tmp_path / "reference.net"
    test = tmp_path / "test.net"
    reference.write_text(
        """begin species
1 A() 1
2 B() 0
end species
begin reactions
0 1 2 k
end reactions
""",
        encoding="utf-8",
    )
    test.write_text(
        """begin species
1 A() 1
2 C() 0
end species
begin reactions
0 1 2 k
end reactions
""",
        encoding="utf-8",
    )

    diff = compare_network_files(reference, test)

    assert diff is not None
    assert diff.ok is False
    assert diff.n_species_ref == diff.n_species_test == 2
    assert diff.n_reactions_ref == diff.n_reactions_test == 1


def test_cross_validation_missing_engine_output_is_an_error(tmp_path):
    """A successful engine exit without a network cannot become a pass."""

    models = tmp_path / "Validate"
    models.mkdir()
    (models / "model.bngl").write_text("begin model\nend model\n", encoding="utf-8")
    no_output = tmp_path / "no_output.sh"
    no_output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    no_output.chmod(0o755)

    results, details = run_cross_validation(
        no_output,
        no_output,
        models,
        model_names=["model"],
    )

    assert results == {"pass": 0, "fail": 0, "error": 1}
    assert details == ["ERROR model (missing C++ .net)"]


def test_cross_validation_stages_generation_without_simulation_actions():
    """Network parity must not accidentally execute a model's simulations."""

    staged = _network_only_text("""begin parameters
k 1
end parameters
begin actions
setParameter(\"k\", 2)
generate_network({overwrite=>1})
simulate_ode({t_end=>10,n_steps=>10})
end actions
""")

    assert 'setParameter("k", 2)' in staged
    assert "simulate_ode" not in staged
    assert staged.endswith(
        'begin actions\n  setParameter("k", 2)\n'
        "  generate_network({overwrite=>1})\nend actions\n"
    )


def test_weekly_cross_validation_uses_structural_oracle_runner():
    """C++/Perl validation must compare typed networks, not section counts."""

    job = _workflow_job_from(WEEKLY_WORKFLOW, "cross-validation")
    assert "python scripts/cross_validate.py" in job
    assert "--bng-perl legacy/perl/BNG2.pl" in job
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in job
    assert "grep -c" not in job
    assert "species counts" not in job


def test_reference_validation_can_fail_closed_on_missing_oracles(tmp_path):
    """A claimed reference gate must not turn a missing .net into a skip."""

    validate_dir = tmp_path / "Validate"
    (validate_dir / "DAT_validate").mkdir(parents=True)
    (validate_dir / "missing_oracle.bngl").write_text(
        "begin model\nend model\n", encoding="utf-8"
    )

    results, details = run_validation(
        "unused-bng-cpp",
        validate_dir,
        strict_references=True,
    )

    assert results == {"pass": 0, "fail": 0, "skip": 0, "error": 1}
    assert details == ["ERROR missing_oracle (no reference .net)"]


def test_reference_ci_jobs_enable_strict_reference_validation():
    """PR and weekly reference jobs must opt into the fail-closed contract."""

    assert "--strict-references" in _workflow_job("validation")
    weekly_job = _workflow_job_from(WEEKLY_WORKFLOW, "bng-validation")
    assert "--strict-references" in weekly_job


def test_reference_ci_jobs_emit_terminal_validation_summaries():
    """PR and weekly reference jobs must publish their result table."""

    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in _workflow_job("validation")
    assert '--summary-file "$GITHUB_STEP_SUMMARY"' in _workflow_job_from(
        WEEKLY_WORKFLOW, "bng-validation"
    )


def test_validation_summary_records_counts_source_and_binary_digest(
    tmp_path, monkeypatch
):
    """The reusable validation summary must preserve provenance and outcomes."""

    bng_cpp = tmp_path / "bng_cpp"
    bng_cpp.write_bytes(b"bng3-test-binary")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SHA", "source-sha-123")

    write_validation_summary(
        summary,
        {
            "pass": 4,
            "fail": 1,
            "skip": 2,
            "error": 3,
        },
        bng_cpp,
        tmp_path / "Validate",
        strict_references=True,
    )

    text = summary.read_text(encoding="utf-8")
    assert "source-sha-123" in text
    assert "bng_cpp SHA-256" in text
    assert "| 10 | 4 | 1 | 3 | 2 |" in text
    assert "explicit exclusions only" in text
    assert text.count("| ---: | ---: | ---: | ---: | ---: |") == 1


def test_cross_validation_summary_records_both_engines_without_duplicate_header(
    tmp_path, monkeypatch
):
    """The structural cross-check summary must be auditable and well formed."""

    bng_cpp = tmp_path / "bng_cpp"
    bng_cpp.write_bytes(b"bng3-test-binary")
    bng_perl = tmp_path / "BNG2.pl"
    bng_perl.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SHA", "source-sha-456")

    write_cross_validation_summary(
        summary,
        {"pass": 3, "fail": 1, "error": 2},
        bng_cpp,
        bng_perl,
        tmp_path / "Validate",
    )

    text = summary.read_text(encoding="utf-8")
    assert "source-sha-456" in text
    assert "BNG2 oracle SHA-256" in text
    assert "bng_cpp SHA-256" in text
    assert "| 6 | 3 | 1 | 2 |" in text
    assert text.count("| ---: | ---: | ---: | ---: |") == 1


def test_reference_exclusion_manifest_is_explicit_and_corpus_backed():
    """The former exclusion ledger is closed and contains no skipped models."""

    manifest = json.loads(REFERENCE_EXCLUSIONS.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "closed"
    assert set(manifest["profiles"]) == {"pull_request", "weekly"}
    assert manifest["profiles"] == {"pull_request": [], "weekly": []}
    assert manifest["reasons"] == {}

    action_models = load_validation_manifest(VALIDATION_MANIFEST)
    assert action_models
    assert len(action_models) == len(set(action_models))
    assert all((VALIDATE_DIR / f"{model}.bngl").is_file() for model in action_models)

    aliases = load_validation_molecule_name_aliases(VALIDATION_MANIFEST)
    assert aliases == {
        "test_sbml_flat": {
            "A____": "A",
            "AA____": "AA",
            "B____": "B",
            "C____": "C",
            "D____": "D",
        }
    }
    assert (VALIDATE_DIR / "test_sbml_flat.bngl").is_file()


def test_reference_ci_jobs_run_the_full_corpus_without_exclusions():
    """CI must run both network and action-output fixtures without skips."""

    validation_job = _workflow_job("validation")
    weekly_job = _workflow_job_from(WEEKLY_WORKFLOW, "bng-validation")
    assert "SKIP=" not in validation_job
    assert "SKIP=" not in weekly_job
    assert "--skip-file" not in validation_job
    assert "--skip-profile" not in validation_job
    assert "--skip-file" not in weekly_job
    assert "--skip-profile" not in weekly_job
    assert (
        "--validation-manifest tests/validation/validation_manifest.json"
        in validation_job
    )
    assert (
        "--validation-manifest tests/validation/validation_manifest.json" in weekly_job
    )


def test_validate_loads_the_committed_reference_exclusion_profile():
    """The CLI loader must expose the same ordered models as the manifest."""

    manifest = json.loads(REFERENCE_EXCLUSIONS.read_text(encoding="utf-8"))
    assert (
        load_skip_models(REFERENCE_EXCLUSIONS, "pull_request")
        == manifest["profiles"]["pull_request"]
    )
    assert (
        load_skip_models(REFERENCE_EXCLUSIONS, "weekly")
        == manifest["profiles"]["weekly"]
    )


def test_batch_ssa_parity_script_fails_closed_when_it_cannot_reach_its_models():
    """The gate must go red, not pass or skip, when the extension is absent.

    `main` turns the CPU gate's boolean into an exit status. Run from a
    directory where `models/*.bngl` does not resolve, the gate has to fail --
    otherwise deleting or misconfiguring the build step would green the job
    having tested nothing. This runs the real script, so it needs no compiled
    extension: it fails before it gets that far, which is the property.
    """

    script = REPO / "tests" / "test_batch_ssa_statistical_parity.py"
    assert script.is_file()
    completed = subprocess.run(
        [sys.executable, str(script), "--mode", "cpu"],
        cwd=REPO / "scripts",
        capture_output=True,
        text=True,
        timeout=600,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "PYTHONPATH": "",
        },
    )
    assert completed.returncode != 0, (
        "the batch-SSA CPU gate exited 0 from a directory where its model "
        "fixtures do not resolve, so a missing build would pass the job"
    )


def test_parity_script_cpu_mode_translates_a_failed_gate_into_a_nonzero_exit():
    """A failed parity comparison must reach the runner as a nonzero status.

    Asserting this on the source keeps the contract hermetic: this suite cannot
    build the extension, so it cannot make the gate fail for real. What it can
    pin is the wiring the CI job depends on -- gate result to exit status, exit
    status to process status -- and that the CPU mode reports on the CPU gate
    rather than on a GPU comparison that skips without a backend.
    """

    source = (REPO / "tests" / "test_batch_ssa_statistical_parity.py").read_text(
        encoding="utf-8"
    )
    assert "return 0 if ok else 1" in source, (
        "the CPU gate's result is no longer translated into an exit status; a "
        "failed parity comparison would exit 0 and the CI job would go green"
    )
    assert re.search(
        r"if\s+__name__\s*==\s*[\"']__main__[\"']:\s*\n\s*sys\.exit\(main\(\)\)", source
    ), "the parity script must propagate main()'s status via sys.exit under __main__"
    assert re.search(r"if\s+args\.mode\s*==\s*\"gpu\":", source), (
        "--mode gpu must be dispatched before the CPU gate; the CI job runs "
        "--mode cpu, so the two modes have to stay distinguishable"
    )
    assert source.count("run_cpu_reference_gate()") >= 2, (
        "the CPU gate must be invoked from main() and tested independently of "
        "the GPU comparison"
    )
