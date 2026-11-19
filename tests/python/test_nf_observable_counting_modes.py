"""Compare Species and Molecules counts for an explicitly bonded dimer."""

import bionetgen


def test_bonded_dimer_initial_counts(tmp_path):
    bngl_obs = """
    begin model
    begin parameters
        k 1.0
    end parameters
    begin molecule types
        D(a,b)
    end molecule types
    begin seed species
        D(a!1,b).D(a!1,b) 50
    end seed species
    begin observables
        Molecules D_mol D()
        Species D_spec D()
    end observables
    begin reaction rules
        D(a,b) -> 0 k
    end reaction rules
    end model
    """
    path = tmp_path / "dimer.bngl"
    path.write_text(bngl_obs)
    m_obs = bionetgen.load(str(path))
    obs_dict = {obs.name: obs for obs in m_obs.observables}
    assert "D_mol" in obs_dict
    assert "D_spec" in obs_dict
    assert obs_dict["D_mol"].type == "Molecules"
    assert obs_dict["D_spec"].type == "Species"
    result = m_obs.simulate(method="nf", t_end=0.1, n_steps=1, seed=42)
    assert result.observables["D_mol"][0] == 100
    assert result.observables["D_spec"][0] == 50
