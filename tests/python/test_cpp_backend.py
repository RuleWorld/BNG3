"""Tests for the C++ backend bindings."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from _extdep import require_extension

_cpp = require_extension()
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

    @pytest.mark.parametrize("seed_pattern", ["@cell:$A() 3", "$@cell:A() 3"])
    def test_parse_fixed_seed_marker_after_compartment_prefix(self, seed_pattern):
        text = f"""
begin model
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    {seed_pattern}
end seed species
end model
"""

        model = _cpp.parse_string(text)

        assert len(model.seed_species) == 1
        assert model.seed_species[0].is_constant
        assert model.seed_species[0].compartment == "cell"

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
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "inside_model.gdat"
        assert output.exists()
        content = output.read_text()
        assert "Atot" in content
        rows = [
            line.split()
            for line in content.splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == [0.0, 1.0]

    def test_integer_state_increment_and_decrement_rules_are_expanded(self, tmp_path):
        bngl = tmp_path / "integer_states.bngl"
        bngl.write_text("""
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
""")

        model = _cpp.parse_file(str(bngl))

        # Eight transitions in each direction, with the integer state range
        # inferred from the two native boundary rules.
        assert len(model.reaction_rules) == 16

    def test_singular_function_block_header_is_accepted(self, tmp_path):
        """BNG2/NFsim-era fixtures use ``begin function`` as a legacy alias."""
        bngl = tmp_path / "singular_function_block.bngl"
        bngl.write_text("""
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
""")

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

    def test_cbnGL_iteration_three_deduplicates_compartmented_isomorphs(self):
        """Match the BNG2 iteration-3 boundary for the cBNGL fixture.

        The independent BNG2 oracle reports 16 species after iteration 3.
        Two isomorphic compartmented products can serialize their root
        molecules in different orders; that representation detail must not
        create a second species.
        """
        model = _cpp.parse_file(get_model_path("Motivating_example_cBNGL.bngl"))
        network = _cpp.generate_network(model, max_iter=3)

        assert network.num_species == 16

    def test_python_max_iter_override_bypasses_invalid_bngl_protocol_option(
        self, tmp_path
    ):
        bngl = tmp_path / "python_max_iter_override.bngl"
        bngl.write_text(
            """
begin molecule types
    A(s~0~1~2)
end molecule types
begin seed species
    A(s~0) 1
end seed species
begin reaction rules
    r01: A(s~0) -> A(s~1) 1
    r12: A(s~1) -> A(s~2) 1
end reaction rules
begin actions
    generate_network({max_iter=>(1/0)**0})
end actions
""",
            encoding="utf-8",
        )
        model = _cpp.parse_file(str(bngl))

        # The direct binding's numeric option (default 100, or the explicit
        # value below) retains its existing contract independently of BNGL actions.
        default_network = _cpp.generate_network(model)
        assert default_network.num_species == 3
        assert default_network.num_reactions == 2

        network = _cpp.generate_network(model, max_iter=2)
        assert network.num_species == 3
        assert network.num_reactions == 2

    @pytest.mark.parametrize(
        "max_agg, expected_species, expected_reactions",
        [("1+1", 2, 1), ("-1", 1, 0)],
    )
    def test_python_generate_network_uses_typed_bngl_max_agg(
        self, tmp_path, max_agg, expected_species, expected_reactions
    ):
        bngl = tmp_path / "python_max_agg.bngl"
        bngl.write_text(
            f"""
begin model
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 1
end seed species
begin reaction rules
    bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({{overwrite=>1,max_iter=>3,max_agg=>{max_agg}}})
""",
            encoding="utf-8",
        )
        model = _cpp.parse_file(str(bngl))

        # The direct Python API continues to use its existing max_iter default;
        # max_agg remains the option on the model's BNGL generate_network action.
        network = _cpp.generate_network(model)
        assert network.num_species == expected_species
        assert network.num_reactions == expected_reactions

    @pytest.mark.parametrize(
        "max_stoich, expected_species, expected_reactions",
        [
            ("{A=>1+1}", 2, 1),
            ("{A=>1}", 1, 0),
            ("{A=>2.5}", 2, 1),
            ("{A=>-1}", 1, 0),
        ],
    )
    def test_python_generate_network_uses_typed_bngl_max_stoich(
        self, tmp_path, max_stoich, expected_species, expected_reactions
    ):
        bngl = tmp_path / "python_max_stoich.bngl"
        bngl.write_text(
            f"""
begin model
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 1
end seed species
begin reaction rules
    bind: A(b) + A(b) -> A(b!1).A(b!1) 1
end reaction rules
end model

generate_network({{overwrite=>1,max_iter=>3,max_stoich=>{max_stoich}}})
""",
            encoding="utf-8",
        )
        model = _cpp.parse_file(str(bngl))

        # Network generation through the Python binding must compile the
        # model's BNGL max_stoich action with the same typed limits.
        network = _cpp.generate_network(model)
        assert network.num_species == expected_species
        assert network.num_reactions == expected_reactions

    def test_generate_network_can_prune_structurally_zero_local_rate_products(
        self, tmp_path
    ):
        model_template = """
begin model
begin parameters
    kOn 1
    kOff 1
end parameters
begin molecule types
    A(b,c)
    B(a)
    C(a)
end molecule types
begin seed species
    A(b,c) 100
    B(a) 100
    C(a) 100
end seed species
begin observables
    Molecules B_local B()
    Molecules C_local C()
end observables
begin functions
    B_rate_on(x) = if(C_local(x)>0,0,kOn)
    C_rate_on(x) = if(B_local(x)>0,0,kOn)
end functions
begin reaction rules
    bind_B: %x:A(b) + B(a) <-> %x:A(b!1).B(a!1) B_rate_on(x),kOff
    bind_C: %x:A(c) + C(a) <-> %x:A(c!1).C(a!1) C_rate_on(x),kOff
end reaction rules
end model
"""

        def generate(filename, option=""):
            bngl = tmp_path / filename
            bngl.write_text(
                model_template
                + "\ngenerate_network({overwrite=>1,max_iter=>8"
                + option
                + "})\n",
                encoding="utf-8",
            )
            return _cpp.generate_network(_cpp.parse_file(str(bngl)))

        unpruned = generate("zero_rate_unpruned.bngl")
        pruned = generate("zero_rate_pruned.bngl", ",prune_zero_rates=>1")

        def has_ternary_complex(network):
            return any(
                all(name.count(f"{molecule}(") == 1 for molecule in ("A", "B", "C"))
                for name in network.species_names
            )

        def has_complex(network, present, absent=()):
            return any(
                all(name.count(f"{molecule}(") == 1 for molecule in present)
                and all(name.count(f"{molecule}(") == 0 for molecule in absent)
                for name in network.species_names
            )

        assert has_ternary_complex(unpruned)
        # The absent ternary species also proves that zero-rate candidates are
        # rejected before their product species are inserted.
        assert not has_ternary_complex(pruned)
        # Seed species remain present even when a zero-rate candidate would
        # otherwise reach a structurally matching product.
        assert any(name.startswith("A(") for name in pruned.species_names)
        assert any(name.startswith("B(") for name in pruned.species_names)
        assert any(name.startswith("C(") for name in pruned.species_names)
        assert has_complex(pruned, ("A", "B"), ("C",))
        assert has_complex(pruned, ("A", "C"), ("B",))
        assert any(
            reaction.startswith("bind_B:|") for reaction in pruned.reaction_strings
        )
        assert any(
            reaction.startswith("bind_C:|") for reaction in pruned.reaction_strings
        )
        # The parameterized reverse rates remain unknown to the proof and are
        # retained independently of the structurally-zero forward direction.
        assert any(
            reaction.startswith("_reverse__bind_B:|")
            for reaction in pruned.reaction_strings
        )
        assert any(
            reaction.startswith("_reverse__bind_C:|")
            for reaction in pruned.reaction_strings
        )

        seeded_template = model_template.replace(
            "    C(a) 100\nend seed species",
            "    C(a) 100\n    A(b!1,c!2).B(a!1).C(a!2) 1\nend seed species",
        )
        seeded_path = tmp_path / "zero_rate_seeded_product.bngl"
        seeded_path.write_text(
            seeded_template
            + "\ngenerate_network({overwrite=>1,max_iter=>8,prune_zero_rates=>1})\n",
            encoding="utf-8",
        )
        seeded_network = _cpp.generate_network(_cpp.parse_file(str(seeded_path)))
        assert has_ternary_complex(seeded_network)

    def test_zero_rate_pruning_preserves_global_and_symbolic_parameter_rates(
        self, tmp_path
    ):
        bngl = tmp_path / "zero_rate_unknowns.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    kZero 0
    kOn 1
end parameters
begin molecule types
    A()
    B()
    C()
    D()
end molecule types
begin seed species
    A() 1
    C() 1
end seed species
begin observables
    Molecules C_total C()
end observables
begin functions
    global_gate() = if(C_total>0,0,kOn)
end functions
begin reaction rules
    A() -> B() kZero
    A() -> D() global_gate()
end reaction rules
end model
generate_network({overwrite=>1,prune_zero_rates=>1})
""",
            encoding="utf-8",
        )

        network = _cpp.generate_network(_cpp.parse_file(str(bngl)))

        assert any(name.startswith("B(") for name in network.species_names)
        assert any(name.startswith("D(") for name in network.species_names)

    def test_zero_rate_pruning_preserves_rate_with_undefined_operand(self, tmp_path):
        bngl = tmp_path / "zero_rate_undefined_operand.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    undefined_rate: A() -> B() 0 * sqrt(-1)
end reaction rules
end model
generate_network({overwrite=>1,prune_zero_rates=>1})
""",
            encoding="utf-8",
        )

        network = _cpp.generate_network(_cpp.parse_file(str(bngl)))

        # sqrt(-1) has no finite value, so the rate is not proven to be zero.
        # Pruning must retain the possible B product instead of treating the
        # left-hand zero as an algebraic short circuit.
        assert any(name.startswith("B(") for name in network.species_names)

    @pytest.mark.parametrize("entry", ["A=>2^3", "A=>1e309", 'A=>"2"'])
    def test_python_generate_network_defers_unsupported_max_stoich(
        self, tmp_path, entry
    ):
        bngl = tmp_path / "python_invalid_max_stoich.bngl"
        bngl.write_text(
            f"""
begin model
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 1
end seed species
end model

generate_network({{max_stoich=>{{{entry}}}}})
""",
            encoding="utf-8",
        )
        model = _cpp.parse_file(str(bngl))

        with pytest.raises(RuntimeError) as error:
            _cpp.generate_network(model)
        assert "max_stoich" in str(error.value)
        assert entry in str(error.value)

    def test_python_generate_network_defers_invalid_max_agg_diagnostic(self, tmp_path):
        bngl = tmp_path / "python_invalid_max_agg.bngl"
        bngl.write_text(
            """
begin model
begin molecule types
    A(b)
end molecule types
begin seed species
    A(b) 1
end seed species
end model

generate_network({max_agg=>"2junk"})
""",
            encoding="utf-8",
        )
        model = _cpp.parse_file(str(bngl))

        with pytest.raises(RuntimeError) as error:
            _cpp.generate_network(model)
        assert "max_agg" in str(error.value)
        assert '"2junk"' in str(error.value)

    def test_model_function_forward_rate_keeps_complex_reverse_rate(self, tmp_path):
        """A model-function forward rate must not drop its reverse rate."""
        bngl = tmp_path / "reversible_function_rate.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    k 3
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 0
end seed species
begin functions
    forward() = 1
end functions
begin reaction rules
    0 <-> A() forward(),10^k
end reaction rules
end model
""",
            encoding="utf-8",
        )

        model = bionetgen.load(str(bngl))
        model.generate_network()
        net = tmp_path / "reversible_function_rate.net"
        model.write_net(str(net))

        text = net.read_text(encoding="utf-8")
        assert "rateLaw1 1000" in text
        assert "rateLaw1 #_reverse__R1" in text
        assert "(10 ^ k) #_reverse__R1" not in text


class TestSimulation:
    def test_parameter_only_model_simulates_without_zero_state_cvode(self):
        model = _cpp.parse_string("""
begin model
begin parameters
    k 2
end parameters
begin functions
    signal() = k + time
end functions
end model
""")
        network = _cpp.generate_network(model)

        result = _cpp.simulate_ode(model, network, t_end=1.0, n_steps=2)

        assert result["time"].tolist() == pytest.approx([0.0, 0.5, 1.0])
        assert result["concentrations"].shape == (3, 0)
        assert result["functions"]["signal"].tolist() == pytest.approx([2.0, 2.5, 3.0])

    def test_unused_species_degradation_parameter_does_not_change_ode(self):
        model = _cpp.parse_string("""
begin model
begin parameters
    proAUR1_degradation_rate 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Species X X()
end observables
begin reaction rules
    synth: 0 -> X() 1
    degrade: X() -> 0 0.07
end reaction rules
end model
""")
        network = _cpp.generate_network(model)
        result = _cpp.simulate_ode(
            model, network, t_end=1.0, n_steps=1, rtol=1e-7, atol=1e-12
        )

        assert result["observables"]["X"][-1] == pytest.approx(0.9658024875, rel=1e-7)

    def test_ode_derived_rate_fallback_matches_rule_rate_prefix(self):
        model = _cpp.parse_string("""
begin model
begin parameters
    R1Rate_2 0.5
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Species X X()
end observables
begin reaction rules
    R1: 0 -> X() 1
    degrade: X() -> 0 0.07
end reaction rules
end model
""")
        network = _cpp.generate_network(model)
        result = _cpp.simulate_ode(
            model, network, t_end=1.0, n_steps=1, rtol=1e-7, atol=1e-12
        )

        assert result["observables"]["X"][-1] == pytest.approx(0.48290124, rel=1e-7)

    def test_bng2_zero_argument_function_rates_execute(self, tmp_path):
        """The BNG2 test_time fixture must execute through the action path."""
        source = Path(VALIDATION_DIR) / "Validate" / "test_time.bngl"
        bngl = tmp_path / source.name
        bngl.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "test_time.gdat"
        assert output.exists()
        rows = output.read_text(encoding="utf-8").splitlines()
        assert rows[0].lstrip("#").split() == [
            "time",
            "t",
            "x_exact",
            "x_builtin",
            "f_correct",
            "f_builtin",
            "f_diff",
        ]
        assert len(rows) == 102  # header plus 100 output intervals and t=0
        final = [float(value) for value in rows[-1].split()]
        assert final[1] == pytest.approx(10.0)
        # Both rate laws integrate from 0 to 10 as \int_0^10 t dt = 50.
        # In the scheduled BNG2 replay, x_builtin is still zero at t=0.02;
        # keep this assertion tied to the time integral, not that trajectory.
        assert final[2] == pytest.approx(50.0, rel=1e-8)
        assert final[3] == pytest.approx(50.0, rel=1e-8)
        assert final[4] == pytest.approx(10.0)
        assert final[5] == pytest.approx(10.0)
        assert final[6] == pytest.approx(0.0, abs=1e-10)

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

    def test_total_rate_does_not_apply_reactant_symmetry_factor(self):
        """A complete SBML flux must not be divided by repeated-reactant symmetry."""
        model = _cpp.parse_string("""
begin model
begin parameters
    k 1.0
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
    A() + A() + A() -> 0 k TotalRate
end reaction rules
end model
""")
        network = _cpp.generate_network(model)
        result = _cpp.simulate_ode(model, network, t_end=1.0, n_steps=1)

        assert result["observables"]["Atot"][-1] == pytest.approx(7.0)

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

        # Explicit grids stay exact through the direct API when they omit
        # t_start, including when an initial stop_if check is false.
        omitted_start_times = [2.25, 2.5, 2.75]
        ode = _cpp.simulate_ode(
            model,
            network,
            t_start=2.0,
            t_end=2.75,
            n_steps=0,
            sample_times=omitted_start_times,
            stop_if="Xtot < 0",
        )
        assert ode["time"].tolist() == omitted_start_times

        ssa = _cpp.simulate_ssa(
            model,
            network,
            t_start=2.0,
            t_end=2.75,
            n_steps=0,
            sample_times=omitted_start_times,
            seed=42,
            stop_if="Xtot < 0",
        )
        assert ssa["time"].tolist() == omitted_start_times

        with pytest.raises(RuntimeError, match="batch SSA does not support stop_if"):
            _cpp.simulate_ssa(
                model,
                network,
                t_end=3.0,
                t_start=2.0,
                sample_times=[2.25, 2.5, 2.75],
                batch_size=2,
                batch_gpu_preferred=False,
                stop_if="Xtot > 99",
            )

        zero_species = tmp_path / "zero_species.bngl"
        zero_species.write_text("""
begin model
begin parameters
    N 4
end parameters
begin molecule types
    X()
end molecule types
end model
""")
        zero_model = _cpp.parse_file(str(zero_species))
        zero_network = _cpp.generate_network(zero_model)
        with pytest.raises(RuntimeError, match="batch SSA does not support stop_if"):
            _cpp.simulate_ssa(
                zero_model,
                zero_network,
                t_start=2.0,
                t_end=3.0,
                sample_times=[2.25, 2.5, 2.75],
                batch_size=2,
                batch_gpu_preferred=False,
                stop_if="time > 1",
            )

        stopped = _cpp.simulate_ode(
            model,
            network,
            t_start=2.0,
            t_end=3.0,
            n_steps=0,
            sample_times=[2.25, 2.5, 2.75],
            stop_if="Xtot > 99",
        )
        assert stopped["time"].tolist() == [2.0]
        assert stopped["observables"]["Xtot"].tolist() == [100.0]

        with pytest.raises(RuntimeError, match="stop_if"):
            _cpp.simulate_ode(model, network, t_end=1.0, n_steps=1, stop_if="Xtot <")

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

    def test_nf_negative_composite_rate_raises_value_error(self, tmp_path):
        bngl = tmp_path / "nf_negative_composite_rate.bngl"
        bngl.write_text("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    bad() = -1 + 0 * Xtot
end functions
begin reaction rules
    birth: 0 -> X() bad()
end reaction rules
end model
""")

        model = bionetgen.load(str(bngl))
        with pytest.raises(ValueError, match="R1.*negative propensity"):
            model.simulate(method="nf", t_end=0.0, n_steps=1, seed=1)

    def test_nf_simulation_honors_absolute_start_time(self, tmp_path):
        # Source-derived from NFsim test/Issue78/issue78.bngl and afad408:
        # absolute start time must affect both the output axis and a generic
        # time() function used as a reaction rate.
        bngl = tmp_path / "issue78.bngl"
        bngl.write_text("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    stimulus() = time()
end functions
begin reaction rules
    R: 0 -> X() stimulus()
end reaction rules
end model
""")
        model = bionetgen.load(str(bngl))
        result = model.simulate(
            method="nf",
            t_start=100.0,
            t_end=102.0,
            n_steps=0,
            sample_times=[100.0, 101.0, 102.0],
            seed=1,
        )

        assert result.time.tolist() == pytest.approx([100.0, 101.0, 102.0])
        assert result.observables["Xtot"][-1] > 100.0

        uniform = model.simulate(
            method="nf", t_start=100.0, t_end=102.0, n_steps=20, seed=1
        )
        assert uniform.time[0] == 100.0
        assert uniform.time[-1] == 102.0
        assert uniform.observables["Xtot"][-1] > 100.0
        assert uniform.observables["Xtot"][10] == result.observables["Xtot"][1]
        assert uniform.observables["Xtot"][-1] == result.observables["Xtot"][-1]

    def test_nf_sampling_matches_nfsim_accumulated_output_grid(self, tmp_path):
        # Source-derived from NFsim System::sim: output checkpoints advance by
        # repeated dSampleTime addition, not by multiplying the step index.
        bngl = tmp_path / "nf_sample_grid.bngl"
        bngl.write_text("""
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
""")
        model = _cpp.parse_file(str(bngl))
        result = _cpp.simulate_nf(model, t_end=0.2, n_steps=20, seed=1)

        dt = 0.2 / 20
        expected = [0.0]
        for _ in range(19):
            expected.append(expected[-1] + dt)
        expected.append(0.2)
        assert result["time"].tolist() == expected

    def test_nf_final_sample_excludes_event_after_stopping_time(self, tmp_path):
        bngl = tmp_path / "nf_final_sample_excludes_crossing_event.bngl"
        bngl.write_text("""
begin model
begin molecule types
    X()
end molecule types
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    birth: 0 -> X() 1.0
end reaction rules
end model
""")

        model = _cpp.parse_file(str(bngl))
        result = _cpp.simulate_nf(model, t_end=1e-6, n_steps=1, seed=1)

        assert result["construction_path"] == "direct"
        assert result["time"].tolist() == [0.0, 1e-6]
        assert result["observables"]["Xtot"].tolist() == [0.0, 0.0]

    def test_nf_simulation_accepts_traversal_limit(self, tmp_path):
        bngl = tmp_path / "nf_traversal_limit.bngl"
        bngl.write_text("""
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
""")

        model = _cpp.parse_file(str(bngl))
        result = _cpp.simulate_nf(
            model, t_end=1.0, n_steps=1, seed=1, traversal_limit=1
        )

        assert result["construction_path"] == "direct"
        assert result["time"].tolist() == [0.0, 1.0]

    def test_nf_simulation_resolves_relative_tfun_from_model_path(
        self, tmp_path, monkeypatch
    ):
        table_dir = tmp_path / "tables"
        table_dir.mkdir()
        (table_dir / "rate.dat").write_text("0 1\n10 1\n")
        bngl = tmp_path / "relative_tfun.bngl"
        bngl.write_text("""
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
""")

        monkeypatch.chdir(tmp_path.parent)
        model = bionetgen.load(str(bngl))
        result = model.simulate(method="nf", t_end=1.0, n_steps=2, seed=1)

        assert result.time[-1] == pytest.approx(1.0)
        assert result.observables["A_total"][0] == pytest.approx(1.0)

    def test_nf_local_function_mixing_global_and_local_observable_is_refused(
        self, tmp_path, monkeypatch
    ):
        # ruleworld/nfsim#104: a local function reading both a global
        # observable (outside its argument) and a locally-scoped observable
        # goes stale, so both loaders must refuse it instead of returning
        # silently wrong propensities.
        bngl = tmp_path / "local_global_observable.bngl"
        bngl.write_text("""
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
""")

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        with pytest.raises(RuntimeError, match="direct AST initialization required"):
            bionetgen.load(str(bngl)).simulate(
                method="nf", t_end=1.0, n_steps=2, seed=1
            )

        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT")
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
        with pytest.raises(RuntimeError, match="Failed to initialize NFSim system"):
            bionetgen.load(str(bngl)).simulate(
                method="nf", t_end=1.0, n_steps=2, seed=1
            )

    def test_nf_direct_dynamic_rate_wraps_scoped_local_function(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "dynamic_scoped_local_rate.bngl"
        bngl.write_text("""
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
""")

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        result = bionetgen.load(str(bngl)).simulate(
            method="nf", t_end=0.0, n_steps=1, seed=1
        )

        assert result.time.tolist() == [0.0, 0.0]

    def test_nf_direct_route_can_be_required(self, tmp_path, monkeypatch):
        bngl = tmp_path / "strict_nf.bngl"
        bngl.write_text("""
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
""")
        model = _cpp.parse_file(str(bngl))
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")

        with pytest.raises(RuntimeError, match="direct AST initialization required"):
            _cpp.simulate_nf(model, t_end=1.0, n_steps=1)

    def test_nf_xml_fallback_requires_explicit_opt_in(self, tmp_path, monkeypatch):
        bngl = tmp_path / "implicit_xml_nf.bngl"
        bngl.write_text("""
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
""")
        model = _cpp.parse_file(str(bngl))
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)
        monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)

        with pytest.raises(RuntimeError, match="XML fallback disabled"):
            _cpp.simulate_nf(model, t_end=1.0, n_steps=1)

    def test_nf_physical_units_cannot_use_forced_xml_fallback(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "physical_units_forced_xml.bngl"
        bngl.write_text("""
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin parameters
    k = 1e-9 [M/second]
  end parameters
  begin compartments
    cell 3 2 [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin reaction rules
    source: 0 -> A()@cell k
  end reaction rules
end model
""")
        model = _cpp.parse_file(str(bngl))
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)

        with pytest.raises(RuntimeError, match="cannot preserve physical units"):
            _cpp.simulate_nf(model, t_end=1e-14, n_steps=1, seed=42)

    def test_simulate_method_nf_uses_nf_route(self, tmp_path, monkeypatch):
        bngl = tmp_path / "action_nf.bngl"
        bngl.write_text("""
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
""")
        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")

        model = bionetgen.load(str(bngl))
        model.execute()

        assert (tmp_path / "action_nf_route.gdat").exists()
        assert (tmp_path / "action_nf_route.species").exists()

    def test_action_nf_xml_fallback_requires_explicit_opt_in(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "implicit_action_xml_nf.bngl"
        bngl.write_text("""
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
""")
        monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
        monkeypatch.delenv("BNG_NFSIM_REQUIRE_DIRECT", raising=False)
        monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)

        with pytest.raises(RuntimeError, match="XML fallback disabled"):
            bionetgen.load(str(bngl)).execute()

    def test_simulate_nf_rejects_unsupported_continue(self, tmp_path):
        bngl = tmp_path / "nf_continue.bngl"
        bngl.write_text("""
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
""")

        with pytest.raises(RuntimeError, match="NFsim does not support 'continue'"):
            bionetgen.load(str(bngl)).execute()

    @pytest.mark.parametrize(
        ("option", "value", "message"),
        [
            ("param", '"-unsupported_nf_flag"', "param"),
        ],
    )
    def test_simulate_nf_rejects_unhandled_controls(
        self, tmp_path, option, value, message
    ):
        bngl = tmp_path / f"nf_{option}.bngl"
        bngl.write_text(f"""
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
""")

        with pytest.raises(RuntimeError, match=message):
            bionetgen.load(str(bngl)).execute()

    def test_simulate_nf_accepts_legacy_supported_param_flags(self, tmp_path):
        bngl = tmp_path / "nf_param_compat.bngl"
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "param_compat.gdat"
        assert output.exists()
        assert "X_total" in output.read_text()

    def test_simulate_nf_action_preserves_explicit_traversal_limit(
        self, tmp_path, capfd
    ):
        bngl = tmp_path / "nf_utl.bngl"
        bngl.write_text("""
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
    simulate_nf({prefix=>"utl",t_end=>0,n_steps=>1,utl=>1,verbose=>1})
end actions
end model
""")

        bionetgen.load(str(bngl)).execute(verbose=True)

        assert "Universal traversal limit = 1" in capfd.readouterr().err

    def test_simulate_nf_separates_complex_bookkeeping_from_ring_blocking(
        self, tmp_path
    ):
        """NFsim's -cb and -bscb switches must keep their distinct meanings.

        Native NFsim enables complex bookkeeping for ``-cb`` but blocks an
        intracomplex bond only when ``-bscb`` is also present. This fixture
        makes that distinction observable with a high-rate ring closure.
        """
        bngl = tmp_path / "nf_complex_flags.bngl"
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        cb_rows = (tmp_path / "cb.gdat").read_text().splitlines()
        bscb_rows = (tmp_path / "bscb.gdat").read_text().splitlines()
        assert float(cb_rows[-1].split()[1]) == pytest.approx(1.0)
        assert float(bscb_rows[-1].split()[1]) == pytest.approx(0.0)

    def test_simulate_nf_action_honors_sample_times(self, tmp_path):
        bngl = tmp_path / "nf_sample_times.bngl"
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "sample_times.gdat"
        rows = [
            line.split()
            for line in output.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == pytest.approx([0.0, 0.25, 0.75, 1.0])

    def test_simulate_nf_action_honors_absolute_start_time(self, tmp_path):
        # Source-derived from NFsim test/Issue78/issue78.bngl and afad408:
        # action execution must preserve the absolute time axis and evaluate
        # time() at that axis.
        bngl = tmp_path / "issue78_action.bngl"
        bngl.write_text("""
begin model
begin molecule types
    X()
end molecule types
begin seed species
    X() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin functions
    stimulus() = time()
end functions
begin reaction rules
    R: 0 -> X() stimulus()
end reaction rules
begin actions
    simulate_nf({prefix=>"issue78",t_start=>100,t_end=>102,sample_times=>[100,101,102],seed=>1,print_functions=>1})
    simulate_nf({prefix=>"issue78_uniform",t_start=>100,t_end=>102,n_steps=>20,seed=>1,print_functions=>1})
end actions
end model
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "issue78.gdat"
        rows = [
            line.split()
            for line in output.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == pytest.approx([100.0, 101.0, 102.0])
        assert "stimulus" in output.read_text()

        uniform_output = tmp_path / "issue78_uniform.gdat"
        uniform_rows = [
            line.split()
            for line in uniform_output.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(uniform_rows) == 21
        assert float(uniform_rows[0][0]) == 100.0
        assert float(uniform_rows[10][0]) == 101.0
        assert float(uniform_rows[-1][0]) == 102.0
        assert float(uniform_rows[0][-1]) == 100.0
        assert float(uniform_rows[10][-1]) == 101.0
        assert float(uniform_rows[-1][-1]) == 102.0
        assert float(uniform_rows[0][1]) == float(rows[0][1])
        assert float(uniform_rows[10][1]) == float(rows[1][1])
        assert float(uniform_rows[-1][1]) == float(rows[-1][1])

    def test_simulate_nf_action_outputs_global_functions(self, tmp_path):
        bngl = tmp_path / "nf_functions.bngl"
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "functions.gdat"
        assert "rate" in output.read_text()

    def test_simulate_nf_action_binary_output_writes_header(self, tmp_path):
        bngl = tmp_path / "nf_binary.bngl"
        bngl.write_text("""
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
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "binary.gdat"
        assert output.exists()
        assert output.stat().st_size > 0
        assert (tmp_path / "binary.gdat.head").exists()
        assert "Time" in (tmp_path / "binary.gdat.head").read_text()

    def test_simulate_nf_action_rejects_invalid_equilibration(self, tmp_path):
        bngl = tmp_path / "nf_bad_equil.bngl"
        bngl.write_text("""
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
""")

        with pytest.raises(RuntimeError, match="equil.*non-negative"):
            bionetgen.load(str(bngl)).execute()

    def test_action_rejects_unknown_simulation_method(self, tmp_path):
        bngl = tmp_path / "unknown_method.bngl"
        bngl.write_text("""
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
""")

        with pytest.raises(RuntimeError, match="unsupported simulation method"):
            bionetgen.load(str(bngl)).execute()

    def test_action_rejects_unknown_visualization_type(self, tmp_path):
        bngl = tmp_path / "unknown_visualization.bngl"
        bngl.write_text("""
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
""")

        with pytest.raises(RuntimeError, match="unsupported visualization type"):
            bionetgen.load(str(bngl)).execute()

    def test_writefile_honors_ssc_prefix_suffix_and_overwrite(self, tmp_path):
        bngl = tmp_path / "writefile_contract.bngl"
        bngl.write_text("""
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
""")

        model = bionetgen.load(str(bngl))
        model.execute()

        output = tmp_path / "export_v1.rxn"
        assert output.exists()
        assert "new X" in output.read_text()

        with pytest.raises(RuntimeError, match="file exists"):
            model.execute()

    def test_readnetwork_alias_loads_net_data(self, tmp_path):
        net_path = tmp_path / "import.net"
        net_path.write_text("""# imported network
begin parameters
    1 k 0.2
end parameters
begin species
    1 X() 7
end species
begin reactions
    1 1 0 k
end reactions
""")
        bngl = tmp_path / "readnetwork.bngl"
        bngl.write_text("""
begin model
end model

readNetwork({file=>"import.net"})
writeNetwork()
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "readnetwork.net"
        assert output.exists()
        assert "X() 7" in output.read_text()

    @pytest.mark.parametrize(
        ("initial_amount", "expected_amount", "error"),
        [
            ("(RAS_tot * (1 - RAS_t0_active))", 60000.0, None),
            ("10^2", 100.0, None),
            ("MISSING_AMOUNT", None, r"Failed to evaluate \.net initial amount"),
            ("1e308 * 1e308", None, "is not finite"),
        ],
    )
    def test_net_reload_evaluates_symbolic_initial_amount_with_context(
        self, tmp_path, initial_amount, expected_amount, error
    ):
        (tmp_path / "context.bngl").write_text(
            """begin model
begin parameters
    RAS_tot 60000
    RAS_t0_active 0
end parameters
end model
""",
            encoding="utf-8",
        )
        (tmp_path / "input.net").write_text(
            """begin parameters
    1 RAS_tot 60000
    2 RAS_t0_active 0
end parameters
begin species
    1 RAS(g~GDP,sos) __INITIAL_AMOUNT__
end species
begin reactions
end reactions
begin groups
    1 RAS_GDP 1
end groups
""".replace("__INITIAL_AMOUNT__", initial_amount),
            encoding="utf-8",
        )
        protocol = tmp_path / "symbolic_net_reload.bngl"
        protocol.write_text(
            """begin model
end model
begin actions
    readFile({file=>"context.bngl"})
    readFile({file=>"input.net"})
    simulate_ode({prefix=>"symbolic_net_reload",netfile=>"input.net",t_start=>0,t_end=>1,n_steps=>1,print_CDAT=>1})
end actions
""",
            encoding="utf-8",
        )

        if expected_amount is None:
            with pytest.raises(RuntimeError, match=error):
                bionetgen.load(str(protocol)).execute()
            return

        bionetgen.load(str(protocol)).execute()

        cdat = tmp_path / "symbolic_net_reload.cdat"
        rows = [
            [float(value) for value in line.split()]
            for line in cdat.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        assert rows[0][1] == pytest.approx(expected_amount)

    def test_set_add_concentration_survives_network_regeneration_in_net(self, tmp_path):
        bngl = tmp_path / "set_add_initial.bngl"
        bngl.write_text(
            """
begin model
begin parameters
    S0 100
    kRT 2
    kTR 1
end parameters
begin molecule types
    S(c~R~T)
end molecule types
begin seed species
    S(c~R) S0
end seed species
begin observables
    Molecules Total S()
end observables
begin reaction rules
    S(c~R) <-> S(c~T) kRT,kTR
end reaction rules
end model
begin actions
    setConcentration("S(c~R)","S0")
    addConcentration("S(c~R)","S0")
    generate_network({overwrite=>1})
end actions
""",
            encoding="utf-8",
        )

        bionetgen.load(str(bngl)).execute()

        net = tmp_path / "set_add_initial.net"
        assert net.exists()
        species_block = (
            net.read_text(encoding="utf-8")
            .split("begin species", 1)[1]
            .split("end species", 1)[0]
        )
        species_rows = [
            line.split() for line in species_block.splitlines() if line.strip()
        ]
        assert any(
            len(row) >= 3
            and row[1] == "S(c~R)"
            and float(row[2]) == pytest.approx(200.0)
            for row in species_rows
        )

    @pytest.mark.parametrize(
        "route", ["readFile", "include_network", "generate_network"]
    )
    def test_net_reload_preserves_compartmented_constant_species(self, tmp_path, route):
        net_path = tmp_path / "constant_compartment.net"
        net_path.write_text(
            """begin species
    1 @cell::$A() 7
end species
begin reactions
end reactions
""",
            encoding="utf-8",
        )
        bngl = tmp_path / "constant_compartment_roundtrip.bngl"
        if route == "readFile":
            load_action = 'readFile({file=>"constant_compartment.net"})'
        elif route == "include_network":
            load_action = 'include_network({file=>"constant_compartment.net"})'
        else:
            (tmp_path / "constant_compartment_roundtrip.net").write_text(
                net_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            load_action = "generate_network({overwrite=>0})"
        bngl.write_text(
            """
begin model
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
end molecule types
end model
begin actions
    __LOAD_ACTION__
    writeNetwork({prefix=>"constant_compartment_roundtrip",overwrite=>1})
end actions
""".replace("__LOAD_ACTION__", load_action),
            encoding="utf-8",
        )

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "constant_compartment_roundtrip.net"
        assert output.exists()
        assert "@cell::$A() 7" in output.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "route", ["readFile", "include_network", "generate_network"]
    )
    def test_net_reload_preserves_dynamic_rate_function_and_observable(
        self, tmp_path, route
    ):
        source = tmp_path / "dynamic_source.bngl"
        source.write_text(
            """
begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_free A()
end observables
begin functions
    rate() A_free
end functions
begin reaction rules
    A() -> 0 rate()
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
end actions
""",
            encoding="utf-8",
        )
        bionetgen.load(str(source)).execute()
        net_path = tmp_path / "dynamic_source.net"
        assert net_path.exists()
        net_text = net_path.read_text(encoding="utf-8")
        assert "A_free" in net_text
        assert "rate() A_free" in net_text

        reload = tmp_path / "dynamic_reload.bngl"
        if route == "readFile":
            load_action = 'readFile({file=>"dynamic_source.net"})'
        elif route == "include_network":
            load_action = 'include_network({file=>"dynamic_source.net"})'
        else:
            (tmp_path / "dynamic_reload.net").write_text(net_text, encoding="utf-8")
            load_action = "generate_network({overwrite=>0})"
        reload.write_text(
            """
begin model
begin molecule types
    A()
    B()
end molecule types
begin observables
    Molecules A_free B()
end observables
end model
begin actions
    __LOAD_ACTION__
    simulate({method=>"ode",t_end=>1,n_steps=>10,prefix=>"dynamic_reload"})
end actions
""".replace("__LOAD_ACTION__", load_action),
            encoding="utf-8",
        )
        bionetgen.load(str(reload)).execute()

        gdat = tmp_path / "dynamic_reload.gdat"
        assert gdat.exists()
        lines = gdat.read_text(encoding="utf-8").splitlines()
        header = next(
            line.lstrip("# ").split() for line in lines if line.startswith("#")
        )
        assert header == ["time", "A_free"]
        rows = [
            [float(value) for value in line.split()]
            for line in lines
            if line and not line.startswith("#")
        ]
        assert rows
        assert rows[0][1] == pytest.approx(10.0)
        for row in rows:
            expected = 10.0 / (1.0 + 10.0 * row[0])
            assert row[1] == pytest.approx(expected, rel=2e-3, abs=1e-4)

    def test_readnetwork_alias_rejects_missing_file(self, tmp_path):
        bngl = tmp_path / "missing_readnetwork.bngl"
        bngl.write_text("""
begin model
end model

readNetwork({file=>"missing.net"})
""")

        with pytest.raises(RuntimeError, match=r"Failed to read \.net file"):
            bionetgen.load(str(bngl)).execute()

    def test_readmodel_alias_loads_bngl_data(self, tmp_path):
        imported = tmp_path / "imported.bngl"
        imported.write_text("""
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
""")
        bngl = tmp_path / "readmodel.bngl"
        bngl.write_text("""
begin model
end model

readModel({file=>"imported.bngl"})
writeModel()
""")

        bionetgen.load(str(bngl)).execute()

        output = tmp_path / "readmodel_out.bngl"
        assert output.exists()
        assert "X()" in output.read_text()

    def test_readmodel_alias_rejects_missing_file(self, tmp_path):
        bngl = tmp_path / "missing_readmodel.bngl"
        bngl.write_text("""
begin model
end model

readModel({file=>"missing.bngl"})
""")

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
            method="nf", t_end=10.0, n_steps=0, sample_times=nf_sample_times, seed=42
        )
        assert result.time.tolist() == nf_sample_times

        with pytest.raises(ValueError, match="only for method='ssa'"):
            model.simulate(method="ode", t_end=1.0, n_steps=1, max_sim_steps=1)

        for method in ["pla", "psa"]:
            result = model.simulate(method=method, t_start=2.0, t_end=4.0, n_steps=2)
            assert result.time[0] == pytest.approx(2.0)
            assert result.time[-1] == pytest.approx(4.0)

        result = model.simulate(method="nf", t_start=1.0, t_end=2.0, n_steps=1, seed=1)
        assert result.time.tolist() == pytest.approx([1.0, 2.0])

        with pytest.raises(
            ValueError, match="equilibrate must be finite and non-negative"
        ):
            model.simulate(method="nf", t_end=1.0, n_steps=1, equilibrate=-0.1)

        result = model.simulate(
            method="nf", t_end=1.0, n_steps=1, seed=1, equilibrate=0.1
        )
        assert result.time.tolist() == pytest.approx([0.0, 1.0])

    def test_ode_exports_user_functions_without_internal_helpers(self, tmp_path):
        bngl = tmp_path / "function_outputs.bngl"
        bngl.write_text("""
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
begin functions
    _c_X() = Xtot
    algebraic() = k * _c_X()
end functions
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")

        result = bionetgen.load(str(bngl)).simulate(method="ode", t_end=1.0, n_steps=2)

        assert set(result.functions) == {"algebraic"}
        assert result.functions["algebraic"].tolist() == pytest.approx(
            0.1 * result.observables["Xtot"]
        )

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

    def test_parameter_value_is_read_only_and_refreshes_dependents(self, tmp_path):
        bngl = tmp_path / "derived_params.bngl"
        bngl.write_text("""
begin model
begin parameters
    base 2
    derived 3*base
    transitive 2*derived
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() transitive
end seed species
end model
""")
        model = bionetgen.load(str(bngl))

        with pytest.raises(AttributeError):
            model.get_parameter("base").value = 5.0

        model.set_parameter("base", 5.0)
        assert model.get_parameter("base").value == pytest.approx(5.0)
        assert model.get_parameter("derived").value == pytest.approx(15.0)
        assert model.get_parameter("transitive").value == pytest.approx(30.0)

        fresh = bionetgen.load(str(bngl))
        fresh.set_parameter("base", 5.0)
        snapshot = _cpp._compiled_snapshot(model._model)
        fresh_snapshot = _cpp._compiled_snapshot(fresh._model)
        values = {
            parameter["name"]: parameter["constant_value"]
            for parameter in snapshot["parameters"]
        }
        fresh_values = {
            parameter["name"]: parameter["constant_value"]
            for parameter in fresh_snapshot["parameters"]
        }
        assert (
            values
            == fresh_values
            == {
                "base": pytest.approx(5.0),
                "derived": pytest.approx(15.0),
                "transitive": pytest.approx(30.0),
            }
        )

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

    def test_action_sample_times_precedence_and_continue_start(self, tmp_path):
        bngl = tmp_path / "action_sample_times_boundaries.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
begin actions
    simulate_ode({prefix=>"precedence",t_start=>2,t_end=>3,n_steps=>2,sample_times=>[2.25,2.5,2.75]})
    simulate_ode({prefix=>"continue",t_start=>2,t_end=>3,n_steps=>1})
    simulate_ode({prefix=>"continue",continue=>1,t_end=>4,sample_times=>[3.5]})
end actions
end model
""")

        model = bionetgen.load(str(bngl))
        model.execute()

        def times(prefix):
            return [
                float(line.split()[0])
                for line in (tmp_path / f"{prefix}.gdat").read_text().splitlines()
                if line and not line.startswith("#")
            ]

        # n_steps wins and leaves the requested sample_times inactive.
        assert times("precedence") == [2.0, 2.5, 3.0]
        # The continued action starts at t=3 (the previous run's end), so its
        # grid is [3, 3.5, 4] before the duplicate t=3 row is appended away.
        assert times("continue") == [2.0, 3.0, 3.5, 4.0]

    def test_continue_t_end_is_a_duration_when_t_start_is_omitted(self, tmp_path):
        bngl = tmp_path / "continue_duration.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 1
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
begin actions
    simulate_ode({prefix=>"continue",t_end=>100,n_steps=>1})
    setConcentration("X()", 2)
    simulate_ode({prefix=>"continue",continue=>1,t_end=>10,n_steps=>1})
end actions
end model
""")

        model = bionetgen.load(str(bngl))
        model.execute()

        rows = [
            line.split()
            for line in (tmp_path / "continue.gdat").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert [float(row[0]) for row in rows] == [0.0, 100.0, 110.0]
        assert float(rows[-1][1]) == pytest.approx(2.0)

    def test_ssa_output_step_interval_records_internal_step_cadence(self, tmp_path):
        bngl = tmp_path / "ssa_output_step_interval.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 100
end parameters
begin molecule types
    X()
    Y()
end molecule types
begin seed species
    X() 10
    Y() 0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> Y() k
end reaction rules
begin actions
    simulate({method=>"ssa",prefix=>"cadence",t_end=>1,n_steps=>10,output_step_interval=>2,max_sim_steps=>5,seed=>1,print_CDAT=>0})
end actions
end model
""")

        model = bionetgen.load(str(bngl))
        model.execute()

        rows = [
            line.split()
            for line in (tmp_path / "cadence.gdat").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(rows) == 4  # initial state, steps 2 and 4, then final step 5
        assert float(rows[0][0]) == 0.0
        assert 0.0 < float(rows[1][0]) < float(rows[2][0])
        assert float(rows[2][0]) < float(rows[3][0]) <= 1.0

    def test_issue_208_default_ode_tolerance_tracks_tight_reference(self):
        fixture = (
            Path(__file__).parent.parent
            / "fixtures"
            / "upstream_issues"
            / "issue_208_integrator_accuracy.bngl"
        )
        model = _cpp.parse_file(str(fixture))
        network = _cpp.generate_network(model)

        default = _cpp.simulate_ode(model, network, t_end=10000, n_steps=1000)
        reference = _cpp.simulate_ode(
            model,
            network,
            t_end=10000,
            n_steps=1000,
            atol=1e-13,
            rtol=1e-13,
        )

        for name in ("LR", "LR2", "R"):
            actual = default["observables"][name]
            expected = reference["observables"][name]
            assert len(actual) == len(expected) == 1001
            for observed, target in zip(actual, expected):
                assert observed == pytest.approx(target, rel=1e-3, abs=1e-14)

    def test_parameter_scan_action_writes_final_observables(self, tmp_path):
        bngl = tmp_path / "scan_action.bngl"
        bngl.write_text("""
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
""")

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

    def test_parameter_scan_action_supports_process_isolated_workers(self, tmp_path):
        bngl = tmp_path / "scan_action_parallel.bngl"
        bngl.write_text("""
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

parameter_scan({method=>"ode",parameter=>"k",par_scan_vals=>[0.1,0.2],parallel=>1,num_cores=>2,t_end=>1,n_steps=>1})
""")

        bionetgen.load(str(bngl)).execute()

        scan_path = tmp_path / "scan_action_parallel_k.scan"
        assert scan_path.exists()
        rows = [
            line.split()
            for line in scan_path.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        assert len(rows) == 2
        assert [float(row[0]) for row in rows] == pytest.approx([0.1, 0.2])
        assert float(rows[0][1]) > float(rows[1][1])
        for index in (1, 2):
            assert (
                tmp_path
                / "scan_action_parallel_k"
                / f"scan_action_parallel_k_{index:05d}.gdat"
            ).exists()

    def test_parameter_scan_partial_range_uses_explicit_values(self, tmp_path):
        bngl = tmp_path / "scan_partial_range.bngl"
        bngl.write_text("""
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
""")

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
        bngl.write_text("""
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
""")

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
        bngl.write_text("""
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
""")

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
        bngl.write_text("""
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
""")

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        bionetgen.load(str(bngl)).execute()

        assert (tmp_path / "protocol_nf.gdat").exists()
        assert (tmp_path / "protocol_nf.species").exists()
        assert not (tmp_path / "protocol_nf.xml").exists()

    def test_simulate_protocol_applies_concentration_before_nf(
        self, tmp_path, monkeypatch
    ):
        bngl = tmp_path / "protocol_nf_concentration.bngl"
        bngl.write_text("""
begin model
begin parameters
    k 0
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
    setConcentration("X()",0)
    simulate_nf({prefix=>"protocol_nf_concentration",t_end=>1,n_steps=>1,seed=>1})
end protocol
end model

simulate_protocol()
""")

        monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
        bionetgen.load(str(bngl)).execute()

        rows = [
            line.split()
            for line in (tmp_path / "protocol_nf_concentration.gdat")
            .read_text()
            .splitlines()
            if line and not line.startswith("#")
        ]
        assert rows[-1][1] == "0.00000000e+00"

    def test_linear_parameter_sensitivity_writes_gsc_and_csc(self, tmp_path):
        bngl = tmp_path / "linear_sensitivity.bngl"
        bngl.write_text("""
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
""")

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
