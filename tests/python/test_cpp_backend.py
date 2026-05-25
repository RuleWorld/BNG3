"""Tests for the C++ backend bindings."""

import os
import pytest

_cpp = pytest.importorskip("bionetgen._bionetgen_cpp")
import bionetgen

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
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
        "model_name, expected_species, expected_reactions",
        [
            ("blbr.bngl", 20, 92),
            ("Motivating_example_cBNGL.bngl", 78, 354),
        ],
    )
    def test_validation_models_match_reference(
        self, model_name, expected_species, expected_reactions
    ):
        model = _cpp.parse_file(get_model_path(model_name))
        network = _cpp.generate_network(model)

        assert network.num_species == expected_species
        assert network.num_reactions == expected_reactions


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
        assert len(result["time"]) == 11
        assert result["time"][0] == 0.0
        assert result["time"][-1] == pytest.approx(5.0)
        obs_values = next(iter(result["observables"].values()))
        assert len(obs_values) == 11


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


class TestIO:
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
