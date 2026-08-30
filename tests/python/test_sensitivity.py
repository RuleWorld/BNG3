import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

from bionetgen.builder import ModelBuilder


def test_sensitivity_decay_model():
    builder = ModelBuilder("Decay")
    builder.add_parameter("k", 0.1)
    builder.add_parameter("X0", 100)
    builder.add_molecule_type("X()")
    builder.add_seed_species("X()", "X0")
    builder.add_observable("Molecules", "Xtot", "X()")
    builder.add_rule("X() -> 0", "k")

    model = builder.build()
    result = model.sensitivity_analysis(
        parameters=["k"], observables=["Xtot"], t_end=10, n_steps=50, delta=0.01
    )

    assert result.matrix.shape == (1, 1)
    assert result.matrix[0, 0] == pytest.approx(-1.0, abs=0.2)
    assert result.rank("Xtot")[0][0] == "k"


def test_sensitivity_binding_signs():
    builder = ModelBuilder("Binding")
    builder.add_parameter("k_on", 1.0)
    builder.add_parameter("k_off", 0.1)
    builder.add_parameter("A0", 100)
    builder.add_parameter("B0", 200)
    builder.add_molecule_type("A(b)")
    builder.add_molecule_type("B(a)")
    builder.add_seed_species("A(b)", "A0")
    builder.add_seed_species("B(a)", "B0")
    builder.add_observable("Molecules", "AB", "A(b!1).B(a!1)")
    builder.add_rule("A(b) + B(a) -> A(b!1).B(a!1)", "k_on")
    builder.add_rule("A(b!1).B(a!1) -> A(b) + B(a)", "k_off")

    model = builder.build()
    result = model.sensitivity_analysis(
        parameters=["k_on", "k_off"],
        observables=["AB"],
        t_end=50,
        n_steps=100,
        delta=0.01,
    )

    assert result.matrix[0, 0] > 0
    assert result.matrix[1, 0] < 0


def test_sensitivity_forwards_advanced_simulation_controls():
    builder = ModelBuilder("AdvancedSensitivity")
    builder.add_parameter("k", 0.1)
    builder.add_molecule_type("X()")
    builder.add_seed_species("X()", 100)
    builder.add_observable("Molecules", "Xtot", "X()")
    builder.add_rule("X() -> 0", "k")
    model = builder.build()

    result = model.sensitivity_analysis(
        parameters=["k"],
        observables=["Xtot"],
        method="ode",
        t_end=1.0,
        n_steps=0,
        sample_times=[0.0, 0.25, 1.0],
        max_step=0.1,
        stop_if="Xtot < 0",
        sparse=False,
        check_product_scale=1000.0,
    )

    assert result.baseline.time.tolist() == [0.0, 0.25, 1.0]


def test_sensitivity_rejects_invalid_inputs():
    builder = ModelBuilder("InvalidSensitivity")
    builder.add_parameter("k", 0.1)
    builder.add_molecule_type("X()")
    builder.add_seed_species("X()", 100)
    builder.add_observable("Molecules", "Xtot", "X()")
    builder.add_rule("X() -> 0", "k")
    model = builder.build()

    with pytest.raises(ValueError, match="Unknown parameter"):
        model.sensitivity_analysis(parameters=["missing"])
    with pytest.raises(ValueError, match="delta"):
        model.sensitivity_analysis(delta=0.0)
