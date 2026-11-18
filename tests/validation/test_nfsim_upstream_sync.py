"""Replay representative product-molecularity cases from the locked NFsim source."""

import os
import subprocess
from pathlib import Path

import pytest


def terminal_counts(command, output, tmp_path, env):
    output.unlink(missing_ok=True)
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = output.read_text().splitlines()
    names = rows[0].lstrip("#").split()
    return dict(zip(names[1:], map(float, rows[-1].split()[1:]), strict=True))


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (
            "delete_molecule_products",
            dict(ChainPlus=0, TrianglePlus=100, ChainDot=100, TriangleDot=0),
        ),
        ("dot_products", dict(Single=100, Ring=0, Opened=100, ViaY=100)),
        ("products_never_joined", dict(Bridged=100, Aon=0, Btot=100)),
        ("ring_two_reactants", dict(Ring=100, Single=0, Cfree=100)),
        ("ring_energy_rule", dict(Ring=100)),
    ],
)
def test_embedded_and_direct_match_upstream_product_constraints(
    tmp_path, case, expected
):
    upstream = os.environ.get("NFSIM_SYNC_ORACLE")
    candidate = os.environ.get("NFSIM_SYNC_CANDIDATE_BIN")
    if not upstream or not candidate:
        pytest.skip("requires the locked NFsim checkout and BNG3 candidate binaries")

    upstream = Path(upstream).resolve()
    candidate = Path(candidate).resolve()
    fixture = upstream / "test" / "molecularity" / case
    xml_args = [
        "-xml",
        fixture.with_suffix(".xml"),
        "-sim",
        "10",
        "-oSteps",
        "2",
        "-seed",
        "1",
    ]
    env = dict(os.environ, BNG_NFSIM_REQUIRE_DIRECT="1")
    oracle_output = tmp_path / "oracle.gdat"
    oracle = terminal_counts(
        [upstream / "build" / "NFsim", *xml_args, "-o", oracle_output],
        oracle_output,
        tmp_path,
        env,
    )
    assert {name: oracle[name] for name in expected} == expected

    for connectivity in (False, True):
        embedded_output = tmp_path / "embedded.gdat"
        flags = ["-connect"] if connectivity else []
        embedded = terminal_counts(
            [candidate / "NFsim", *xml_args, *flags, "-o", embedded_output],
            embedded_output,
            tmp_path,
            env,
        )
        model = tmp_path / "direct.bngl"
        model.write_text(
            fixture.with_suffix(".bngl").read_text().split("begin actions", 1)[0]
            + "begin actions\n"
            + f'simulate_nf({{prefix=>"direct",t_end=>10,n_steps=>2,seed=>1,pcg=>{int(connectivity)}}})\n'
            + "end actions\n"
        )
        direct = terminal_counts(
            [candidate / "bng_cpp", model], tmp_path / "direct.gdat", tmp_path, env
        )
        for result in (embedded, direct):
            assert {name: result[name] for name in expected} == expected
            if case == "ring_energy_rule":
                assert 0 < result["Lfree"] < 100
                assert result["Lfree"] + result["Single"] == 100
