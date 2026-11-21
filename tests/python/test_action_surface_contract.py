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


def test_generated_hybrid_model_runs_through_public_nfcore(tmp_path, monkeypatch):
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    _model(tmp_path, "generate_hybrid_model({overwrite=>1, execute=>0})").execute()
    hybrid = bionetgen.load(tmp_path / "model_hpp.bngl")
    result = hybrid.simulate(method="nfcore", t_end=0.2, n_steps=4, seed=7)

    assert result.backend == "nfsim"
    assert result.observables["A_total"][-1] > 0
    assert (result.observables["A_total"] + result.observables["B_total"] == 20).all()


@pytest.mark.parametrize("method", ["nfcore", "nfnext"])
def test_hybrid_clock_initializes_at_requested_start(tmp_path, method):
    _model(tmp_path, "generate_hybrid_model({overwrite=>1, execute=>0})").execute()
    hybrid = bionetgen.load(tmp_path / "model_hpp.bngl")
    result = hybrid.simulate(method=method, t_start=2, t_end=2.1, n_steps=1, seed=42)
    assert result.time.tolist() == [2.0, 2.1]
    assert result.observables["A_total"][0] == 0
    assert result.observables["B_total"][0] == 20
    assert (result.observables["A_total"] + result.observables["B_total"] == 20).all()


def test_population_map_total_rate_survives_generation_and_execution(tmp_path):
    source = tmp_path / "total_rate.bngl"
    source.write_text(
        MODEL.replace(
            "begin seed species",
            "begin population types\n  A_pop()\nend population types\nbegin seed species",
        )
        .replace("  B() N", "  A() N")
        .replace("  Molecules B_total B()", "  Molecules Population A_pop()")
        .replace("A() -> A_pop() k_map", "A() -> A_pop() 1 TotalRate")
        + "\nbegin actions\ngenerate_hybrid_model({overwrite=>1, execute=>0})\nend actions\n"
    )
    model = bionetgen.load(source)
    model.execute()
    generated = (tmp_path / "total_rate_hpp.bngl").read_text()
    assert "A() -> A_pop() 1 TotalRate" in generated

    from bionetgen.bngir import from_bngir, to_bngir

    round_trip = from_bngir(to_bngir(model, version="0.2"))
    assert round_trip._model.population_maps[0].total_rate

    # Each jump consumes one particle at absolute rate 1 while any remain.
    # The 20-copy cutoff has negligible effect on the mean at T=1.
    converted = []
    for seed in range(100, 228):
        result = model.simulate(method="nfnext", t_end=1, n_steps=1, seed=seed)
        assert (
            result.observables["A_total"] + result.observables["Population"] == 20
        ).all()
        converted.append(result.observables["Population"][-1])
    assert sum(converted) / len(converted) == pytest.approx(1, abs=0.5)


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


@pytest.mark.parametrize("method", ["nfcore", "nfnext"])
def test_hybrid_continuation_uses_final_state_and_updated_rate(tmp_path, method):
    _model(tmp_path, "generate_hybrid_model({overwrite=>1, execute=>0})").execute()
    path = tmp_path / "model_hpp.bngl"
    path.write_text(
        path.read_text().replace("B() -> A_pop() k_make", "B() -> A_pop() 2*k_make")
    )
    hybrid = bionetgen.load(path)
    before = hybrid.simulate(method=method, t_end=0.1, n_steps=1, seed=42)
    at_boundary = before.observables["B_total"][-1]
    assert 0 < at_boundary < 20

    hybrid.set_parameter("k_make", 0)
    after = hybrid.simulate(
        method=method, t_start=0.1, t_end=1, n_steps=2, continue_simulation=True
    )
    assert after.time.tolist() == [0.1, 0.55, 1.0]
    assert after.observables["B_total"].tolist() == [at_boundary] * 3
    assert after.observables["A_total"].tolist() == [20 - at_boundary] * 3

    fresh = hybrid.simulate(method=method, t_start=1, t_end=2, n_steps=1)
    assert fresh.observables["B_total"].tolist() == [20, 20]


def test_hybrid_nf_actions_continue_from_final_state(tmp_path):
    _model(tmp_path, "generate_hybrid_model({overwrite=>1, execute=>0})").execute()
    path = tmp_path / "model_hpp.bngl"
    path.write_text(
        path.read_text().split("## model actions ##")[0]
        + """
begin actions
  simulate_nf({t_end=>0.1, n_steps=>1, seed=>42, suffix=>"before"})
  setParameter("k_make",0)
  simulate_nf({t_end=>1, n_steps=>2, suffix=>"after"})
end actions
"""
    )
    bionetgen.load(path).execute()
    before = (tmp_path / "model_hpp_before.gdat").read_text().splitlines()
    after = (tmp_path / "model_hpp_after.gdat").read_text().splitlines()
    boundary = [float(cell) for cell in before[-1].split()]
    assert 0 < boundary[2] < 20
    assert [float(cell) for cell in after[1].split()] == pytest.approx(boundary)
    assert [float(cell) for cell in after[-1].split()] == pytest.approx(
        [1.0, *boundary[1:]]
    )
