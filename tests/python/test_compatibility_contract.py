"""Small, source-derived PyBioNetGen compatibility contracts."""

from __future__ import annotations

import importlib.util
import os
import json
import inspect
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import bionetgen

REPO = Path(__file__).resolve().parents[2]
MODEL = Path(__file__).with_name("test.bngl")
SUPPORTED_METHODS = ("ode", "ssa", "nf", "pla", "psa")


def _write_method_matrix_model(path: Path) -> Path:
    path.write_text("""begin model
begin parameters
    k 0.2
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_count A()
    Molecules B_count B()
end observables
begin reaction rules
    convert: A() -> B() k
end reaction rules
end model
""")
    return path


def test_legacy_public_symbols_are_available_from_package_root():
    assert callable(bionetgen.bngmodel)
    assert callable(bionetgen.run)
    assert callable(bionetgen.sim_getter)
    assert bionetgen.SympyOdes is not None
    assert callable(bionetgen.export_sympy_odes)
    assert bionetgen.BNGResult is not None


def test_public_sympy_ode_export_runs_from_package_root(tmp_path):
    if importlib.util.find_spec("sympy") is None:
        pytest.skip("SymPy is an optional integration")

    model_path = _write_method_matrix_model(tmp_path / "sympy-model.bngl")
    result = bionetgen.export_sympy_odes(
        model_path, out_dir=str(tmp_path / "mex"), mex_suffix="compat"
    )

    assert isinstance(result, bionetgen.SympyOdes)
    assert len(result.species) == 2
    assert len(result.params) == 1
    assert len(result.odes) == 2


@pytest.mark.parametrize("method", SUPPORTED_METHODS)
def test_installed_python_api_runs_each_supported_method(tmp_path, method):
    model_path = _write_method_matrix_model(tmp_path / f"{method}.bngl")

    result = bionetgen.run(
        str(model_path),
        method=method,
        t_end=0.5,
        n_steps=4,
        seed=7,
    )

    assert result.time.shape == (5,)
    assert np.allclose(result.time, np.linspace(0.0, 0.5, 5))
    assert set(result.observables) == {"A_count", "B_count"}
    assert all(values.shape == (5,) for values in result.observables.values())
    assert all(np.isfinite(values).all() for values in result.observables.values())


def test_package_root_defaults_to_modern_ode_grid(tmp_path):
    model_path = _write_method_matrix_model(tmp_path / "default-run.bngl")

    result = bionetgen.run(model_path)

    assert isinstance(result, bionetgen.SimResult)
    assert result.time.shape == (101,)
    assert result.time[0] == 0.0
    assert result.time[-1] == 100.0


def test_package_root_signature_exposes_both_dispatch_forms():
    parameters = inspect.signature(bionetgen.run).parameters

    assert tuple(parameters) == (
        "path",
        "args",
        "method",
        "t_end",
        "n_steps",
        "kwargs",
    )
    assert parameters["args"].kind is inspect.Parameter.VAR_POSITIONAL
    assert parameters["method"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD


def test_package_root_keeps_positional_modern_method_and_time_arguments(tmp_path):
    model_path = _write_method_matrix_model(tmp_path / "positional.bngl")

    result = bionetgen.run(str(model_path), "ssa", 0.5, 4)

    assert isinstance(result, bionetgen.SimResult)
    assert np.allclose(result.time, np.linspace(0.0, 0.5, 5))


def test_package_root_keeps_string_positional_legacy_output_directory(tmp_path):
    output = tmp_path / "legacy-string-output"

    result = bionetgen.run(MODEL, str(output))

    assert isinstance(result, bionetgen.BNGResult)
    assert {"test.net", "test.xml", "test.gdat", "test.cdat"}.issubset(
        {path.name for path in output.iterdir()}
    )


def test_legacy_run_accepts_output_directory_and_returns_file_result(tmp_path):
    output = tmp_path / "results"

    result = bionetgen.run(MODEL, output)

    assert isinstance(result, bionetgen.BNGResult)
    assert result.process_return == 0
    assert {"test.net", "test.xml", "test.gdat", "test.cdat"}.issubset(
        {path.name for path in output.iterdir()}
    )
    assert result.gdats["test"].dtype.names[0] == "time"
    assert np.isfinite(result.gdats["test"]["time"]).all()


def test_legacy_run_supports_method_and_time_overrides(tmp_path):
    output = tmp_path / "override-results"

    result = bionetgen.run(
        MODEL,
        out=output,
        method="ode",
        t_span=(2.0, 3.0),
        n_points=5,
    )

    assert isinstance(result, bionetgen.BNGResult)
    assert result.process_return == 0
    assert not (output / "test.xml").exists()
    assert not (output / "test.net").exists()
    assert (output / "test.gdat").is_file()
    data = result.gdats["test"]
    assert data.dtype.names[0] == "time"
    assert len(data) == 5
    assert np.allclose(data["time"], np.linspace(2.0, 3.0, 5))


def _write_action_workflow_model(path: Path, *, fail_after_simulation=False) -> Path:
    later_action = (
        'setConcentration("missing()",1)'
        if fail_after_simulation
        else "resetConcentrations()"
    )
    path.write_text(f"""begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules A_count A()
    Molecules B_count B()
end observables
begin reaction rules
    convert: A() -> B() k
end reaction rules
end model
writeXML()
generate_network()
simulate_ode({{t_end=>10,n_steps=>20,suffix=>"ode"}})
{later_action}
simulate_ssa({{t_end=>10,n_steps=>20,seed=>17,suffix=>"ssa"}})
""")
    return path


def _capture_parsed_actions(monkeypatch):
    parsed_models = []
    parse_file = bionetgen._bionetgen_cpp.parse_file

    def capture(path):
        parsed = parse_file(path)
        parsed_models.append(
            (
                parsed,
                [(action.name, dict(action.arguments)) for action in parsed.actions],
            )
        )
        return parsed

    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", capture)
    return parsed_models


def test_time_only_override_preserves_declared_simulation_actions(
    tmp_path, monkeypatch
):
    model = _write_action_workflow_model(tmp_path / "declared.bngl")
    parsed_models = _capture_parsed_actions(monkeypatch)
    output = tmp_path / "declared-results"

    result = bionetgen.run(model, out=output, t_span=(2.0, 3.0), n_points=5)

    assert isinstance(result, bionetgen.BNGResult)
    assert {
        "declared.xml",
        "declared.net",
        "declared_ode.gdat",
        "declared_ssa.gdat",
    }.issubset({path.name for path in output.iterdir()})
    for suffix in ("ode", "ssa"):
        data = result.gdats[f"declared_{suffix}"]
        assert np.allclose(data["time"], np.linspace(2.0, 3.0, 5))
    assert np.allclose(
        result.gdats["declared_ssa"]["A_count"],
        np.rint(result.gdats["declared_ssa"]["A_count"]),
    )
    parsed, original_actions = parsed_models[0]
    assert [(action.name, dict(action.arguments)) for action in parsed.actions] == (
        original_actions
    )


def test_time_only_override_restores_actions_when_execution_raises(
    tmp_path, monkeypatch
):
    model = _write_action_workflow_model(
        tmp_path / "failing.bngl", fail_after_simulation=True
    )
    parsed_models = _capture_parsed_actions(monkeypatch)
    output = tmp_path / "failing-results"

    with pytest.raises(bionetgen.BNGError, match="species not found"):
        bionetgen.run(model, out=output, t_span=(2.0, 3.0), n_points=5)

    parsed, original_actions = parsed_models[0]
    assert [(action.name, dict(action.arguments)) for action in parsed.actions] == (
        original_actions
    )


@pytest.mark.parametrize(
    "simulation_action",
    [
        "simulate_ode({t_end=>10,sample_times=>[1,2]})",
        "simulate_ode({t_end=>10,n_steps=>20,continue=>1})",
    ],
)
def test_time_only_override_rejects_unsupported_action_grids_before_output(
    tmp_path, simulation_action
):
    model = tmp_path / "unsupported-grid.bngl"
    _write_action_workflow_model(model)
    model.write_text(
        model.read_text().replace(
            'simulate_ode({t_end=>10,n_steps=>20,suffix=>"ode"})',
            simulation_action,
        )
    )
    output = tmp_path / "unsupported-grid-results"

    with pytest.raises(NotImplementedError, match="sample_times|continue"):
        bionetgen.run(model, out=output, t_span=(2.0, 3.0), n_points=5)

    assert not output.exists()


def test_time_only_override_requires_a_direct_simulation_action(tmp_path):
    model = tmp_path / "no-simulation.bngl"
    model.write_text("""begin model
end model
writeXML()
""")
    output = tmp_path / "no-simulation-results"

    with pytest.raises(NotImplementedError, match="direct simulation action"):
        bionetgen.run(model, out=output, t_start=1.0)

    assert not output.exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({99: {"t_end": "1"}}, "outside the model action list"),
        ({2: {"n_steps": "0"}}, "positive integer"),
        ({2: {"t_start": "3", "t_end": "2"}}, "greater than or equal"),
        ({2: {"unsupported": "1"}}, "unsupported action override key"),
    ],
)
def test_native_action_override_validation_precedes_execution(
    tmp_path, overrides, message
):
    cpp = bionetgen._bionetgen_cpp
    model = cpp.parse_file(str(MODEL))
    original = [(action.name, dict(action.arguments)) for action in model.actions]
    output = tmp_path / "native-validation-results"
    output.mkdir()
    output_model = output / "validation.bngl"
    output_model.write_text("begin model\nend model\n")

    with pytest.raises(ValueError, match=message):
        cpp.execute(model, str(output_model), action_overrides=overrides)

    assert [(action.name, dict(action.arguments)) for action in model.actions] == (
        original
    )
    assert {path.name for path in output.iterdir()} == {"validation.bngl"}


@pytest.mark.parametrize("method", ["simulate_pla", "simulate_psa"])
def test_time_start_override_is_applied_to_pla_and_psa_actions(tmp_path, method):
    model = _write_method_matrix_model(tmp_path / f"{method}.bngl")
    with model.open("a", encoding="utf-8") as handle:
        handle.write(f"generate_network()\n{method}({{t_end=>3,n_steps=>4}})\n")
    output = tmp_path / f"{method}-results"

    result = bionetgen.run(model, out=output, t_start=2.0)

    action_result = result.gdats[model.stem]
    assert np.allclose(action_result["time"], np.linspace(2.0, 3.0, 5))


def test_unknown_keyword_method_is_rejected_before_legacy_execution(
    tmp_path, monkeypatch
):
    output = tmp_path / "must-not-be-created"

    def unexpected_execution(*args, **kwargs):
        pytest.fail("unknown keyword method reached the legacy action runner")

    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", unexpected_execution)

    with pytest.raises((TypeError, ValueError), match="method|simulation"):
        bionetgen.run(MODEL, method="odde", out=output)

    assert not output.exists()


def test_package_root_rejects_duplicate_dispatch_arguments(tmp_path):
    model = _write_method_matrix_model(tmp_path / "duplicate.bngl")
    output = tmp_path / "duplicate-output"

    with pytest.raises(TypeError, match="method.*multiple|multiple.*method"):
        bionetgen.run(str(model), "ssa", method="ode")
    with pytest.raises(TypeError, match="t_end.*multiple|multiple.*t_end"):
        bionetgen.run(str(model), "ssa", 0.5, t_end=1.0)
    with pytest.raises(TypeError, match="out.*multiple|multiple.*out"):
        bionetgen.run(MODEL, output, out=output)


def test_default_package_import_does_not_load_optional_integrations(tmp_path):
    code = """
import importlib.abc
import sys

blocked = {'cement', 'colorlog', 'pandas', 'matplotlib', 'sympy', 'libsbml', 'roadrunner', 'nbclient', 'nbformat', 'ipykernel', 'seaborn', 'lxml', 'networkx'}
class BlockOptionalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'optional import attempted: {fullname}')

sys.meta_path.insert(0, BlockOptionalImports())
import bionetgen
assert bionetgen.load is not None
assert not (blocked & {name.split('.')[0] for name in sys.modules})
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_notebook_command_writes_a_valid_model_specific_notebook(tmp_path):
    input_model = _write_method_matrix_model(tmp_path / "notebook_model.bngl")
    output = tmp_path / "notebook_model.ipynb"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bionetgen.cli",
            "notebook",
            "--input",
            str(input_model),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    notebook = json.loads(output.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert input_model.resolve().as_posix() in code
    assert "model = bionetgen.load(" in code
    assert "result = model.simulate()" in code
    assert "result.plot()" in code
    assert "res = r[0]" not in code
    assert all(
        cell["outputs"] == [] and cell["execution_count"] is None
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def test_default_notebook_uses_bng3_compatible_file_results(tmp_path):
    output = tmp_path / "default.ipynb"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    generated = subprocess.run(
        [sys.executable, "-m", "bionetgen.cli", "notebook", "--output", str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert generated.returncode == 0, generated.stderr
    notebook = json.loads(output.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert 'r = bionetgen.run("simple_model.bngl", "test")' in code
    assert "r.gdats[key]" in code
    assert "r.results" not in code
    assert "plt.plot(res['time'], res[name], label=name)" in code
    assert "import seaborn" not in code
    assert all(
        cell["outputs"] == [] and cell["execution_count"] is None
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def test_generated_notebooks_execute_in_qualified_kernel(tmp_path, monkeypatch):
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    nbformat = pytest.importorskip("nbformat")

    kernel_name = "bng3-qualified"
    kernel_path = tmp_path / "jupyter" / "kernels" / kernel_name
    kernel_path.mkdir(parents=True)
    kernel_spec = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "BNG3 qualified test kernel",
        "language": "python",
    }
    (kernel_path / "kernel.json").write_text(json.dumps(kernel_spec), encoding="utf-8")
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path / "jupyter"))

    installed_package = Path(bionetgen.__file__).resolve()
    installed_extension = Path(bionetgen._bionetgen_cpp.__file__).resolve()
    cases = ("model-specific", "default")
    for case in cases:
        case_dir = tmp_path / case
        case_dir.mkdir()
        output = case_dir / "generated.ipynb"
        command = [
            sys.executable,
            "-m",
            "bionetgen.cli",
            "notebook",
            "--output",
            str(output),
        ]
        if case == "model-specific":
            input_model = _write_method_matrix_model(case_dir / "notebook_model.bngl")
            command.extend(["--input", str(input_model)])

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        generated = subprocess.run(
            command,
            cwd=case_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert generated.returncode == 0, generated.stderr

        notebook = nbformat.read(output, as_version=4)
        notebook.metadata["kernelspec"] = {
            "display_name": "BNG3 qualified test kernel",
            "language": "python",
            "name": kernel_name,
        }
        notebook.cells.append(
            nbformat.v4.new_code_cell(
                "import sys\n"
                "from pathlib import Path\n"
                "import bionetgen\n"
                "import bionetgen._bionetgen_cpp as cpp\n"
                f"assert Path(sys.executable).resolve() == Path({sys.executable!r}).resolve()\n"
                f"assert Path(bionetgen.__file__).resolve() == Path({str(installed_package)!r})\n"
                f"assert Path(cpp.__file__).resolve() == Path({str(installed_extension)!r})"
            )
        )
        executed = nbclient.NotebookClient(
            notebook,
            timeout=120,
            kernel_name=kernel_name,
            resources={"metadata": {"path": str(case_dir)}},
        ).execute()

        assert any(
            "image/png" in cell_output.data
            for cell in executed.cells
            for cell_output in cell.get("outputs", [])
            if cell_output.output_type == "display_data"
        ), case


@pytest.mark.parametrize("source", ["model_file", "model_str"])
def test_legacy_roadrunner_adapter_runs_analytic_sbml(tmp_path, source):
    if importlib.util.find_spec("roadrunner") is None:
        pytest.skip("libRoadRunner is an optional integration")

    sbml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="first_order_decay">
    <listOfCompartments>
      <compartment id="cell" size="1" />
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="cell" initialConcentration="10"
               boundaryCondition="false" hasOnlySubstanceUnits="false" />
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.2" />
    </listOfParameters>
    <listOfReactions>
      <reaction id="decay" reversible="false">
        <listOfReactants>
          <speciesReference species="A" stoichiometry="1" />
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    model_path = tmp_path / "first_order_decay.xml"
    model_path.write_text(sbml, encoding="utf-8")
    if source == "model_file":
        simulator = bionetgen.sim_getter(model_file=str(model_path), sim_type="libRR")
    else:
        simulator = bionetgen.sim_getter(model_str=sbml, sim_type="libRR")

    result = simulator.simulate(0.0, 1.0, 11)

    assert result.shape == (11, 2)
    assert tuple(result.colnames) == ("time", "[A]")
    assert np.allclose(result["time"], np.linspace(0.0, 1.0, 11))
    assert np.allclose(
        result["[A]"],
        10.0 * np.exp(-0.2 * np.asarray(result["time"])),
        rtol=1e-5,
        atol=1e-8,
    )


@pytest.mark.parametrize("source", ["model_file", "model_str"])
def test_legacy_roadrunner_adapter_reports_missing_optional_dependency(
    monkeypatch, source
):
    monkeypatch.setitem(sys.modules, "roadrunner", None)
    with pytest.raises(ImportError, match="install the optional roadrunner dependency"):
        if source == "model_file":
            bionetgen.sim_getter(model_file=str(MODEL), sim_type="libRR")
        else:
            bionetgen.sim_getter(model_str="<sbml/>", sim_type="libRR")


@pytest.mark.parametrize("backend", ["modern", "legacy"])
def test_sbml_backends_report_missing_optional_libsbml(tmp_path, backend):
    source = tmp_path / "model.xml"
    source.write_text("<sbml/>", encoding="utf-8")
    code = f"""
import importlib.abc
import bionetgen
import sys

class BlockLibSBML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'libsbml':
            raise ModuleNotFoundError("No module named 'libsbml'")

sys.meta_path.insert(0, BlockLibSBML())
try:
    bionetgen.from_sbml({str(source)!r}, atomizer_backend={backend!r})
except bionetgen.BioNetGenError as exc:
    assert 'libsbml' in str(exc).lower(), str(exc)
else:
    raise AssertionError('SBML import unexpectedly succeeded without libsbml')
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_compatibility_runner_rejects_simulator_backend_override(tmp_path):
    model_path = _write_method_matrix_model(tmp_path / "bngsim-selector.bngl")
    output = tmp_path / "bngsim-output"

    with pytest.raises(NotImplementedError, match="only simulator='auto' is supported"):
        bionetgen.run(model_path, out=output, simulator="bngsim")

    assert not output.exists()


@pytest.mark.parametrize("output_directory", [False, True])
@pytest.mark.parametrize("entry_point", ["compat", "public"])
@pytest.mark.parametrize(
    "override",
    [
        {},
        {"method": "ssa"},
        {"t_span": (0, 1)},
        {"n_points": 2},
        {"t_end": 1},
        {"n_steps": 1},
    ],
)
def test_compatibility_timeout_is_rejected_before_execution(
    tmp_path, monkeypatch, output_directory, entry_point, override
):
    from bionetgen.compat.runner import run as compatibility_run

    run = compatibility_run if entry_point == "compat" else bionetgen.run

    def unexpected_execution(*args, **kwargs):
        pytest.fail("unsupported timeout reached model execution")

    monkeypatch.setattr(bionetgen, "load", unexpected_execution)
    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", unexpected_execution)
    output = tmp_path / "results" if output_directory else None

    with pytest.raises(NotImplementedError, match="timeout"):
        run(MODEL, out=output, timeout=1, **override)

    if output is not None:
        assert not output.exists()


def test_module_entry_point_exposes_cli_help(tmp_path):
    env = os.environ.copy()
    package_path = Path(bionetgen.__file__).resolve()
    source_package = (REPO / "python" / "bionetgen").resolve()
    source_mode = package_path.is_relative_to(source_package)
    if source_mode:
        extension_dir = REPO / "build" / "cpp"
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(REPO / "python"),
                str(extension_dir),
                env.get("PYTHONPATH", ""),
            ]
        )
        code = (
            "import pathlib, runpy, sys, bionetgen; "
            "bionetgen.__path__.insert(0, "
            "str(pathlib.Path(sys.argv.pop(1)).resolve())); "
            "runpy.run_module('bionetgen', run_name='__main__', alter_sys=True)"
        )
        command = [sys.executable, "-c", code, str(extension_dir), "--help"]
        cwd = REPO
    else:
        # An installed-mode child must not inherit paths that could replace
        # the wheel being tested. Its working directory is outside the repo.
        env.pop("PYTHONPATH", None)
        command = [sys.executable, "-m", "bionetgen", "--help"]
        cwd = tmp_path
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert "BioNetGen" in result.stdout


def test_legacy_sim_getter_rejects_unknown_simulator_type():
    with pytest.raises(ValueError, match="not supported"):
        bionetgen.sim_getter(model_file=str(MODEL), sim_type="unknown")
