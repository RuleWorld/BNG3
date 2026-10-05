from scripts.regen_golden import ensemble_model_source


def test_ensemble_model_source_uses_clean_definition_and_fixed_seed_actions():
    original = """begin model
begin parameters
    k 1
end parameters
end model

## actions ##
simulate_ssa({t_end=>999,n_steps=>1})
"""

    generated = ensemble_model_source(
        original, seeds=range(1, 3), t_end=10, n_steps=50
    )

    assert generated.startswith("begin model\n")
    assert "k 1" in generated
    assert "t_end=>999" not in generated
    assert generated.count("resetConcentrations()") == 2
    assert 'suffix=>"seed_0001",seed=>1' in generated
    assert 'suffix=>"seed_0002",seed=>2' in generated
    assert generated.count("t_end=>10,n_steps=>50") == 2


def test_ensemble_model_source_supports_models_without_outer_end_model():
    original = """begin parameters
    k 1
end parameters
begin reaction rules
    A() -> B() k
end reaction rules
simulate_ode({t_end=>1})
"""

    generated = ensemble_model_source(
        original, seeds=range(1, 2), t_end=10, n_steps=50
    )

    assert "A() -> B() k" in generated
    assert "simulate_ode" not in generated
    assert 'suffix=>"seed_0001",seed=>1' in generated
