"""Focused regression tests for BNGL NFnext/NFcore action selection, physical units on NFsim/NFnext, and NFnext dynamic energy / population-map execution."""

from __future__ import annotations

import math
from pathlib import Path
import subprocess

import numpy as np
import pytest

import bionetgen
import bionetgen._bionetgen_cpp as cpp


def _read_gdat(path: Path) -> dict[str, np.ndarray]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    header = next(line for line in lines if line.startswith("#"))
    cols = [c for c in header.lstrip("#").split() if c]
    rows = np.loadtxt([line for line in lines if not line.startswith("#")], ndmin=2)
    return {col: rows[:, idx] for idx, col in enumerate(cols)}


# =============================================================================
# Task 1: BNGL Action simulate({method=>"nfnext"/"nfcore"/"nf"}) & simulate_nf
# =============================================================================


class TestActionNfEngineSelection:
    MODEL_BODY = """begin model
begin parameters
    kf 2.0
    kr 1.0
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
    A(s~0) <-> A(s~1) kf, kr
end reaction rules
end model
"""

    def test_simulate_method_nfnext_action_writes_gdat_and_species(
        self, tmp_path: Path, capfd
    ):
        bngl = tmp_path / "act_nfnext.bngl"
        bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate({method=>"nfnext", prefix=>"nfnext_out", t_end=>3, n_steps=>6, seed=>42, verbose=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(bngl)).execute(verbose=True)
        err = capfd.readouterr().err
        assert "Running NFnext in-process" in err

        gdat = _read_gdat(tmp_path / "nfnext_out.gdat")
        np.testing.assert_allclose(gdat["time"], np.linspace(0.0, 3.0, 7))
        np.testing.assert_allclose(gdat["A0"] + gdat["A1"], 100.0)
        assert gdat["A1"][-1] > 0

        species_path = tmp_path / "nfnext_out.species"
        assert species_path.is_file()
        species_text = species_path.read_text(encoding="utf-8")
        assert "A(s~" in species_text

    def test_simulate_method_nfcore_action_supports_nfcore_options(
        self, tmp_path: Path, capfd
    ):
        bngl = tmp_path / "act_nfcore.bngl"
        bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate({method=>"nfcore", prefix=>"nfcore_out", t_end=>2, n_steps=>4, seed=>7, utl=>2, equil=>0.5, verbose=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(bngl)).execute(verbose=True)
        err = capfd.readouterr().err
        assert "Running NFSim in-process" in err
        assert "Universal traversal limit = 2" in err

        gdat = _read_gdat(tmp_path / "nfcore_out.gdat")
        np.testing.assert_allclose(gdat["A0"] + gdat["A1"], 100.0)
        assert (tmp_path / "nfcore_out.species").is_file()

    def test_simulate_method_nf_dispatches_to_nfnext_when_clean_and_nfcore_when_needed(
        self, tmp_path: Path, capfd
    ):
        clean_bngl = tmp_path / "act_nf_clean.bngl"
        clean_bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate({method=>"nf", prefix=>"clean_nf", t_end=>2, n_steps=>4, seed=>11, verbose=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(clean_bngl)).execute(verbose=True)
        assert "Running NFnext in-process" in capfd.readouterr().err
        gdat = _read_gdat(tmp_path / "clean_nf.gdat")
        np.testing.assert_allclose(gdat["A0"] + gdat["A1"], 100.0)
        assert (tmp_path / "clean_nf.species").is_file()

        nfcore_opt_bngl = tmp_path / "act_nf_equil.bngl"
        nfcore_opt_bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate({method=>"nf", prefix=>"equil_nf", t_end=>2, n_steps=>4, seed=>11, equil=>0.2, verbose=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(nfcore_opt_bngl)).execute(verbose=True)
        assert "Running NFSim in-process" in capfd.readouterr().err
        assert (tmp_path / "equil_nf.gdat").is_file()

    def test_simulate_nf_explicit_engine_selector(self, tmp_path: Path, capfd):
        bngl = tmp_path / "simnf_engine.bngl"
        bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate_nf({engine=>"nfnext", prefix=>"simnf_next", t_end=>1, n_steps=>2, seed=>5, verbose=>1})
    simulate_nf({engine=>"nfcore", prefix=>"simnf_core", t_end=>1, n_steps=>2, seed=>5, verbose=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(bngl)).execute(verbose=True)
        err = capfd.readouterr().err
        assert "Running NFnext in-process" in err
        assert "Running NFSim in-process" in err
        assert (tmp_path / "simnf_next.gdat").is_file()
        assert (tmp_path / "simnf_core.gdat").is_file()

    def test_simulate_method_nfnext_continuation_and_parameter_scan(
        self, tmp_path: Path
    ):
        cont_bngl = tmp_path / "nfnext_cont.bngl"
        cont_bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    simulate({method=>"nfnext", prefix=>"phase1", t_end=>1, n_steps=>2, seed=>10})
    setParameter("kf", 0.0)
    simulate({method=>"nfnext", prefix=>"phase2", continue=>1, t_end=>3, n_steps=>2, seed=>11})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(cont_bngl)).execute()
        p1 = _read_gdat(tmp_path / "phase1.gdat")
        p2 = _read_gdat(tmp_path / "phase2.gdat")
        assert p2["time"][0] == pytest.approx(1.0)
        assert p2["time"][-1] == pytest.approx(3.0)
        assert p2["A0"][0] == pytest.approx(p1["A0"][-1])
        assert p2["A0"][-1] >= p2["A0"][0]

        scan_bngl = tmp_path / "nfnext_scan.bngl"
        scan_bngl.write_text(
            self.MODEL_BODY
            + """begin actions
    parameter_scan({method=>"nfnext", parameter=>"kf", par_scan_vals=>[0.5, 2.0], t_end=>1, n_steps=>2, seed=>3})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(scan_bngl)).execute()
        scan_file = tmp_path / "nfnext_scan_kf.scan"
        assert scan_file.is_file()
        rows = [
            line.split()
            for line in scan_file.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(r[0]) for r in rows] == pytest.approx([0.5, 2.0])

    def test_action_refuses_nfcore2_and_nfcore_only_options_on_nfnext(
        self, tmp_path: Path
    ):
        bad_proto = tmp_path / "bad_nfcore2.bngl"
        bad_proto.write_text(
            self.MODEL_BODY
            + 'begin actions\n simulate({method=>"nfcore2", t_end=>1, n_steps=>2})\nend actions\n',
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="nfcore2"):
            bionetgen.load(str(bad_proto)).execute()

        bad_opt = tmp_path / "bad_nfnext_opt.bngl"
        bad_opt.write_text(
            self.MODEL_BODY
            + 'begin actions\n simulate({method=>"nfnext", t_end=>1, n_steps=>2, utl=>3})\nend actions\n',
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="NFcore-only option 'utl'"):
            bionetgen.load(str(bad_opt)).execute()

        bad_conflict = tmp_path / "bad_conflict.bngl"
        bad_conflict.write_text(
            self.MODEL_BODY
            + 'begin actions\n simulate({method=>"nfnext", engine=>"nfcore", t_end=>1, n_steps=>2})\nend actions\n',
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="Conflicting network-free engine"):
            bionetgen.load(str(bad_conflict)).execute()


# =============================================================================
# Task 2: Physical Units on Direct NFsim & NFnext vs ODE/Analytic Solutions
# =============================================================================


class TestPhysicalUnitsDirectNfsimAndNfnext:
    def test_minute_and_millisecond_time_basis_match_ode_and_analytic(
        self, tmp_path: Path
    ):
        # k = 30 [minute^-1] = 0.5 [second^-1]; concentration seed = 100 items in 1 fL.
        minute_src = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits minute
  end units
  begin parameters
    k = 30 [minute^-1]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 1.660538863127e-7 [M]
  end seed species
  begin observables
    Molecules A_count A()@cell
  end observables
  begin reaction rules
    decay: A()@cell -> 0 k
  end reaction rules
end model
"""
        path = tmp_path / "minute_decay.bngl"
        path.write_text(minute_src, encoding="utf-8")
        model = bionetgen.load(str(path))

        t_end = 1.0
        ode = model.simulate(method="ode", t_end=t_end, n_steps=10)
        expected = 100.0 * math.exp(-0.5 * t_end)
        assert ode.observables["A_count"][0] == pytest.approx(100.0, rel=1e-6)
        assert ode.observables["A_count"][-1] == pytest.approx(expected, rel=1e-4)

        n_runs = 100
        p = math.exp(-0.5 * t_end)
        se = math.sqrt(100.0 * p * (1.0 - p) / n_runs)
        for method in ("nfcore", "nfnext"):
            vals = [
                float(
                    model.simulate(
                        method=method, t_end=t_end, n_steps=1, seed=400 + i
                    ).observables["A_count"][-1]
                )
                for i in range(n_runs)
            ]
            mean = float(np.mean(vals))
            assert abs(mean - expected) <= 4.5 * se, (
                f"{method} minute-basis mean {mean} disagreed with ODE/analytic {expected}"
            )
            # Wrong (unconverted k=30 s^-1) would be ~0, >100 sigma away.
            assert mean > 40.0

        # Custom millisecond time basis: k = 5e-4 [ms^-1] = 0.5 [s^-1].
        ms_src = minute_src.replace(
            "timeunits minute",
            "unit ms = 1e-3*second\n    timeunits ms",
        ).replace("k = 30 [minute^-1]", "k = 5e-4 [ms^-1]")
        ms_path = tmp_path / "ms_decay.bngl"
        ms_path.write_text(ms_src, encoding="utf-8")
        ms_model = bionetgen.load(str(ms_path))
        for method in ("nfcore", "nfnext"):
            vals = [
                float(
                    ms_model.simulate(
                        method=method, t_end=t_end, n_steps=1, seed=800 + i
                    ).observables["A_count"][-1]
                )
                for i in range(n_runs)
            ]
            assert abs(float(np.mean(vals)) - expected) <= 4.5 * se

    def test_homobimolecular_physical_units_match_between_nfcore_nfnext_and_exact_law(
        self, tmp_path: Path
    ):
        # 2 molecules of A(b) in 1 fL; k = 60 * 6.02214076e8 [M^-1/minute] => k_count = 1.0 [item^-1/s].
        # Symmetry factor = 0.5 => hazard for 2 molecules = 1.0 * C(2,2) = 1.0 s^-1 => P(free at t=1) = exp(-1).
        homo_src = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits minute
  end units
  begin parameters
    kon = 3.613284456e10 [M^-1/minute]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A(b)
  end molecule types
  begin seed species
    A(b)@cell 2 [molecule]
  end seed species
  begin observables
    Molecules FreeA A(b)@cell
    Molecules Dimer A(b!1)@cell.A(b!1)@cell
  end observables
  begin reaction rules
    dimer: A(b)@cell + A(b)@cell -> A(b!1)@cell.A(b!1)@cell kon
  end reaction rules
end model
"""
        path = tmp_path / "homo_units.bngl"
        path.write_text(homo_src, encoding="utf-8")
        model = bionetgen.load(str(path))
        n_runs = 200
        p = math.exp(-1.0)
        se = math.sqrt(p * (1.0 - p) / n_runs)
        for method in ("nfcore", "nfnext"):
            survived = sum(
                1
                for i in range(n_runs)
                if model.simulate(
                    method=method, t_end=1.0, n_steps=1, seed=1200 + i
                ).observables["FreeA"][-1]
                == 2.0
            )
            assert abs(survived / n_runs - p) <= 4.5 * se
            assert abs(survived / n_runs - math.exp(-2.0)) > 4.5 * se

    def test_trimolecular_and_bidirectional_compound_rate_physical_units(
        self, tmp_path: Path
    ):
        # Reversible binding with compound parameter kon = koff / KD (docs/BNG3_UNITS.md idiom):
        # KD = 100 nM = 1e-7 M, koff = 1.0 s^-1 => kon = 1e7 M^-1 s^-1.
        # In V = 1 fL with N_A = 6.02214076e23: kon_count = 1e7 / 6.02214076e8 = 0.0166053886 item^-1 s^-1.
        compound_src = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = second
  end units
  begin parameters
    KD = 100 [nM]
    koff = 1.0 [second^-1]
    kon = koff / KD
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A(b)
    B(a)
  end molecule types
  begin seed species
    A(b)@cell 50 [molecule]
    B(a)@cell 50 [molecule]
  end seed species
  begin observables
    Molecules Bound A(b!1)@cell.B(a!1)@cell
  end observables
  begin reaction rules
    bind: A(b)@cell + B(a)@cell -> A(b!1)@cell.B(a!1)@cell kon
    unbind: A(b!1)@cell.B(a!1)@cell -> A(b)@cell + B(a)@cell koff
  end reaction rules
end model
"""
        path = tmp_path / "compound_units.bngl"
        path.write_text(compound_src, encoding="utf-8")
        model = bionetgen.load(str(path))
        ode_bound = float(
            model.simulate(method="ode", t_end=5.0, n_steps=10).observables["Bound"][-1]
        )
        assert 10.0 < ode_bound < 40.0
        for method in ("nfcore", "nfnext"):
            vals = [
                float(
                    model.simulate(
                        method=method, t_end=5.0, n_steps=1, seed=2100 + i
                    ).observables["Bound"][-1]
                )
                for i in range(60)
            ]
            assert abs(float(np.mean(vals)) - ode_bound) < 3.0

        # Bidirectional rule (<->) with physical-unit forward and reverse rates:
        # A + B <-> C + D with kfwd = 2*krev so equilibrium has C/(A+C) = sqrt(2)/(1+sqrt(2)).
        bidir_src = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = minute
  end units
  begin parameters
    kfwd = 1.2e9 [M^-1/minute]
    krev = 0.6e9 [M^-1/minute]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
    C()
    D()
  end molecule types
  begin seed species
    A()@cell 40 [molecule]
    B()@cell 40 [molecule]
    C()@cell 0 [molecule]
    D()@cell 0 [molecule]
  end seed species
  begin observables
    Molecules C_count C()@cell
  end observables
  begin reaction rules
    exch: A()@cell + B()@cell <-> C()@cell + D()@cell kfwd, krev
  end reaction rules
end model
"""
        bidir_path = tmp_path / "bidir_units.bngl"
        bidir_path.write_text(bidir_src, encoding="utf-8")
        bidir_model = bionetgen.load(str(bidir_path))
        ode_c = float(
            bidir_model.simulate(method="ode", t_end=10.0, n_steps=10).observables[
                "C_count"
            ][-1]
        )
        assert 20.0 < ode_c < 28.0
        for method in ("nfcore", "nfnext"):
            vals = [
                float(
                    bidir_model.simulate(
                        method=method, t_end=10.0, n_steps=1, seed=2500 + i
                    ).observables["C_count"][-1]
                )
                for i in range(60)
            ]
            assert abs(float(np.mean(vals)) - ode_c) < 3.0

        # Trimolecular (molecularity 3): A + B + C -> D with 1 each, k3_count = 1.0 s^-1.
        tri_src = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeunits second
  end units
  begin parameters
    k3 = 3.626617935254e17 [M^-2/second]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
    C()
    D()
  end molecule types
  begin seed species
    A()@cell 1
    B()@cell 1
    C()@cell 1
    D()@cell 0
  end seed species
  begin observables
    Molecules A_obs A()@cell
  end observables
  begin reaction rules
    tri: A()@cell + B()@cell + C()@cell -> D()@cell k3
  end reaction rules
end model
"""
        tri_path = tmp_path / "tri_units.bngl"
        tri_path.write_text(tri_src, encoding="utf-8")
        tri_model = bionetgen.load(str(tri_path))
        n_runs = 200
        p = math.exp(-1.0)
        se = math.sqrt(p * (1.0 - p) / n_runs)
        for method in ("nfcore", "nfnext"):
            survived = sum(
                1
                for i in range(n_runs)
                if tri_model.simulate(
                    method=method, t_end=1.0, n_steps=1, seed=3100 + i
                ).observables["A_obs"][-1]
                == 1.0
            )
            assert abs(survived / n_runs - p) <= 4.5 * se

    def test_unconvertible_physical_units_remain_fail_closed_on_both_engines(
        self, tmp_path: Path
    ):
        # Missing NumberPerQuantityUnit bridge for mole <-> item
        no_bridge = """begin model
  setOption("units", "strict")
  begin parameters
    k = 1e-8 [M/second]
  end parameters
  begin compartments
    cell 3 1 [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin reaction rules
    0 -> A()@cell k
  end reaction rules
end model
"""
        p1 = tmp_path / "no_bridge.bngl"
        p1.write_text(no_bridge, encoding="utf-8")
        m1 = bionetgen.load(str(p1))
        for method in ("nfcore", "nfnext"):
            with pytest.raises(RuntimeError):
                m1.simulate(method=method, t_end=1.0, n_steps=1, seed=1)

        # Missing 3D volume for concentration seed
        no_vol_seed = """begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin parameters
    k = 0.5 [second^-1]
  end parameters
  begin molecule types
    A()
  end molecule types
  begin seed species
    A() 1 [nM]
  end seed species
  begin reaction rules
    A() -> 0 k
  end reaction rules
end model
"""
        p2 = tmp_path / "no_vol_seed.bngl"
        p2.write_text(no_vol_seed, encoding="utf-8")
        m2 = bionetgen.load(str(p2))
        for method in ("nfcore", "nfnext"):
            with pytest.raises(RuntimeError):
                m2.simulate(method=method, t_end=1.0, n_steps=1, seed=1)


# =============================================================================
# Task 3: NFnext Dynamic Energy & Population-Map End-to-End Parity
# =============================================================================


class TestNfnextDynamicEnergyAndPopulationMaps:
    def test_nfnext_dynamic_energy_binding_matches_boltzmann_equilibrium(
        self, tmp_path: Path
    ):
        # Dynamic energy function: G_bind = -0.1 * NB() = -1.0 (since NB = 10 constant).
        # Detailed balance: kf = exp(-0.5), kr = exp(-1.5) => P(bound at T=3) = kf/(kf+kr)*(1-exp(-(kf+kr)*T)).
        src = """begin model
  begin parameters
    phi 0.5
    Ea 1.0
    g_per_b -0.1
  end parameters
  begin molecule types
    A(b)
    B(a)
    Mod()
  end molecule types
  begin seed species
    A(b) 1
    B(a) 1
    Mod() 10
  end seed species
  begin observables
    Molecules NMod Mod()
    Molecules Bound A(b!1).B(a!1)
  end observables
  begin functions
    bind_dG() = g_per_b * NMod()
  end functions
  begin energy patterns
    ep_bind: A(b!1).B(a!1) bind_dG()
  end energy patterns
  begin reaction rules
    bind: A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea), Arrhenius(phi, Ea)
  end reaction rules
end model
"""
        m = cpp.parse_string(src)
        T = 3.0
        kf = math.exp(-0.5)
        kr = math.exp(-1.5)
        expected = kf / (kf + kr) * (1.0 - math.exp(-(kf + kr) * T))
        n_runs = 200
        bound = sum(
            1
            for i in range(n_runs)
            if cpp.simulate_nfnext(m, [0.0, T], seed=5000 + i)["observables"]["Bound"][-1]
            > 0.5
        )
        se = math.sqrt(expected * (1.0 - expected) / n_runs)
        assert abs(bound / n_runs - expected) <= 4.5 * se
