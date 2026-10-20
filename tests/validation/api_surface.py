"""Generated public API and CLI surface qualification for issue #171.

The family drives every supported simulation method through the installed
Python API and through the installed command-line interface, and judges each
route against an independent closed-form law.  Neither route is judged against
the other route's output alone: the deterministic route is compared with the
analytic trajectory of a first-order decay process, and the stochastic routes
are compared with the exact binomial count law of that process.

Every API/CLI difference is declared in :data:`INTENTIONAL_INCOMPATIBILITIES`
and exercised by the ``intentional-incompatibilities`` check, so an
unexplained divergence fails instead of being reported as a benign difference.

The stochastic statements are limited to the terminal-time marginal of the
first-order decay family: an ensemble mean, an ensemble dispersion and a
per-trajectory range, each against the exact binomial law, with a recorded
seed budget and an explicit error budget.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import campaign, integrated_marginals, reporting

ROOT = Path(__file__).resolve().parents[2]
ISSUES = (171,)

METHODS = ("ode", "ssa", "nf", "pla", "psa")
DETERMINISTIC_METHODS = ("ode",)
STOCHASTIC_METHODS = ("ssa", "nf", "pla", "psa")

SURFACE_CHECKS = (
    "signatures-defaults",
    "positional-dispatch",
    "timeouts",
    "actions",
    "results-files",
    "exceptions",
    "optional-imports",
    "intentional-incompatibilities",
)
METHOD_CHECKS = ("api-vs-law", "cli-vs-law", "route-agreement")

# The ensemble budget is part of the recorded evidence.
ENSEMBLE_RUNS = 24
ENSEMBLE_SEED_BASE = 20260101
ENSEMBLE_WORKERS = 8
# Family-wide error budget for the stochastic law statements.
ALPHA = 1e-3
# Declared tolerances for the deterministic comparison.
ODE_ATOL = 1e-9
ODE_RTOL = 1e-8
# The CLI's own default tolerances (rtol 1e-8) bound the default-grid
# comparison; the tolerance stays far below a semantic difference.
DEFAULT_ATOL = 1e-6
DEFAULT_RTOL = 1e-6
# The exact binomial law is evaluated at these tail probabilities.
LAW_TAIL = 1e-6
# The sample variance of the terminal count must stay inside this multiple of
# the exact binomial variance.
LAW_VARIANCE_BAND = (0.25, 4.0)
# The ensemble mean must stay inside this many analytic standard errors.
LAW_MEAN_SIGMAS = 5.0
# Optional third-party distributions that must stay optional.
OPTIONAL_DISTRIBUTIONS = ("sympy", "matplotlib", "networkx", "cement", "scipy")

# Declared API/CLI incompatibilities.  Each entry names the difference and the
# exact observation that proves it.  A difference that is not declared here
# fails the ``intentional-incompatibilities`` check.
INTENTIONAL_INCOMPATIBILITIES = (
    {
        "id": "result-container",
        "summary": (
            "The API returns a SimResult object; the CLI writes a result file "
            "and returns only a process exit status."
        ),
        "observation": {
            "api_result_type": "SimResult",
            "cli_result_type": "process-exit-status",
            "cli_written_files": ["result.tsv"],
        },
    },
    {
        "id": "table-columns",
        "summary": (
            "The CLI table carries only observable columns; the API result "
            "additionally exposes the per-species concentration matrix, which "
            "the network-free route does not provide at all."
        ),
        "observation": {
            "cli_columns": ["time", "Atot"],
            "api_concentration_columns": 1,
            "nf_concentration_columns": None,
        },
    },
    {
        "id": "method-dispatch",
        "summary": (
            "The API accepts the simulation method as the second positional "
            "argument; the CLI requires --method and rejects a positional "
            "method argument."
        ),
        "observation": {
            "api_positional_method": "accepted",
            "cli_positional_method": "rejected",
        },
    },
    {
        "id": "timeout",
        "summary": (
            "Neither entry point implements a timeout.  The API refuses an "
            "explicit timeout with a typed exception; the CLI has no timeout "
            "option and rejects it as an unknown option."
        ),
        "observation": {
            "api_legacy_timeout": "NotImplementedError",
            "api_modern_timeout": "TypeError",
            "cli_timeout": "unknown-option",
        },
    },
    {
        "id": "actions",
        "summary": (
            "The CLI 'run MODEL' route simulates one run and does not execute "
            "the model's action block; the API file-runner contract and the "
            "CLI 'run --input' route do execute it."
        ),
        "observation": {
            "cli_run_artifacts": [],
            "api_file_runner_artifacts": [
                "decay_actions.cdat",
                "decay_actions.gdat",
                "decay_actions.net",
            ],
            "cli_file_runner_artifacts": [
                "decay_actions.cdat",
                "decay_actions.gdat",
                "decay_actions.net",
            ],
        },
    },
    {
        "id": "exceptions",
        "summary": (
            "The API raises typed exceptions; the CLI maps them to exit "
            "codes and rewrites option spellings in the message."
        ),
        "observation": {
            "api_invalid_method": "ValueError",
            "api_invalid_n_steps": "ValueError",
            "cli_invalid_option_exit_code": 1,
            "cli_missing_model_exit_code": 2,
        },
    },
    {
        "id": "optional-imports",
        "summary": (
            "Optional third-party distributions are resolved lazily: importing "
            "bionetgen imports none of them, and a missing optional "
            "distribution surfaces as an ImportError rather than a silent "
            "None."
        ),
        "observation": {
            "imported_optional_distributions": [],
            "missing_sympy": "ImportError",
            "missing_cement": "imported",
        },
    },
    {
        "id": "none-defaults",
        "summary": (
            "An explicit None for t_end or n_steps is a provided value for the "
            "API and is rejected; the CLI's unset options are None and map to "
            "the documented defaults.  method=None is the one API exception "
            "and selects the default method."
        ),
        "observation": {
            "api_method_none": "accepted",
            "api_t_end_none": "TypeError",
            "api_n_steps_none": "TypeError",
        },
    },
)


def model_cases():
    """The generated model family.  Each case has an independent law."""
    return (
        dict(id="decay", k=0.5, n0=60, t_end=2.0, n_steps=4),
        dict(id="defaults", k=0.01, n0=100, t_end=100.0, n_steps=100),
    )


def model_bngl(case, *, actions=()):
    """Render the generated first-order decay model."""
    lines = [
        "begin model",
        "begin parameters",
        f"  k {case['k']}",
        f"  N0 {case['n0']}",
        "end parameters",
        "begin molecule types",
        "  A()",
        "end molecule types",
        "begin seed species",
        "  A() N0",
        "end seed species",
        "begin observables",
        "  Molecules Atot A()",
        "end observables",
        "begin reaction rules",
        "  A() -> 0 k",
        "end reaction rules",
    ]
    if actions:
        lines += ["begin actions", *actions, "end actions"]
    lines += ["end model", ""]
    return "\n".join(lines)


def surface_check_ids():
    return [f"api-surface:surface:{name}" for name in SURFACE_CHECKS]


def method_check_ids():
    return [
        f"api-surface:methods:{method}:{leg}"
        for method in METHODS
        for leg in METHOD_CHECKS
    ]


def check_ids():
    """Stable identities of every generated check in this family."""
    return [*surface_check_ids(), *method_check_ids()]


def law_mean(times, case):
    """Closed-form mean of the first-order decay process."""
    import numpy as np

    return float(case["n0"]) * np.exp(
        -float(case["k"]) * np.asarray(times, dtype=float)
    )


def law_variance(times, case):
    """Exact binomial variance of the first-order decay count law."""
    import numpy as np

    probability = np.exp(-float(case["k"]) * np.asarray(times, dtype=float))
    return float(case["n0"]) * probability * (1.0 - probability)


def binomial_cdf(population, probability, count):
    """Exact binomial cumulative probability."""
    if count < 0:
        return 0.0
    if count >= population:
        return 1.0
    return sum(
        math.comb(population, k)
        * probability**k
        * (1.0 - probability) ** (population - k)
        for k in range(count + 1)
    )


def binomial_range(population, probability, tail):
    """Smallest and largest count inside the exact central binomial range."""
    low, high = 0, population
    while low < population and binomial_cdf(population, probability, low) <= tail:
        low += 1
    while high > 0 and binomial_cdf(population, probability, high) >= 1.0 - tail:
        high -= 1
    return low, high


def _row(check_id, status, detail, first_difference=None, **evidence):
    kinds = {
        "PASS": "supported-execution",
        "FAIL": "supported-execution",
        "UNSUPPORTED": "diagnostic-only",
    }
    return {
        "id": check_id,
        "check": check_id.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "stage": "api-surface",
        "evidence_kind": kinds.get(status, "harness-error"),
        "supported_execution": status in {"PASS", "FAIL"},
        **evidence,
    }


def _law_difference(observed, expected, *, atol, rtol):
    """First difference between an observed trajectory and the closed form."""
    import numpy as np

    observed = np.asarray(observed, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if observed.shape != expected.shape:
        return {
            "field": "shape",
            "observed": list(observed.shape),
            "expected": list(expected.shape),
        }
    for index, value in enumerate(observed):
        if not np.isfinite(value):
            return {"field": "finite", "row": index, "observed": float(value)}
    unequal = ~np.isclose(observed, expected, atol=atol, rtol=rtol, equal_nan=False)
    if unequal.any():
        index = int(np.flatnonzero(unequal)[0])
        return {
            "field": "value",
            "row": index,
            "observed": float(observed[index]),
            "expected": float(expected[index]),
            "absolute_error": abs(float(observed[index]) - float(expected[index])),
        }
    return None


def _trajectory_difference(left, right, *, atol=0.0, rtol=0.0):
    """First difference between two observed trajectories."""
    import numpy as np

    left_time = np.asarray(left[0], dtype=float)
    right_time = np.asarray(right[0], dtype=float)
    if left_time.shape != right_time.shape:
        return {
            "field": "time.shape",
            "left": list(left_time.shape),
            "right": list(right_time.shape),
        }
    if not np.array_equal(left_time, right_time):
        index = int(np.flatnonzero(left_time != right_time)[0])
        return {
            "field": "time",
            "row": index,
            "left": float(left_time[index]),
            "right": float(right_time[index]),
        }
    for name in left[1]:
        if name not in right[1]:
            return {"field": "observables", "missing": name}
        a = np.asarray(left[1][name], dtype=float)
        b = np.asarray(right[1][name], dtype=float)
        if a.shape != b.shape:
            return {
                "field": name + ".shape",
                "left": list(a.shape),
                "right": list(b.shape),
            }
        unequal = ~np.isclose(a, b, atol=atol, rtol=rtol, equal_nan=False)
        if unequal.any():
            index = int(np.flatnonzero(unequal)[0])
            return {
                "field": name,
                "row": index,
                "left": float(a[index]),
                "right": float(b[index]),
            }
    return None


def cli_leg():
    """Resolve the command-line entry point that runs the imported package.

    The installed console script is preferred when the installed distribution
    owns the same package that the API leg imports.  Otherwise the module
    entry point is used with the package root pinned on ``PYTHONPATH`` so both
    legs provably execute the same code.
    """
    import bionetgen
    import bionetgen.model as model_module

    package_dir = Path(bionetgen.__file__).resolve().parent
    import_root = package_dir.parent
    native = getattr(model_module, "_cpp", None)
    native_root = Path(native.__file__).resolve().parent if native is not None else None
    executable = shutil.which("bionetgen")
    owned = False
    if executable is not None:
        try:
            distribution = importlib.metadata.distribution("bionetgen")
            owned = package_dir == Path(distribution.locate_file("bionetgen")).resolve()
        except importlib.metadata.PackageNotFoundError:
            owned = False
    if executable is not None and owned:
        return {
            "command": [executable],
            "environment": None,
            "kind": "installed-console-script",
            "executable": executable,
            "package": str(package_dir),
        }
    roots = [str(import_root)]
    if native_root is not None and native_root != import_root:
        roots.append(str(native_root))
    existing = os.environ.get("PYTHONPATH")
    if existing:
        roots.append(existing)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(roots))
    return {
        "command": [sys.executable, "-m", "bionetgen"],
        "environment": environment,
        "kind": "module-entry-point",
        "executable": sys.executable,
        "package": str(package_dir),
    }


def leg_identity(leg):
    """Report the package and native extension the command-line leg imports.

    The console script reports the package it imported through its own ``info``
    command, so the identity belongs to the entry point that will run the
    checks rather than to an unrelated interpreter.
    """
    probe = (
        "import json\n"
        "import bionetgen\n"
        "import bionetgen.model as model_module\n"
        "native = getattr(model_module, '_cpp', None)\n"
        "print(json.dumps({\n"
        "    'package': bionetgen.__file__,\n"
        "    'native': None if native is None else native.__file__,\n"
        "}))\n"
    )
    environment = (
        leg["environment"] if leg["environment"] is not None else dict(os.environ)
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "the command-line leg could not report its package identity: "
            + (completed.stdout + completed.stderr)[-400:]
        )
    identity = json.loads(completed.stdout.strip().splitlines()[-1])
    if leg["kind"] == "installed-console-script":
        reported = subprocess.run(
            [leg["executable"], "info"],
            capture_output=True,
            text=True,
            timeout=120,
            env=leg["environment"],
        )
        if reported.returncode != 0:
            raise RuntimeError(
                "the installed console script could not report its package: "
                + (reported.stdout + reported.stderr)[-400:]
            )
        entry = None
        for line in reported.stdout.splitlines():
            if line.startswith("Python package: "):
                entry = line.split(": ", 1)[1].strip()
        if entry is None:
            raise RuntimeError(
                "the installed console script did not report its package path"
            )
        identity["entry_package"] = entry
    return identity


def run_cli(leg, argv, cwd, timeout=180):
    """Run the command-line leg and return the completed process."""
    command = [*leg["command"], *[str(part) for part in argv]]
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=leg["environment"],
    )
    return command, completed


def read_table(path):
    """Read a CLI result table into its header and numeric rows.

    The CLI writes a tab-separated table and the action block writes a
    space-separated ``.gdat``; both are read by their header names.
    """
    import numpy as np

    header, rows = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            header = line.lstrip("#").strip().split()
            continue
        rows.append([float(value) for value in line.split()])
    if not rows:
        raise ValueError("CLI result table has no data rows")
    return header, np.asarray(rows, dtype=float)


def _api_trajectory(result):
    """Normalize a public SimResult into (time, observables)."""
    return (
        [float(value) for value in result.time],
        {
            name: [float(value) for value in values]
            for name, values in result.observables.items()
        },
    )


def _table_trajectory(header, data):
    """Normalize a CLI result table into (time, observables)."""
    if not header or header[0] != "time":
        raise ValueError("CLI result table has no time column")
    return (
        [float(value) for value in data[:, 0]],
        {
            name: [float(value) for value in data[:, index]]
            for index, name in enumerate(header)
            if index
        },
    )


def _blocked_modules_script(directory, blocked):
    """Write a sitecustomize that makes the named distributions unimportable.

    An absent distribution raises ``ModuleNotFoundError``; the blocker models
    exactly that, so the product's own optional-dependency handling is
    exercised rather than bypassed.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sitecustomize.py"
    path.write_text(
        "import sys\n"
        f"BLOCKED = {tuple(blocked)!r}\n"
        "\n"
        "class _Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self.find_spec(name, path)\n"
        "\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BLOCKED:\n"
        "            raise ModuleNotFoundError(\n"
        "                'No module named ' + repr(name), name=name\n"
        "            )\n"
        "        return None\n"
        "\n"
        "for _name in list(sys.modules):\n"
        "    if _name.split('.')[0] in BLOCKED:\n"
        "        del sys.modules[_name]\n"
        "sys.meta_path.insert(0, _Blocker())\n",
        encoding="utf-8",
    )
    return path


def _run_python(code, *, environment=None, cwd=None, timeout=180):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
    )


class _Context:
    """Shared state for one family execution."""

    def __init__(self, directory):
        import bionetgen
        import bionetgen.model as model_module

        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.bionetgen = bionetgen
        self.leg = cli_leg()
        self.identity = leg_identity(self.leg)
        api_package = Path(bionetgen.__file__).resolve()
        cli_package = Path(self.identity["package"]).resolve()
        if cli_package != api_package:
            raise RuntimeError(
                "the command-line leg imported a different package than the API "
                f"leg: {cli_package} != {api_package}"
            )
        entry_package = self.identity.get("entry_package")
        if entry_package is not None:
            entry = Path(entry_package).resolve()
            if entry != api_package.parent:
                raise RuntimeError(
                    "the installed console script imported a different package "
                    f"than the API leg: {entry} != {api_package.parent}"
                )
        native = getattr(model_module, "_cpp", None)
        api_native = Path(native.__file__).resolve() if native is not None else None
        cli_native = self.identity.get("native")
        if api_native is not None and cli_native is not None:
            if Path(cli_native).resolve() != api_native:
                raise RuntimeError(
                    "the command-line leg imported a different native extension "
                    f"than the API leg: {cli_native} != {api_native}"
                )
        self.observations = {}
        self.cases = {case["id"]: case for case in model_cases()}
        self.sources = {}
        for case in model_cases():
            path = self.directory / f"{case['id']}.bngl"
            path.write_text(model_bngl(case), encoding="utf-8")
            self.sources[case["id"]] = path

    def source(self, case_id):
        return self.sources[case_id]

    def api_run(self, source, *args, **options):
        return self.bionetgen.run(str(source), *args, **options)

    def cli(self, argv, cwd=None, timeout=180):
        return run_cli(
            self.leg, argv, cwd if cwd is not None else self.directory, timeout=timeout
        )


def _check_signatures_defaults(context):
    """Declared defaults must agree between the API, the CLI and the law."""
    import inspect

    differences = []
    bionetgen = context.bionetgen
    differences.extend(_check_none_defaults(context))
    wrapper = inspect.signature(bionetgen.run)
    for name in ("method", "t_end", "n_steps"):
        if name not in wrapper.parameters:
            differences.append({"field": "run.parameters", "missing": name})
    simulate = inspect.signature(bionetgen.BioNetGenModel.simulate)
    expected = {
        "method": "ode",
        "t_end": 100.0,
        "n_steps": 100,
        "t_start": 0.0,
        "rtol": 1e-8,
        "atol": 1e-12,
        "seed": 0,
        "pla_config": "",
        "psa_poplevel": 100.0,
        "verbose": False,
    }
    for name, value in expected.items():
        actual = simulate.parameters[name].default
        if actual != value or type(actual) is not type(value):
            differences.append(
                {
                    "field": f"simulate.{name}.default",
                    "expected": value,
                    "actual": actual,
                }
            )
    case = context.cases["defaults"]
    source = context.source("defaults")
    api = context.api_run(source)
    api_time = [float(value) for value in api.time]
    if len(api_time) != 101 or api_time[0] != 0.0 or api_time[-1] != 100.0:
        differences.append(
            {
                "field": "api.default_grid",
                "length": len(api_time),
                "start": api_time[0] if api_time else None,
                "end": api_time[-1] if api_time else None,
            }
        )
    output = context.directory / "defaults-cli.tsv"
    command, completed = context.cli(
        ["run", str(source), "--output", str(output)], cwd=context.directory
    )
    if completed.returncode != 0 or not output.is_file():
        differences.append(
            {
                "field": "cli.default_run",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    else:
        header, data = read_table(output)
        if header != ["time", "Atot"] or data.shape != (101, 2):
            differences.append(
                {
                    "field": "cli.default_table",
                    "header": header,
                    "shape": list(data.shape),
                }
            )
        else:
            difference = _law_difference(
                data[:, 1],
                law_mean(data[:, 0], case),
                atol=DEFAULT_ATOL,
                rtol=DEFAULT_RTOL,
            )
            if difference is not None:
                differences.append(dict(difference, field="cli.default_law"))
            api_values = [float(value) for value in api.observables["Atot"]]
            difference = _law_difference(
                api_values,
                law_mean(api_time, case),
                atol=DEFAULT_ATOL,
                rtol=DEFAULT_RTOL,
            )
            if difference is not None:
                differences.append(dict(difference, field="api.default_law"))
            difference = _trajectory_difference(
                (api_time, {"Atot": api_values}),
                (data[:, 0].tolist(), {"Atot": data[:, 1].tolist()}),
                atol=DEFAULT_ATOL,
                rtol=DEFAULT_RTOL,
            )
            if difference is not None:
                differences.append(dict(difference, field="default_route_difference"))
    return differences


def _check_positional_dispatch(context):
    """The API's positional dispatch must behave as documented."""
    differences = []
    case = context.cases["decay"]
    source = context.source("decay")
    try:
        result = context.api_run(source, "ssa", case["t_end"], case["n_steps"])
    except Exception as exc:
        differences.append(
            {
                "field": "api.positional_method",
                "exception": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        if len(result.time) != case["n_steps"] + 1:
            differences.append(
                {
                    "field": "api.positional_method.length",
                    "observed": len(result.time),
                    "expected": case["n_steps"] + 1,
                }
            )
        if float(result.time[-1]) != case["t_end"]:
            differences.append(
                {
                    "field": "api.positional_method.t_end",
                    "observed": float(result.time[-1]),
                    "expected": case["t_end"],
                }
            )
    try:
        context.api_run(source, "ssa", case["t_end"], case["n_steps"], method="ode")
    except TypeError as exc:
        if "multiple values for argument 'method'" not in str(exc):
            differences.append({"field": "api.duplicate_method", "detail": str(exc)})
    except Exception as exc:
        differences.append(
            {
                "field": "api.duplicate_method",
                "exception": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        differences.append({"field": "api.duplicate_method", "detail": "accepted"})
    try:
        context.api_run(source, 2.0)
    except TypeError as exc:
        if "must be a simulation method or output path" not in str(exc):
            differences.append({"field": "api.bad_positional", "detail": str(exc)})
    except Exception as exc:
        differences.append(
            {"field": "api.bad_positional", "exception": f"{type(exc).__name__}: {exc}"}
        )
    else:
        differences.append({"field": "api.bad_positional", "detail": "accepted"})
    try:
        context.api_run(source, "ssa", case["t_end"], case["n_steps"], 1, 2)
    except TypeError as exc:
        if "at most four positional arguments" not in str(exc):
            differences.append(
                {"field": "api.too_many_positionals", "detail": str(exc)}
            )
    except Exception as exc:
        differences.append(
            {
                "field": "api.too_many_positionals",
                "exception": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        differences.append({"field": "api.too_many_positionals", "detail": "accepted"})
    # The CLI has no positional method argument.
    _, completed = context.cli(["run", str(source), "ssa"], cwd=context.directory)
    if completed.returncode == 0 or "extra argument" not in (
        completed.stdout + completed.stderr
    ):
        differences.append(
            {
                "field": "cli.positional_method",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    context.observations["method-dispatch"] = {
        "api_positional_method": (
            "accepted"
            if not any(item["field"] == "api.positional_method" for item in differences)
            else "rejected"
        ),
        "cli_positional_method": (
            "rejected" if completed.returncode != 0 else "accepted"
        ),
    }
    return differences


def _check_timeouts(context):
    """Neither entry point may silently ignore a requested timeout."""
    differences = []
    source = context.source("decay")
    output = context.directory / "timeout-legacy"
    try:
        context.api_run(source, out=str(output), timeout=5)
    except NotImplementedError as exc:
        if "timeout" not in str(exc):
            differences.append({"field": "api.legacy_timeout", "detail": str(exc)})
    except Exception as exc:
        differences.append(
            {"field": "api.legacy_timeout", "exception": f"{type(exc).__name__}: {exc}"}
        )
    else:
        differences.append({"field": "api.legacy_timeout", "detail": "accepted"})
    try:
        context.api_run(source, method="ode", timeout=5)
    except TypeError as exc:
        if "timeout" not in str(exc):
            differences.append({"field": "api.modern_timeout", "detail": str(exc)})
    except Exception as exc:
        differences.append(
            {"field": "api.modern_timeout", "exception": f"{type(exc).__name__}: {exc}"}
        )
    else:
        differences.append({"field": "api.modern_timeout", "detail": "accepted"})
    _, completed = context.cli(
        ["run", str(source), "--timeout", "5"], cwd=context.directory
    )
    output_text = completed.stdout + completed.stderr
    if completed.returncode != 2 or "No such option" not in output_text:
        differences.append(
            {
                "field": "cli.timeout",
                "exit_code": completed.returncode,
                "output": output_text[-400:],
            }
        )
    context.observations["timeout"] = {
        "api_legacy_timeout": (
            "NotImplementedError"
            if not any(item["field"] == "api.legacy_timeout" for item in differences)
            else "unknown"
        ),
        "api_modern_timeout": (
            "TypeError"
            if not any(item["field"] == "api.modern_timeout" for item in differences)
            else "unknown"
        ),
        "cli_timeout": ("unknown-option" if completed.returncode == 2 else "accepted"),
    }
    return differences


def _action_model(context):
    """A model whose action block writes a network and a trajectory."""
    case = context.cases["decay"]
    path = context.directory / "decay_actions.bngl"
    path.write_text(
        model_bngl(
            case,
            actions=(
                "generate_network({overwrite=>1})",
                "writeNetwork({overwrite=>1})",
                'simulate({method=>"ode",t_end=>2,n_steps=>4,rtol=>1e-10,atol=>1e-12})',
            ),
        ),
        encoding="utf-8",
    )
    return path


def _artifacts(directory, stem):
    return sorted(
        path.name
        for path in Path(directory).iterdir()
        if path.is_file() and path.suffix in {".net", ".gdat", ".cdat", ".xml"}
    )


def _check_actions(context):
    """The action block must be executed identically by both entry points."""
    differences = []
    case = context.cases["decay"]
    source = _action_model(context)
    api_directory = context.directory / "actions-api"
    cli_directory = context.directory / "actions-cli"
    legacy_api_directory = context.directory / "actions-legacy-api"
    legacy_cli_directory = context.directory / "actions-legacy-cli"
    for directory in (
        api_directory,
        cli_directory,
        legacy_api_directory,
        legacy_cli_directory,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    api_source = api_directory / source.name
    cli_source = cli_directory / source.name
    shutil.copy2(source, api_source)
    shutil.copy2(source, cli_source)
    model = context.bionetgen.load(str(api_source))
    model.execute()
    api_artifacts = _artifacts(api_directory, source.stem)
    if not api_artifacts:
        differences.append({"field": "api.execute", "detail": "no action artifact"})
    _, completed = context.cli(["execute", str(cli_source)], cwd=cli_directory)
    if completed.returncode != 0:
        differences.append(
            {
                "field": "cli.execute",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    cli_artifacts = _artifacts(cli_directory, source.stem)
    if api_artifacts != cli_artifacts:
        differences.append(
            {
                "field": "actions.artifact_set",
                "api": api_artifacts,
                "cli": cli_artifacts,
            }
        )
    # The action trajectory must satisfy the independent law.
    for label, directory in (("api", api_directory), ("cli", cli_directory)):
        gdat = directory / (source.stem + ".gdat")
        if not gdat.is_file():
            differences.append({"field": f"{label}.action_gdat", "detail": "missing"})
            continue
        header, data = read_table(gdat)
        if header is None or len(header) != 2:
            differences.append({"field": f"{label}.action_gdat", "header": header})
            continue
        difference = _law_difference(
            data[:, 1],
            law_mean(data[:, 0], case),
            atol=ODE_ATOL,
            rtol=ODE_RTOL,
        )
        if difference is not None:
            differences.append(dict(difference, field=f"{label}.action_law"))
    # The file-runner contract executes the action block; the single-run CLI
    # route does not.
    context.bionetgen.run(str(source), out=str(legacy_api_directory))
    legacy_api_artifacts = _artifacts(legacy_api_directory, source.stem)
    _, completed = context.cli(
        ["run", "--input", str(source), "--output", str(legacy_cli_directory)],
        cwd=context.directory,
    )
    if completed.returncode != 0:
        differences.append(
            {
                "field": "cli.legacy_run",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    legacy_cli_artifacts = _artifacts(legacy_cli_directory, source.stem)
    if legacy_api_artifacts != legacy_cli_artifacts:
        differences.append(
            {
                "field": "actions.legacy_artifact_set",
                "api": legacy_api_artifacts,
                "cli": legacy_cli_artifacts,
            }
        )
    single_directory = context.directory / "actions-single-run"
    single_directory.mkdir(parents=True, exist_ok=True)
    single_source = single_directory / source.name
    shutil.copy2(source, single_source)
    output = single_directory / "result.tsv"
    _, completed = context.cli(
        ["run", str(single_source), "--method", "ode", "--output", str(output)],
        cwd=single_directory,
    )
    if completed.returncode != 0:
        differences.append(
            {
                "field": "cli.single_run",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    single_artifacts = _artifacts(single_directory, source.stem)
    if single_artifacts:
        differences.append(
            {"field": "actions.single_run_artifacts", "artifacts": single_artifacts}
        )
    context.observations["actions"] = {
        "cli_run_artifacts": single_artifacts,
        "api_file_runner_artifacts": legacy_api_artifacts,
        "cli_file_runner_artifacts": legacy_cli_artifacts,
    }
    return differences


def _check_results_files(context):
    """Both entry points must expose the same trajectory in their own shape."""
    differences = []
    case = context.cases["decay"]
    source = context.source("decay")
    api = context.api_run(
        source,
        method="ode",
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        rtol=1e-10,
        atol=1e-12,
    )
    if not hasattr(api, "time") or not isinstance(api.observables, dict):
        differences.append(
            {"field": "api.result_shape", "detail": "missing result members"}
        )
        return differences
    api_time = [float(value) for value in api.time]
    api_values = [float(value) for value in api.observables["Atot"]]
    concentrations = api.concentrations
    if concentrations is None:
        differences.append({"field": "api.concentrations", "detail": "missing"})
    else:
        import numpy as np

        shape = tuple(np.asarray(concentrations).shape)
        if shape != (case["n_steps"] + 1, 1):
            differences.append(
                {"field": "api.concentrations.shape", "shape": list(shape)}
            )
    difference = _law_difference(
        api_values, law_mean(api_time, case), atol=ODE_ATOL, rtol=ODE_RTOL
    )
    if difference is not None:
        differences.append(dict(difference, field="api.law"))
    output = context.directory / "result.tsv"
    _, completed = context.cli(
        [
            "run",
            str(source),
            "--method",
            "ode",
            "--t-end",
            repr(case["t_end"]),
            "--n-steps",
            str(case["n_steps"]),
            "--rtol",
            "1e-10",
            "--atol",
            "1e-12",
            "--output",
            str(output),
        ],
        cwd=context.directory,
    )
    if completed.returncode != 0 or not output.is_file():
        differences.append(
            {
                "field": "cli.run",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
        return differences
    header, data = read_table(output)
    if header != ["time", "Atot"]:
        differences.append({"field": "cli.header", "header": header})
    difference = _law_difference(
        data[:, 1], law_mean(data[:, 0], case), atol=ODE_ATOL, rtol=ODE_RTOL
    )
    if difference is not None:
        differences.append(dict(difference, field="cli.law"))
    # The network-free route does not provide a concentration matrix.
    nf = context.api_run(
        source,
        method="nf",
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        seed=7,
    )
    nf_concentrations = nf.concentrations
    context.observations["result-container"] = {
        "api_result_type": type(api).__name__,
        "cli_result_type": "process-exit-status",
        "cli_written_files": [output.name],
    }
    context.observations["table-columns"] = {
        "cli_columns": list(header or []),
        "api_concentration_columns": 1 if concentrations is not None else None,
        "nf_concentration_columns": (
            None if nf_concentrations is None else int(nf_concentrations.shape[1])
        ),
    }
    return differences


def _check_exceptions(context):
    """Both entry points must refuse invalid input with their own contract."""
    differences = []
    case = context.cases["decay"]
    source = context.source("decay")
    model = context.bionetgen.load(str(source))
    expected = (
        ({"method": "bogus"}, ValueError, "Unknown simulation method"),
        ({"method": 123}, TypeError, "method must be a string"),
        ({"n_steps": 0}, ValueError, "n_steps must be positive"),
        ({"rtol": 0.0}, ValueError, "rtol must be finite and positive"),
        ({"t_end": -1.0}, ValueError, "t_end must be greater than or equal"),
    )
    for options, kind, message in expected:
        try:
            model.simulate(**options)
        except kind as exc:
            if message not in str(exc):
                differences.append(
                    {
                        "field": f"api.exception.{sorted(options)[0]}",
                        "detail": str(exc),
                    }
                )
        except Exception as exc:
            differences.append(
                {
                    "field": f"api.exception.{sorted(options)[0]}",
                    "exception": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            differences.append(
                {"field": f"api.exception.{sorted(options)[0]}", "detail": "accepted"}
            )
    # The CLI maps the same invalid input to an exit status.
    _, completed = context.cli(
        ["run", str(source), "--rtol", "0"], cwd=context.directory
    )
    cli_text = completed.stdout + completed.stderr
    if completed.returncode != 1 or "rtol must be finite and positive" not in cli_text:
        differences.append(
            {
                "field": "cli.invalid_option",
                "exit_code": completed.returncode,
                "output": cli_text[-400:],
            }
        )
    missing = context.directory / "missing-model.bngl"
    _, completed = context.cli(["run", str(missing)], cwd=context.directory)
    if completed.returncode != 2:
        differences.append(
            {
                "field": "cli.missing_model",
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    context.observations["exceptions"] = {
        "api_invalid_method": "ValueError",
        "api_invalid_n_steps": "ValueError",
        "cli_invalid_option_exit_code": 1,
        "cli_missing_model_exit_code": 2,
    }
    return differences


def _check_optional_imports(context):
    """Optional distributions must stay optional and stay lazily imported."""
    differences = []
    probe = (
        "import bionetgen, sys, json;"
        "print(json.dumps(sorted({name.split('.')[0] for name in sys.modules"
        " if name.split('.')[0] in %r})))" % (OPTIONAL_DISTRIBUTIONS,)
    )
    completed = _run_python(probe, environment=dict(os.environ))
    if completed.returncode != 0:
        differences.append(
            {
                "field": "import.bionetgen",
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
        imported = []
    else:
        imported = json.loads(completed.stdout.strip().splitlines()[-1])
    if imported:
        differences.append(
            {"field": "import.optional_distributions", "imported": imported}
        )
    blocked = context.directory / "blocked"
    _blocked_modules_script(blocked, ("sympy", "cement"))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(blocked), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    probe = (
        "import bionetgen, json\n"
        "out = {}\n"
        "try:\n"
        "    bionetgen.SympyOdes\n"
        "    out['sympy'] = 'imported'\n"
        "except ImportError as exc:\n"
        "    out['sympy'] = 'ImportError'\n"
        "except Exception as exc:\n"
        "    out['sympy'] = type(exc).__name__\n"
        "try:\n"
        "    bionetgen.defaults\n"
        "    out['cement'] = 'imported'\n"
        "except ImportError as exc:\n"
        "    out['cement'] = 'ImportError'\n"
        "except Exception as exc:\n"
        "    out['cement'] = type(exc).__name__\n"
        "print(json.dumps(out))\n"
    )
    completed = _run_python(probe, environment=environment)
    if completed.returncode != 0:
        differences.append(
            {
                "field": "import.blocked",
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
        blocked_result = {"sympy": "unknown", "cement": "unknown"}
    else:
        blocked_result = json.loads(completed.stdout.strip().splitlines()[-1])
    if blocked_result.get("sympy") != "ImportError":
        differences.append(
            {"field": "import.missing_sympy", "observed": blocked_result.get("sympy")}
        )
    if blocked_result.get("cement") != "imported":
        differences.append(
            {"field": "import.missing_cement", "observed": blocked_result.get("cement")}
        )
    # An unknown public name is an AttributeError, not a silent None.
    probe = (
        "import bionetgen\n"
        "try:\n"
        "    bionetgen.definitely_not_a_public_name\n"
        "    print('accepted')\n"
        "except AttributeError:\n"
        "    print('AttributeError')\n"
    )
    completed = _run_python(probe, environment=dict(os.environ))
    if completed.returncode != 0 or completed.stdout.strip() != "AttributeError":
        differences.append(
            {
                "field": "import.unknown_name",
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        )
    # The CLI's optional commands must not be required by the core commands.
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(blocked), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    _, completed = context.cli(["--help"], cwd=context.directory)
    if completed.returncode != 0:
        differences.append({"field": "cli.help", "exit_code": completed.returncode})
    context.observations["optional-imports"] = {
        "imported_optional_distributions": imported,
        "missing_sympy": blocked_result.get("sympy"),
        "missing_cement": blocked_result.get("cement"),
    }
    return differences


def _check_none_defaults(context):
    """An explicit None is a provided value for the API's time arguments."""
    differences = []
    source = context.source("decay")
    result = context.api_run(source, method=None)
    if len(result.time) != 101:
        differences.append({"field": "api.method_none", "length": len(result.time)})
    for name in ("t_end", "n_steps"):
        try:
            context.api_run(source, **{name: None})
        except TypeError:
            continue
        except Exception as exc:
            differences.append(
                {
                    "field": f"api.{name}_none",
                    "exception": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            differences.append({"field": f"api.{name}_none", "detail": "accepted"})
    context.observations["none-defaults"] = {
        "api_method_none": "accepted",
        "api_t_end_none": "TypeError",
        "api_n_steps_none": "TypeError",
    }
    return differences


def _check_intentional_incompatibilities(context):
    """Every declared difference must be observed exactly as declared."""
    differences = []
    for declaration in INTENTIONAL_INCOMPATIBILITIES:
        observed = context.observations.get(declaration["id"])
        if observed is None:
            differences.append(
                {
                    "field": f"incompatibility.{declaration['id']}",
                    "detail": "no observation was recorded for the declaration",
                }
            )
            continue
        if observed != declaration["observation"]:
            differences.append(
                {
                    "field": f"incompatibility.{declaration['id']}",
                    "declared": declaration["observation"],
                    "observed": observed,
                }
            )
    # The method dispatch and timeout declarations are recorded by their own
    # checks; make sure they are present.
    for name in ("method-dispatch", "timeout"):
        if name not in context.observations:
            differences.append(
                {
                    "field": f"incompatibility.{name}",
                    "detail": "no observation was recorded for the declaration",
                }
            )
    return differences


def _api_ensemble(context, method, case, seeds):
    """Run the public API route for every recorded seed."""
    import numpy as np

    source = context.source(case["id"])
    trajectories = []
    for seed in seeds:
        result = context.api_run(
            source,
            method=method,
            t_end=case["t_end"],
            n_steps=case["n_steps"],
            seed=seed,
        )
        trajectories.append([float(value) for value in result.observables["Atot"]])
    return np.asarray(trajectories, dtype=float), None


def _cli_ensemble(context, method, case, seeds):
    """Run the command-line route for every recorded seed."""
    import numpy as np

    source = context.source(case["id"])
    directory = context.directory / "cli-ensemble" / method
    directory.mkdir(parents=True, exist_ok=True)

    def one(index):
        seed = seeds[index]
        output = directory / f"run-{index:03d}.tsv"
        _, completed = context.cli(
            [
                "run",
                str(source),
                "--method",
                method,
                "--t-end",
                repr(case["t_end"]),
                "--n-steps",
                str(case["n_steps"]),
                "--seed",
                str(seed),
                "--output",
                str(output),
            ],
            cwd=directory,
        )
        if completed.returncode != 0 or not output.is_file():
            return None, {
                "index": index,
                "seed": seed,
                "exit_code": completed.returncode,
                "output": (completed.stdout + completed.stderr)[-400:],
            }
        _, data = read_table(output)
        return [float(value) for value in data[:, 1]], None

    with ThreadPoolExecutor(max_workers=ENSEMBLE_WORKERS) as pool:
        outcomes = list(pool.map(one, range(len(seeds))))
    failures = [failure for _, failure in outcomes if failure is not None]
    if failures:
        return None, failures
    return np.asarray([values for values, _ in outcomes], dtype=float), None


def _law_statements(samples, case, times):
    """Compare an ensemble against the exact binomial count law."""
    import numpy as np

    statements = []
    terminal = samples[:, -1]
    expected_mean = float(law_mean([times[-1]], case)[0])
    expected_variance = float(law_variance([times[-1]], case)[0])
    observed_mean = float(terminal.mean())
    observed_variance = float(terminal.var(ddof=1))
    standard_error = math.sqrt(expected_variance / len(terminal))
    limit = LAW_MEAN_SIGMAS * standard_error
    difference = None
    if abs(observed_mean - expected_mean) > limit:
        difference = {
            "field": "ensemble_mean",
            "observed": observed_mean,
            "expected": expected_mean,
            "limit": limit,
            "standard_error": standard_error,
        }
    statements.append(
        (
            "law-mean",
            difference is None,
            "exact binomial mean with an analytic standard-error budget",
            difference,
        )
    )
    low = LAW_VARIANCE_BAND[0] * expected_variance
    high = LAW_VARIANCE_BAND[1] * expected_variance
    difference = None
    if not low <= observed_variance <= high:
        difference = {
            "field": "ensemble_dispersion",
            "observed": observed_variance,
            "expected": expected_variance,
            "band": [low, high],
        }
    statements.append(
        (
            "law-dispersion",
            difference is None,
            "exact binomial variance with a declared chi-square band",
            difference,
        )
    )
    probability = math.exp(-float(case["k"]) * float(times[-1]))
    low_count, high_count = binomial_range(int(case["n0"]), probability, LAW_TAIL)
    difference = None
    outside = [int(value) for value in terminal if not low_count <= value <= high_count]
    if outside:
        difference = {
            "field": "trajectory_range",
            "outside": sorted(set(outside))[:8],
            "range": [low_count, high_count],
        }
    statements.append(
        (
            "law-range",
            difference is None,
            "exact binomial central range at the declared tail probability",
            difference,
        )
    )
    if not np.all(np.diff(samples, axis=1) <= 0):
        statements.append(
            (
                "law-monotone",
                False,
                "a first-order decay count never increases",
                {"field": "monotone"},
            )
        )
    else:
        statements.append(
            ("law-monotone", True, "a first-order decay count never increases", None)
        )
    return statements


def _method_checks(context, method):
    """Execute the API, CLI and route checks for one simulation method."""
    rows = []
    case = context.cases["decay"]
    seeds = [ENSEMBLE_SEED_BASE + index for index in range(ENSEMBLE_RUNS)]
    times = [
        case["t_end"] * index / case["n_steps"] for index in range(case["n_steps"] + 1)
    ]
    if method in DETERMINISTIC_METHODS:
        rows.extend(_deterministic_method_checks(context, method, case, times))
        return rows
    api_samples, api_failure = _api_ensemble(context, method, case, seeds)
    cli_samples, cli_failure = _cli_ensemble(context, method, case, seeds)
    api_statements = []
    if api_samples is None:
        api_statements.append(
            (
                "law-samples",
                False,
                "the API route produced no ensemble",
                {"field": "api_ensemble", "failures": api_failure},
            )
        )
    else:
        api_statements.extend(_law_statements(api_samples, case, times))
        api_statements.extend(_source_law_statements(api_samples, case, times))
    cli_statements = []
    if cli_samples is None:
        cli_statements.append(
            (
                "law-samples",
                False,
                "the CLI route produced no ensemble",
                {"field": "cli_ensemble", "failures": cli_failure},
            )
        )
    else:
        cli_statements.extend(_law_statements(cli_samples, case, times))
        cli_statements.extend(_source_law_statements(cli_samples, case, times))
    for leg, statements, samples in (
        ("api-vs-law", api_statements, api_samples),
        ("cli-vs-law", cli_statements, cli_samples),
    ):
        failed = [name for name, ok, _, _ in statements if not ok]
        difference = next(
            (item for _, ok, _, item in statements if not ok and item is not None),
            None,
        )
        rows.append(
            _row(
                f"api-surface:methods:{method}:{leg}",
                "FAIL" if failed else "PASS",
                (
                    "independent first-order decay law: "
                    + ", ".join(name for name, _, _, _ in statements)
                    + (f"; failed: {', '.join(failed)}" if failed else "")
                ),
                difference,
                observations=dict(
                    (name, {"ok": ok, "detail": detail})
                    for name, ok, detail, _ in statements
                ),
                law="exact binomial count law of a first-order decay process",
                ensemble_runs=ENSEMBLE_RUNS,
                seeds=seeds,
                alpha=ALPHA,
            )
        )
        if samples is None:
            continue
    # The two routes must agree with each other for the same recorded seed,
    # and that agreement never replaces the law comparison above.
    if api_samples is not None and cli_samples is not None:
        difference = None
        for index in range(len(seeds)):
            difference = _trajectory_difference(
                ([times[-1]], {"Atot": api_samples[index].tolist()}),
                ([times[-1]], {"Atot": cli_samples[index].tolist()}),
            )
            if difference is not None:
                difference = dict(difference, seed=seeds[index])
                break
        failed = []
        for leg in ("api-vs-law", "cli-vs-law"):
            row = next(item for item in rows if item["id"].endswith(f":{method}:{leg}"))
            if row["status"] != "PASS":
                failed.append(leg)
        status = "PASS"
        if difference is not None:
            status = "FAIL"
        elif failed:
            status = "FAIL"
        rows.append(
            _row(
                f"api-surface:methods:{method}:route-agreement",
                status,
                (
                    "API and CLI trajectories agree for every recorded seed; "
                    "the independent law remains the primary oracle"
                ),
                difference,
                route_difference=(
                    "identical trajectories for the same recorded seed"
                    if difference is None
                    else "the routes diverged for a recorded seed"
                ),
                law_failures=failed,
                ensemble_runs=ENSEMBLE_RUNS,
                seeds=seeds,
            )
        )
    else:
        rows.append(
            _row(
                f"api-surface:methods:{method}:route-agreement",
                "NOT_TESTED",
                "a route produced no ensemble, so the routes cannot be compared",
            )
        )
    return rows


def _source_law_statements(samples, case, times):
    """Reuse the harness source-count-law comparator for the ensemble."""
    law_case = {
        "law": "first-order",
        "initial": int(case["n0"]),
        "rate": float(case["k"]),
        "times": list(times),
        "volume": 1.0,
    }
    statements = []
    for row in integrated_marginals.assess_samples(samples, law_case, alpha=ALPHA):
        statements.append(
            (
                f"source-law:{row['check']}",
                row["status"] == "PASS",
                row["detail"],
                row.get("first_difference"),
            )
        )
    return statements


def _deterministic_method_checks(context, method, case, times):
    """Compare the deterministic route with the closed-form trajectory."""
    rows = []
    source = context.source(case["id"])
    options = dict(
        method=method,
        t_end=case["t_end"],
        n_steps=case["n_steps"],
        rtol=1e-10,
        atol=1e-12,
    )
    api = context.api_run(source, **options)
    api_trajectory = _api_trajectory(api)
    difference = _law_difference(
        api_trajectory[1]["Atot"],
        law_mean(api_trajectory[0], case),
        atol=ODE_ATOL,
        rtol=ODE_RTOL,
    )
    rows.append(
        _row(
            f"api-surface:methods:{method}:api-vs-law",
            "FAIL" if difference else "PASS",
            "the API trajectory matches the closed-form first-order decay law",
            difference,
            law="closed-form first-order decay trajectory",
        )
    )
    output = context.directory / f"{method}-cli.tsv"
    _, completed = context.cli(
        [
            "run",
            str(source),
            "--method",
            method,
            "--t-end",
            repr(case["t_end"]),
            "--n-steps",
            str(case["n_steps"]),
            "--rtol",
            "1e-10",
            "--atol",
            "1e-12",
            "--output",
            str(output),
        ],
        cwd=context.directory,
    )
    if completed.returncode != 0 or not output.is_file():
        rows.append(
            _row(
                f"api-surface:methods:{method}:cli-vs-law",
                "FAIL",
                "the CLI route did not produce a result table",
                {
                    "field": "cli.run",
                    "exit_code": completed.returncode,
                    "output": (completed.stdout + completed.stderr)[-400:],
                },
            )
        )
        rows.append(
            _row(
                f"api-surface:methods:{method}:route-agreement",
                "NOT_TESTED",
                "the CLI route produced no trajectory",
            )
        )
        return rows
    header, data = read_table(output)
    cli_trajectory = _table_trajectory(header, data)
    difference = _law_difference(
        cli_trajectory[1]["Atot"],
        law_mean(cli_trajectory[0], case),
        atol=ODE_ATOL,
        rtol=ODE_RTOL,
    )
    rows.append(
        _row(
            f"api-surface:methods:{method}:cli-vs-law",
            "FAIL" if difference else "PASS",
            "the CLI trajectory matches the closed-form first-order decay law",
            difference,
            law="closed-form first-order decay trajectory",
        )
    )
    difference = _trajectory_difference(
        api_trajectory, cli_trajectory, atol=ODE_ATOL, rtol=ODE_RTOL
    )
    status = "PASS"
    if difference is not None:
        status = "FAIL"
    elif any(row["status"] != "PASS" for row in rows):
        status = "FAIL"
    rows.append(
        _row(
            f"api-surface:methods:{method}:route-agreement",
            status,
            (
                "API and CLI trajectories agree for the same request; the "
                "independent law remains the primary oracle"
            ),
            difference,
            law_failures=[row["check"] for row in rows if row["status"] != "PASS"],
        )
    )
    return rows


def run(directory):
    """Execute the generated public API and CLI surface checks."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        context = _Context(directory)
    except Exception as exc:
        return [
            _row(
                check_id,
                "NOT_TESTED",
                f"the public package could not be prepared: {type(exc).__name__}: {exc}",
            )
            for check_id in check_ids()
        ]
    rows = []
    handlers = {
        "signatures-defaults": _check_signatures_defaults,
        "positional-dispatch": _check_positional_dispatch,
        "timeouts": _check_timeouts,
        "actions": _check_actions,
        "results-files": _check_results_files,
        "exceptions": _check_exceptions,
        "optional-imports": _check_optional_imports,
    }
    for name in SURFACE_CHECKS:
        if name == "intentional-incompatibilities":
            continue
        handler = handlers[name]
        try:
            differences = handler(context)
        except Exception as exc:
            rows.append(
                _row(
                    f"api-surface:surface:{name}",
                    "FAIL",
                    f"the surface check raised {type(exc).__name__}: {exc}",
                )
            )
            continue
        rows.append(
            _row(
                f"api-surface:surface:{name}",
                "FAIL" if differences else "PASS",
                (
                    "the declared public surface contract holds"
                    if not differences
                    else "the declared public surface contract was violated"
                ),
                differences[0] if differences else None,
                differences=differences,
            )
        )
    try:
        differences = _check_intentional_incompatibilities(context)
    except Exception as exc:
        differences = [
            {
                "field": "incompatibility",
                "exception": f"{type(exc).__name__}: {exc}",
            }
        ]
    rows.append(
        _row(
            "api-surface:surface:intentional-incompatibilities",
            "FAIL" if differences else "PASS",
            (
                "every declared API/CLI difference was observed exactly as " "declared"
                if not differences
                else "a declared API/CLI difference was not observed as declared"
            ),
            differences[0] if differences else None,
            differences=differences,
            declared=[
                {
                    "id": item["id"],
                    "summary": item["summary"],
                    "observation": item["observation"],
                }
                for item in INTENTIONAL_INCOMPATIBILITIES
            ],
        )
    )
    for method in METHODS:
        try:
            rows.extend(_method_checks(context, method))
        except Exception as exc:
            for leg in METHOD_CHECKS:
                rows.append(
                    _row(
                        f"api-surface:methods:{method}:{leg}",
                        "FAIL",
                        f"the method check raised {type(exc).__name__}: {exc}",
                    )
                )
    return rows


def build_report(rows, directory):
    """Assemble the harness report for this family."""
    directory = Path(directory).resolve()
    report = dict(
        schema_version=1,
        generated_by="tests.validation.api_surface",
        source=dict(
            revision=campaign.git(ROOT, "rev-parse", "HEAD"),
            dirty=bool(campaign.git(ROOT, "status", "--porcelain")),
        ),
        subject=dict(
            package=str(Path(sys.modules["bionetgen"].__file__).resolve().parent),
            binary=str(Path(sys.modules["bionetgen"].__file__).resolve().parent),
        ),
        references={},
        configuration=dict(
            methods=list(METHODS),
            ensemble_runs=ENSEMBLE_RUNS,
            ensemble_seeds=[
                ENSEMBLE_SEED_BASE + index for index in range(ENSEMBLE_RUNS)
            ],
            alpha=ALPHA,
            law="exact binomial count law of a first-order decay process",
            model_cases=[dict(case) for case in model_cases()],
        ),
        results=rows,
    )
    report["investigation_tasks"] = reporting.investigation_tasks(report, directory)
    for task in report["investigation_tasks"]:
        task["replay_status"] = "PREPARED_NOT_EXECUTED"
    return report


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report directory must be empty")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    rows = run(args.report_dir)
    report = build_report(rows, args.report_dir)
    (args.report_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    failures = [row["id"] for row in rows if row["status"] != "PASS"]
    for row in rows:
        print(f"{row['status']:>12}  {row['id']}")
    if failures:
        print("failing checks: " + ", ".join(failures))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
