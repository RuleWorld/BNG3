"""The public seed contract must hold for every stochastic simulation method.

Regression coverage for the silent seed loss in the PLA and PSA routes: the
simulators already honoured ``OdeOptions::seed`` but the bindings never
forwarded the public ``seed`` argument, so two runs with the same seed
produced different trajectories.
"""

import os

import numpy as np
import pytest
from click.testing import CliRunner

from bionetgen.cli import main

STOCHASTIC_METHODS = ["ssa", "nf", "pla", "psa"]

MODEL = """begin model
begin parameters
    k 0.5
    N0 60
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() N0
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
end model
"""


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "decay.bngl"
    path.write_text(MODEL)
    return path


@pytest.mark.parametrize("method", STOCHASTIC_METHODS)
def test_api_seed_selects_a_reproducible_trajectory(model, method):
    import bionetgen

    options = dict(method=method, t_end=2.0, n_steps=4)
    first = bionetgen.load(str(model)).simulate(seed=20260101, **options)
    second = bionetgen.load(str(model)).simulate(seed=20260101, **options)
    other = bionetgen.load(str(model)).simulate(seed=20260102, **options)

    assert np.array_equal(
        first.observables["Atot"], second.observables["Atot"]
    ), f"{method} ignored the requested seed"
    assert not np.array_equal(
        first.observables["Atot"], other.observables["Atot"]
    ), f"{method} produced the same trajectory for different seeds"


@pytest.mark.parametrize("method", STOCHASTIC_METHODS)
def test_installed_cli_seed_selects_a_reproducible_trajectory(model, method, tmp_path):
    runner = CliRunner()

    def run(seed, name):
        output = tmp_path / name
        result = runner.invoke(
            main,
            [
                "run",
                str(model),
                "--method",
                method,
                "--t-end",
                "2",
                "--n-steps",
                "4",
                "--seed",
                str(seed),
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        return np.loadtxt(output, comments="#")[:, 1]

    first = run(20260101, "first.tsv")
    second = run(20260101, "second.tsv")
    other = run(20260102, "other.tsv")

    assert np.array_equal(first, second), f"{method} ignored the requested seed"
    assert not np.array_equal(first, other)


def test_the_public_api_and_the_cli_share_one_seeded_trajectory(model, tmp_path):
    """The same seed must select the same trajectory through both entry points."""
    import bionetgen

    runner = CliRunner()
    output = tmp_path / "cli.tsv"
    result = runner.invoke(
        main,
        [
            "run",
            str(model),
            "--method",
            "pla",
            "--t-end",
            "2",
            "--n-steps",
            "4",
            "--seed",
            "20260101",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    api = bionetgen.load(str(model)).simulate(
        method="pla", t_end=2.0, n_steps=4, seed=20260101
    )
    assert np.array_equal(
        np.loadtxt(output, comments="#")[:, 1], api.observables["Atot"]
    )


def test_the_documented_seed_default_remains_a_system_seed(model):
    """seed=0 keeps the documented system-default behaviour."""
    import bionetgen

    options = dict(method="pla", t_end=2.0, n_steps=4)
    first = bionetgen.load(str(model)).simulate(seed=0, **options)
    second = bionetgen.load(str(model)).simulate(seed=0, **options)
    assert not np.array_equal(
        first.observables["Atot"], second.observables["Atot"]
    ), "seed=0 must not select a reproducible stream"


def test_optional_imports_are_not_required_by_the_seed_contract():
    """The seed contract does not pull an optional distribution into scope."""
    import subprocess
    import sys

    script = (
        "import sys, bionetgen;"
        "print(sorted({name.split('.')[0] for name in sys.modules"
        " if name.split('.')[0] in ('sympy', 'matplotlib', 'networkx', 'cement')}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
    assert os.path.basename(sys.executable)
