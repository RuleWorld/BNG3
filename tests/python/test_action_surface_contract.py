"""The action surface must refuse the options it cannot honour.

The public API rejects a tolerance that is not finite and positive, and an
output window that runs backwards.  The action surface used to accept both
silently, so the same model behaved differently depending on which surface
asked for it.

``generate_hybrid_model(execute=>1)`` runs the requested actions on the
*generated hybrid model*, as BNG2 does.  Hybrid NFsim must execute that
generated population/particle model through NFcore's population-aware event
loop; finite-network ODE and SSA actions remain unsupported for this model.
"""

import pytest

import bionetgen
from _extdep import require_extension

require_extension()


MODEL = """begin model
begin parameters
  k_make 10
  k_map 10
  N 20
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  B() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  B() -> A() k_make
end reaction rules
begin population maps
  A() -> A_pop() k_map
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


@pytest.mark.parametrize(
    "simulation_action",
    [
        "simulate_nf({t_end=>0.1, n_steps=>4, seed=>1})",
        "simulate({method=>'nf', t_end=>0.1, n_steps=>4, seed=>1})",
    ],
)
def test_hybrid_model_generation_executes_population_trajectory_with_nfsim(
    tmp_path, simulation_action
):
    model = _model(
        tmp_path,
        f"generate_hybrid_model({{overwrite=>1, execute=>1, "
        f'actions=>["{simulation_action}"]}})',
    )
    model.execute()
    output = tmp_path / "model_hpp.gdat"
    assert output.is_file()
    lines = [
        line
        for line in output.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lines) > 1
    assert float(lines[-1].split()[0]) == pytest.approx(0.1)
    columns = output.read_text().splitlines()[0].lstrip("#").split()
    rows = [[float(value) for value in line.split()] for line in lines]
    a_total = columns.index("A_total")
    b_total = columns.index("B_total")
    assert all(row[a_total] + row[b_total] == pytest.approx(20) for row in rows)
    species = (tmp_path / "model_hpp.species").read_text()
    population_rows = [
        line.split() for line in species.splitlines() if line.startswith("A_pop()")
    ]
    assert population_rows
    assert int(population_rows[0][1]) > 0


def test_hybrid_model_generation_still_refuses_finite_network_simulation(tmp_path):
    model = _model(
        tmp_path,
        "generate_hybrid_model({overwrite=>1, execute=>1, "
        "actions=>['simulate({method=>\"ode\", t_end=>1, n_steps=>10})']})",
    )
    with pytest.raises(
        RuntimeError,
        match="hybrid population execution refinement is not supported",
    ):
        model.execute()


def test_hybrid_nfsim_particleizes_whole_complexes_and_preserves_multiplicity(tmp_path):
    source = tmp_path / "complex.bngl"
    source.write_text("""begin model
begin parameters
  k_off 10
  N 8
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x!1).A(x!1) N
end seed species
begin observables
  Molecules A_units A()
  Species Dimer_species A==2
end observables
begin reaction rules
  A(x!1).A(x!1) -> A(x) + A(x) k_off
end reaction rules
begin population maps
  A(x!1).A(x!1) -> Dimer_pop() k_off
end population maps
end model

begin actions
generate_hybrid_model({overwrite=>1, execute=>1, actions=>["simulate_nf({t_end=>0.2, n_steps=>4, seed=>7})"]})
end actions
""")
    bionetgen.load(source).execute()

    output = tmp_path / "complex_hpp.gdat"
    lines = [
        line
        for line in output.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    columns = output.read_text().splitlines()[0].lstrip("#").split()
    rows = [[float(value) for value in line.split()] for line in lines]
    a_units = columns.index("A_units")
    dimers = columns.index("Dimer_species")
    assert all(row[a_units] == pytest.approx(16) for row in rows)
    assert rows[-1][dimers] < rows[0][dimers]


def test_hybrid_generation_accepts_bng2_population_types_and_conversion_cycles(
    tmp_path,
):
    source = tmp_path / "population-cycle.bngl"
    source.write_text("""begin model
begin parameters
  k_forward 2
  k_reverse 1
  k_map 0.1
  N 20
end parameters
begin molecule types
  A()
  B()
end molecule types
begin population types
  A_pop()
end population types
begin seed species
  A() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  A() -> B() k_forward
  B() -> A() k_reverse
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
end model

begin actions
generate_hybrid_model({overwrite=>1, execute=>1, actions=>["simulate_nf({t_end=>1, n_steps=>10, seed=>23})"]})
end actions
""")

    bionetgen.load(source).execute()

    generated = (tmp_path / "population-cycle_hpp.bngl").read_text()
    assert "A_pop population" in generated
    assert "A_pop() -> B() k_forward" in generated
    assert "B() -> A_pop() k_reverse" in generated
    output = tmp_path / "population-cycle_hpp.gdat"
    assert output.is_file()
    columns = output.read_text().splitlines()[0].lstrip("#").split()
    rows = [
        [float(value) for value in line.split()]
        for line in output.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert len(rows) == 11
    a_total = columns.index("A_total")
    b_total = columns.index("B_total")
    assert all(row[a_total] + row[b_total] == pytest.approx(20) for row in rows)
    assert 0 < rows[-1][b_total] < 20


def test_population_type_name_cannot_duplicate_a_molecule_type(tmp_path):
    source = tmp_path / "duplicate-population-type.bngl"
    source.write_text("""begin model
begin molecule types
  A_pop()
end molecule types
begin population types
  A_pop()
end population types
end model
""")
    with pytest.raises(RuntimeError, match="Molecule type A_pop previously defined"):
        bionetgen.load(source)


def test_hybrid_nfsim_preserves_population_conversion_inside_compartment(tmp_path):
    source = tmp_path / "compartment.bngl"
    source.write_text("""begin model
begin parameters
  k_fast 100
  k_slow 0.1
  N 20
end parameters
begin compartments
  c1 3 1
  c2 3 1
  c3 3 1
end compartments
begin molecule types
  A()
  B1()
  B2()
end molecule types
begin seed species
  @c1:A() N
  @c2:A() N
end seed species
begin observables
  Molecules A_total A()
  Molecules c1_units @c1:A()
  Molecules c2_units @c2:A()
  Molecules B1_total B1()
  Molecules B2_total B2()
  Molecules all_units A(),B1(),B2()
end observables
begin reaction rules
  @c1:A() -> @c1:B1() k_fast
  @c2:A() -> @c2:B2() k_slow
end reaction rules
begin population maps
  c1: @c1:A() -> P() k_fast
  c2: @c2:A() -> P() k_slow
  c3: @c3:A() -> P() k_fast
end population maps
end model

begin actions
generate_hybrid_model({overwrite=>1, execute=>1, actions=>["simulate_nf({t_end=>0.1, n_steps=>4, seed=>2})"]})
end actions
""")
    bionetgen.load(source).execute()

    output = tmp_path / "compartment_hpp.gdat"
    lines = [
        line
        for line in output.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    columns = output.read_text().splitlines()[0].lstrip("#").split()
    rows = [[float(value) for value in line.split()] for line in lines]
    b1 = columns.index("B1_total")
    b2 = columns.index("B2_total")
    c1_units = columns.index("c1_units")
    c2_units = columns.index("c2_units")
    all_units = columns.index("all_units")
    assert rows[-1][b1] > rows[-1][b2]
    assert rows[-1][c1_units] < rows[-1][c2_units]
    assert all(row[all_units] == pytest.approx(40) for row in rows)
    hybrid = (tmp_path / "compartment_hpp.bngl").read_text()
    assert "@c1:P() N" in hybrid
    assert "@c2:P() N" in hybrid
    assert "@c3:P() 0" in hybrid
    assert "_MapRule0: @c1:A() -> @c1:P() k_fast" in hybrid
    assert "_MapRule1: @c2:A() -> @c2:P() k_slow" in hybrid
    assert "Molecules c1_units @c1:A(),@c1:P()" in hybrid
    assert "Molecules c2_units @c2:A(),@c2:P()" in hybrid


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


def test_hybrid_model_generation_preserves_protocol_execution(tmp_path):
    source = tmp_path / "protocol_hybrid.bngl"
    source.write_text("""begin model
begin parameters
  k_make 0.1
  k_map 10
  N 20
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  B() N
end seed species
begin observables
  Molecules A_total A()
  Molecules B_total B()
end observables
begin reaction rules
  B() -> A() k_make
end reaction rules
begin population maps
  A() -> A_pop() k_map
end population maps
begin protocol
  setParameter("k_make", 10)
  simulate_nf({prefix=>\"protocol_hpp\", t_end=>0.1, n_steps=>4, seed=>23})
end protocol
end model

begin actions
generate_hybrid_model({overwrite=>1, execute=>1, actions=>[\"simulate_protocol()\"]})
end actions
""")
    bionetgen.load(source).execute()

    output = tmp_path / "protocol_hpp.gdat"
    assert output.is_file()
    raw = output.read_text().splitlines()
    columns = raw[0].lstrip("#").split()
    rows = [line.split() for line in raw if line and not line.startswith("#")]
    assert float(rows[-1][0]) == pytest.approx(0.1)
    final = [float(value) for value in rows[-1]]
    assert final[columns.index("A_total")] + final[
        columns.index("B_total")
    ] == pytest.approx(20)
    assert final[columns.index("B_total")] < 15
    hybrid = (tmp_path / "protocol_hybrid_hpp.bngl").read_text()
    assert "begin protocol" in hybrid
    assert 'setParameter("k_make", 10)' in hybrid
    assert "simulate_nf({" in hybrid
    assert 'prefix=>"protocol_hpp"' in hybrid

    unsupported = tmp_path / "unsupported_protocol.bngl"
    unsupported.write_text(
        source.read_text().replace(
            'simulate_nf({prefix=>"protocol_hpp", t_end=>0.1, n_steps=>4, seed=>23})',
            'simulate({method=>"ode", t_end=>0.1, n_steps=>4})',
        )
    )
    with pytest.raises(
        RuntimeError,
        match="hybrid population execution refinement is not supported",
    ):
        bionetgen.load(unsupported).execute()


def test_simulation_without_continue_reinitializes_baseline_concentrations(tmp_path):
    source = tmp_path / "model_reset.bngl"
    source.write_text("""begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  S()
  P()
end molecule types
begin seed species
  S() 100
  P() 0
end seed species
begin observables
  Molecules S_obs S()
  Molecules P_obs P()
end observables
begin reaction rules
  S() -> P() k
end reaction rules
end model

begin actions
generate_network({overwrite=>1})
simulate_ode({prefix=>"phase1", t_end=>10, n_steps=>10})
simulate_ode({prefix=>"phase2", t_end=>10, n_steps=>10})
simulate_ode({prefix=>"phase3", t_end=>10, n_steps=>10, continue=>1})
end actions
""")
    bionetgen.load(source).execute()

    # Phase 1: starts at 100, ends depleted
    p1_lines = (tmp_path / "phase1.gdat").read_text().splitlines()
    p1_cols = p1_lines[0].lstrip("#").split()
    s_idx = p1_cols.index("S_obs")
    p1_first = [float(v) for v in p1_lines[1].split()]
    p1_last = [float(v) for v in p1_lines[-1].split()]
    assert p1_first[s_idx] == pytest.approx(100.0)
    assert p1_last[s_idx] < 50.0

    # Phase 2 (continue=0 / omitted): reinitializes to baseline (100)
    p2_lines = (tmp_path / "phase2.gdat").read_text().splitlines()
    p2_first = [float(v) for v in p2_lines[1].split()]
    p2_last = [float(v) for v in p2_lines[-1].split()]
    assert p2_first[s_idx] == pytest.approx(100.0)
    assert p2_last[s_idx] < 50.0

    # Phase 3 (continue=1, separate prefix): append mode writes without header,
    # starting from step 1 (t=11), continuing smoothly from phase 2 end state (t=10, S~36.79)
    p3_lines = [
        l for l in (tmp_path / "phase3.gdat").read_text().splitlines() if l.strip()
    ]
    p3_first = [float(v) for v in p3_lines[0].split()]
    assert float(p3_first[0]) == pytest.approx(11.0)
    assert p3_first[s_idx] < p2_last[s_idx]
    assert p3_first[s_idx] == pytest.approx(p2_last[s_idx] * 0.904837418, rel=1e-3)


def test_simulation_after_protocol_and_add_concentration_reinitializes_baseline(
    tmp_path,
):
    source = tmp_path / "model_proto.bngl"
    source.write_text("""begin model
begin parameters
  k 0.01
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 50
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin protocol
  setConcentration("A()", 100)
  simulate_ode({prefix=>"sim1", t_end=>5, n_steps=>5})
  addConcentration("A()", 50)
  simulate_ode({prefix=>"sim2", t_end=>5, n_steps=>5})
end protocol
end model

begin actions
generate_network({overwrite=>1})
simulate_protocol()
simulate_ode({prefix=>"sim3", t_end=>1, n_steps=>2})
end actions
""")
    bionetgen.load(source).execute()

    # sim1 starts at setConcentration baseline (100)
    s1_lines = (tmp_path / "sim1.gdat").read_text().splitlines()
    s1_first = [float(v) for v in s1_lines[1].split()]
    assert s1_first[1] == pytest.approx(100.0)

    # sim3 is a standalone non-continuation action after protocol:
    # must reinitialize to baseline concentration (100, established by setConcentration),
    # not mutated state from sim2 + addConcentration
    s3_lines = (tmp_path / "sim3.gdat").read_text().splitlines()
    s3_first = [float(v) for v in s3_lines[1].split()]
    assert s3_first[1] == pytest.approx(100.0)
