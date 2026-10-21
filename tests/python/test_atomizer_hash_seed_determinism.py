"""The emitted model must not depend on the interpreter's hash seed.

The modern Atomizer folds a rate law that it recognizes as an elementary
mass-action law into a *coefficient*.  The numeric probe behind that fold
evaluates the law at a few sample points, and it has to give every species and
every assignment-rule variable a distinct value so that a law which is *not*
mass-action does not look constant.  Which symbol gets which sample point is a
choice the source model has to make for itself, because the coefficient the
probe reports is a function of it.

The probe used to sort the probed symbols by name *length* only.  Equally long
names were therefore left in the iteration order of a set, and a set's
iteration order depends on the process's ``PYTHONHASHSEED``.  The folded
coefficient, and with it the generated flat BNGL, therefore changed from one
run to the next: the same source model produced four different constants
under four different seeds.

The fixture ``models/mass_action_probe_order.sbml`` is the smallest model that
shows it.  It has two species of the same length (``Aa`` and ``Bb``) and two
assignment-rule parameters of the same length (``p1`` and ``p2``), and its
rate law names both an equally long species and an equally long
assignment-rule variable, so that the sample point each of them occupies
decides the coefficient the probe reports.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "tests" / "python" / "models" / "mass_action_probe_order.sbml"

# The seeds are the ones the corpus measurement work uses to tell a difference
# in the conversion from a difference in the hash order.
HASH_SEEDS = ("0", "1", "2", "3")


def _environment(hash_seed: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = hash_seed
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "python"), str(REPO / "build" / "cpp")]
    )
    return environment


def _run_worker(worker: str, *arguments: str, hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", worker, *arguments],
        check=True,
        capture_output=True,
        cwd=REPO,
        env=_environment(hash_seed),
        text=True,
    )
    return completed.stdout


def test_flat_bngl_is_byte_identical_across_hash_seeds():
    """The same source model must produce the same flat BNGL under any seed."""

    worker = """import sys
from bionetgen.atomizer.modern import Atomizer
source = sys.argv[1]
result = Atomizer(atomize=False, quiet_mode=True).atomize(
    open(source, encoding="utf-8").read()
)
if not result.success:
    raise RuntimeError(result.error or "the Atomizer failed")
sys.stdout.write(result.bngl)
"""
    outputs = {
        hash_seed: _run_worker(worker, str(SOURCE), hash_seed=hash_seed)
        for hash_seed in HASH_SEEDS
    }

    digests = {
        hash_seed: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for hash_seed, text in outputs.items()
    }
    assert len(set(digests.values())) == 1, digests
    # The rate the writer emits is a folded coefficient; it has to be the same
    # number under every seed, not merely a number of the same length.
    rates = {
        hash_seed: next(
            line.strip()
            for line in outputs[hash_seed].splitlines()
            if line.strip().startswith("r:")
        )
        for hash_seed in HASH_SEEDS
    }
    assert len(set(rates.values())) == 1, rates


def test_folded_mass_action_constant_is_the_same_number_under_every_seed():
    """The probe's coefficient must not depend on the hash order either."""

    worker = """from bionetgen.atomizer.modern import SBMLCompartment, check_mass_action
value = check_mass_action(
    "k0 * (Aa / __compartment_cell__) + k1 * p2",
    "Aa",
    "__compartment_cell__",
    {"k0": 0.01, "k1": 1e-06},
    {"cell": SBMLCompartment(id="cell", size=1)},
    {"Aa": "cell", "Bb": "cell"},
    {"p1", "p2"},
    reaction_order=1,
)
print(repr(value))
"""
    outputs = {
        hash_seed: _run_worker(worker, hash_seed=hash_seed) for hash_seed in HASH_SEEDS
    }

    assert len(set(outputs.values())) == 1, outputs
