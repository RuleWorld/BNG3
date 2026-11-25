"""Run explicitly in parity CI with the locked NFsim checkout and candidate binaries."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def nfsim_binaries():
    upstream = Path(os.environ["NFSIM_SYNC_ORACLE"]).resolve()
    candidate = Path(os.environ["NFSIM_SYNC_CANDIDATE_BIN"]).resolve()
    for executable in (
        upstream / "build/NFsim",
        candidate / "NFsim",
        candidate / "bng_cpp",
    ):
        assert executable.is_file() and os.access(executable, os.X_OK), executable
    return upstream, candidate


@pytest.mark.parametrize("embedded", [False, True], ids=["oracle", "embedded"])
def test_upstream_xml_regressions(nfsim_binaries, embedded):
    upstream, candidate = nfsim_binaries
    binary = candidate / "NFsim" if embedded else upstream / "build/NFsim"
    result = subprocess.run(
        [sys.executable, upstream / "validate/regressions/check_xml_ports.py", binary],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
        ("dot_in_split_products", dict(Chain=100, Ring=0, PQ=0)),
        ("products_never_joined", dict(Bridged=100, Aon=0, Btot=100)),
        ("ring_two_reactants", dict(Ring=100, Single=0, Cfree=100)),
        ("ring_energy_rule", dict(Ring=100)),
        ("three_products", dict(Chain3=0, Ring3=100, Chain5=0, Ring5=100)),
    ],
)
def test_embedded_and_direct_match_upstream_product_constraints(
    tmp_path, nfsim_binaries, case, expected
):
    upstream, candidate = nfsim_binaries
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


def _run_nfsim(binary, args, cwd):
    return subprocess.run(
        [str(binary), *map(str, args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_embedded_matches_upstream_rulemonkey_refusal(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    xml = upstream / "test" / "molecularity" / "ring_two_reactants.xml"
    for flag in ("-rm", "-rulemonkey"):
        for binary in (upstream / "build" / "NFsim", candidate / "NFsim"):
            proc = _run_nfsim(
                binary,
                ["-xml", xml, "-sim", "1", "-oSteps", "1", "-seed", "1", flag, "-o", tmp_path / "out.gdat"],
                tmp_path,
            )
            assert proc.returncode != 0
            assert "RuleMonkey mode" in (proc.stdout + proc.stderr)


def test_embedded_matches_upstream_single_rng_and_unseeded(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    xml = upstream / "test" / "molecularity" / "dot_molecule_two_candidates.xml"
    oracle_out = tmp_path / "oracle.gdat"
    embedded_out = tmp_path / "embedded.gdat"
    for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
        proc = _run_nfsim(
            binary,
            ["-xml", xml, "-sim", "1", "-oSteps", "5", "-seed", "17", "-o", out],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    assert embedded_out.read_text() == oracle_out.read_text()

    # Unseeded runs choose and print a random seed so trajectories can be repeated.
    seeds = set()
    for i in range(3):
        proc = _run_nfsim(
            candidate / "NFsim",
            ["-xml", xml, "-sim", "0.1", "-oSteps", "1", "-o", tmp_path / f"unseeded_{i}.gdat"],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        for line in proc.stdout.splitlines():
            if "Seeding random number generator with:" in line:
                seeds.add(int(line.split(":")[-1].strip()))
    assert len(seeds) >= 2


def test_embedded_matches_upstream_no_bscb_conserved_total(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    xml = upstream / "test" / "molecularity" / "no_bscb_conserved_total.xml"
    for binary in (upstream / "build" / "NFsim", candidate / "NFsim"):
        out = tmp_path / f"{binary.parent.name}.gdat"
        proc = _run_nfsim(
            binary,
            ["-xml", xml, "-no-bscb", "-sim", "10", "-oSteps", "10", "-seed", "3", "-o", out],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = out.read_text().splitlines()[1:]
        assert rows
        for row in rows:
            assert float(row.split()[1]) == 30.0


def test_embedded_matches_upstream_unknown_rate_law_refusal(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    xml = tmp_path / "unknown_ratelaw.xml"
    xml.write_text(
        (upstream / "test" / "Issue134" / "issue134_hill.xml")
        .read_text()
        .replace('type="Hill"', 'type="UnknownRateLawType"'),
        encoding="utf-8",
    )
    for binary in (upstream / "build" / "NFsim", candidate / "NFsim"):
        proc = _run_nfsim(
            binary,
            ["-xml", xml, "-sim", "1", "-oSteps", "1", "-seed", "1", "-o", tmp_path / "out.gdat"],
            tmp_path,
        )
        assert proc.returncode != 0 or not (tmp_path / "out.gdat").exists()
        assert "UnknownRateLawType" in (proc.stdout + proc.stderr)


def test_embedded_matches_upstream_rnf_and_set_parameter(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    # First-word RNF command dispatch (#144), zero-rate rule activation (#137), and MM refresh (#141).
    cases = [
        (upstream / "test" / "Issue144" / "issue144_keq.xml", "set Keq 5\nupdate\nsim 2 4\n"),
        (upstream / "test" / "setParameter" / "zero_rate_rule.xml", "set kon 3\nupdate\nsim 2 4\n"),
        (upstream / "test" / "setParameter" / "mm_set_parameter.xml", "set kcat 5\nset Km 10\nupdate\nsim 2 4\n"),
    ]
    for idx, (xml, block) in enumerate(cases):
        oracle_out = tmp_path / f"oracle_{idx}.gdat"
        embedded_out = tmp_path / f"embedded_{idx}.gdat"
        for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
            rnf = tmp_path / f"run_{idx}_{binary.parent.name}.rnf"
            rnf.write_text(f"-xml {xml}\n-o {out}\n-seed 11\nbegin\n{block}end\n", encoding="utf-8")
            proc = _run_nfsim(binary, ["-rnf", rnf], tmp_path)
            assert proc.returncode == 0, proc.stdout + proc.stderr
        assert embedded_out.read_text() == oracle_out.read_text()


def test_embedded_matches_upstream_time_table_and_tfun_comments(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    for name in ("time_table_step.xml", "time_table_step_up.xml", "time_table_ramp.xml"):
        xml = upstream / "test" / "Issue142" / name
        oracle_out = tmp_path / f"oracle_{name}.gdat"
        embedded_out = tmp_path / f"embedded_{name}.gdat"
        for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
            proc = _run_nfsim(
                binary,
                ["-xml", xml, "-sim", "5", "-oSteps", "5", "-seed", "7", "-o", out],
                tmp_path,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
        assert embedded_out.read_text() == oracle_out.read_text()

    # .tfun file with UTF-8 BOM, # header/comments, CRLF endings, and malformed line rejection (#150).
    good_tfun = tmp_path / "good.tfun"
    good_tfun.write_bytes(b"\xef\xbb\xbf# time rate\r\n\r\n0 0 # start\r\n1 5\r\n5 5\r\n")
    bad_tfun = tmp_path / "bad.tfun"
    bad_tfun.write_text("# header\n0 0\n1\n2 2\n", encoding="utf-8")
    template = (upstream / "test" / "Issue142" / "time_table_ramp.xml").read_text()
    assert 'mode="inline"' in template or 'xData=' in template
    # Build a minimal file-backed TFUN XML from time_table_ramp.xml.
    import re
    good_xml = tmp_path / "good_tfun.xml"
    bad_xml = tmp_path / "bad_tfun.xml"
    for target_xml, data_file in ((good_xml, good_tfun), (bad_xml, bad_tfun)):
        patched = re.sub(r'mode="inline"', 'mode="file"', template)
        patched = re.sub(r'xData="[^"]*"\s*', '', patched)
        patched = re.sub(r'yData="[^"]*"', f'file="{data_file}"', patched)
        target_xml.write_text(patched, encoding="utf-8")
    out = tmp_path / "good_tfun.gdat"
    proc = _run_nfsim(candidate / "NFsim", ["-xml", good_xml, "-sim", "5", "-oSteps", "5", "-seed", "5", "-o", out], tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out.is_file()
    proc_bad = _run_nfsim(candidate / "NFsim", ["-xml", bad_xml, "-sim", "1", "-oSteps", "1", "-seed", "5", "-o", tmp_path / "bad.gdat"], tmp_path)
    assert "expected two numbers" in (proc_bad.stdout + proc_bad.stderr)


def test_embedded_matches_upstream_whole_complex_and_matchonce(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    for name in ("whole_complex_deletion.xml", "match_once.xml", "match_once_disjoint.xml", "match_once_symmetric.xml"):
        xml = upstream / "test" / "perComplex" / name
        oracle_out = tmp_path / f"oracle_{name}.gdat"
        embedded_out = tmp_path / f"embedded_{name}.gdat"
        for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
            proc = _run_nfsim(
                binary,
                ["-xml", xml, "-sim", "2", "-oSteps", "4", "-seed", "13", "-o", out],
                tmp_path,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
        assert embedded_out.read_text() == oracle_out.read_text()

    # Nonlinear MM with multi-match complex fails closed.
    for name in ("mm_whole_complex_deletion.xml", "mm_match_once.xml"):
        xml = upstream / "test" / "perComplex" / name
        proc = _run_nfsim(
            candidate / "NFsim",
            ["-xml", xml, "-sim", "2", "-oSteps", "2", "-seed", "1", "-o", tmp_path / f"{name}.gdat"],
            tmp_path,
        )
        assert proc.returncode != 0
        assert "Michaelis-Menten" in (proc.stdout + proc.stderr)


def test_embedded_matches_upstream_reactant_count_and_math_parser(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    for name in (
        "reactant_count_zero_order.xml",
        "reactant_count_unimolecular.xml",
        "reactant_count_local.xml",
        "reactant_count_product.xml",
    ):
        xml = upstream / "test" / "ReactantCount" / name
        proc = _run_nfsim(
            candidate / "NFsim",
            ["-xml", xml, "-sim", "1", "-oSteps", "1", "-seed", "1", "-o", tmp_path / f"{name}.gdat"],
            tmp_path,
        )
        assert "which reads reactant_" in (proc.stdout + proc.stderr)

    accepted = upstream / "test" / "ReactantCount" / "reactant_count_accepted.xml"
    oracle_out = tmp_path / "oracle_acc.gdat"
    embedded_out = tmp_path / "embedded_acc.gdat"
    for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
        proc = _run_nfsim(binary, ["-xml", accepted, "-sim", "2", "-oSteps", "2", "-seed", "9", "-o", out], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    assert embedded_out.read_text() == oracle_out.read_text()

    # Built-in mathFuncParser self-test includes Tests 8-10 (#152).
    proc_math = _run_nfsim(candidate / "NFsim", ["-test", "mathFuncParser"], tmp_path)
    assert proc_math.returncode == 0, proc_math.stdout + proc_math.stderr
    assert "8) test rint()" in proc_math.stdout
    assert "9) test numeric literals" in proc_math.stdout
    assert "10) test expressions muParser refuses" in proc_math.stdout


def test_embedded_matches_upstream_tiny_propensity_and_end_time(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    xml = upstream / "test" / "Issue145" / "issue145_slow.xml"
    oracle_out = tmp_path / "oracle_slow.gdat"
    embedded_out = tmp_path / "embedded_slow.gdat"
    for binary, out in ((upstream / "build" / "NFsim", oracle_out), (candidate / "NFsim", embedded_out)):
        proc = _run_nfsim(binary, ["-xml", xml, "-sim", "10", "-oSteps", "5", "-seed", "23", "-o", out], tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    assert embedded_out.read_text() == oracle_out.read_text()


def test_embedded_and_direct_match_upstream_seed_rounding(tmp_path, nfsim_binaries):
    upstream, candidate = nfsim_binaries
    fixture_xml = upstream / "validate" / "regressions" / "issue160.xml"
    fixture_bngl = upstream / "validate" / "regressions" / "issue160.bngl"
    expected = dict(A_tot=1807, B_tot=20, C_tot=1, D_tot=3)
    env = dict(os.environ, BNG_NFSIM_REQUIRE_DIRECT="1")

    oracle_out = tmp_path / "oracle_seed.gdat"
    oracle = terminal_counts(
        [upstream / "build" / "NFsim", "-xml", fixture_xml, "-sim", "1", "-oSteps", "1", "-seed", "1", "-o", oracle_out],
        oracle_out,
        tmp_path,
        env,
    )
    assert oracle == expected

    embedded_out = tmp_path / "embedded_seed.gdat"
    proc_emb = _run_nfsim(
        candidate / "NFsim",
        ["-xml", fixture_xml, "-sim", "1", "-oSteps", "1", "-seed", "1", "-o", embedded_out],
        tmp_path,
    )
    assert proc_emb.returncode == 0, proc_emb.stdout + proc_emb.stderr
    assert "is not a whole number; rounded to " in (proc_emb.stdout + proc_emb.stderr)
    header, *rows = [line for line in embedded_out.read_text().splitlines() if line.strip()]
    embedded = dict(zip(header.lstrip("#").split()[1:], [int(float(v)) for v in rows[-1].split()[1:]]))
    assert embedded == expected

    model = tmp_path / "issue160_direct.bngl"
    model.write_text(
        fixture_bngl.read_text().replace(
            "writeXML()",
            'begin actions\nsimulate_nf({prefix=>"direct_seed",t_end=>1,n_steps=>1,seed=>1})\nend actions',
        )
    )
    proc_dir = subprocess.run(
        [str(candidate / "bng_cpp"), str(model)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc_dir.returncode == 0, proc_dir.stdout + proc_dir.stderr
    assert "is not a whole number; rounded to " in (proc_dir.stdout + proc_dir.stderr)
    d_header, *d_rows = [
        line for line in (tmp_path / "direct_seed.gdat").read_text().splitlines() if line.strip()
    ]
    direct = dict(zip(d_header.lstrip("#").split()[1:], [int(float(v)) for v in d_rows[-1].split()[1:]]))
    assert direct == expected
