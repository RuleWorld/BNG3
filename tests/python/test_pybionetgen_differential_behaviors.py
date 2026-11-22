import os
import tempfile

import numpy as np
import pytest

import bionetgen

MODEL_WITH_ACTIONS = """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_tot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin actions
  generate_network({overwrite=>1})
  simulate({method=>"ode",t_end=>2,n_steps=>4})
end actions
end model
"""

MODEL_NO_ACTIONS = """
begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_tot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
"""


def _write_model(tmp_path, text, name="m.bngl"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_modelapi_runner_run_returns_bngresult_and_outputs(tmp_path):
    from bionetgen.modelapi.runner import run as mrun

    model = _write_model(tmp_path, MODEL_WITH_ACTIONS)
    out = tmp_path / "out"
    result = mrun(model, out=str(out))

    assert type(result).__name__ == "BNGResult"
    assert "m" in result.gdats
    assert (out / "m.gdat").is_file()
    g = result.gdats["m"]
    assert g.dtype.names[:2] == ("time", "A_tot")
    assert len(g) == 5
    assert np.allclose(g["time"], np.linspace(0.0, 2.0, 5))
    assert np.allclose(
        g["A_tot"], 10.0 * np.exp(-0.5 * g["time"]), rtol=1e-5, atol=1e-8
    )


@pytest.mark.parametrize("entry_point", ["public", "modelapi"])
def test_file_runner_normalizes_explicit_format_like_pybionetgen(tmp_path, entry_point):
    from bionetgen.modelapi.runner import run as mrun

    model = _write_model(tmp_path, MODEL_WITH_ACTIONS)
    run = bionetgen.run if entry_point == "public" else mrun
    result = run(model, out=str(tmp_path / "upper-format"), format=" BNGL ")

    assert type(result).__name__ == "BNGResult"
    assert "m" in result.gdats


def test_modelapi_runner_run_out_none_uses_temp_results(tmp_path, monkeypatch):
    from bionetgen.modelapi.runner import run as mrun

    monkeypatch.chdir(tmp_path)
    model = _write_model(tmp_path, MODEL_WITH_ACTIONS)
    result = mrun(model)

    assert type(result).__name__ == "BNGResult"
    assert "m" in result.gdats
    # temp-run contract: results returned without leaving persistent output dir in cwd
    assert [p.name for p in tmp_path.iterdir()] == ["m.bngl"]


def test_bngresult_loads_direct_gdat_file(tmp_path):
    from bionetgen.modelapi.runner import run as mrun
    from bionetgen.core.tools.result import BNGResult

    model = _write_model(tmp_path, MODEL_WITH_ACTIONS)
    out = tmp_path / "out"
    mrun(model, out=str(out))
    gdat = out / "m.gdat"
    result = BNGResult(str(gdat))

    assert "m" in result.gdats
    assert result.gdats["m"].dtype.names[:2] == ("time", "A_tot")


def test_network_api_loads_generated_net(tmp_path):
    from bionetgen.modelapi.runner import run as mrun
    from bionetgen.network.network import Network
    import bionetgen.network as network_pkg

    model = _write_model(tmp_path, MODEL_WITH_ACTIONS)
    out = tmp_path / "out"
    mrun(model, out=str(out))
    net_path = out / "m.net"

    net = Network(str(net_path))
    assert hasattr(net, "species")
    assert hasattr(net, "reactions")
    assert callable(getattr(net, "write_model", None))
    assert hasattr(network_pkg, "Network")
    assert hasattr(network_pkg, "BNGNetworkParser")


def test_core_tools_exports_pybionetgen_symbols():
    from bionetgen.core.tools import (
        BNGCLI,
        BNGGdiff,
        BNGInfo,
        BNGPlotter,
        BNGResult,
        BNGVisualize,
        BNGSIM_AVAILABLE,
        BNGSIM_HAS_NFSIM,
        BNGSIM_VERSION,
        detect_input_format,
        execute_bngsim_backend_payload,
        run_bngl_with_bngsim,
        run_bngl_with_bngsim_backend_hook,
        run_nfsim,
        run_with_bngsim,
    )

    assert BNGResult is not None
    assert BNGCLI is not None
    assert BNGPlotter is not None
    assert BNGInfo is not None
    assert BNGVisualize is not None
    assert BNGGdiff is not None
    assert isinstance(BNGSIM_AVAILABLE, bool)
    assert isinstance(BNGSIM_HAS_NFSIM, bool)
    assert callable(detect_input_format)
    assert callable(run_with_bngsim)
    assert callable(run_bngl_with_bngsim)
    assert callable(run_bngl_with_bngsim_backend_hook)
    assert callable(run_nfsim)
    assert callable(execute_bngsim_backend_payload)


def test_bngmodel_inline_load_edit_save_no_actions():
    from bionetgen import bngmodel

    model = bngmodel(MODEL_NO_ACTIONS, verbose=True)
    assert "k" in model.parameters
    assert getattr(model, "verbose", None) is True
    model.parameters.k = 2
    text = str(model)
    assert "2" in text
    assert "begin model" in text


def test_main_pybionetgen_helper_exports():
    import bionetgen.main as main

    assert callable(getattr(main, "get_conf", None))
    assert callable(getattr(main, "get_default_bng_path", None))
    assert callable(getattr(main, "get_default_app", None))
    conf = main.get_conf()
    assert hasattr(conf, "get")
    assert main.get_default_bng_path() == conf.get("bngpath")
    try:
        app = main.get_default_app()
    except ImportError as exc:
        # PyBioNetGen CLI helpers require cement; absence is an explicit optional dependency.
        assert "cement" in str(exc).lower()
    else:
        assert app is not None


def test_modelapi_protocol_block_api_and_parsing(tmp_path):
    from bionetgen.modelapi.blocks import ProtocolBlock
    from bionetgen.modelapi.model import bngmodel

    m = bngmodel(MODEL_NO_ACTIONS, verbose=True)
    m.add_protocol_block()
    assert isinstance(m.protocol, ProtocolBlock)
    m.protocol.add_action(
        "simulate", {"method": '"ode"', "t_end": "10", "n_steps": "10"}
    )
    s = str(m)
    assert "begin protocol" in s
    assert "simulate" in s

    text = """begin model
begin parameters
  k 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_tot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
begin protocol
  simulate({method=>"ode",t_end=>10,n_steps=>10})
end protocol
end model
"""
    path = tmp_path / "proto.bngl"
    path.write_text(text)
    m2 = bngmodel(str(path))
    assert isinstance(m2.protocol, ProtocolBlock)
    assert len(m2.protocol) == 1
    assert "simulate" in str(m2.protocol)
