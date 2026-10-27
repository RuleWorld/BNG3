"""Compiled execution coverage for molecule-count observable comparisons."""

from __future__ import annotations

from pathlib import Path

from tests.validation import runner


def test_species_observable_molecule_count_comparators_execute(bng_cpp, tmp_path):
    source = tmp_path / "species_count_observables.bngl"
    source.write_text(
        """begin model
begin molecule types
  R(l,l)
end molecule types
begin observables
  Species R2 R()==2
  Species R3 R()==3
  Species R4 R()==4
  Species Rgt4 R()>4
end observables
begin seed species
  R(l,l) 10
  R(l!1,l).R(l!1,l) 2
  R(l!1,l).R(l!1,l!2).R(l!2,l) 3
  R(l!1,l).R(l!1,l!2).R(l!2,l!3).R(l!3,l!4).R(l!4,l) 5
end seed species
begin reaction rules
  dissoc: R(l!1,l).R(l!1,l) -> R(l,l) + R(l,l) 0.01
end reaction rules
end model

simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>1})
""",
        encoding="utf-8",
    )

    run_dir = tmp_path / "run"
    net, _, error = runner.run_cli_path(bng_cpp, source, run_dir)
    assert net is not None, f"compiled observable simulation failed: {error}"

    gdat = run_dir / "species_count_observables.gdat"
    assert gdat.is_file(), "simulation produced no observable time course"
    rows = [line.split() for line in gdat.read_text(encoding="utf-8").splitlines()]
    assert rows[0][2:] == ["R2", "R3", "R4", "Rgt4"]
    assert [float(value) for value in rows[1][1:]] == [2.0, 3.0, 0.0, 5.0]
