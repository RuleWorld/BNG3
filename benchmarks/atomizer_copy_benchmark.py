#!/usr/bin/env python3
"""Benchmark Atomizer structure copies against the deepcopy baseline."""

from __future__ import annotations

import argparse
import copy
import json
import platform
import statistics
import sys
import timeit
import tracemalloc
from pathlib import Path
from typing import Callable, Dict, Iterable, Tuple

from bionetgen.atomizer.modern import (
    Component as ModernComponent,
    Molecule as ModernMolecule,
    Species as ModernSpecies,
)
from bionetgen.atomizer.utils import smallStructures, structures


def _modern_component() -> ModernComponent:
    return ModernComponent(
        "site",
        "site",
        bonds=[1, 2, 3, 4],
        states=["P", "U", "0", "active"],
    )


def _modern_species() -> ModernSpecies:
    species = ModernSpecies()
    for molecule_index in range(8):
        molecule = ModernMolecule(f"M{molecule_index}")
        for component_index in range(6):
            molecule.components.append(
                ModernComponent(
                    f"site{component_index}",
                    bonds=[1, 2],
                    states=["P", "U", "0"],
                )
            )
        species.molecules.append(molecule)
    species.bond_numbers = list(range(1, 16))
    species.bonds = [(f"M{index}_site0", f"M{index + 1}_site0") for index in range(7)]
    return species


def _legacy_component() -> structures.Component:
    component = structures.Component("site")
    component.bonds = ["1", "2", "3", "4"]
    component.states = ["P", "U", "0", "active"]
    component.activeState = "P"
    return component


def _legacy_molecule() -> structures.Molecule:
    molecule = structures.Molecule("M")
    for component_index in range(6):
        component = _legacy_component()
        component.name = f"site{component_index}"
        molecule.components.append(component)
    return molecule


def _small_component() -> smallStructures.Component:
    component = smallStructures.Component("site", "site")
    component.bonds = ["1", "2", "3", "4"]
    component.states = ["P", "U", "0", "active"]
    component.activeState = "P"
    return component


def _small_species() -> smallStructures.Species:
    species = smallStructures.Species()
    for molecule_index in range(8):
        molecule = smallStructures.Molecule(f"M{molecule_index}", str(molecule_index))
        for component_index in range(6):
            component = _small_component()
            component.name = f"site{component_index}"
            molecule.components.append(component)
        species.molecules.append(molecule)
    return species


def _fixtures() -> Iterable[Tuple[str, object]]:
    return (
        ("modern_component", _modern_component()),
        ("modern_species", _modern_species()),
        ("legacy_component", _legacy_component()),
        ("legacy_molecule", _legacy_molecule()),
        ("small_component", _small_component()),
        ("small_species", _small_species()),
    )


def _assert_copy_isolated(label: str, value: object) -> None:
    copied = value.copy()  # type: ignore[attr-defined]
    if "component" in label:
        copied.bonds.append("copy")  # type: ignore[attr-defined]
        assert value.bonds != copied.bonds  # type: ignore[attr-defined]
        return

    if "species" in label:
        copied.molecules[0].components[0].bonds.append("copy")  # type: ignore[attr-defined]
        assert value.molecules[0].components[0].bonds != (  # type: ignore[attr-defined]
            copied.molecules[0].components[0].bonds
        )
        return

    copied.components[0].bonds.append("copy")  # type: ignore[attr-defined]
    assert value.components[0].bonds != copied.components[0].bonds  # type: ignore[attr-defined]


def _measure(
    operation: Callable[[object], object],
    value: object,
    iterations: int,
    repeats: int,
) -> Dict[str, float]:
    timer = timeit.Timer(
        "operation(value)", globals={"operation": operation, "value": value}
    )
    samples = timer.repeat(repeat=repeats, number=iterations)

    tracemalloc.start()
    timer.timeit(number=iterations)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "min_us_per_copy": min(samples) * 1e6 / iterations,
        "median_us_per_copy": statistics.median(samples) * 1e6 / iterations,
        "peak_bytes": float(peak_bytes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("--iterations and --repeats must be positive")

    results = []
    for label, value in _fixtures():
        _assert_copy_isolated(label, value)
        results.append(
            {
                "case": label,
                "copy": _measure(
                    lambda item: item.copy(), value, args.iterations, args.repeats
                ),
                "deepcopy_baseline": _measure(
                    copy.deepcopy, value, args.iterations, args.repeats
                ),
            }
        )

    payload = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "iterations": args.iterations,
        "repeats": args.repeats,
        "results": results,
    }
    output = json.dumps(payload, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
