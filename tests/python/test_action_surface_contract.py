"""The action surface must refuse the options it cannot honour.

The public API rejects a tolerance that is not finite and positive, and an
output window that runs backwards.  The action surface used to accept both
silently, so the same model behaved differently depending on which surface
asked for it.

``generate_hybrid_model(execute=>1)`` runs the requested actions on the
*generated hybrid model*, as BNG2 does.  It used to run the ODE on the
original model instead, which is a different model: the hybrid model states
its populations as molecule types with population mapping rules, and BNG3 has
no population execution semantics, so running the original model silently
changed the model's meaning.  A requested simulation action on the hybrid
model is refused instead.
"""

import pytest

import bionetgen
from _extdep import require_extension

require_extension()


MODEL = """begin model
begin parameters
  k 1
  N 100
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() N
end seed species
begin reaction rules
  A() -> B() k
end reaction rules
begin population maps
  A() -> A_pop() k
end population maps
end model
"""


def _model(tmp_path, actions, name="model.bngl"):
    source = tmp_path / name
    source.write_text(MODEL + "\nbegin actions\n" + actions + "\nend actions\n")
    return bionetgen.load(source)


def test_action_surface_refuses_a_non_positive_absolute_tolerance(tmp_path):
    model = _model(
        tmp_path, 'simulate({method=>"ode", t_end=>1, n_steps=>10, atol=>0})'
    )
    with pytest.raises(RuntimeError, match="atol must be finite and positive"):
        model.execute()


def test_action_surface_refuses_a_non_positive_relative_tolerance(tmp_path):
    model = _model(
        tmp_path, 'simulate({method=>"ode", t_end=>1, n_steps=>10, rtol=>-1})'
    )
    with pytest.raises(RuntimeError, match="rtol must be finite and positive"):
        model.execute()


def test_action_surface_refuses_an_output_window_that_runs_backwards(tmp_path):
    model = _model(
        tmp_path, 'simulate({method=>"ode", t_start=>5, t_end=>1, n_steps=>10})'
    )
    with pytest.raises(
        RuntimeError, match="t_end must be greater than or equal to t_start"
    ):
        model.execute()


def test_hybrid_model_generation_refuses_to_simulate_the_population_model(tmp_path):
    model = _model(
        tmp_path,
        "generate_hybrid_model({overwrite=>1, execute=>1, "
        "actions=>['simulate({method=>\"ode\", t_end=>1, n_steps=>10})']})",
    )
    with pytest.raises(
        RuntimeError, match="hybrid population execution refinement is not supported"
    ):
        model.execute()


def test_hybrid_model_generation_does_not_run_the_original_model(tmp_path):
    model = _model(
        tmp_path,
        'generate_hybrid_model({overwrite=>1, execute=>1, actions=>["writeXML()"]})',
    )
    model.execute()
    # The hybrid model was generated and the requested action ran against it.
    assert (tmp_path / "model_hpp.bngl").is_file()
    # The original model was not simulated: no simulation output was written
    # for it.
    assert not (tmp_path / "model_hpp.cdat").exists()
    assert not (tmp_path / "model_hpp.gdat").exists()
