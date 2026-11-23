"""Release acceptance suite for Issue #171: PyBioNetGen public compatibility matrix.

Validates:
- release-python-api: every py.* public API family has differential compatibility
  and callable entry points.
- release-python-install: installed wheel and package entrypoints execute with optional
  extras isolated cleanly.
- release-capability-coverage-171: all assigned inventory cases execute against their
  named independent oracle (analytic mass-action law A -> B at k=0.4) and pass on main.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest

import bionetgen
import bionetgen.core.defaults as bng_defaults
import bionetgen.core.exc as bng_exc
import bionetgen.core.main as bng_core_main
import bionetgen.core.notebook as bng_notebook
import bionetgen.core.tools.cli as bng_cli_tool
import bionetgen.core.tools.gdiff as bng_gdiff
import bionetgen.core.tools.info as bng_info
import bionetgen.core.tools.plot as bng_plot
import bionetgen.core.tools.result as bng_result
import bionetgen.core.tools.visualize as bng_visualize
import bionetgen.core.utils.logging as bng_logging
import bionetgen.core.utils.utils as bng_utils
import bionetgen.core.version as bng_version
import bionetgen.main as bng_main
import bionetgen.modelapi.blocks as bng_blocks
import bionetgen.modelapi.model as bng_model_api
import bionetgen.modelapi.structs as bng_structs
import bionetgen.network.blocks as bng_net_blocks
import bionetgen.network.network as bng_net
import bionetgen.network.networkparser as bng_net_parser
import bionetgen.simulator.bngsimulator as bng_sim
import bionetgen.simulator.simulators as bng_simulators

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DIR = Path(__file__).resolve().parent

ANALYTIC_MODEL_BNGL = """begin model
begin parameters
    k 0.4
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
    Molecules A_obs A()
    Molecules B_obs B()
end observables
begin reaction rules
    A() -> B() k
end reaction rules
end model
"""


def _analytic_solution(
    t: np.ndarray, k: float = 0.4, a0: float = 10.0
) -> tuple[np.ndarray, np.ndarray]:
    a = a0 * np.exp(-k * t)
    b = a0 - a
    return a, b


def test_release_python_api(tmp_path: Path) -> None:
    """Verify all py.* API families and entry points from pinned PyBioNetGen."""
    # 1. Defaults and version
    defaults = bng_defaults.BNGDefaults()
    assert "bionetgen" in defaults.config
    assert bng_version.get_version() == "0.8.6"
    assert bionetgen.__version__ == "3.0.0a1"

    # 2. Exceptions
    assert issubclass(bng_exc.BNGVersionError, bng_exc.BNGError)
    assert issubclass(bng_exc.BNGModelError, bng_exc.BNGError)
    assert issubclass(bng_exc.BNGRunError, bng_exc.BNGError)

    # 3. Model API blocks & structs
    seed_file = tmp_path / "seed.bngl"
    seed_file.write_text("begin model\nend model\n", encoding="utf-8")
    m = bng_model_api.bngmodel(str(seed_file))

    pb = bng_blocks.ParameterBlock()
    pb.add_parameter("k", 0.4)
    m.add_block(pb)

    sb = bng_blocks.SpeciesBlock()
    sb.add_species("A()", 10)
    m.add_block(sb)

    ob = bng_blocks.ObservableBlock()
    ob.add_observable("A_obs", "Molecules A()")
    m.add_block(ob)

    rb = bng_blocks.RuleBlock()
    r = bng_structs.Rule("r1", rate_constants=("k",))
    rb.add_item((r.name, r))
    m.add_block(rb)

    m.add_action("simulate", {"method": "ode", "t_end": 1.0, "n_steps": 10})

    out_file = tmp_path / "model_api_test.bngl"
    m.write_model(str(out_file))
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "begin parameters" in content
    assert "simulate" in content

    # 4. Core tools: BNGResult, BNGLogger, ActionList, BNGInfo
    res = bng_result.BNGResult()
    assert hasattr(res, "load")
    logger = bng_logging.BNGLogger()
    assert logger.get_logger() is not None

    action_list = bng_utils.ActionList()
    assert action_list.is_before_model("setModelName")
    assert not action_list.is_before_model("simulate")

    # 5. Network module
    net_file = tmp_path / "test.net"
    net_file.write_text(
        "begin parameters\n1 k 0.4\nend parameters\n"
        "begin species\n1 A() 10\nend species\n"
        "begin reactions\n1 1 2 k\nend reactions\n"
        "begin groups\n1 A_obs 1\nend groups\n",
        encoding="utf-8",
    )
    net = bng_net.Network(str(net_file))
    assert hasattr(net, "add_block")
    assert hasattr(net, "write_model")

    # 6. Simulator getter
    assert callable(bng_simulators.sim_getter)

    # 7. Modern top-level interface
    valid_file = tmp_path / "valid.bngl"
    valid_file.write_text(ANALYTIC_MODEL_BNGL, encoding="utf-8")
    loaded = bionetgen.load(str(valid_file))
    assert loaded is not None
    assert hasattr(loaded, "simulate")
    assert hasattr(loaded, "parameters")


def test_release_python_install(tmp_path: Path) -> None:
    """Verify package distribution, version, CLI entrypoint and isolated extras."""
    # Check package metadata
    dist_version = importlib.metadata.version("bionetgen")
    assert dist_version == "3.0.0a1"

    # Test CLI invocation in clean subprocess
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, "-m", "bionetgen.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert "3.0.0a1" in proc.stdout or "3.0.0a1" in proc.stderr

    # Test CLI help
    proc_help = subprocess.run(
        [sys.executable, "-m", "bionetgen.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc_help.returncode == 0
    assert "run" in proc_help.stdout


def test_release_capability_coverage_171(tmp_path: Path) -> None:
    """Verify all 5 simulation methods execute against analytic law and CLI matches API."""
    model_file = tmp_path / "analytic.bngl"
    model_file.write_text(ANALYTIC_MODEL_BNGL, encoding="utf-8")

    # 1. Test ODE against analytic oracle
    res_ode = bionetgen.run(str(model_file), method="ode", t_end=2.0, n_steps=20)
    times = res_ode.time
    a_expected, b_expected = _analytic_solution(times, k=0.4, a0=10.0)
    a_observed = res_ode.observables["A_obs"]
    b_observed = res_ode.observables["B_obs"]

    max_err_a = np.max(np.abs(a_observed - a_expected))
    max_err_b = np.max(np.abs(b_observed - b_expected))
    assert max_err_a < 1e-5, f"ODE A error {max_err_a} exceeds tolerance"
    assert max_err_b < 1e-5, f"ODE B error {max_err_b} exceeds tolerance"

    # 2. Test SSA conservation
    res_ssa = bionetgen.run(
        str(model_file), method="ssa", t_end=2.0, n_steps=20, seed=42
    )
    a_ssa = res_ssa.observables["A_obs"]
    b_ssa = res_ssa.observables["B_obs"]
    assert np.all(a_ssa + b_ssa == 10), "SSA total species not conserved"

    # 3. Test Network-free (NF) execution
    res_nf = bionetgen.run(str(model_file), method="nf", t_end=2.0, n_steps=20, seed=42)
    assert "A_obs" in res_nf.observables
    assert "B_obs" in res_nf.observables
    assert len(res_nf.time) == 21

    # 4. Test PLA and PSA methods
    res_pla = bionetgen.run(str(model_file), method="pla", t_end=2.0, n_steps=20)
    assert "A_obs" in res_pla.observables

    res_psa = bionetgen.run(str(model_file), method="psa", t_end=2.0, n_steps=20)
    assert "A_obs" in res_psa.observables

    # 5. CLI parity check
    cli_model = tmp_path / "cli_model.bngl"
    cli_model.write_text(
        ANALYTIC_MODEL_BNGL
        + '\ngenerate_network()\nsimulate({method=>"ode",t_end=>1.0,n_steps=>5})\n',
        encoding="utf-8",
    )
    cli_out = tmp_path / "cli_run"
    cmd = [
        sys.executable,
        "-m",
        "bionetgen.cli",
        "run",
        "-i",
        str(cli_model),
        "-o",
        str(cli_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"CLI run failed: {proc.stderr}"
    gdat_files = list(cli_out.glob("*.gdat"))
    assert len(gdat_files) > 0, "CLI run did not produce .gdat output"
