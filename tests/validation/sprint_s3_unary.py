"""Independent network and analytic-law checks for the S3 unary slice."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare, runner
from tests.validation.strict import require_oracle
from tests.validation.test_export_formats import _locked_bng2_script

SOURCE_MODEL = """\
begin parameters
    k 0.4
end parameters
begin molecule types
    A(s~U~P,c~x~y)
end molecule types
begin seed species
    A(s~U,c~x) 3
    A(s~U,c~y) 2
end seed species
begin observables
    Molecules U A(s~U,c~x)
    Molecules P A(s~P,c~x)
    Molecules Untouched A(s~U,c~y)
end observables
begin reaction rules
    activate: A(s~U,c~x) -> A(s~P,c~x) k
end reaction rules
"""


def test_compiled_unary_network_matches_pinned_bng2_and_analytic_law(
    bng_cpp: Path, tmp_path: Path
) -> None:
    bng2 = _locked_bng2_script()
    require_oracle(
        bng2 is not None,
        "pinned BNG2 checkout is unavailable or does not match the upstream lock",
    )
    assert bng2 is not None
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(perl is not None, "Perl is required to run pinned BNG2")
    assert perl is not None

    oracle_input = tmp_path / "s3_unary_bng2.bngl"
    oracle_input.write_text(
        SOURCE_MODEL + "\ngenerate_network({overwrite=>1,max_iter=>3})\n",
        encoding="utf-8",
    )
    oracle_output = tmp_path / "bng2"
    oracle_output.mkdir()
    oracle_env = os.environ.copy()
    oracle_env["BNGPATH"] = str(bng2.parent)
    oracle = subprocess.run(
        [
            perl,
            str(bng2),
            "--outdir",
            str(oracle_output),
            "--check",
            "--netgen",
            str(oracle_input),
        ],
        cwd=tmp_path,
        env=oracle_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert oracle.returncode == 0, (
        "pinned BNG2 rejected the independently validated unary source model:\n"
        f"stdout:\n{oracle.stdout}\nstderr:\n{oracle.stderr}"
    )

    bng3_input = tmp_path / "s3_unary_bng3.bngl"
    bng3_input.write_text(
        SOURCE_MODEL
        + "\ngenerate_network({overwrite=>1,max_iter=>3})\n"
        + "simulate_ode({t_start=>0,t_end=>1,n_steps=>10,"
        + "rtol=>1e-10,atol=>1e-12,print_CDAT=>1})\n",
        encoding="utf-8",
    )
    bng3_output = tmp_path / "bng3"
    net_path, gdat_path, error = runner.run_cli_path(
        bng_cpp, bng3_input, bng3_output, timeout=60
    )
    assert net_path is not None, f"BNG3 native network generation failed: {error}"
    assert gdat_path is not None, f"BNG3 ODE consumer produced no trajectory: {error}"

    expected_net = compare.parse_net(oracle_output / "s3_unary_bng2.net")
    actual_net = compare.parse_net(net_path)
    assert expected_net is not None, "pinned BNG2 produced no parseable network"
    assert actual_net is not None, "BNG3 produced no parseable network"
    network_diff = compare.compare_net(
        expected_net,
        actual_net,
        compare_rates=True,
        compare_initial_amounts=True,
    )
    assert network_diff.ok, (
        "compiled unary network differs from pinned BNG2:\n" f"{network_diff.summary()}"
    )
    assert expected_net.n_species == 3
    assert expected_net.n_reactions == 1
    assert {name: entries for name, entries in expected_net.groups.values()} == {
        "U": {1: 1.0},
        "P": {3: 1.0},
        "Untouched": {2: 1.0},
    }

    observed, columns = compare.parse_gdat(gdat_path)
    assert observed is not None, "BNG3 ODE trajectory is not readable"
    assert columns is not None
    times = np.asarray([row[columns.index("time")] for row in observed])
    u = 3.0 * np.exp(-0.4 * times)
    expected = np.column_stack((times, u, 3.0 - u, np.full_like(times, 2.0)))
    diff = compare.compare_trajectories(
        expected,
        ["time", "U", "P", "Untouched"],
        observed,
        columns,
        rtol=1e-8,
        atol=1e-10,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, (
        "native ODE consumer disagrees with U(t)=3 exp(-0.4 t), "
        "P(t)=3-U(t), and fixed context=2: "
        f"{diff.summary()}"
    )
    assert math.isclose(float(observed[-1, columns.index("Untouched")]), 2.0)
