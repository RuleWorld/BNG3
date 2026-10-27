"""Source-law checks for composite legacy TFUN rates."""

from pathlib import Path
import shutil

import numpy as np
import pytest

from scripts.cross_validate import _stage_model
from tests.validation import compare, corpus, runner
from tests.validation.strict import require_oracle


def test_composite_tfun_factors_survive_network_generation(bng_cpp, tmp_path):
    source = corpus.resolve("test_tfun")
    require_oracle(source is not None, "test_tfun source model is unavailable")
    source_root = next(
        (root for root in corpus.MODEL_DIRS if source.is_relative_to(root)),
        source.parent,
    )
    staged = _stage_model(source, source_root, tmp_path / "input")

    net_path, _, error = runner.run_cli_path(bng_cpp, staged, tmp_path / "generated")
    assert net_path is not None, error

    network = compare.parse_net(net_path)
    assert network is not None

    # These are source-level divisions around TFUN, not part of its index.
    # BNG2's legacy TFUN serializer drops such wrappers, so this checks
    # BNG3's generated network against the authored source law directly.
    assert network.rate_defs["k1"] == "tfun('DAT_validate/test.dat', mctr)"
    assert network.rate_defs["k2"] == "(tfun('DAT_validate/test.dat', mctr) / 10)"
    assert network.rate_defs["k3"] == "(tfun('DAT_validate/test.dat', mctr) / k_t)"
    assert network.rate_defs["k4"] == "(tfun('DAT_validate/test.dat', mctr) / mctr)"

    reaction_function_by_reactant = {
        network.species_by_index[reactants[0]]: rate
        for reactants, _products, rate in network._raw
        if reactants
    }
    assert reaction_function_by_reactant == {
        "A()": "k1",
        "B()": "k2",
        "C()": "k3",
        "D()": "k4",
    }


def test_composite_tfun_rate_survives_net_reload_simulation(bng_cpp, tmp_path):
    source = tmp_path / "source.bngl"
    source.write_text(
        """begin model
begin parameters
end parameters
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
    f() = TFUN(time, "rates.dat")/10
end functions
begin reaction rules
    0 -> X() f()
end reaction rules
end model
begin actions
generate_network({overwrite=>1})
simulate_ode({prefix=>"source",t_start=>0,t_end=>1,n_steps=>10,print_CDAT=>1})
end actions
""",
        encoding="utf-8",
    )
    table = tmp_path / "rates.dat"
    table.write_text("0 20\n1 20\n", encoding="utf-8")

    source_run = tmp_path / "source-run"
    source_run.mkdir()
    shutil.copy2(table, source_run / table.name)
    source_net, _, source_error = runner.run_cli_path(bng_cpp, source, source_run)
    assert source_net is not None, source_error
    source_trajectory = np.loadtxt(source_run / "source.gdat", comments="#")

    network = compare.parse_net(source_net)
    assert network is not None
    assert network.rate_defs["f"] == "(tfun('rates.dat', time) / 10)"

    reload_run = tmp_path / "reload-run"
    reload_run.mkdir()
    shutil.copy2(source_net, reload_run / "input.net")
    shutil.copy2(table, reload_run / table.name)
    reload_source = reload_run / "reload.bngl"
    reload_source.write_text(
        'readFile({file=>"input.net"})\n'
        'simulate_ode({prefix=>"reload",netfile=>"input.net",'
        "t_start=>0,t_end=>1,n_steps=>10,print_CDAT=>1})\n",
        encoding="utf-8",
    )
    _, _, reload_error = runner.run_cli_path(bng_cpp, reload_source, reload_run)
    assert not reload_error, reload_error
    reload_trajectory = np.loadtxt(reload_run / "reload.gdat", comments="#")

    np.testing.assert_allclose(
        reload_trajectory, source_trajectory, rtol=1e-12, atol=1e-12
    )
    assert reload_trajectory[-1, 1] == pytest.approx(2.0, rel=1e-9, abs=1e-9)
