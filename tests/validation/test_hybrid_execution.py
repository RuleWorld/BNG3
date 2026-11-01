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
INITIAL_DIMERS = 8
K_DIMER_OFF = 1.5
T_DIMER = 0.5
K_CYCLE_FORWARD = 2.0
K_CYCLE_REVERSE = 1.0
T_CYCLE = 1.0
N_CYCLE_STEPS = 10
K_PROTOCOL_RATE = 10.0
K_PROTOCOL_INITIAL = 0.1
T_PROTOCOL = 0.1
N_PROTOCOL_STEPS = 4
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

DIMER_CONVERSION_MODEL = f"""begin model
begin parameters
  k_off {K_DIMER_OFF}
  N {INITIAL_DIMERS}
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x!1).A(x!1) N
end seed species
begin observables
  Molecules A_units A()
  Species Dimer_species A==2
end observables
begin reaction rules
  A(x!1).A(x!1) -> A(x) + A(x) k_off
end reaction rules
begin population maps
  A(x!1).A(x!1) -> Dimer_pop() k_off
end population maps
end model
"""

CYCLE_CONVERSION_MODEL = f"""begin model
begin parameters
  k_forward {K_CYCLE_FORWARD}
  k_reverse {K_CYCLE_REVERSE}
  k_map 0.1
  N {INITIAL_B}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin population types
  A_pop()
end population types
begin seed species
  A() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  A() -> B() k_forward
  B() -> A() k_reverse
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
end model
"""

PROTOCOL_CONVERSION_MODEL = MODEL.replace(
    f"k_make {K_MAKE}", f"k_make {K_PROTOCOL_INITIAL}"
).replace(
    "begin seed species",
    "begin population types\n  A_pop()\nend population types\nbegin seed species",
)

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

COMPARTMENT_NATIVE_MODEL = f"""begin model
begin parameters
  k_fast 100
  k_slow 0.1
  k_map 100
  N {INITIAL_B}
end parameters
begin compartments
  c1 3 1
  c2 3 1
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
  Molecules c1_A @c1:A()
  Molecules c2_A @c2:A()
  Molecules B1_total B1()
  Molecules B2_total B2()
  Molecules all_units A(),B1(),B2()
end observables
begin reaction rules
  @c1:A() -> @c1:B1() k_fast
  @c2:A() -> @c2:B2() k_slow
end reaction rules
begin population maps
  c1: @c1:A() -> P1() k_map
  c2: @c2:A() -> P2() k_map
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


def _run_bng2_dimer_hybrid(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    source = tmp_path / "dimer.bngl"
    source.write_text(
        DIMER_CONVERSION_MODEL
        + '\nbegin actions\n'
        + 'generate_hybrid_model({overwrite=>1, execute=>1, actions=>["writeXML()"]})\n'
        + "end actions\n"
    )
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    result = subprocess.run(
        [os.environ.get("PERL", "perl"), str(bng2), str(source)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    xml = tmp_path / "dimer_hpp.xml"
    assert xml.is_file() and xml.stat().st_size, result.stderr
    return xml, source


def _run_native_dimer_ensemble(xml: Path, tmp_path: Path):
    # Species observables need NFsim's complex bookkeeping enabled.
    binary = _locked_native_nfsim()
    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"native-dimer-{seed}"
        work_dir.mkdir()
        output = work_dir / "dimer.gdat"
        result = subprocess.run(
            [
                str(binary), "-xml", str(xml), "-o", str(output),
                "-sim", str(T_DIMER), "-oSteps", str(N_STEPS), "-seed", str(seed),
                "-cb",
            ],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"native NFsim seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_bng3_dimer_ensemble(tmp_path: Path):
    import bionetgen

    runs = []
    first_hpp = None
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"bng3-dimer-{seed}"
        work_dir.mkdir()
        action = (
            "generate_hybrid_model({overwrite=>1, execute=>1, "
            f'actions=>["simulate_nf({{t_end=>{T_DIMER}, '
            f'n_steps=>{N_STEPS}, seed=>{seed}}})"]}})'
        )
        source = work_dir / "dimer.bngl"
        source.write_text(
            DIMER_CONVERSION_MODEL + f"\nbegin actions\n{action}\nend actions\n"
        )
        bionetgen.load(source).execute()
        output = work_dir / "dimer_hpp.gdat"
        assert output.is_file(), f"BNG3 seed {seed}: missing dimer trajectory"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 seed {seed}: malformed dimer trajectory"
        runs.append((data, columns))
        if first_hpp is None:
            first_hpp = work_dir / "dimer_hpp.bngl"
    assert first_hpp is not None and first_hpp.is_file()
    return runs, first_hpp


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


def _run_compartment_native_pair(tmp_path: Path):
    """Run a two-compartment HPP through BNG3 and native NFsim independently."""
    import bionetgen

    bng3_runs = []
    xml = None
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"compartment-native-bng3-{seed}"
        work_dir.mkdir()
        action = (
            "generate_hybrid_model({overwrite=>1, execute=>1, "
            'actions=>["writeXML()", '
            f'"simulate_nf({{t_end=>{T_END}, n_steps=>{N_STEPS}, seed=>{seed}}})"]}})'
        )
        source = work_dir / "compartment.bngl"
        source.write_text(
            COMPARTMENT_NATIVE_MODEL
            + f"\nbegin actions\n{action}\nend actions\n"
        )
        bionetgen.load(source).execute()
        output = work_dir / "compartment_hpp.gdat"
        assert output.is_file(), f"BNG3 compartment seed {seed}: missing .gdat"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 compartment seed {seed}: malformed trajectory"
        bng3_runs.append((data, columns))
        if xml is None:
            xml = work_dir / "compartment_hpp.xml"
            assert xml.is_file(), "BNG3 did not emit the compartment HPP XML"

    assert xml is not None
    native_runs = _run_native_ensemble(xml, tmp_path)
    return native_runs, bng3_runs, xml


def _write_cycle_source(path: Path, *, engine: str, seed: int | None = None) -> Path:
    if engine == "bng2":
        action = (
            'generate_hybrid_model({overwrite=>1, execute=>1, '
            'actions=>["writeXML()"]})'
        )
    elif engine == "bng3":
        assert seed is not None
        action = (
            "generate_hybrid_model({overwrite=>1, execute=>1, "
            f'actions=>["simulate_nf({{t_end=>{T_CYCLE}, '
            f'n_steps=>{N_CYCLE_STEPS}, seed=>{seed}}})"]}})'
        )
    else:
        raise ValueError(engine)
    path.write_text(CYCLE_CONVERSION_MODEL + f"\nbegin actions\n{action}\nend actions\n")
    return path


def _run_bng2_cycle_hybrid(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    source = _write_cycle_source(tmp_path / "cycle.bngl", engine="bng2")
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    result = subprocess.run(
        [os.environ.get("PERL", "perl"), str(bng2), "--outdir", str(tmp_path), str(source)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    xml = tmp_path / "cycle_hpp.xml"
    assert xml.is_file() and xml.stat().st_size, result.stderr
    return xml, source


def _run_native_cycle_ensemble(xml: Path, tmp_path: Path):
    _locked_native_nfsim()
    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        path, error = oracle_nfsim.run_nfsim(
            xml,
            tmp_path / f"native-cycle-{seed}",
            t_end=T_CYCLE,
            n_steps=N_CYCLE_STEPS,
            seed=seed,
        )
        assert path is not None, f"native NFsim cycle seed {seed}: {error}"
        data, columns = compare.parse_gdat(path)
        assert data is not None, f"native NFsim cycle seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_bng3_cycle_ensemble(tmp_path: Path):
    import bionetgen

    runs = []
    first_hpp = None
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"bng3-cycle-{seed}"
        work_dir.mkdir()
        source = _write_cycle_source(
            work_dir / "cycle.bngl", engine="bng3", seed=seed
        )
        bionetgen.load(source).execute()
        output = work_dir / "cycle_hpp.gdat"
        assert output.is_file(), f"BNG3 cycle seed {seed}: missing trajectory"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 cycle seed {seed}: malformed trajectory"
        runs.append((data, columns))
        if first_hpp is None:
            first_hpp = work_dir / "cycle_hpp.bngl"
    assert first_hpp is not None and first_hpp.is_file()
    return runs, first_hpp


def _write_protocol_source(
    path: Path, *, engine: str, seed: int | None = None
) -> Path:
    if engine == "bng2":
        model = PROTOCOL_CONVERSION_MODEL.replace(
            f"k_make {K_PROTOCOL_INITIAL}", f"k_make {K_PROTOCOL_RATE}"
        )
        action = (
            'generate_hybrid_model({overwrite=>1, execute=>1, '
            'actions=>["writeXML()"]})'
        )
    elif engine == "bng3":
        assert seed is not None
        model = PROTOCOL_CONVERSION_MODEL.replace("end model\n", "")
        protocol = (
            f"\nbegin protocol\n"
            + f'  setParameter("k_make", {K_PROTOCOL_RATE})\n'
            + "  simulate_nf({"
            + f'prefix=>"protocol_hpp", t_end=>{T_PROTOCOL}, '
            + f"n_steps=>{N_PROTOCOL_STEPS}, seed=>{seed}"
            + "})\nend protocol\n"
        )
        action = (
            'generate_hybrid_model({overwrite=>1, execute=>1, '
            'actions=>["simulate_protocol()"]})'
        )
    else:
        raise ValueError(engine)
    path.write_text(
        model
        + (protocol if engine == "bng3" else "")
        + ("end model\n" if engine == "bng3" else "")
        + f"\nbegin actions\n{action}\nend actions\n"
    )
    return path


def _run_bng2_protocol_hybrid(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    source = _write_protocol_source(tmp_path / "protocol.bngl", engine="bng2")
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    env["PERL5LIB"] = str(bng2.parent / "Perl2")
    result = subprocess.run(
        [os.environ.get("PERL", "perl"), str(bng2), "--outdir", str(tmp_path), str(source)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    xml = tmp_path / "protocol_hpp.xml"
    assert xml.is_file() and xml.stat().st_size, result.stderr
    return xml


def _run_native_protocol_ensemble(xml: Path, tmp_path: Path):
    _locked_native_nfsim()
    runs = []
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        path, error = oracle_nfsim.run_nfsim(
            xml,
            tmp_path / f"native-protocol-{seed}",
            t_end=T_PROTOCOL,
            n_steps=N_PROTOCOL_STEPS,
            seed=seed,
        )
        assert path is not None, f"native NFsim protocol seed {seed}: {error}"
        data, columns = compare.parse_gdat(path)
        assert data is not None, f"native NFsim protocol seed {seed}: malformed trajectory"
        runs.append((data, columns))
    return runs


def _run_bng3_protocol_ensemble(tmp_path: Path):
    import bionetgen

    runs = []
    first_hpp = None
    for seed in range(BASE_SEED, BASE_SEED + RUNS):
        work_dir = tmp_path / f"bng3-protocol-{seed}"
        work_dir.mkdir()
        source = _write_protocol_source(
            work_dir / "protocol.bngl", engine="bng3", seed=seed
        )
        bionetgen.load(source).execute()
        output = work_dir / "protocol_hpp.gdat"
        assert output.is_file(), f"BNG3 protocol seed {seed}: missing trajectory"
        data, columns = compare.parse_gdat(output)
        assert data is not None, f"BNG3 protocol seed {seed}: malformed trajectory"
        runs.append((data, columns))
        if first_hpp is None:
            first_hpp = work_dir / "protocol_hpp.bngl"
    assert first_hpp is not None and first_hpp.is_file()
    return runs, first_hpp


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


def _check_hybrid_model_action_options(
    tmp_path, capfd, *, write_slice_evidence: bool = True
):
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
    if evidence_target and write_slice_evidence:
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
            "scope": "generate_hybrid_model action options only",
            "coverage_check": "release-capability-coverage-150",
            "source": {
                "revision": _git_revision(ROOT),
                "dirty": bool(
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(ROOT),
                            "status",
                            "--porcelain",
                            "--untracked-files=no",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                ),
            },
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
    return coverage


@pytest.mark.nf
@pytest.mark.parity
def test_issue_150_generate_hybrid_model_action_options(tmp_path, capfd):
    _check_hybrid_model_action_options(tmp_path, capfd)


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


def _write_native_compartment_evidence(
    xml: Path, native_runs, bng3_runs, comparison
) -> None:
    target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if not target:
        return
    evidence_dir = Path(target)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_xml = evidence_dir / "bng3-compartment-hybrid.xml"
    shutil.copy2(xml, evidence_xml)
    with (evidence_dir / "native-compartment-trajectories.csv").open(
        "w", newline=""
    ) as output:
        writer = csv.writer(output)
        writer.writerow(
            ("engine", "seed", "time", "A_total", "B1_total", "B2_total", "all_units")
        )
        for label, runs in (("native-nfsim", native_runs), ("bng3", bng3_runs)):
            for index, (data, columns) in enumerate(runs):
                for row in data:
                    writer.writerow(
                        (
                            label,
                            BASE_SEED + index,
                            row[columns.index("time")],
                            row[columns.index("A_total")],
                            row[columns.index("B1_total")],
                            row[columns.index("B2_total")],
                            row[columns.index("all_units")],
                        )
                    )
    lock = load_lock()
    nfsim = _locked_native_nfsim()
    report = {
        "schema_version": 1,
        "slice": "independent-native-nfsim-compartment-hpp",
        "acceptance_status": "partial; canonical BNG2 hybrid transformation does not support compartments",
        "source": {"revision": _git_revision(ROOT)},
        "subject": {"xml_sha256": hashlib.sha256(evidence_xml.read_bytes()).hexdigest()},
        "oracle": {
            "engine": "native NFsim",
            "revision": lock["sources"]["nfsim"]["revision"],
            "binary_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
        },
        "budget": {
            "runs_per_engine": RUNS,
            "first_seed": BASE_SEED,
            "last_seed": BASE_SEED + RUNS - 1,
            "t_end": T_END,
            "n_steps": N_STEPS,
        },
        "distributional_comparison": {
            "passed": comparison.ok,
            "n_sigma": 4.0,
            "max_violation_fraction": 0.05,
            "violations": comparison.n_violations,
            "points_checked": comparison.n_points_checked,
            "worst_z": comparison.worst_z,
        },
        "analytic_laws": {
            "B1_total": f"Binomial({INITIAL_B}, 1 - exp(-100 * time))",
            "B2_total": f"Binomial({INITIAL_B}, 1 - exp(-0.1 * time))",
            "A_total + B1_total + B2_total": "40 at every output sample",
            "all_units": "40 at every output sample",
        },
        "trajectory_artifact": "native-compartment-trajectories.csv",
    }
    (evidence_dir / "native-compartment-qualification.json").write_text(
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
def hybrid_dimer_ensembles(tmp_path_factory):
    """Independent native and BNG3 trajectories for whole-dimer conversion."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    require_oracle(
        oracle_perl._bng2_path() is not None,
        "pinned BNG2 unavailable (set BNG2_PERL)",
    )
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-dimer")
    xml, bng2_source = _run_bng2_dimer_hybrid(temp / "bng2")
    native_runs = _run_native_dimer_ensemble(xml, temp)
    bng3_runs, hpp = _run_bng3_dimer_ensemble(temp)
    return native_runs, bng3_runs, xml, hpp, bng2_source


@pytest.fixture(scope="module")
def hybrid_conversion_cycle_ensembles(tmp_path_factory):
    """Run a mapped A↔B cycle through BNG2/native NFsim and BNG3."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    require_oracle(
        oracle_perl._bng2_path() is not None,
        "pinned BNG2 unavailable (set BNG2_PERL)",
    )
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-cycle")
    xml, source = _run_bng2_cycle_hybrid(temp / "bng2")
    native_runs = _run_native_cycle_ensemble(xml, temp)
    bng3_runs, hpp = _run_bng3_cycle_ensemble(temp)
    return native_runs, bng3_runs, xml, hpp, source


@pytest.fixture(scope="module")
def hybrid_protocol_ensembles(tmp_path_factory):
    """Compare BNG3's pre-run parameter assignment with the equivalent static HPP."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    require_oracle(
        oracle_perl._bng2_path() is not None,
        "pinned BNG2 unavailable (set BNG2_PERL)",
    )
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-protocol")
    xml = _run_bng2_protocol_hybrid(temp / "bng2")
    native_runs = _run_native_protocol_ensemble(xml, temp)
    bng3_runs, hpp = _run_bng3_protocol_ensemble(temp)
    return native_runs, bng3_runs, xml, hpp


@pytest.fixture(scope="module")
def compartment_hybrid_ensembles(tmp_path_factory):
    """Check compartment-preserving hybrid trajectories against analytic laws."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-compartments")
    bng3_runs = _run_bng3_compartment_ensemble(temp)
    _write_compartment_evidence(temp, bng3_runs)
    return bng3_runs


@pytest.fixture(scope="module")
def native_compartment_hybrid_ensembles(tmp_path_factory):
    """Use pinned native NFsim to run a BNG3-generated compartment HPP XML."""
    require_oracle(runner.api_available(), "compiled BNG3 API unavailable")
    runner._ensure_source_python_path()
    temp = tmp_path_factory.mktemp("release-hybrid-compartment-native")
    return _run_compartment_native_pair(temp)


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
def test_release_hybrid_population_particle_conversion_cycle(
    hybrid_conversion_cycle_ensembles,
):
    """Qualify reversible particle/population transitions against an exact CTMC law."""
    native_runs, bng3_runs, xml, hpp, source = hybrid_conversion_cycle_ensembles
    comparison = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert comparison.ok, comparison.summary()

    forward = K_CYCLE_FORWARD
    reverse = K_CYCLE_REVERSE
    probability_b = lambda times: (forward / (forward + reverse)) * (
        1.0 - np.exp(-(forward + reverse) * times)
    )
    probability_a = lambda times: 1.0 - probability_b(times)
    for label, runs in (("native NFsim", native_runs), ("BNG3", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs,
            "B_total",
            population=INITIAL_B,
            probability=probability_b,
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "A_total",
            population=INITIAL_B,
            probability=probability_a,
            label=label,
        )
        for data, columns in runs:
            a = data[:, columns.index("A_total")]
            b = data[:, columns.index("B_total")]
            assert np.array_equal(a + b, np.full_like(a, INITIAL_B)), (
                f"{label}: population/particle conservation violated"
            )

    evidence_target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if evidence_target:
        evidence_dir = Path(evidence_target)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml, evidence_dir / "bng2-cycle-hybrid.xml")
        shutil.copy2(hpp, evidence_dir / "bng3-cycle-hybrid.bngl")
        with (evidence_dir / "cycle-trajectories.csv").open(
            "w", newline=""
        ) as output:
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
        bng2 = oracle_perl._bng2_path()
        nfsim = _locked_native_nfsim()
        assert bng2 is not None
        lock = load_lock()
        report = {
            "schema_version": 1,
            "checks": ["release-hybrid", "release-hybrid-conservation"],
            "case": "reversible particle-to-population conversion cycle",
            "source": {
                "revision": _git_revision(ROOT),
                "bng2_input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "bng3_hpp_sha256": hashlib.sha256(hpp.read_bytes()).hexdigest(),
            },
            "oracles": {
                "bng2": {
                    "revision": _git_revision(bng2.parent),
                    "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                    "xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                },
                "native_nfsim": {
                    "revision": lock["sources"]["nfsim"]["revision"],
                    "binary_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
                },
            },
            "budget": {
                "runs_per_engine": RUNS,
                "first_seed": BASE_SEED,
                "last_seed": BASE_SEED + RUNS - 1,
                "t_end": T_CYCLE,
                "n_steps": N_CYCLE_STEPS,
            },
            "distributional_comparison": {
                "passed": comparison.ok,
                "n_sigma": 4.0,
                "max_violation_fraction": 0.05,
                "violations": comparison.n_violations,
                "points_checked": comparison.n_points_checked,
                "worst_z": comparison.worst_z,
            },
            "analytic_law": {
                "B_total": (
                    f"Binomial({INITIAL_B}, {K_CYCLE_FORWARD}/"
                    f"({K_CYCLE_FORWARD}+{K_CYCLE_REVERSE}) * "
                    f"(1-exp(-({K_CYCLE_FORWARD}+{K_CYCLE_REVERSE})*time)))"
                ),
                "A_total": f"{INITIAL_B} - B_total",
                "conservation": f"A_total + B_total = {INITIAL_B}",
                "trajectory_artifact": "cycle-trajectories.csv",
            },
        }
        (evidence_dir / "conversion-cycle-qualification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_hybrid_protocol_parameter_rate_and_conservation(
    hybrid_protocol_ensembles,
):
    """Qualify a protocol rate assignment before the hybrid trajectory starts."""
    native_runs, bng3_runs, xml, hpp = hybrid_protocol_ensembles
    comparison = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert comparison.ok, comparison.summary()

    survival = lambda times: np.exp(-K_PROTOCOL_RATE * times)
    production = lambda times: 1.0 - survival(times)
    for label, runs in (("native NFsim", native_runs), ("BNG3 protocol", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs,
            "B_total",
            population=INITIAL_B,
            probability=survival,
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "A_total",
            population=INITIAL_B,
            probability=production,
            label=label,
        )
        for data, columns in runs:
            a = data[:, columns.index("A_total")]
            b = data[:, columns.index("B_total")]
            assert np.array_equal(a + b, np.full_like(a, INITIAL_B))

    evidence_target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if evidence_target:
        evidence_dir = Path(evidence_target)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml, evidence_dir / "bng2-protocol-hybrid.xml")
        shutil.copy2(hpp, evidence_dir / "bng3-protocol-hybrid.bngl")
        with (evidence_dir / "protocol-trajectories.csv").open(
            "w", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(("engine", "seed", "time", "A_total", "B_total"))
            for label, runs in (("native-nfsim", native_runs), ("bng3-protocol", bng3_runs)):
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
        bng2 = oracle_perl._bng2_path()
        nfsim = _locked_native_nfsim()
        assert bng2 is not None
        lock = load_lock()
        report = {
            "schema_version": 1,
            "checks": ["release-hybrid", "release-hybrid-conservation"],
            "case": "pre-run protocol parameter assignment",
            "source": {
                "revision": _git_revision(ROOT),
                "native_reference_xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                "bng3_hpp_sha256": hashlib.sha256(hpp.read_bytes()).hexdigest(),
            },
            "oracles": {
                "bng2": {
                    "revision": _git_revision(bng2.parent),
                    "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                },
                "native_nfsim": {
                    "revision": lock["sources"]["nfsim"]["revision"],
                    "binary_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
                },
            },
            "protocol": {
                "initial_parameter": K_PROTOCOL_INITIAL,
                "assigned_parameter": K_PROTOCOL_RATE,
                "assignment_occurs_before_simulation": True,
            },
            "budget": {
                "runs_per_engine": RUNS,
                "first_seed": BASE_SEED,
                "last_seed": BASE_SEED + RUNS - 1,
                "t_end": T_PROTOCOL,
                "n_steps": N_PROTOCOL_STEPS,
            },
            "distributional_comparison": {
                "passed": comparison.ok,
                "n_sigma": 4.0,
                "max_violation_fraction": 0.05,
                "violations": comparison.n_violations,
                "points_checked": comparison.n_points_checked,
                "worst_z": comparison.worst_z,
            },
            "analytic_law": {
                "B_total": f"Binomial({INITIAL_B}, exp(-{K_PROTOCOL_RATE} * time))",
                "A_total": f"Binomial({INITIAL_B}, 1 - exp(-{K_PROTOCOL_RATE} * time))",
                "conservation": f"A_total + B_total = {INITIAL_B}",
                "trajectory_artifact": "protocol-trajectories.csv",
            },
        }
        (evidence_dir / "protocol-rate-qualification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_hybrid_whole_dimer_conversion_and_multiplicity(
    hybrid_dimer_ensembles,
):
    """Compare BNG2/native NFsim and BNG3 whole-complex population breakup."""
    native_runs, bng3_runs, xml, hpp, source = hybrid_dimer_ensembles
    comparison = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert comparison.ok, comparison.summary()

    survival = lambda times: np.exp(-K_DIMER_OFF * times)
    for label, runs in (("native NFsim", native_runs), ("BNG3", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs,
            "Dimer_species",
            population=INITIAL_DIMERS,
            probability=survival,
            label=label,
        )
        for data, columns in runs:
            dimers = data[:, columns.index("Dimer_species")]
            units = data[:, columns.index("A_units")]
            assert np.array_equal(
                units, np.full_like(units, 2 * INITIAL_DIMERS)
            ), f"{label}: whole-complex conversion lost molecule multiplicity"
            assert np.all(dimers >= 0)

    evidence_target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if evidence_target:
        evidence_dir = Path(evidence_target)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xml, evidence_dir / "bng2-dimer-hybrid.xml")
        shutil.copy2(hpp, evidence_dir / "bng3-dimer-hybrid.bngl")
        with (evidence_dir / "dimer-trajectories.csv").open(
            "w", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(("engine", "seed", "time", "Dimer_species", "A_units"))
            for label, runs in (("native-nfsim", native_runs), ("bng3", bng3_runs)):
                for index, (data, columns) in enumerate(runs):
                    for row in data:
                        writer.writerow(
                            (
                                label,
                                BASE_SEED + index,
                                row[columns.index("time")],
                                row[columns.index("Dimer_species")],
                                row[columns.index("A_units")],
                            )
                        )

        bng2 = oracle_perl._bng2_path()
        nfsim = _locked_native_nfsim()
        lock = load_lock()
        report = {
            "schema_version": 1,
            "check_slice": "whole-complex-dimer-conversion",
            "checks": ["release-hybrid", "release-hybrid-conservation"],
            "source": {
                "revision": _git_revision(ROOT),
                "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            "references": {
                "bng2": {
                    "revision": _git_revision(bng2.parent),
                    "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                    "xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                    "locked_source_revision": lock["sources"]["bionetgen"]["revision"],
                },
                "native_nfsim": {
                    "revision": lock["sources"]["nfsim"]["revision"],
                    "binary_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
                    "options": ["-cb"],
                },
            },
            "budget": {
                "runs_per_engine": RUNS,
                "first_seed": BASE_SEED,
                "last_seed": BASE_SEED + RUNS - 1,
                "t_end": T_DIMER,
                "n_steps": N_STEPS,
            },
            "comparison": {
                "passed": comparison.ok,
                "n_sigma": 4.0,
                "max_violation_fraction": 0.05,
                "violations": comparison.n_violations,
                "points_checked": comparison.n_points_checked,
                "worst_z": comparison.worst_z,
            },
            "analytic_law": {
                "Dimer_species": f"Binomial({INITIAL_DIMERS}, exp(-{K_DIMER_OFF} * time))",
                "A_units": f"2 * {INITIAL_DIMERS} conserved at each sample",
                "trajectory_artifact": "dimer-trajectories.csv",
                "bng3_hpp_sha256": hashlib.sha256(hpp.read_bytes()).hexdigest(),
            },
        }
        (evidence_dir / "dimer-qualification.json").write_text(
            json.dumps(report, indent=2) + "\n"
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


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_hybrid_compartment_distribution_against_locked_native_nfsim(
    native_compartment_hybrid_ensembles,
):
    """Compare a BNG3 compartment HPP with native NFsim and analytic laws."""
    native_runs, bng3_runs, xml = native_compartment_hybrid_ensembles
    comparison = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert comparison.ok, comparison.summary()

    for label, runs in (("native NFsim", native_runs), ("BNG3", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs,
            "B1_total",
            population=INITIAL_B,
            probability=lambda times: 1.0 - np.exp(-100.0 * times),
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "B2_total",
            population=INITIAL_B,
            probability=lambda times: 1.0 - np.exp(-0.1 * times),
            label=label,
        )
        for data, columns in runs:
            a = data[:, columns.index("A_total")]
            b1 = data[:, columns.index("B1_total")]
            b2 = data[:, columns.index("B2_total")]
            units = data[:, columns.index("all_units")]
            total = np.full_like(a, 2 * INITIAL_B)
            assert np.array_equal(a + b1 + b2, total)
            assert np.array_equal(units, total)

    _write_native_compartment_evidence(xml, native_runs, bng3_runs, comparison)


@pytest.mark.nf
@pytest.mark.parity
@pytest.mark.stochastic
@pytest.mark.slow
def test_release_capability_coverage_150(
    tmp_path,
    capfd,
    hybrid_ensembles,
    hybrid_dimer_ensembles,
    hybrid_conversion_cycle_ensembles,
    hybrid_protocol_ensembles,
):
    """Run every assigned #150 inventory row against its named oracle."""
    action_cases = _check_hybrid_model_action_options(
        tmp_path / "action-options", capfd, write_slice_evidence=False
    )

    native_runs, bng3_runs = hybrid_ensembles
    hybrid_comparison = compare.compare_stochastic(
        native_runs,
        bng3_runs,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert hybrid_comparison.ok, hybrid_comparison.summary()
    for label, runs in (("native NFsim", native_runs), ("BNG3", bng3_runs)):
        compare.qualify_binomial_marginal(
            runs,
            "B_total",
            population=INITIAL_B,
            probability=lambda times: np.exp(-K_MAKE * times),
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "A_total",
            population=INITIAL_B,
            probability=lambda times: 1.0 - np.exp(-K_MAKE * times),
            label=label,
        )
        for data, columns in runs:
            total = data[:, columns.index("A_total")] + data[:, columns.index("B_total")]
            assert np.array_equal(total, np.full_like(total, INITIAL_B))

    native_dimers, bng3_dimers, dimer_xml, dimer_hpp, dimer_source = (
        hybrid_dimer_ensembles
    )
    dimer_comparison = compare.compare_stochastic(
        native_dimers,
        bng3_dimers,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert dimer_comparison.ok, dimer_comparison.summary()
    for label, runs in (("native NFsim", native_dimers), ("BNG3", bng3_dimers)):
        compare.qualify_binomial_marginal(
            runs,
            "Dimer_species",
            population=INITIAL_DIMERS,
            probability=lambda times: np.exp(-K_DIMER_OFF * times),
            label=label,
        )
        for data, columns in runs:
            units = data[:, columns.index("A_units")]
            assert np.array_equal(units, np.full_like(units, 2 * INITIAL_DIMERS))

    native_cycle, bng3_cycle, cycle_xml, cycle_hpp, cycle_source = (
        hybrid_conversion_cycle_ensembles
    )
    cycle_comparison = compare.compare_stochastic(
        native_cycle,
        bng3_cycle,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert cycle_comparison.ok, cycle_comparison.summary()
    cycle_probability_b = lambda times: (K_CYCLE_FORWARD / (K_CYCLE_FORWARD + K_CYCLE_REVERSE)) * (
        1.0 - np.exp(-(K_CYCLE_FORWARD + K_CYCLE_REVERSE) * times)
    )
    for label, runs in (("native NFsim", native_cycle), ("BNG3", bng3_cycle)):
        compare.qualify_binomial_marginal(
            runs,
            "B_total",
            population=INITIAL_B,
            probability=cycle_probability_b,
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "A_total",
            population=INITIAL_B,
            probability=lambda times: 1.0 - cycle_probability_b(times),
            label=label,
        )
        for data, columns in runs:
            total = data[:, columns.index("A_total")] + data[:, columns.index("B_total")]
            assert np.array_equal(total, np.full_like(total, INITIAL_B))

    native_protocol, bng3_protocol, protocol_xml, protocol_hpp = (
        hybrid_protocol_ensembles
    )
    protocol_comparison = compare.compare_stochastic(
        native_protocol,
        bng3_protocol,
        n_sigma=4.0,
        max_violation_frac=0.05,
        min_ref_runs=RUNS,
        min_test_runs=RUNS,
        columns=compare.COLUMNS_EXACT,
    )
    assert protocol_comparison.ok, protocol_comparison.summary()
    protocol_survival = lambda times: np.exp(-K_PROTOCOL_RATE * times)
    for label, runs in (("native NFsim", native_protocol), ("BNG3", bng3_protocol)):
        compare.qualify_binomial_marginal(
            runs,
            "B_total",
            population=INITIAL_B,
            probability=protocol_survival,
            label=label,
        )
        compare.qualify_binomial_marginal(
            runs,
            "A_total",
            population=INITIAL_B,
            probability=lambda times: 1.0 - protocol_survival(times),
            label=label,
        )
        for data, columns in runs:
            total = data[:, columns.index("A_total")] + data[:, columns.index("B_total")]
            assert np.array_equal(total, np.full_like(total, INITIAL_B))

    inventory_cases = {
        **action_cases,
        "hybrid.execution": True,
    }
    assert len(inventory_cases) == 8 and all(inventory_cases.values())

    target = os.environ.get("BNG3_HYBRID_EVIDENCE_DIR")
    if target:
        evidence_dir = Path(target)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dimer_xml, evidence_dir / "bng2-dimer-hybrid.xml")
        shutil.copy2(dimer_hpp, evidence_dir / "bng3-dimer-hybrid.bngl")
        with (evidence_dir / "dimer-trajectories.csv").open(
            "w", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(("engine", "seed", "time", "Dimer_species", "A_units"))
            for label, runs in (("native-nfsim", native_dimers), ("bng3", bng3_dimers)):
                for index, (data, columns) in enumerate(runs):
                    for row in data:
                        writer.writerow(
                            (
                                label,
                                BASE_SEED + index,
                                row[columns.index("time")],
                                row[columns.index("Dimer_species")],
                                row[columns.index("A_units")],
                            )
                        )

        shutil.copy2(cycle_xml, evidence_dir / "bng2-cycle-hybrid.xml")
        shutil.copy2(cycle_hpp, evidence_dir / "bng3-cycle-hybrid.bngl")
        with (evidence_dir / "cycle-trajectories.csv").open(
            "w", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(("engine", "seed", "time", "A_total", "B_total"))
            for label, runs in (("native-nfsim", native_cycle), ("bng3", bng3_cycle)):
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

        shutil.copy2(protocol_xml, evidence_dir / "bng2-protocol-hybrid.xml")
        shutil.copy2(protocol_hpp, evidence_dir / "bng3-protocol-hybrid.bngl")
        with (evidence_dir / "protocol-trajectories.csv").open(
            "w", newline=""
        ) as output:
            writer = csv.writer(output)
            writer.writerow(("engine", "seed", "time", "A_total", "B_total"))
            for label, runs in (("native-nfsim", native_protocol), ("bng3", bng3_protocol)):
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

        bng2 = oracle_perl._bng2_path()
        nfsim = _locked_native_nfsim()
        assert bng2 is not None
        lock = load_lock()
        report = {
            "schema_version": 1,
            "checks": [
                "release-hybrid",
                "release-hybrid-conservation",
                "release-capability-coverage-150",
            ],
            "source": {
                "revision": _git_revision(ROOT),
                "dirty": bool(
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(ROOT),
                            "status",
                            "--porcelain",
                            "--untracked-files=no",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                ),
            },
            "oracles": {
                "bng2": {
                    "revision": _git_revision(bng2.parent),
                    "script_sha256": hashlib.sha256(bng2.read_bytes()).hexdigest(),
                    "locked_source_revision": lock["sources"]["bionetgen"]["revision"],
                },
                "native_nfsim": {
                    "revision": lock["sources"]["nfsim"]["revision"],
                    "binary_sha256": hashlib.sha256(nfsim.read_bytes()).hexdigest(),
                },
            },
            "inventory_cases": {
                identity: {"passed": True} for identity in inventory_cases
            },
            "budget": {
                "runs_per_engine": RUNS,
                "first_seed": BASE_SEED,
                "last_seed": BASE_SEED + RUNS - 1,
                "single_molecule": {"t_end": T_END, "samples": N_STEPS + 1},
                "dimer": {"t_end": T_DIMER, "samples": N_STEPS + 1},
                "conversion_cycle": {
                    "t_end": T_CYCLE,
                    "samples": N_CYCLE_STEPS + 1,
                },
                "protocol_rate_assignment": {
                    "effective_rate": K_PROTOCOL_RATE,
                    "t_end": T_PROTOCOL,
                    "samples": N_PROTOCOL_STEPS + 1,
                },
            },
            "distributional_comparison": {
                "columns": "exact",
                "n_sigma": 4.0,
                "max_violation_fraction": 0.05,
                "minimum_runs_per_engine": RUNS,
            },
            "scope": {
                "executed_cases": [
                    "generate_hybrid_model action defaults/options/errors",
                    "single-molecule B to A to A_pop conversion",
                    "whole A-A dimer population conversion and dissociation",
                    "reversible A_pop to B particle cycle with analytic CTMC law",
                    "protocol parameter assignment before hybrid simulation",
                ],
                "limitations": [
                    "canonical BNG2 generate_hybrid_model does not transform compartment models",
                    "dynamic threshold changes are not covered by this aggregate evidence",
                    "this evidence does not establish full #150 issue acceptance on main",
                ],
            },
            "issue_150_acceptance": "not established by this bounded PR artifact",
            "semantic_checks": {
                "release-hybrid": {
                    "passed": hybrid_comparison.ok,
                    "points_checked": hybrid_comparison.n_points_checked,
                    "violations": hybrid_comparison.n_violations,
                    "worst_z": hybrid_comparison.worst_z,
                    "runs_per_engine": RUNS,
                },
                "release-hybrid-conservation": {
                    "passed": True,
                    "analytic_laws": [
                        f"Binomial({INITIAL_B}, exp(-{K_MAKE} * time)) B_total",
                        f"Binomial({INITIAL_B}, 1 - exp(-{K_MAKE} * time)) A_total",
                        f"Binomial({INITIAL_DIMERS}, exp(-{K_DIMER_OFF} * time)) Dimer_species",
                        f"A_units = {2 * INITIAL_DIMERS} at every dimer sample",
                        (
                            f"Binomial({INITIAL_B}, {K_CYCLE_FORWARD}/"
                            f"({K_CYCLE_FORWARD}+{K_CYCLE_REVERSE}) * "
                            f"(1-exp(-({K_CYCLE_FORWARD}+{K_CYCLE_REVERSE})*time))) B_total"
                        ),
                        f"A_total + B_total = {INITIAL_B} at every cycle sample",
                        f"Binomial({INITIAL_B}, exp(-{K_PROTOCOL_RATE} * time)) B_total after pre-run protocol assignment",
                        f"A_total + B_total = {INITIAL_B} at every protocol sample",
                    ],
                },
                "whole_dimer_native_comparison": {
                    "passed": dimer_comparison.ok,
                    "points_checked": dimer_comparison.n_points_checked,
                    "violations": dimer_comparison.n_violations,
                    "worst_z": dimer_comparison.worst_z,
                    "runs_per_engine": RUNS,
                },
                "conversion_cycle_native_comparison": {
                    "passed": cycle_comparison.ok,
                    "points_checked": cycle_comparison.n_points_checked,
                    "violations": cycle_comparison.n_violations,
                    "worst_z": cycle_comparison.worst_z,
                    "runs_per_engine": RUNS,
                },
                "protocol_parameter_native_comparison": {
                    "passed": protocol_comparison.ok,
                    "points_checked": protocol_comparison.n_points_checked,
                    "violations": protocol_comparison.n_violations,
                    "worst_z": protocol_comparison.worst_z,
                    "runs_per_engine": RUNS,
                },
            },
            "artifacts": {
                "hybrid_qualification": "qualification.json",
                "hybrid_trajectories": "trajectories.csv",
                "dimer_xml_sha256": hashlib.sha256(dimer_xml.read_bytes()).hexdigest(),
                "dimer_hpp_sha256": hashlib.sha256(dimer_hpp.read_bytes()).hexdigest(),
                "dimer_source_sha256": hashlib.sha256(dimer_source.read_bytes()).hexdigest(),
                "dimer_trajectories": "dimer-trajectories.csv",
                "cycle_xml": "bng2-cycle-hybrid.xml",
                "cycle_xml_sha256": hashlib.sha256(cycle_xml.read_bytes()).hexdigest(),
                "cycle_hpp": "bng3-cycle-hybrid.bngl",
                "cycle_hpp_sha256": hashlib.sha256(cycle_hpp.read_bytes()).hexdigest(),
                "cycle_source_sha256": hashlib.sha256(cycle_source.read_bytes()).hexdigest(),
                "cycle_trajectories": "cycle-trajectories.csv",
                "protocol_xml": "bng2-protocol-hybrid.xml",
                "protocol_xml_sha256": hashlib.sha256(protocol_xml.read_bytes()).hexdigest(),
                "protocol_hpp": "bng3-protocol-hybrid.bngl",
                "protocol_hpp_sha256": hashlib.sha256(protocol_hpp.read_bytes()).hexdigest(),
                "protocol_trajectories": "protocol-trajectories.csv",
            },
        }
        (evidence_dir / "capability-coverage-150.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )

