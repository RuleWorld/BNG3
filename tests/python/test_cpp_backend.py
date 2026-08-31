"""Tests for the C++ backend bindings."""

import os
import xml.etree.ElementTree as ET

import pytest

_cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
import bionetgen

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
VALIDATION_DIR = os.path.join(os.path.dirname(__file__), "..", "validation")


def get_model_path(name):
    """Find a model file in the test directories."""
    for base in [MODELS_DIR, VALIDATION_DIR]:
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    pytest.skip(f"Model {name} not found")


class TestParser:
    def test_parse_simple_model(self, tmp_path):
        bngl = tmp_path / "test.bngl"
        bngl.write_text("""
begin model
begin parameters
    k_on 1.0
    k_off 0.1
    A0 100
    B0 200
end parameters

begin molecule types
    A(b)
    B(a)
end molecule types

begin seed species
    A(b) A0
    B(a) B0
end seed species

begin observables
    Molecules Afree A(b)
    Molecules AB A(b!1).B(a!1)
end observables

begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k_on
    A(b!1).B(a!1) -> A(b) + B(a) k_off
end reaction rules

begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
end model
""")
        model = _cpp.parse_file(str(bngl))
        assert model is not None
        assert len(model.parameters) == 4
        assert len(model.molecule_types) == 2
        assert len(model.seed_species) == 2
        assert len(model.observables) == 2
        assert len(model.reaction_rules) == 2

    def test_parse_string(self):
        text = """
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
"""
        model = _cpp.parse_string(text)
        assert len(model.parameters) == 1
        assert len(model.molecule_types) == 1

    def test_parse_error(self, tmp_path):
        bngl = tmp_path / "bad.bngl"
        bngl.write_text("this is not valid BNGL syntax {{{{")
        with pytest.raises(_cpp.ParseError):
            _cpp.parse_file(str(bngl))

    def test_file_not_found(self):
        with pytest.raises(_cpp.ParseError):
            _cpp.parse_file("/nonexistent/path.bngl")

    def test_actions_after_model_blocks_are_accepted(self, tmp_path):
        bngl = tmp_path / "actions_inside_model.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k_deg 1.0
    k_syn 10.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    $A() 5
    B() 0
end seed species
begin observables
    Molecules Atot A()
    Molecules Btot B()
end observables
begin reaction rules
    A() -> 0 k_deg
    0 -> B() k_syn
end reaction rules
generate_network({overwrite=>1})
simulate_nf({prefix=>"inside_model",t_end=>1,n_steps=>1,seed=>7})
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "inside_model.gdat"
        assert output.exists()
        assert "Atot" in output.read_text()

    def test_integer_state_increment_and_decrement_rules_are_expanded(self, tmp_path):
        bngl = tmp_path / "integer_states.bngl"
        bngl.write_text(
            """
begin parameters
    kr 5
    kb 20
end parameters
begin seed species
    ReceptorDimer(m~3) 4000
end seed species
begin observables
    Molecules R0 ReceptorDimer(m~0)
    Molecules R8 ReceptorDimer(m~8)
end observables
begin reaction rules
    ReceptorDimer(m~^[8]) -> ReceptorDimer(m~++) kr
    ReceptorDimer(m~^[0]) -> ReceptorDimer(m~--) kb
end reaction rules
"""
        )

        model = _cpp.parse_file(str(bngl))

        # Eight transitions in each direction, with the integer state range
        # inferred from the two native boundary rules.
        assert len(model.reaction_rules) == 16

    def test_singular_function_block_header_is_accepted(self, tmp_path):
        """BNG2/NFsim-era fixtures use ``begin function`` as a legacy alias."""
        bngl = tmp_path / "singular_function_block.bngl"
        bngl.write_text(
            """
begin parameters
    k 2
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin function
    rate() = k
end function
begin reaction rules
    X() -> 0 rate()
end reaction rules
"""
        )

        model = _cpp.parse_file(str(bngl))

        assert len(model.functions) == 1
        assert model.functions[0].name == "rate"
        assert len(model.reaction_rules) == 1


class TestNetworkGeneration:
    def test_generate_simple(self, tmp_path):
        bngl = tmp_path / "gen.bngl"
        bngl.write_text("""
begin model
begin parameters
    k_on 1.0
    k_off 0.1
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 200
end seed species
begin observables
    Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) -> A(b!1).B(a!1) k_on
    A(b!1).B(a!1) -> A(b) + B(a) k_off
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        network = _cpp.generate_network(model)
        assert network.num_species >= 2
        assert network.num_reactions >= 2

    @pytest.mark.parametrize(
        "model_name, expected_species",
        [
            ("blbr.bngl", 20),
            ("Motivating_example_cBNGL.bngl", 78),
        ],
    )
    def test_validation_models_generate_network(self, model_name, expected_species):
        model = _cpp.parse_file(get_model_path(model_name))
        network = _cpp.generate_network(model)

        assert network.num_species == expected_species
        # Reaction-count differential parity belongs to tests/validation, where
        # the strict exception ledger covers the known blbr over-count.
        assert network.num_reactions > 0


class TestSimulation:
    def test_ode_simulation(self, tmp_path):
        bngl = tmp_path / "sim.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        network = _cpp.generate_network(model)
        result = _cpp.simulate_ode(model, network, t_end=10.0, n_steps=50)

        assert "time" in result
        assert len(result["time"]) == 51  # n_steps + 1
        assert result["time"][0] == 0.0
        assert result["time"][-1] == pytest.approx(10.0)

    def test_ssa_simulation(self, tmp_path):
        bngl = tmp_path / "ssa.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        network = _cpp.generate_network(model)
        result = _cpp.simulate_ssa(model, network, t_end=10.0, n_steps=50, seed=42)
        assert "time" in result

    def test_simulation_output_controls(self, tmp_path):
        bngl = tmp_path / "controls.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        network = _cpp.generate_network(model)
        sample_times = [0.0, 0.25, 1.5, 10.0]

        ode = _cpp.simulate_ode(
            model, network, t_end=10.0, n_steps=0, sample_times=sample_times
        )
        assert ode["time"].tolist() == sample_times

        ssa = _cpp.simulate_ssa(
            model,
            network,
            t_end=10.0,
            n_steps=0,
            sample_times=sample_times,
            seed=42,
        )
        assert ssa["time"].tolist() == sample_times

        with pytest.raises(RuntimeError, match="stop_if"):
            _cpp.simulate_ode(
                model, network, t_end=1.0, n_steps=1, stop_if="Xtot <"
            )

    @pytest.mark.parametrize("method", ["pla", "psa"])
    def test_approximate_simulation_respects_start_time(self, tmp_path, method):
        bngl = tmp_path / f"{method}.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        network = _cpp.generate_network(model)
        if method == "pla":
            result = _cpp.simulate_pla(
                model, network, t_start=2.0, t_end=4.0, n_steps=2
            )
        else:
            result = _cpp.simulate_psa(
                model, network, t_start=2.0, t_end=4.0, n_steps=2
            )

        assert result["time"][0] == pytest.approx(2.0)
        assert result["time"][-1] == pytest.approx(4.0)

    def test_nf_simulation(self, tmp_path):
        bngl = tmp_path / "nf.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        result = _cpp.simulate_nf(model, t_end=5.0, n_steps=10, seed=1)

        assert "time" in result
        assert "observables" in result
        assert result["construction_path"] == "direct"
        assert len(result["time"]) == 11
        assert result["time"][0] == 0.0
        assert result["time"][-1] == pytest.approx(5.0)
        obs_values = next(iter(result["observables"].values()))
        assert len(obs_values) == 11

    def test_nf_simulation_resolves_relative_tfun_from_model_path(
        self, tmp_path, monkeypatch
    ):
        table_dir = tmp_path / "tables"
        table_dir.mkdir()
        (table_dir / "rate.dat").write_text("0 1\n10 1\n")
        bngl = tmp_path / "relative_tfun.bngl"
        bngl.write_text(
            """
begin model
begin parameters
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules A_total A()
end observables
begin functions
    rate = TFUN(time, "tables/rate.dat")
end functions
begin reaction rules
    A() -> 0 rate
end reaction rules
end model
"""
        )

        monkeypatch.chdir(tmp_path.parent)
        model = bionetgen.load(str(bngl))
        result = model.simulate(method="nf", t_end=1.0, n_steps=2, seed=1)

        assert result.time[-1] == pytest.approx(1.0)
        assert result.observables["A_total"][0] == pytest.approx(1.0)

    def test_nf_direct_local_function_accepts_bare_global_observable(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "local_global_observable.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A(s~0~1)
    C(d)
end molecule types
begin seed species
    A(s~0) 1
    C(d!1).C(d!1) 1
end seed species
begin observables
    Molecules Atot A()
    Molecules Ctot C()
end observables
begin functions
    loc(x) = k*Atot + 0*Ctot(x)
end functions
begin reaction rules
    A(s~0) + C(d!1)%x.C(d!1) -> A(s~1) + C(d!1)%x.C(d!1) loc(x)
end reaction rules
end model
"""
        )

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        model = bionetgen.load(str(bngl))
        direct = model.simulate(
            method="nf", t_end=1.0, n_steps=2, seed=1
        )

        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT")
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
        xml = model.simulate(method="nf", t_end=1.0, n_steps=2, seed=1)

        assert direct.time.tolist() == xml.time.tolist()
        assert direct.observable_names == xml.observable_names
        for name in direct.observable_names:
            assert direct.observables[name].tolist() == xml.observables[name].tolist()

    def test_nf_direct_dynamic_rate_wraps_scoped_local_function(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "dynamic_scoped_local_rate.bngl"
        bngl.write_text(
            """
begin model
begin parameters
end parameters
begin molecule types
    A(s~0~1)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin observables
    Molecules A1 A(s~1)
end observables
begin functions
    tally(x) = A1(x)
end functions
begin reaction rules
    A(s~0)%x -> A(s~1) 2 + tally(x)
end reaction rules
end model
"""
        )

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        result = bionetgen.load(str(bngl)).simulate(
            method="nf", t_end=0.0, n_steps=1, seed=1
        )

        assert result.time.tolist() == [0.0, 0.0]

    def test_nf_direct_route_can_be_required(self, tmp_path, monkeypatch):
        bngl = tmp_path / "strict_nf.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
end model
"""
        )
        model = _cpp.parse_file(str(bngl))
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")

        with pytest.raises(RuntimeError, match="direct AST initialization required"):
            _cpp.simulate_nf(model, t_end=1.0, n_steps=1)

    def test_nf_xml_fallback_requires_explicit_opt_in(self, tmp_path, monkeypatch):
        bngl = tmp_path / "implicit_xml_nf.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
end model
"""
        )
        model = _cpp.parse_file(str(bngl))
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)
        monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)

        with pytest.raises(RuntimeError, match="XML fallback disabled"):
            _cpp.simulate_nf(model, t_end=1.0, n_steps=1)

    def test_simulate_method_nf_uses_nf_route(self, tmp_path, monkeypatch):
        bngl = tmp_path / "action_nf.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin actions
    simulate({method=>"nf",suffix=>"route",t_end=>1,n_steps=>2,seed=>1})
end actions
end model
"""
        )
        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")

        model = bionetgen.load(str(bngl))
        model.execute()

        assert (tmp_path / "action_nf_route.gdat").exists()
        assert (tmp_path / "action_nf_route.species").exists()

    def test_action_nf_xml_fallback_requires_explicit_opt_in(self, tmp_path, monkeypatch):
        bngl = tmp_path / "implicit_action_xml_nf.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    simulate_nf({prefix=>"implicit",t_end=>1,n_steps=>1})
end actions
end model
"""
        )
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)
        monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)

        with pytest.raises(RuntimeError, match="XML fallback disabled"):
            bionetgen.load(str(bngl)).execute()

    def test_simulate_nf_rejects_unsupported_continue(self, tmp_path):
        bngl = tmp_path / "nf_continue.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    simulate_nf({continue=>1,t_end=>1,n_steps=>1})
end actions
end model
"""
        )

        with pytest.raises(RuntimeError, match="NFsim does not support 'continue'"):
            bionetgen.load(str(bngl)).execute()

    @pytest.mark.parametrize(
        ("option", "value", "message"),
        [
            ("t_start", "1", "t_start"),
            ("param", "\"-unsupported_nf_flag\"", "param"),
        ],
    )
    def test_simulate_nf_rejects_unhandled_controls(
        self, tmp_path, option, value, message
    ):
        bngl = tmp_path / f"nf_{option}.bngl"
        bngl.write_text(
            f"""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    simulate_nf({{{option}=>{value},t_end=>1,n_steps=>1}})
end actions
end model
"""
        )

        with pytest.raises(RuntimeError, match=message):
            bionetgen.load(str(bngl)).execute()

    def test_simulate_nf_accepts_legacy_supported_param_flags(self, tmp_path):
        bngl = tmp_path / "nf_param_compat.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin actions
    simulate_nf({prefix=>"param_compat",t_end=>1,n_steps=>1,param=>"-gml 1000000 -utl 4 -notf"})
end actions
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "param_compat.gdat"
        assert output.exists()
        assert "X_total" in output.read_text()

    def test_simulate_nf_separates_complex_bookkeeping_from_ring_blocking(
        self, tmp_path
    ):
        """NFsim's -cb and -bscb switches must keep their distinct meanings.

        Native NFsim enables complex bookkeeping for ``-cb`` but blocks an
        intracomplex bond only when ``-bscb`` is also present. This fixture
        makes that distinction observable with a high-rate ring closure.
        """
        bngl = tmp_path / "nf_complex_flags.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 1000000
end parameters
begin molecule types
    A(x,y)
    B(x,z)
end molecule types
begin seed species
    A(x!1,y).B(x!1,z) 1
end seed species
begin observables
    Molecules closed A(y!2).B(z!2)
end observables
begin reaction rules
    A(x!1,y) + B(x!1,z) -> A(x!1,y!2).B(x!1,z!2) k
end reaction rules
begin actions
    simulate_nf({prefix=>"cb",t_end=>1,n_steps=>1,seed=>1,complex=>1})
    simulate_nf({prefix=>"bscb",t_end=>1,n_steps=>1,seed=>1,complex=>1,param=>"-bscb"})
end actions
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        cb_rows = (tmp_path / "cb.gdat").read_text().splitlines()
        bscb_rows = (tmp_path / "bscb.gdat").read_text().splitlines()
        assert float(cb_rows[-1].split()[1]) == pytest.approx(1.0)
        assert float(bscb_rows[-1].split()[1]) == pytest.approx(0.0)

    def test_simulate_nf_action_honors_sample_times(self, tmp_path):
        bngl = tmp_path / "nf_sample_times.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin actions
    simulate_nf({prefix=>"sample_times",t_end=>1,sample_times=>[0,0.25,0.75]})
end actions
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "sample_times.gdat"
        rows = [
            line.split()
            for line in output.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == pytest.approx([0.0, 0.25, 0.75, 1.0])

    def test_simulate_nf_action_outputs_global_functions(self, tmp_path):
        bngl = tmp_path / "nf_functions.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin functions
    rate = k
end functions
begin reaction rules
    X() -> 0 rate
end reaction rules
begin actions
    simulate_nf({prefix=>"functions",t_end=>1,n_steps=>1,print_functions=>1})
end actions
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "functions.gdat"
        assert "rate" in output.read_text()

    def test_simulate_nf_action_binary_output_writes_header(self, tmp_path):
        bngl = tmp_path / "nf_binary.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    simulate_nf({prefix=>"binary",t_end=>1,n_steps=>1,binary_output=>1})
end actions
end model
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "binary.gdat"
        assert output.exists()
        assert output.stat().st_size > 0
        assert (tmp_path / "binary.gdat.head").exists()
        assert "Time" in (tmp_path / "binary.gdat.head").read_text()

    def test_simulate_nf_action_rejects_invalid_equilibration(self, tmp_path):
        bngl = tmp_path / "nf_bad_equil.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    simulate_nf({equil=>-1,t_end=>1,n_steps=>1})
end actions
end model
"""
        )

        with pytest.raises(RuntimeError, match="equil.*non-negative"):
            bionetgen.load(str(bngl)).execute()

    def test_action_rejects_unknown_simulation_method(self, tmp_path):
        bngl = tmp_path / "unknown_method.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules X_total X()
end observables
begin reaction rules
    X() -> 0 1
end reaction rules
begin actions
    simulate({method=>"not_a_method",t_end=>1,n_steps=>1})
end actions
end model
"""
        )

        with pytest.raises(RuntimeError, match="unsupported simulation method"):
            bionetgen.load(str(bngl)).execute()

    def test_action_rejects_unknown_visualization_type(self, tmp_path):
        bngl = tmp_path / "unknown_visualization.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin actions
    visualize({type=>"not_a_visualization"})
end actions
end model
"""
        )

        with pytest.raises(RuntimeError, match="unsupported visualization type"):
            bionetgen.load(str(bngl)).execute()

    def test_writefile_honors_ssc_prefix_suffix_and_overwrite(self, tmp_path):
        bngl = tmp_path / "writefile_contract.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin reaction rules
    X() -> 0 k
end reaction rules
end model

writeFile({format=>"ssc",prefix=>"export",suffix=>"v1"})
"""
        )

        model = bionetgen.load(str(bngl))
        model.execute()

        output = tmp_path / "export_v1.rxn"
        assert output.exists()
        assert "new X" in output.read_text()

        with pytest.raises(RuntimeError, match="file exists"):
            model.execute()

    def test_readnetwork_alias_loads_net_data(self, tmp_path):
        net_path = tmp_path / "import.net"
        net_path.write_text(
            """# imported network
begin parameters
    1 k 0.2
end parameters
begin species
    1 X() 7
end species
begin reactions
    1 1 0 k
end reactions
"""
        )
        bngl = tmp_path / "readnetwork.bngl"
        bngl.write_text(
            """
begin model
end model

readNetwork({file=>"import.net"})
writeNetwork()
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "readnetwork.net"
        assert output.exists()
        assert "X() 7" in output.read_text()

    def test_readnetwork_alias_rejects_missing_file(self, tmp_path):
        bngl = tmp_path / "missing_readnetwork.bngl"
        bngl.write_text(
            """
begin model
end model

readNetwork({file=>"missing.net"})
"""
        )

        with pytest.raises(RuntimeError, match=r"Failed to read \.net file"):
            bionetgen.load(str(bngl)).execute()

    def test_readmodel_alias_loads_bngl_data(self, tmp_path):
        imported = tmp_path / "imported.bngl"
        imported.write_text(
            """
begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 7
end seed species
end model
"""
        )
        bngl = tmp_path / "readmodel.bngl"
        bngl.write_text(
            """
begin model
end model

readModel({file=>"imported.bngl"})
writeModel()
"""
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "readmodel_out.bngl"
        assert output.exists()
        assert "X()" in output.read_text()

    def test_readmodel_alias_rejects_missing_file(self, tmp_path):
        bngl = tmp_path / "missing_readmodel.bngl"
        bngl.write_text(
            """
begin model
end model

readModel({file=>"missing.bngl"})
"""
        )

        with pytest.raises(RuntimeError, match="Could not open BNGL file"):
            bionetgen.load(str(bngl)).execute()


class TestHighLevelAPI:
    def test_load_and_simulate(self, tmp_path):
        bngl = tmp_path / "api.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = bionetgen.load(str(bngl))
        assert len(model.parameters) == 1
        assert len(model.reaction_rules) == 1

        result = model.simulate(method="ode", t_end=10.0, n_steps=50)
        assert result.n_steps == 51
        assert len(result.observable_names) >= 1

        sample_times = [0.0, 0.25, 1.5, 10.0]
        result = model.simulate(
            method="ode", t_end=10.0, n_steps=0, sample_times=sample_times
        )
        assert result.time.tolist() == sample_times

        result = model.simulate(
            method="ssa", t_end=10.0, n_steps=0, sample_times=sample_times, seed=42
        )
        assert result.time.tolist() == sample_times

        nf_sample_times = [0.0, 0.25, 1.5, 10.0]
        result = model.simulate(
            method="nf", t_end=10.0, n_steps=0,
            sample_times=nf_sample_times, seed=42
        )
        assert result.time.tolist() == nf_sample_times

        with pytest.raises(ValueError, match="only for method='ssa'"):
            model.simulate(
                method="ode", t_end=1.0, n_steps=1, max_sim_steps=1
            )

        for method in ["pla", "psa"]:
            result = model.simulate(method=method, t_start=2.0, t_end=4.0, n_steps=2)
            assert result.time[0] == pytest.approx(2.0)
            assert result.time[-1] == pytest.approx(4.0)

        with pytest.raises(ValueError, match="t_start=0.0"):
            model.simulate(method="nf", t_start=1.0, t_end=2.0, n_steps=1)

        with pytest.raises(ValueError, match="equilibrate must be finite and non-negative"):
            model.simulate(
                method="nf", t_end=1.0, n_steps=1, equilibrate=-0.1
            )

        result = model.simulate(
            method="nf", t_end=1.0, n_steps=1, seed=1, equilibrate=0.1
        )
        assert result.time.tolist() == pytest.approx([0.0, 1.0])

    def test_set_parameter(self, tmp_path):
        bngl = tmp_path / "param.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
        model = bionetgen.load(str(bngl))
        model.set_parameter("k", 0.5)

    def test_action_simulation_honors_sample_times(self, tmp_path):
        bngl = tmp_path / "action_controls.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 100
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
begin actions
    simulate_ode({prefix=>"sample",t_start=>0,t_end=>2,sample_times=>[0,0.25,1.5,2]})
end actions
end model
""")

        model = bionetgen.load(str(bngl))
        model.execute()
        rows = [
            line.split()
            for line in (tmp_path / "sample.gdat").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == [0.0, 0.25, 1.5, 2.0]

    def test_parameter_scan_action_writes_final_observables(self, tmp_path):
        bngl = tmp_path / "scan_action.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model

generate_network({overwrite=>1})
parameter_scan({method=>"ode",parameter=>"k",par_min=>0.1,par_max=>0.2,n_scan_pts=>2,par_scan_vals=>[9,10],t_end=>1,n_steps=>1})
"""
        )

        model = bionetgen.load(str(bngl))
        model.execute()

        scan_path = tmp_path / "scan_action_k.scan"
        assert scan_path.exists()
        rows = [
            line.split()
            for line in scan_path.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(rows) == 2
        assert [float(row[0]) for row in rows] == pytest.approx([0.1, 0.2])
        assert float(rows[0][1]) > float(rows[1][1])

    def test_parameter_scan_partial_range_uses_explicit_values(self, tmp_path):
        bngl = tmp_path / "scan_partial_range.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model

generate_network({overwrite=>1})
parameter_scan({method=>"ode",parameter=>"k",par_min=>0.9,par_scan_vals=>[0.1,0.2],t_end=>1,n_steps=>1})
"""
        )

        bionetgen.load(str(bngl)).execute()

        scan_path = tmp_path / "scan_partial_range_k.scan"
        assert scan_path.exists()
        rows = [
            line.split()
            for line in scan_path.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == pytest.approx([0.1, 0.2])

    def test_parameter_scan_nf_action_writes_final_observables(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "scan_nf_action.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model

parameter_scan({method=>"nf",parameter=>"k",par_scan_vals=>[0.1,0.2],t_end=>1,n_steps=>2,seed=>1})
"""
        )

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        bionetgen.load(str(bngl)).execute()

        scan_path = tmp_path / "scan_nf_action_k.scan"
        assert scan_path.exists()
        rows = [
            line.split()
            for line in scan_path.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(rows) == 2
        assert [float(row[0]) for row in rows] == pytest.approx([0.1, 0.2])

    def test_protocol_parameter_scan_uses_explicit_values(self, tmp_path):
        bngl = tmp_path / "protocol_scan.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
begin protocol
    simulate({method=>"ode",t_start=>0,t_end=>1,n_steps=>1})
end protocol
end model

generate_network({overwrite=>1})
parameter_scan({method=>"protocol",parameter=>"k",par_scan_vals=>[0.1,0.2]})
"""
        )

        model = bionetgen.load(str(bngl))
        model.execute()

        scan_path = tmp_path / "protocol_scan_k.scan"
        assert scan_path.exists()
        rows = [
            line.split()
            for line in scan_path.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(rows) == 2
        assert [float(row[0]) for row in rows] == pytest.approx([0.1, 0.2])
        assert float(rows[0][1]) > float(rows[1][1])

    def test_simulate_protocol_supports_direct_nf(self, tmp_path, monkeypatch):
        bngl = tmp_path / "protocol_nf.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
begin protocol
    simulate_nf({prefix=>"protocol_nf",t_end=>1,n_steps=>2,seed=>1})
end protocol
end model

simulate_protocol()
"""
        )

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        bionetgen.load(str(bngl)).execute()

        assert (tmp_path / "protocol_nf.gdat").exists()
        assert (tmp_path / "protocol_nf.species").exists()
        assert not (tmp_path / "protocol_nf.xml").exists()

    def test_linear_parameter_sensitivity_writes_gsc_and_csc(self, tmp_path):
        bngl = tmp_path / "linear_sensitivity.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model

generate_network({overwrite=>1})
LinearParameterSensitivity({t_end=>1,n_steps=>2,bump=>10,init_equil=>0,re_equil=>0,suffix=>"sens"})
"""
        )

        model = bionetgen.load(str(bngl))
        model.execute()

        gsc_path = tmp_path / "linear_sensitivity_k_sens.gsc"
        csc_path = tmp_path / "linear_sensitivity_k_sens.csc"
        assert gsc_path.exists()
        assert csc_path.exists()
        assert "Xtot" in gsc_path.read_text()
        assert "X()" in csc_path.read_text()


class TestIO:
    def test_in_memory_serialization_round_trips(self, tmp_path):
        bngl = tmp_path / "serialization.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 1.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
""")
        model = bionetgen.load(str(bngl))

        serialized_bngl = model.to_bngl()
        reparsed = _cpp.parse_string(serialized_bngl)
        assert len(reparsed.reaction_rules) == 1
        assert "begin model" in serialized_bngl

        serialized_xml = model.to_xml()
        root = ET.fromstring(serialized_xml)
        assert root.tag.endswith("sbml")
        assert root.find(".//{*}ListOfReactionRules") is not None

    def test_write_xml(self, tmp_path):
        bngl = tmp_path / "io.bngl"
        bngl.write_text("""
begin model
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
""")
        model = bionetgen.load(str(bngl))
        xml_path = str(tmp_path / "output.xml")
        model.write_xml(xml_path)
        assert os.path.exists(xml_path)
        with open(xml_path) as f:
            content = f.read()
        assert "A" in content
