"""Safe-Perl-compatible output-step expressions in declared actions."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare, runner
from tests.validation.strict import require_oracle
from tests.validation.test_export_formats import _locked_bng2_script


MODEL = """begin model
begin parameters
  N 3
  k 0.4
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  convert: A() -> B() k
end reaction rules
{declaration}end model
{action}
"""


@pytest.fixture(scope="module")
def locked_bng2() -> Path:
    script = _locked_bng2_script()
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(
        script is not None and perl is not None,
        "locked BNG2 checkout and Perl are required for action step-count parity",
    )
    assert script is not None
    assert perl is not None
    return script


def _source(entry: str, expression: str) -> str:
    if entry == "simulate_ode":
        return MODEL.format(
            declaration="",
            action=f"simulate_ode({{t_start=>0,t_end=>1,n_steps=>{expression}}})",
        )
    if entry == "simulate_ssa":
        return MODEL.format(
            declaration="",
            action=f"simulate_ssa({{t_start=>0,t_end=>1,n_steps=>{expression},seed=>1}})",
        )

    method = entry.removeprefix("simulate_method_")
    action = (
        f'simulate({{method=>"{method}",t_start=>0,t_end=>1,'
        f'n_steps=>{expression},seed=>1}})'
    )
    return MODEL.format(declaration=f"begin protocol\n{action}\nend protocol\n", action="simulate_protocol()")


def _run_bng2(script: Path, source: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["BNGPATH"] = str(script.parent)
    proc = subprocess.run(
        [
            os.environ.get("PERL", "perl"),
            str(script),
            "--outdir",
            str(out_dir),
            "--no-nfsim",
            str(source),
        ],
        cwd=source.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = out_dir / f"{source.stem}.gdat"
    assert proc.returncode == 0, f"pinned BNG2 action failed: {proc.stderr or proc.stdout}"
    assert output.is_file(), f"pinned BNG2 produced no .gdat: {proc.stderr or proc.stdout}"
    return output


ENTRIES = (
    "simulate_ode",
    "simulate_ssa",
    "simulate_method_ode",
    "simulate_method_ssa",
)


@pytest.mark.parametrize("entry", ENTRIES)
def test_double_star_n_steps_matches_locked_bng2(entry, bng_cpp, locked_bng2, tmp_path):
    source = tmp_path / f"{entry}_power.bngl"
    source.write_text(_source(entry, "2**3"), encoding="utf-8")

    reference_path = _run_bng2(locked_bng2, source, tmp_path / "bng2")
    _, generated_path, error = runner.run_cli_path(bng_cpp, source, tmp_path / "bng3")
    assert generated_path is not None, f"BNG3 action failed: {error}"

    reference, reference_columns = compare.parse_gdat(reference_path)
    generated, generated_columns = compare.parse_gdat(generated_path)
    assert reference is not None and generated is not None
    assert reference_columns == generated_columns
    assert reference.shape[0] == 9, "pinned BNG2 interprets 2**3 as eight intervals"
    assert np.array_equal(reference[:, 0], generated[:, 0]), (
        f"{entry} output times differ from locked BNG2 for n_steps=>2**3: "
        f"reference={reference[:, 0]}, BNG3={generated[:, 0]}"
    )


@pytest.mark.parametrize("entry", ENTRIES)
def test_caret_n_steps_is_refused_instead_of_reinterpreted(
    entry, bng_cpp, locked_bng2, tmp_path
):
    source = tmp_path / f"{entry}_xor.bngl"
    source.write_text(_source(entry, "2^3"), encoding="utf-8")

    reference_path = _run_bng2(locked_bng2, source, tmp_path / "bng2")
    reference, _ = compare.parse_gdat(reference_path)
    assert reference is not None
    assert np.array_equal(reference[:, 0], np.array([0.0, 1.0])), (
        "pinned BNG2 evaluates numeric ^ as Perl XOR, so 2^3 means one interval"
    )

    generated_path, _, error = runner.run_cli_path(
        bng_cpp, source, tmp_path / "bng3"
    )
    assert generated_path is None, "BNG3 must refuse ^ rather than exponentiate it"
    assert "2^3" in error, f"diagnostic must preserve raw n_steps spelling: {error}"
    assert "Safe-Perl" in error, f"expected an explicit semantic-boundary diagnostic: {error}"


def _gdat_rows(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def test_protocol_parameter_mutation_is_resolved_when_simulation_executes(
    bng_cpp, tmp_path
):
    source = tmp_path / "protocol_parameter_steps.bngl"
    source.write_text(
        MODEL.format(
            declaration=(
                'begin protocol\n'
                '  setParameter("N",4)\n'
                '  simulate({method=>"ode",t_start=>0,t_end=>1,n_steps=>N})\n'
                'end protocol\n'
            ),
            action="simulate_protocol()",
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(
        bng_cpp, source, tmp_path / "bng3"
    )
    assert generated_path is not None, f"protocol simulation failed: {error}"
    assert _gdat_rows(generated_path) == 5, (
        "setParameter must take effect before the later action resolves n_steps=>N"
    )


@pytest.mark.parametrize(
    ("inline_steps", "file_steps", "expected_rows"),
    ((None, "2**3", 9), ("4", "8", 5)),
)
def test_argfile_step_count_is_resolved_after_inline_precedence(
    bng_cpp, tmp_path, inline_steps, file_steps, expected_rows
):
    source = tmp_path / "argfile_steps.bngl"
    work_dir = tmp_path / "bng3"
    work_dir.mkdir()
    (work_dir / "steps.txt").write_text(
        f"n_steps {file_steps}\n", encoding="utf-8"
    )
    inline = "" if inline_steps is None else f"n_steps=>{inline_steps},"
    source.write_text(
        MODEL.format(
            declaration="",
            action=(
                "simulate_ode({t_start=>0,t_end=>1,"
                f'{inline}argfile=>"steps.txt"}})'
            ),
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(bng_cpp, source, work_dir)
    assert generated_path is not None, f"argfile simulation failed: {error}"
    assert _gdat_rows(generated_path) == expected_rows


def test_dynamic_exponent_uses_current_parameter_value(bng_cpp, tmp_path):
    source = tmp_path / "dynamic_power_steps.bngl"
    source.write_text(
        MODEL.format(
            declaration="",
            action="simulate_ode({t_start=>0,t_end=>1,n_steps=>2**N})",
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(
        bng_cpp, source, tmp_path / "bng3"
    )
    assert generated_path is not None, f"parameterized exponent failed: {error}"
    assert _gdat_rows(generated_path) == 9, (
        "2**N must evaluate exponentiation against the current parameter value N=3"
    )


def test_dynamic_exponent_uses_protocol_mutated_parameter_value(bng_cpp, tmp_path):
    source = tmp_path / "protocol_dynamic_power_steps.bngl"
    source.write_text(
        MODEL.format(
            declaration=(
                'begin protocol\n'
                '  setParameter("N",4)\n'
                '  simulate({method=>"ode",t_start=>0,t_end=>1,n_steps=>2**N})\n'
                'end protocol\n'
            ),
            action="simulate_protocol()",
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(
        bng_cpp, source, tmp_path / "bng3"
    )
    assert generated_path is not None, f"parameterized protocol exponent failed: {error}"
    assert _gdat_rows(generated_path) == 17, (
        "2**N must use the live protocol value N=4 when simulation executes"
    )


def test_argfile_caret_is_refused_after_effective_arguments_are_merged(
    bng_cpp, tmp_path
):
    source = tmp_path / "argfile_xor.bngl"
    work_dir = tmp_path / "bng3"
    work_dir.mkdir()
    (work_dir / "steps.txt").write_text("n_steps 2^3\n", encoding="utf-8")
    source.write_text(
        MODEL.format(
            declaration="",
            action='simulate_ode({t_start=>0,t_end=>1,argfile=>"steps.txt"})',
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(bng_cpp, source, work_dir)
    assert generated_path is None
    assert "2^3" in error
    assert "Safe-Perl" in error


@pytest.mark.parametrize("method", ("pla", "psa"))
def test_pla_psa_step_expression_keeps_its_existing_dispatch_path(
    bng_cpp, tmp_path, method
):
    source = tmp_path / f"{method}_steps.bngl"
    source.write_text(
        MODEL.format(
            declaration="",
            action=(
                f'simulate({{method=>"{method}",t_start=>0,t_end=>1,'
                'n_steps=>2^3,seed=>1,poplevel=>0})'
            ),
        ),
        encoding="utf-8",
    )

    _, generated_path, error = runner.run_cli_path(
        bng_cpp, source, tmp_path / "bng3"
    )
    assert generated_path is not None, f"{method.upper()} simulation failed: {error}"
    assert _gdat_rows(generated_path) == 9
