import pytest

from tests.validation import runner


def test_ssa_rejects_explicitly_time_dependent_functional_rates(api, tmp_path):
    source = tmp_path / "time_dependent_ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 0
end seed species
begin reaction rules
    A() -> B() time+1
end reaction rules
end model
""",
        encoding="utf-8",
    )

    model = api.load(str(source))

    with pytest.raises(RuntimeError, match="time-dependent rate laws"):
        model.simulate(method="ssa", t_end=1, n_steps=2, seed=1)


def test_ssa_treats_uppercase_T_as_a_case_sensitive_parameter(api, tmp_path):
    source = tmp_path / "uppercase_parameter_ssa.bngl"
    source.write_text(
        """begin model
begin parameters
    T 2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 0
end seed species
begin observables
    Molecules Acount A()
    Molecules Bcount B()
end observables
begin functions
    f() = T + Acount
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
        encoding="utf-8",
    )

    model = api.load(str(source))
    trajectory = runner._result_to_trajectory(
        model.simulate(method="ssa", t_end=1, n_steps=2, seed=1)
    )

    assert trajectory.data[-1, trajectory.columns.index("Bcount")] > 0


def test_ssa_refreshes_state_functional_rate_after_reaction(api, tmp_path):
    source = tmp_path / "state_functional_ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 2
    B() 0
end seed species
begin observables
    Molecules Acount A()
    Molecules Bcount B()
end observables
begin functions
    f() = if(Acount == 2, 1000, 0)
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
        encoding="utf-8",
    )

    model = api.load(str(source))
    trajectory = runner._result_to_trajectory(
        model.simulate(method="ssa", t_end=1, n_steps=1, seed=1)
    )

    assert trajectory.data[-1, trajectory.columns.index("Acount")] == 1
    assert trajectory.data[-1, trajectory.columns.index("Bcount")] == 1


def test_ssa_allows_explicit_counter_tfun_rate(api, tmp_path):
    source = tmp_path / "explicit_tfun_ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 0
end seed species
begin functions
    f() = tfun([0, 1, 2], [2, 4, 6], 1)
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
        encoding="utf-8",
    )

    model = api.load(str(source))

    model.simulate(method="ssa", t_end=1, n_steps=2, seed=1)


def test_ssa_rejects_nonfinite_functional_coefficients(api, tmp_path):
    source = tmp_path / "invalid_functional_ssa.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 1
    B() 0
end seed species
begin functions
    f() = ln(-1)
end functions
begin reaction rules
    A() -> B() f()
end reaction rules
end model
""",
        encoding="utf-8",
    )

    model = api.load(str(source))

    with pytest.raises(RuntimeError, match="non-finite functional rate coefficient"):
        model.simulate(method="ssa", t_end=1, n_steps=2, seed=1)
