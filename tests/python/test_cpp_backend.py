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
parameter_scan({method=>"ode",parameter=>"k",par_min=>0.1,par_max=>0.2,n_scan_pts=>2,t_end=>1,n_steps=>1})
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
