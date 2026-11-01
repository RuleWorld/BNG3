"""Hybrid trajectories against pinned BNG2 and native NFsim.

The BNG2-generated HPP XML is consumed by the independently pinned native
NFsim binary. BNG3 generates the equivalent hybrid model and executes it
through its population-aware NFcore event loop. The two independent ensembles
are additionally checked against the source model's exact binomial marginal
and per-trajectory A+B conservation law.
"""

from __future__ import annotations

import hashlib
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from scripts.ci.oracle_sources import load_lock
from tests.validation import compare, oracle_nfsim, oracle_perl, runner
from tests.validation.strict import require_oracle


RUNS = 200
BASE_SEED = 4100
T_END = 0.1
N_STEPS = 4
INITIAL_B = 20
K_MAKE = 1.0
K_MAP = 100.0
ROOT = Path(__file__).resolve().parents[2]

MODEL = f"""begin model
begin parameters
  k_make {K_MAKE}
  k_map {K_MAP}
  N {INITIAL_B}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  B() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  B() -> A() k_make
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
end model
"""

COMPARTMENT_MODEL = f"""begin model
begin parameters
  k_fast 100
  k_slow 0.1
  N {INITIAL_B}
end parameters
begin compartments
  c1 3 1
  c2 3 1
  c3 3 1
end compartments
begin molecule types
  A()
  B1()
  B2()
end molecule types
begin seed species
  @c1:A() N
  @c2:A() N
end seed species
begin observables
  Molecules A_total A()
  Molecules c1_units @c1:A()
  Molecules c2_units @c2:A()
  Molecules B1_total B1()
  Molecules B2_total B2()
  Molecules all_units A(),B1(),B2()
end observables
begin reaction rules
  @c1:A() -> @c1:B1() k_fast
  @c2:A() -> @c2:B2() k_slow
end reaction rules
begin population maps
  c1: @c1:A() -> P() k_fast
  c2: @c2:A() -> P() k_slow
  c3: @c3:A() -> P() k_fast
end population maps
end model
"""


def _write_source(path: Path, *, engine: str, seed: int | None = None) -> Path:
    if engine == "bng2":
        action = (
            'generate_hybrid_model({overwrite=>1, execute=>1, '
            'actions=>["writeXML()"]})'
        )
    elif engine == "bng3":
        assert seed is not None
        action = (
            "generate_hybrid_model({overwrite=>1, execute=>1, "
            f'actions=>["simulate_nf({{t_end=>{T_END}, '
            f'n_steps=>{N_STEPS}, seed=>{seed}}})"]}})'
        )
    else:
        raise ValueError(engine)
    path.write_text(MODEL + f"\nbegin actions\n{action}\nend actions\n")
    return path


def _write_compartment_source(path: Path, action: str) -> Path:
    path.write_text(COMPARTMENT_MODEL + f"\nbegin actions\n{action}\nend actions\n")
    return path


def _locked_native_nfsim() -> Path:
    binary = oracle_nfsim.nfsim_binary()
    require_oracle(binary is not None, "pinned native NFsim unavailable (set NFSIM_BIN)")
    assert binary is not None
    lock = load_lock()
    expected = lock["oracles"]["nfsim"]["artifact_digest"].split(":", 1)[1]
    actual = hashlib.sha256(binary.read_bytes()).hexdigest()
    require_oracle(actual == expected, f"native NFsim digest mismatch: {actual}")
    return binary


def _run_bng2_hybrid(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    source = _write_source(tmp_path / "hybrid.bngl", engine="bng2")
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    process = subprocess.run(
        [os.environ.get("PERL", "perl"), str(bng2), "--outdir", str(tmp_path), str(source)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stderr or process.stdout
    xml = tmp_path / "hybrid_hpp.xml"
    assert xml.is_file() and xml.stat().st_size, process.stderr
    return xml


def _run_native_ensemble(xml: Path, tmp_path: Path):
    _locked_native_nfsim()
    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        path, error = oracle_nfsim.run_nfsim(
            xml,
            tmp_path / f"native-{seed}",
            t_end=T_END,
            n_steps=N_STEPS,
            seed=seed,
        )
        assert path is not None, f"native NFsim seed {seed}: {error}"
        data, columns = compare.parse_gdat(path)
        assert data is not None, f"native NFsim seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_bng3_ensemble(tmp_path: Path):
    import bionetgen

    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"bng3-{seed}"
        work_dir.mkdir()
        source = _write_source(work_dir / "hybrid.bngl", engine="bng3", seed=seed)
        bionetgen.load(source).execute()
        output = work_dir / "hybrid_hpp.gdat"
        assert output.is_file(), f"BNG3 seed {seed}: missing .gdat"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_bng3_compartment_ensemble(tmp_path: Path):
    import bionetgen

    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"compartment-bng3-{seed}"
        work_dir.mkdir()
        action = (
            "generate_hybrid_model({overwrite=>1, execute=>1, "
            f'actions=>["simulate_nf({{t_end=>{T_END}, '
            f'n_steps=>{N_STEPS}, seed=>{seed}}})"]}})'
        )
        source = _write_compartment_source(work_dir / "compartment.bngl", action)
        bionetgen.load(source).execute()
        output = work_dir / "compartment_hpp.gdat"
        assert output.is_file(), f"BNG3 compartment seed {seed}: missing .gdat"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 compartment seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_hybrid_generation(
    engine: str, source: Path, *, outdir: Path | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run one HPP generation action through BNG2 or the production BNG3 API."""
    if engine == "bng2":
        bng2 = oracle_perl._bng2_path()
        require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
        assert bng2 is not None
        env = os.environ.copy()
        env["BNGPATH"] = str(bng2.parent)
        env["PERL5LIB"] = str(bng2.parent / "Perl2")
        command = [os.environ.get("PERL", "perl"), str(bng2)]
        if outdir is not None:
            command.extend(("--outdir", str(outdir)))
        command.append(str(source))
        return subprocess.run(
            command,
            cwd=source.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    if engine == "bng3":
        import bionetgen

        bionetgen.load(source).execute()
        return None
    raise ValueError(engine)


def _write_option_model(path: Path, action: str) -> Path:
    path.write_text(MODEL + f"\nbegin actions\n{action}\nend actions\n")
    return path


def _option_case(engine: str, root: Path, options: str = ""):
    """Isolate BNG2/BNG3 output-prefix defaults for an action option case."""
    work = root / engine
    work.mkdir(parents=True, exist_ok=True)
    args = f"({{{options}}})" if options else "()"
    source = _write_option_model(work / "model.bngl", f"generate_hybrid_model{args}")
    result = _run_hybrid_generation(engine, source)
    if engine == "bng2":
        assert result is not None
        return result
    return None


@pytest.mark.nf
@pytest.mark.parity
def test_issue_150_generate_hybrid_model_action_options(tmp_path, capfd):
    """Exercise every assigned generate_hybrid_model option against BNG2.

    The pinned BNG2 action is the independent argument/default/error oracle;
    each generated action is also consumed by the production BNG3 route. The
    written BNGL/XML artifacts are checked instead of treating parsing as a
    successful action contract.
    """
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    require_oracle(
        oracle_perl._bng2_path() is not None,
        "pinned BNG2 unavailable (set BNG2_PERL)",
    )
    runner._ensure_source_python_path()

    coverage: dict[str, bool] = {}
    for option in ("actions", "execute", "overwrite", "prefix", "suffix", "verbose"):
        coverage[f"action.generate_hybrid_model.{option}"] = False
    coverage["action.generate_hybrid_model"] = False

    for engine in ("bng2", "bng3"):
        # Defaults: BNG2/BNG3 both write a model with writeXML() as its default
        # action, but do not run it unless execute=>1 is requested.
        result = _option_case(engine, tmp_path / f"defaults-{engine}")
        if engine == "bng2":
            assert result is not None and result.returncode == 0, result
        default_hpp = tmp_path / f"defaults-{engine}" / engine / "model_hpp.bngl"
        assert default_hpp.is_file()
        assert "writeXML()" in default_hpp.read_text()
        assert not default_hpp.with_suffix(".xml").exists()
        coverage["action.generate_hybrid_model"] = True

        empty_result = _option_case(
            engine,
            tmp_path / f"empty-actions-{engine}",
            "overwrite=>1, actions=>[]",
        )
        if engine == "bng2":
            assert empty_result is not None and empty_result.returncode == 0, empty_result
        empty_hpp = tmp_path / f"empty-actions-{engine}" / engine / "model_hpp.bngl"
        assert empty_hpp.is_file()
        assert "## model actions ##" not in empty_hpp.read_text()

        # execute=>1 runs an explicitly supplied action list against the
        # generated hybrid model.
        result = _option_case(
            engine,
            tmp_path / f"execute-{engine}",
            'overwrite=>1, execute=>1, actions=>["writeXML()"]',
        )
        if engine == "bng2":
            assert result is not None and result.returncode == 0, result
        executed_xml = tmp_path / f"execute-{engine}" / engine / "model_hpp.xml"
        assert executed_xml.is_file() and executed_xml.stat().st_size > 0
        coverage["action.generate_hybrid_model.actions"] = True
        coverage["action.generate_hybrid_model.execute"] = True

        # Custom prefix and suffix control the exact generated model and
        # consumer output paths on both implementations.
        custom_dir = tmp_path / f"custom-{engine}" / engine
        custom_dir.mkdir(parents=True)
        custom_prefix = custom_dir / "renamed"
        options = (
            f'overwrite=>1, prefix=>"{custom_prefix}", suffix=>"converted", '
            'execute=>1, actions=>["writeXML()"]'
        )
        result = _option_case(engine, tmp_path / f"custom-{engine}", options)
        if engine == "bng2":
            assert result is not None and result.returncode == 0, result
        custom_hpp = custom_dir / "renamed_converted.bngl"
        assert custom_hpp.is_file()
        assert (custom_dir / "renamed_converted.xml").is_file()
        coverage["action.generate_hybrid_model.prefix"] = True
        coverage["action.generate_hybrid_model.suffix"] = True

        # verbose=>1 reaches the generator's matching diagnostics.
        result = _option_case(
            engine,
            tmp_path / f"verbose-{engine}",
            "overwrite=>1, verbose=>1",
        )
        if engine == "bng2":
            assert result is not None and result.returncode == 0, result
            verbose = result.stdout + result.stderr
        else:
            captured = capfd.readouterr()
            verbose = captured.out + captured.err
        assert "verbose => 1" in verbose
        coverage["action.generate_hybrid_model.verbose"] = True

        # overwrite=>0 refuses an existing target; overwrite=>1 replaces it.
        overwrite_root = tmp_path / f"overwrite-{engine}"
        first = _option_case(engine, overwrite_root, "overwrite=>1")
        if engine == "bng2":
            assert first is not None and first.returncode == 0, first
        target = overwrite_root / engine / "model_hpp.bngl"
        target.write_text("sentinel\n")
        if engine == "bng2":
            refused = _option_case(engine, overwrite_root, "overwrite=>0")
            assert refused is not None
            assert "already exists" in refused.stdout + refused.stderr
        else:
            with pytest.raises(RuntimeError, match="already exists"):
                _option_case(engine, overwrite_root, "overwrite=>0")
        assert target.read_text() == "sentinel\n"
        replaced = _option_case(engine, overwrite_root, "overwrite=>1")
        if engine == "bng2":
            assert replaced is not None and replaced.returncode == 0, replaced
        assert target.read_text() != "sentinel\n"
        coverage["action.generate_hybrid_model.overwrite"] = True

        # BNG2 rejects unknown option names. BNG3 must preserve that failure
        # instead of silently generating an artifact with ignored arguments.
        if engine == "bng2":
            invalid = _option_case(
                engine,
                tmp_path / f"invalid-option-{engine}",
                "overwrite=>1, unsupported_option=>1",
            )
            assert invalid is not None
            assert invalid.returncode != 0, invalid
            assert "Unrecognized option unsupported_option" in (
                invalid.stdout + invalid.stderr
            )
        else:
            with pytest.raises(RuntimeError, match="Unrecognized option unsupported_option"):
                _option_case(
                    engine,
                    tmp_path / f"invalid-option-{engine}",
                    "overwrite=>1, unsupported_option=>1",
                )

    assert all(coverage.values())

    evidence_target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if evidence_target:
        evidence_dir = Path(evidence_target)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        lock = load_lock()
        bng2 = oracle_perl._bng2_path()
        assert bng2 is not None
        artifacts = {}
        for engine in ("bng2", "bng3"):
            source = tmp_path / f"execute-{engine}" / engine
            for suffix in ("bngl", "xml"):
                original = source / f"model_hpp.{suffix}"
                target = evidence_dir / f"{engine}-hybrid.{suffix}"
                shutil.copy2(original, target)
                artifacts[f"{engine}.{suffix}"] = hashlib.sha256(
                    target.read_bytes()
                ).hexdigest()
        report = {
            "schema_version": 1,
            "slice": "issue-150-generate-hybrid-model-action-options",
            "acceptance_status": "partial; hybrid.execution inventory row remains uncovered",
            "source": {"revision": _git_revision(ROOT)},
            "oracles": {
                "bng2": {
                    "revision": _git_revision(bng2.parent),
                    "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                    "locked_source_revision": lock["sources"]["bionetgen"]["revision"],
                }
            },
            "cases": {
                identity: {
                    "passed": passed,
                    "reference": "pinned BNG2 generate_hybrid_model option contract",
                }
                for identity, passed in coverage.items()
            },
            "uncovered_inventory_rows": ["hybrid.execution"],
            "negative_control": {
                "case": "unknown generate_hybrid_model option",
                "bng2": "rejected",
                "bng3": "rejected",
            },
            "artifacts": artifacts,
        }
        (evidence_dir / "capability-coverage-150.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )


def _git_revision(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_qualification_evidence(
    temp: Path, bng2_xml: Path, native_runs, bng3_runs
) -> None:
    target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if not target:
        return
    evidence_dir = Path(target)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    lock = load_lock()
    bng2 = oracle_perl._bng2_path()
    nfsim = oracle_nfsim.nfsim_binary()
    assert bng2 is not None and nfsim is not None
    bng3_input = temp / f"bng3-{BASE_SEED}" / "hybrid.bngl"
    bng3_hpp = temp / f"bng3-{BASE_SEED}" / "hybrid_hpp.bngl"
    shutil.copy2(bng2_xml, evidence_dir / "bng2-hybrid.xml")
    shutil.copy2(bng3_hpp, evidence_dir / "bng3-hybrid.bngl")
    with (evidence_dir / "trajectories.csv").open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("engine", "seed", "time", "A_total", "B_total"))
        for label, runs in (("native-nfsim", native_runs), ("bng3", bng3_runs)):
            for index, (data, columns) in enumerate(runs):
                for row in data:
                    writer.writerow(
                        (
                            label,
                            BASE_SEED + index,
                            row[columns.index("time")],
                            row[columns.index("A_total")],
                            row[columns.index("B_total")],
                        )
                    )
    bng3_input_bytes = bng3_input.read_bytes()
    bng3_hpp_bytes = bng3_hpp.read_bytes()
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    stochastic_result = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    report = {
        "schema_version": 1,
        "checks": ["release-hybrid", "release-hybrid-conservation"],
        "source": {"revision": _git_revision(ROOT), "dirty": dirty},
        "subject": {
            "input_model_sha256": hashlib.sha256(bng3_input_bytes).hexdigest(),
            "generated_hpp_path": "bng3-hybrid.bngl",
            "generated_hpp_sha256": hashlib.sha256(bng3_hpp_bytes).hexdigest(),
        },
        "references": {
            "bng2": {
                "revision": _git_revision(bng2.parent),
                "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                "hybrid_xml_sha256": hashlib.sha256(bng2_xml.read_bytes()).hexdigest(),
            },
            "nfsim": {
                "revision": lock["sources"]["nfsim"]["revision"],
                "artifact_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
            },
        },
        "budget": {
            "runs_per_engine": RUNS,
            "first_seed": BASE_SEED,
            "last_seed": BASE_SEED + RUNS - 1,
            "t_end": T_END,
            "n_steps": N_STEPS,
        },
        "distributional_comparison": {
            "passed": stochastic_result.ok,
            "n_sigma": 4.0,
            "max_violation_fraction": 0.05,
            "column_mode": "exact",
            "violations": stochastic_result.n_violations,
            "points_checked": stochastic_result.n_points_checked,
            "worst_z": stochastic_result.worst_z,
            "summary": (
                f"{stochastic_result.n_violations}/{stochastic_result.n_points_checked} "
                "points exceeded mean +/- 4 pooled SE; "
                f"worst |z|={stochastic_result.worst_z:.2f} "
                f"at {stochastic_result.worst_col!r}"
            ),
        },
        "analytic_law": {
            "B_total": f"Binomial({INITIAL_B}, exp(-{K_MAKE} * time))",
            "A_total": f"Binomial({INITIAL_B}, 1 - exp(-{K_MAKE} * time))",
            "conservation": f"A_total + B_total = {INITIAL_B}",
            "checked": "binomial sample bounds and means within 6 analytic standard errors at each sampled time",
        },
        "trajectory_artifact": "trajectories.csv",
    }
    (evidence_dir / "qualification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


def _write_compartment_evidence(temp: Path, bng3_runs) -> None:
    target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if not target:
        return
    evidence_dir = Path(target)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    generated_hpp = temp / f"compartment-bng3-{BASE_SEED}" / "compartment_hpp.bngl"
    shutil.copy2(generated_hpp, evidence_dir / "compartment-hybrid.bngl")
    with (evidence_dir / "compartment-trajectories.csv").open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("engine", "seed", "time", "B1_total", "B2_total", "all_units"))
        for index, (data, columns) in enumerate(bng3_runs):
            for row in data:
                writer.writerow(
                    (
                        "bng3",
                        BASE_SEED + index,
                        row[columns.index("time")],
                        row[columns.index("B1_total")],
                        row[columns.index("B2_total")],
                        row[columns.index("all_units")],
                    )
                )
    report = {
        "schema_version": 1,
        "check": "analytic-hybrid-compartments",
        "source": {
            "revision": _git_revision(ROOT),
            "dirty": bool(
                subprocess.run(
                    ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            ),
        },
        "subject": {
            "generated_hpp_sha256": hashlib.sha256(generated_hpp.read_bytes()).hexdigest(),
        },
        "budget": {
            "runs_per_engine": RUNS,
            "first_seed": BASE_SEED,
            "last_seed": BASE_SEED + RUNS - 1,
            "t_end": T_END,
            "n_steps": N_STEPS,
        },
        "laws": {
            "B1_total": f"Binomial({INITIAL_B}, 1 - exp(-100 * time))",
            "B2_total": f"Binomial({INITIAL_B}, 1 - exp(-0.1 * time))",
            "all_units": "A + B1 + B2 + P = 40 at every sample",
            "mean_control": "6 analytic standard errors at every sampled time",
        },
        "oracle": "independent analytic binomial marginal laws",
        "trajectory_artifact": "compartment-trajectories.csv",
    }
    (evidence_dir / "compartment-qualification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )


@pytest.fixture(scope="module")
def hybrid_ensembles(tmp_path_factory):
    """One immutable oracle pairing and fixed seed budget for all HPP checks."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid")
    bng2_xml = _run_bng2_hybrid(temp / "bng2")
    native_runs = _run_native_ensemble(bng2_xml, temp)
    bng3_runs = _run_bng3_ensemble(temp)
    _write_qualification_evidence(temp, bng2_xml, native_runs, bng3_runs)
    return native_runs, bng3_runs


@pytest.fixture(scope="module")
def compartment_hybrid_ensembles(tmp_path_factory):
    """Check compartment-preserving hybrid trajectories against analytic laws."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-compartments")
    bng3_runs = _run_bng3_compartment_ensemble(temp)
    _write_compartment_evidence(temp, bng3_runs)
    return bng3_runs


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_hybrid_bng2_native_nfsim_and_bng3_trajectories(hybrid_ensembles):
    """Compare generated HPP distributions against independent native NFsim."""
    native_runs, bng3_runs = hybrid_ensembles

    difference = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert difference.ok, difference.summary()


@pytest.mark.nf
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_hybrid_conservation_and_analytic_conversion_law(hybrid_ensembles):
    """Check conversion observables and molecule conservation against source law."""
    native_runs, bng3_runs = hybrid_ensembles

    # BNG2/NFsim and BNG3 use different RNG construction and draw schedules.
    # Compare distributions, never pathwise trajectories. The B_total marginal
    # is exactly Binomial(N, exp(-k_make*t)); A_total is its complement because
    # A->A_pop changes representation without changing molecule multiplicity.
    survival = lambda times: np.exp(-K_MAKE * times)
    production = lambda times: 1.0 - survival(times)
    for label, runs in (("native NFsim", native_runs), ("BNG3", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs, "B_total", population=INITIAL_B, probability=survival, label=label
        )
        compare.qualify_binomial_marginal(
            runs, "A_total", population=INITIAL_B, probability=production, label=label
        )
        for data, columns in runs:
            a = data[:, columns.index("A_total")]
            b = data[:, columns.index("B_total")]
            assert np.array_equal(a + b, np.full_like(a, INITIAL_B)), (
                f"{label}: A/B molecule conservation violated"
            )


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_hybrid_compartment_rates_and_conservation(compartment_hybrid_ensembles):
    """Check compartment rates and observables against independent laws."""
    bng3_runs = compartment_hybrid_ensembles
    fast_production = lambda times: 1.0 - np.exp(-100.0 * times)
    slow_production = lambda times: 1.0 - np.exp(-0.1 * times)
    compare.qualify_binomial_marginal(
        bng3_runs,
        "B1_total",
        population=INITIAL_B,
        probability=fast_production,
        label="BNG3 compartment c1",
    )
    compare.qualify_binomial_marginal(
        bng3_runs,
        "B2_total",
        population=INITIAL_B,
        probability=slow_production,
        label="BNG3 compartment c2",
    )
    for data, columns in bng3_runs:
        assert np.array_equal(
            data[:, columns.index("all_units")],
            np.full(data.shape[0], 2 * INITIAL_B),
        ), "BNG3 compartmental molecule conservation violated"

