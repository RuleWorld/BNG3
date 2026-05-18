import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

from bionetgen.builder import ModelBuilder


def test_builder_to_bngl_and_simulation():
    builder = ModelBuilder("MyModel")
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

    bngl_text = builder.to_bngl()
    assert "begin model" in bngl_text
    assert "begin reaction rules" in bngl_text

    model = builder.build()
    result = model.simulate(method="ode", t_end=50, n_steps=100)
    assert result.observables["AB"][-1] > result.observables["AB"][0]
