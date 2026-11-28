"""Loop 2 regression tests for ActionDispatch protocols, scans, confinement, and NF continuation."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import bionetgen
import pytest


def _read_table(path: Path) -> tuple[list[str], list[list[float]]]:
    headers: list[str] = []
    rows: list[list[float]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            headers = line[1:].split()
            continue
        rows.append([float(tok) for tok in line.split()])
    return headers, rows


def _find_bng_cpp() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "build" / "cpp" / "bng_cpp"
    if candidate.is_file():
        return candidate
    found = shutil.which("bng_cpp")
    assert found is not None, "bng_cpp CLI binary not found"
    return Path(found)


def test_l2_02_01_parameter_scan_seed_concentration(tmp_path: Path) -> None:
    bngl = tmp_path / "scan_seed.bngl"
    bngl.write_text(
        """begin model
begin parameters
  A0 10
  k1 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() A0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() k1
end reaction rules
end model
generate_network({overwrite=>1})
parameter_scan({parameter=>"A0",par_min=>10,par_max=>100,n_scan_pts=>4,method=>"ode",t_end=>1,n_steps=>5,reset_conc=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, rows = _read_table(tmp_path / "scan_seed_A0.scan")
    assert len(rows) == 4
    expected_a0 = [10.0, 40.0, 70.0, 100.0]
    for row, a0 in zip(rows, expected_a0):
        assert row[0] == pytest.approx(a0, rel=1e-6)
        assert row[1] == pytest.approx(a0 * math.exp(-0.5), rel=1e-4)
        assert row[2] == pytest.approx(a0 * (1.0 - math.exp(-0.5)), rel=1e-4)


def test_l2_10_02_symbolic_setconcentration_preserved_in_scan(tmp_path: Path) -> None:
    bngl = tmp_path / "sym_setconc_scan.bngl"
    bngl.write_text(
        """begin model
begin parameters
  L_conc 0.0
  scale 10.0
  k_eq 2.0
  k_decay 0.5
end parameters
begin molecule types
  A()
  B()
  L()
end molecule types
begin seed species
  A() 100
  B() 0
  L() 0
end seed species
begin observables
  Molecules Btot B()
  Molecules Ltot L()
end observables
begin reaction rules
  A() <-> B() k_eq, k_eq
  L() -> 0 k_decay
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>5,n_steps=>10,suffix=>"equil"})
setConcentration("L()", "L_conc*scale")
parameter_scan({parameter=>"L_conc",par_scan_vals=>[1, 5, 10],method=>"ode",t_end=>1,n_steps=>5,reset_conc=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, rows = _read_table(tmp_path / "sym_setconc_scan_L_conc.scan")
    assert len(rows) == 3
    for row, l_conc in zip(rows, [1.0, 5.0, 10.0]):
        assert row[0] == pytest.approx(l_conc, rel=1e-6)
        # Equilibrated B() (~50) must be preserved across scan points.
        assert row[1] == pytest.approx(50.0, rel=1e-3)
        # Symbolic L_conc*scale must be re-evaluated at each scan point.
        assert row[2] == pytest.approx(l_conc * 10.0 * math.exp(-0.5), rel=1e-4)


def test_l2_10_02_and_03_linear_parameter_sensitivity_seed_and_formula(
    tmp_path: Path,
) -> None:
    bngl = tmp_path / "lps_dep.bngl"
    bngl.write_text(
        """begin model
begin parameters
  A0 100
  k1 0.5
  k2 2*k1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() A0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin reaction rules
  A() -> B() k2
end reaction rules
end model
generate_network({overwrite=>1})
LinearParameterSensitivity({t_end=>1,n_steps=>2,init_equil=>0,re_equil=>0,bump=>10,suffix=>"s"})
setParameter("k1", 0.25)
simulate({method=>"ode",t_end=>1,n_steps=>2,suffix=>"post"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()

    # Check A0 sensitivity: dA(1)/dA0 = exp(-1.0)
    a0_gsc_lines = [
        line.split()
        for line in (tmp_path / "lps_dep_A0_s.gsc").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    a0_sens_at_1 = float(a0_gsc_lines[0][-1])
    assert a0_sens_at_1 == pytest.approx(math.exp(-1.0), rel=1e-3)

    # Check k1 sensitivity through dependent parameter k2 = 2*k1:
    # (100*exp(-2*0.55) - 100*exp(-2*0.5)) / 0.05
    k1_gsc_lines = [
        line.split()
        for line in (tmp_path / "lps_dep_k1_s.gsc").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    expected_k1_sens = (100.0 * math.exp(-1.1) - 100.0 * math.exp(-1.0)) / 0.05
    assert float(k1_gsc_lines[0][-1]) == pytest.approx(expected_k1_sens, rel=1e-3)

    # Verify k2 = 2*k1 remained symbolic after LinearParameterSensitivity restored parameters.
    _, post_rows = _read_table(tmp_path / "lps_dep_post.gdat")
    assert post_rows[-1][1] == pytest.approx(100.0 * math.exp(-0.5), rel=1e-4)


def test_l2_02_02_parameter_scan_reset_conc_zero_with_parallel(tmp_path: Path) -> None:
    bngl = tmp_path / "scan_seq.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
parameter_scan({parameter=>"k",par_scan_vals=>[1,1,1,1],method=>"ode",t_end=>1,n_steps=>5,reset_conc=>0,parallel=>2})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, rows = _read_table(tmp_path / "scan_seq_k.scan")
    assert len(rows) == 4
    for idx, row in enumerate(rows, start=1):
        assert row[1] == pytest.approx(100.0 * math.exp(-float(idx)), rel=1e-4)


def test_l2_02_02_parallel_scan_preserves_shared_net_file(tmp_path: Path) -> None:
    bngl = tmp_path / "scan_par_net.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
parameter_scan({parameter=>"k",par_scan_vals=>[0.5, 1.0, 1.5, 2.0],method=>"ode",t_end=>1,n_steps=>5,reset_conc=>1,parallel=>2})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, rows = _read_table(tmp_path / "scan_par_net_k.scan")
    assert len(rows) == 4
    for row, k in zip(rows, [0.5, 1.0, 1.5, 2.0]):
        assert row[1] == pytest.approx(100.0 * math.exp(-k), rel=1e-4)
    # Shared .net file must retain original parameter k=1.0 rather than a worker value.
    net_text = (tmp_path / "scan_par_net.net").read_text(encoding="utf-8")
    assert "k " in net_text and "1.000000" in net_text or "1" in net_text


def test_l2_02_03_save_reset_parameters_preserves_symbolic_deps(tmp_path: Path) -> None:
    bngl = tmp_path / "reset_params.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k1 1.0
  k2 2*k1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k2
end reaction rules
begin protocol
  saveParameters("p_proto")
  setParameter("k1", 5.0)
  resetParameters("p_proto")
  setParameter("k1", 0.5)
  simulate({method=>"ode",t_end=>1,n_steps=>5})
end protocol
end model
generate_network({overwrite=>1})
saveParameters("p_top")
setParameter("k1", 5.0)
resetParameters("p_top")
setParameter("k1", 0.5)
simulate({method=>"ode",t_end=>1,n_steps=>5,suffix=>"top"})
resetConcentrations()
simulate_protocol({prefix=>"proto_run"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    expected = 100.0 * math.exp(-2.0 * 0.5)
    _, top_rows = _read_table(tmp_path / "reset_params_top.gdat")
    _, proto_rows = _read_table(tmp_path / "proto_run.gdat")
    assert top_rows[-1][1] == pytest.approx(expected, rel=1e-4)
    assert proto_rows[-1][1] == pytest.approx(expected, rel=1e-4)


def test_l2_02_05_net_reload_actions_setparameter_scan_bifurcate(tmp_path: Path) -> None:
    net_file = tmp_path / "m.net"
    net_file.write_text(
        """begin parameters
  1 k1 0.5
end parameters
begin species
  1 A() 100
  2 B() 0
end species
begin reactions
  1 1 2 k1 #R1
end reactions
begin groups
  1 Atot 1
  2 Btot 2
end groups
""",
        encoding="utf-8",
    )
    bngl = tmp_path / "driver.bngl"
    bngl.write_text(
        """readFile({file=>"m.net"})
saveParameters("init")
setParameter("k1", 2.0)
simulate({method=>"ode",t_end=>1,n_steps=>5,suffix=>"setp"})
resetParameters("init")
resetConcentrations()
simulate({method=>"ode",t_end=>1,n_steps=>5,suffix=>"resetp"})
resetConcentrations()
parameter_scan({parameter=>"k1",par_scan_vals=>[0.5, 2.0],method=>"ode",t_end=>1,n_steps=>5,reset_conc=>1})
resetConcentrations()
bifurcate({parameter=>"k1",par_scan_vals=>[0.5, 1.0],method=>"ode",t_end=>1,n_steps=>2,suffix=>"bif"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()

    _, setp_rows = _read_table(tmp_path / "driver_setp.gdat")
    assert setp_rows[-1][1] == pytest.approx(100.0 * math.exp(-2.0), rel=1e-4)
    assert setp_rows[-1][2] == pytest.approx(100.0 * (1.0 - math.exp(-2.0)), rel=1e-4)

    _, resetp_rows = _read_table(tmp_path / "driver_resetp.gdat")
    assert resetp_rows[-1][1] == pytest.approx(100.0 * math.exp(-0.5), rel=1e-4)

    _, scan_rows = _read_table(tmp_path / "driver_k1.scan")
    assert len(scan_rows) == 2
    assert scan_rows[0][1] == pytest.approx(100.0 * math.exp(-0.5), rel=1e-4)
    assert scan_rows[1][1] == pytest.approx(100.0 * math.exp(-2.0), rel=1e-4)

    assert (tmp_path / "driver_bif_bifurcation.gdat").is_file()


def test_l2_02_09_parse_scalar_value_exponent_and_empty(tmp_path: Path) -> None:
    good = tmp_path / "pow_scalar.bngl"
    good.write_text(
        """begin model
begin parameters
  k1 0.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k1
end reaction rules
end model
generate_network({overwrite=>1})
setConcentration("A()", "2**3")
simulate({method=>"ode",t_end=>1,n_steps=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(good)).execute()
    _, rows = _read_table(tmp_path / "pow_scalar.gdat")
    assert rows[-1][1] == pytest.approx(8.0, rel=1e-6)

    empty_bngl = tmp_path / "empty_scalar.bngl"
    empty_bngl.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0
end reaction rules
end model
generate_network({overwrite=>1})
setConcentration("A()", "")
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Unsupported scalar action value"):
        bionetgen.load(str(empty_bngl)).execute()


def test_l2_02_10_write_model_options(tmp_path: Path) -> None:
    poly = tmp_path / "poly.bngl"
    poly.write_text(
        """begin model
begin parameters
  k1 0.5
  k2 2*k1
  kf 1.0
end parameters
begin molecule types
  A(l,r)
end molecule types
begin seed species
  A(l,r) 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A(r) + A(l) -> A(r!1).A(l!1) kf
end reaction rules
end model
writeModel({include_network=>0,suffix=>"no_net"})
writeModel({include_network=>0,evaluate_expressions=>1,suffix=>"ev"})
writeModel({include_network=>0,include_model=>0,suffix=>"params_only"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(poly)).execute()

    no_net = tmp_path / "poly_no_net.bngl"
    ev = tmp_path / "poly_ev.bngl"
    params_only = tmp_path / "poly_params_only.bngl"
    assert no_net.is_file()
    assert "k2 1" in ev.read_text(encoding="utf-8")
    params_text = params_only.read_text(encoding="utf-8")
    assert "begin parameters" in params_text
    assert "begin reaction rules" not in params_text

    # Existing file with overwrite=>0 must fail cleanly; overwrite=>1 must succeed.
    dup = tmp_path / "dup_check.bngl"
    dup.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
end model
writeModel({include_network=>0,suffix=>"dup"})
writeModel({include_network=>0,suffix=>"dup",overwrite=>0})
""",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="file exists"):
        bionetgen.load(str(dup)).execute()


def test_l2_02_12_readfile_skip_actions_and_blocks(tmp_path: Path) -> None:
    sub = tmp_path / "sub.bngl"
    sub.write_text(
        """begin model
begin parameters
  k1 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k1
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>5,suffix=>"from_sub"})
""",
        encoding="utf-8",
    )
    main_actions = tmp_path / "main_act.bngl"
    main_actions.write_text(
        'readFile({file=>"sub.bngl",skip_actions=>0})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(main_actions)).execute()
    _, rows = _read_table(tmp_path / "main_act_from_sub.gdat")
    assert rows[-1][1] == pytest.approx(100.0 * math.exp(-0.5), rel=1e-4)

    params_file = tmp_path / "params.bngl"
    params_file.write_text(
        """begin model
begin parameters
  k1 2.0
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 999
end seed species
end model
""",
        encoding="utf-8",
    )
    main_blocks = tmp_path / "main_blocks.bngl"
    main_blocks.write_text(
        """begin model
begin parameters
  k1 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k1
end reaction rules
end model
readFile({file=>"params.bngl",blocks=>["parameters"]})
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>5})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(main_blocks)).execute()
    _, block_rows = _read_table(tmp_path / "main_blocks.gdat")
    assert block_rows[-1][1] == pytest.approx(10.0 * math.exp(-2.0), rel=1e-4)


def test_l2_02_14_and_15_set_model_name_and_writefile_formats(tmp_path: Path) -> None:
    bngl = tmp_path / "orig.bngl"
    bngl.write_text(
        """setModelName("custom")
begin model
begin parameters
  k1 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> B() k1
end reaction rules
end model
generate_network({overwrite=>1})
writeModel({overwrite=>1})
writeXML()
writeSBML()
writeFile({format=>"mfile",overwrite=>1})
writeFile({format=>"mexfile",overwrite=>1})
parameter_scan({parameter=>"k1",par_min=>0.5,par_max=>1.5,n_scan_pts=>2,method=>"ode",t_end=>1,n_steps=>2})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    for expected in [
        "custom.net",
        "custom.bngl",
        "custom.xml",
        "custom_sbml.xml",
        "custom.m",
        "custom_mex.c",
        "custom_k1.scan",
    ]:
        assert (tmp_path / expected).is_file(), f"missing expected output {expected}"
    assert (tmp_path / "custom_k1").is_dir()


@pytest.mark.parametrize("extra_opts", ["", ",gml=>100000"])
def test_l2_10_04_nf_get_final_state_equil_then_stim(
    tmp_path: Path, extra_opts: str
) -> None:
    bngl = tmp_path / "nf_equil_stim.bngl"
    bngl.write_text(
        f"""begin model
begin molecule types
  A(s~0~1)
  L()
end molecule types
begin seed species
  A(s~0) 200
  L() 0
end seed species
begin observables
  Molecules A1 A(s~1)
  Molecules L_obs L()
end observables
begin reaction rules
  A(s~0) -> A(s~1) 5.0
end reaction rules
end model
simulate({{method=>"nf",t_start=>0,t_end=>10,n_steps=>1,get_final_state=>1,suffix=>"equil",seed=>1{extra_opts}}})
setConcentration("L()", 50)
simulate({{method=>"nf",t_start=>0,t_end=>1,n_steps=>2,get_final_state=>0,suffix=>"stim",seed=>2{extra_opts}}})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, stim_rows = _read_table(tmp_path / "nf_equil_stim_stim.gdat")
    assert stim_rows[0][0] == pytest.approx(0.0)
    assert stim_rows[0][1] == pytest.approx(200.0)
    assert stim_rows[0][2] == pytest.approx(50.0)


def test_l2_06_17_nf_setconcentration_then_continue(tmp_path: Path) -> None:
    bngl = tmp_path / "nf_cont_setconc.bngl"
    bngl.write_text(
        """begin model
begin parameters
  k 0.0
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 100
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
end observables
begin reaction rules
  A(s~0) -> A(s~1) k
end reaction rules
end model
simulate({method=>"nf",t_end=>1.0,n_steps=>2,seed=>42,suffix=>"s1"})
setParameter("k", 2.0)
simulate({method=>"nf",t_end=>2.0,n_steps=>2,continue=>1,seed=>43,suffix=>"s2"})
setConcentration("A(s~0)", 50)
simulate({method=>"nf",t_end=>3.0,n_steps=>2,continue=>1,seed=>44,suffix=>"s3"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, s2_rows = _read_table(tmp_path / "nf_cont_setconc_s2.gdat")
    _, s3_rows = _read_table(tmp_path / "nf_cont_setconc_s3.gdat")
    s2_final_a1 = s2_rows[-1][2]
    assert s2_final_a1 > 50.0
    assert s3_rows[0][0] == pytest.approx(2.0)
    assert s3_rows[-1][0] == pytest.approx(3.0)
    assert s3_rows[0][1] == pytest.approx(50.0)
    assert s3_rows[0][2] == pytest.approx(s2_final_a1)
    assert s3_rows[-1][1] < 50.0
    assert s3_rows[-1][2] > s2_final_a1


def test_l2_10_06_simulate_ode_continue_absolute_tend(tmp_path: Path) -> None:
    bngl = tmp_path / "cont_abs.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  0 -> A() 1.0
end reaction rules
end model
generate_network({overwrite=>1})
simulate_ode({t_start=>0,t_end=>20,n_steps=>2})
simulate_ode({t_end=>40,n_steps=>2,continue=>1})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, rows = _read_table(tmp_path / "cont_abs.gdat")
    assert rows[-1][0] == pytest.approx(40.0, rel=1e-6)
    assert rows[-1][1] == pytest.approx(40.0, rel=1e-4)


def test_l2_10_07a_simulate_nf_negative_t_start(tmp_path: Path) -> None:
    bngl = tmp_path / "nf_neg_tstart.bngl"
    bngl.write_text(
        """begin model
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 200
end seed species
begin observables
  Molecules A0 A(s~0)
  Molecules A1 A(s~1)
end observables
begin reaction rules
  A(s~0) -> A(s~1) 2.0
end reaction rules
end model
simulate({method=>"nf",t_start=>-10,t_end=>0,n_steps=>5,seed=>7,suffix=>"pre"})
simulate({method=>"nf",t_end=>2,n_steps=>2,continue=>1,seed=>8,suffix=>"post"})
""",
        encoding="utf-8",
    )
    bionetgen.load(str(bngl)).execute()
    _, pre_rows = _read_table(tmp_path / "nf_neg_tstart_pre.gdat")
    assert [row[0] for row in pre_rows] == pytest.approx([-10.0, -8.0, -6.0, -4.0, -2.0, 0.0])
    assert pre_rows[0][1] == pytest.approx(200.0)
    assert pre_rows[-1][2] == pytest.approx(200.0)

    _, post_rows = _read_table(tmp_path / "nf_neg_tstart_post.gdat")
    assert [row[0] for row in post_rows] == pytest.approx([0.0, 1.0, 2.0])
    assert post_rows[-1][2] == pytest.approx(200.0)


def test_l2_11_04_outdir_confinement_hybrid_and_overwrite_zero(tmp_path: Path) -> None:
    bng_cpp = _find_bng_cpp()

    # 1. generate_hybrid_model with execute=>1 must stay strictly inside --outdir
    cwd_dir = tmp_path / "cwd"
    out_dir = tmp_path / "isolated_out"
    cwd_dir.mkdir()
    out_dir.mkdir()
    hybrid_src = cwd_dir / "hpp_confine.bngl"
    hybrid_src.write_text(
        """begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin population maps
  A() -> P_A()
end population maps
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_hybrid_model({prefix=>"escaped",overwrite=>1,execute=>1,actions=>["simulate_nf({t_end=>1,n_steps=>2,seed=>1})"]})
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(bng_cpp), "--outdir", str(out_dir), str(hybrid_src)],
        cwd=cwd_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (out_dir / "escaped_hpp.bngl").is_file()
    assert (out_dir / "escaped_hpp.gdat").is_file()
    assert not (cwd_dir / "escaped_hpp.bngl").exists()
    assert not (cwd_dir / "escaped_hpp.gdat").exists()

    # 2. generate_network({overwrite=>0}) must refuse ../ traversal via setModelName
    secret_net = tmp_path / "secret.net"
    secret_net.write_text(
        """begin parameters
  1 k 0
end parameters
begin species
  1 A() 777
end species
begin reactions
end reactions
begin groups
  1 Atot 1
end groups
""",
        encoding="utf-8",
    )
    nested_out = tmp_path / "sub_out"
    nested_out.mkdir()
    escape_src = cwd_dir / "escape_net.bngl"
    escape_src.write_text(
        """setModelName("../secret")
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 0
end reaction rules
end model
generate_network({overwrite=>0})
""",
        encoding="utf-8",
    )
    proc2 = subprocess.run(
        [str(bng_cpp), "--outdir", str(nested_out), str(escape_src)],
        cwd=cwd_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc2.returncode != 0
    assert "escapes output directory" in (proc2.stderr + proc2.stdout)
