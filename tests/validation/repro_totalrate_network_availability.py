#!/usr/bin/env python3
"""Standalone, intentionally failing reproduction for finite-network TotalRate.

Run from the BNG3 repository root after building the native extension:

    PYTHONPATH=python:build/cpp python \
      tests/validation/repro_totalrate_network_availability.py

The script is not collected by pytest. It exits nonzero while the finite-network
TotalRate implementation violates the conserved one-mRNA observable bound or
the seeded SSA population invariants.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess
import sys

MODEL = """
begin model
begin parameters
    k_init 1
    k_elong 1
    k_term 1
end parameters
begin molecule types
    mrna(p0~free~blocked,p1,p2)
    ribosome(asite)
end molecule types
begin seed species
    mrna(p0~free,p1,p2) 1
    ribosome(asite) 5
end seed species
begin observables
    Molecules rib_elong ribosome(asite!1).mrna(p1,p2!1)
end observables
begin reaction rules
    initiate: ribosome(asite) + mrna(p0~free) -> ribosome(asite!1).mrna(p0~blocked!1) k_init TotalRate
    elongate_1: ribosome(asite!1).mrna(p0~blocked!1,p1) -> ribosome(asite!1).mrna(p0~free,p1!1) k_elong
    elongate_2: ribosome(asite!1).mrna(p1!1,p2) -> ribosome(asite!1).mrna(p1,p2!1) k_elong
    terminate: ribosome(asite!1).mrna(p2!1) -> ribosome(asite) + mrna(p2) k_term
end reaction rules
end model
"""


def _load_native_extension(repository: Path):
    """Load this checkout's extension even when another tree is editable."""
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))
    from scripts.ci.python_package_mode import (
        editable_finders_for_package,
        editable_source_roots,
    )

    finders = editable_finders_for_package(sys.meta_path, "bionetgen")
    if finders:
        sys.meta_path = [finder for finder in sys.meta_path if finder not in finders]
        roots = editable_source_roots(finders, "bionetgen")
        sys.path[:] = [
            entry
            for entry in sys.path
            if not any(Path(entry or ".").resolve() == root for root in roots)
        ]

    extension_dir = repository / "build" / "cpp"
    if not extension_dir.is_dir():
        raise RuntimeError(
            f"native extension directory is missing: {extension_dir}; build this checkout"
        )
    sys.path.insert(0, str(extension_dir))
    sys.path.insert(0, str(repository / "python"))
    return importlib.import_module("bionetgen._bionetgen_cpp")


def _network(cpp):
    model = cpp.parse_string(MODEL)
    return model, cpp.generate_network(model)


def _molecule_total(species_names: list[str], values, molecule_type: str) -> float:
    if len(species_names) != len(values):
        raise ValueError(
            "species and population vectors have different lengths: "
            f"{len(species_names)} != {len(values)}"
        )
    return sum(
        float(value) * species_name.count(f"{molecule_type}(")
        for species_name, value in zip(species_names, values)
    )


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    cpp = _load_native_extension(repository)
    source_commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    extension_path = Path(cpp.__file__).resolve()
    extension_sha256 = hashlib.sha256(extension_path.read_bytes()).hexdigest()
    model_sha256 = hashlib.sha256(MODEL.encode("utf-8")).hexdigest()
    print(f"source_checkout_commit={source_commit}", flush=True)
    print(f"native_extension={extension_path}", flush=True)
    print(f"native_extension_sha256={extension_sha256}", flush=True)
    print(
        "native_source_build_binding=UNVERIFIED "
        "(source commit and extension identity are reported separately)",
        flush=True,
    )
    print(f"model_sha256={model_sha256}", flush=True)

    ode_model, ode_network = _network(cpp)
    ode = cpp.simulate_ode(ode_model, ode_network, t_end=20.0, n_steps=20)
    observable = [float(value) for value in ode["observables"]["rib_elong"]]
    ode_species = ode_network.species_names
    ode_mrna_totals = [
        _molecule_total(ode_species, row, "mrna") for row in ode["concentrations"]
    ]
    ode_ribosome_totals = [
        _molecule_total(ode_species, row, "ribosome") for row in ode["concentrations"]
    ]

    ssa_model, ssa_network = _network(cpp)
    ssa = cpp.simulate_ssa(ssa_model, ssa_network, t_end=20.0, n_steps=20, seed=21001)
    ssa_species = ssa_network.species_names
    ssa_mrna_totals = [
        _molecule_total(ssa_species, row, "mrna") for row in ssa["concentrations"]
    ]
    ssa_ribosome_totals = [
        _molecule_total(ssa_species, row, "ribosome") for row in ssa["concentrations"]
    ]

    failures = []
    if min(observable) < -1e-8 or max(observable) > 1.0 + 1e-8:
        failures.append("ODE rib_elong is outside the conserved [0, 1] bound")
    if any(abs(total - 1.0) > 1e-8 for total in ssa_mrna_totals):
        failures.append("SSA mRNA population is not conserved at seed 21001")
    if any(abs(total - 5.0) > 1e-8 for total in ssa_ribosome_totals):
        failures.append("SSA ribosome population is not conserved at seed 21001")

    print(
        "ode_rib_elong_range="
        f"[{min(observable):.12g}, {max(observable):.12g}] expected=[0, 1]"
    )
    print(
        "ode_conserved_totals="
        f"mrna[{min(ode_mrna_totals):.12g}, {max(ode_mrna_totals):.12g}] "
        f"ribosome[{min(ode_ribosome_totals):.12g}, {max(ode_ribosome_totals):.12g}]"
    )
    print(
        "ssa_seed=21001_population_ranges="
        f"mrna[{min(ssa_mrna_totals):.12g}, {max(ssa_mrna_totals):.12g}] "
        f"ribosome[{min(ssa_ribosome_totals):.12g}, {max(ssa_ribosome_totals):.12g}] "
        "expected=[1, 1] and [5, 5]"
    )

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: finite-network TotalRate invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
