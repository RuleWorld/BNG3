from __future__ import annotations
import os
from pathlib import Path

from scripts import nf_energy_statistical_parity as parity


def test_generalized_energy_context_restores_absent_environment():
    os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)
    with parity.generalized_energy(True):
        assert os.environ["BNG_NFSIM_GENERAL_ENERGY"] == "1"
    assert "BNG_NFSIM_GENERAL_ENERGY" not in os.environ


def test_generalized_energy_context_restores_existing_environment():
    os.environ["BNG_NFSIM_GENERAL_ENERGY"] = "custom"
    with parity.generalized_energy(False):
        assert "BNG_NFSIM_GENERAL_ENERGY" not in os.environ
    assert os.environ["BNG_NFSIM_GENERAL_ENERGY"] == "custom"
    os.environ.pop("BNG_NFSIM_GENERAL_ENERGY", None)
