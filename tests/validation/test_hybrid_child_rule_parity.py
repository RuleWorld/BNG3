"""Focused native BNG3 vs pinned BNG2 checks for hybrid rule refinement.

This checks the existing hybrid_test source model. That fixture has no explicit
component states, so the assertions cover child transitions, site/bond
structure, effective rates, and observable automorphisms only.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from tests.validation import oracle_perl
from tests.validation.strict import require_oracle

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tests" / "validation" / "Validate" / "hybrid_test.bngl"
EXPECTED_CHILDREN = {
    "_R2_v1": ("kp1", 3.0),
    "_R2_v2": ("kp1", 6.0),
    "_R3_v1": ("kp2", 1.0),
    "_R3_v2": ("kp2", 2.0),
    "_R4_v1": ("kp2", 1.0),
    "_R4_v2": ("kp2", 2.0),
}


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _find(element: ET.Element, name: str) -> ET.Element:
    found = next((item for item in element.iter() if _tag(item) == name), None)
    assert found is not None, f"missing {name} in {element.get('id')}"
    return found


def _pattern_signature(pattern: ET.Element) -> tuple:
    component_ids: dict[str, tuple[int, int]] = {}
    molecules = []
    for molecule_index, molecule in enumerate(
        item for item in pattern.iter() if _tag(item) == "Molecule"
    ):
        components = []
        for component_index, component in enumerate(
            item for item in molecule.iter() if _tag(item) == "Component"
        ):
            component_ids[component.get("id", "")] = (molecule_index, component_index)
            states = tuple(
                state.get("name") for state in component if _tag(state) == "State"
            )
            components.append(
                (component.get("name"), component.get("numberOfBonds"), states)
            )
        molecules.append((molecule.get("name"), tuple(components)))

    bonds = []
    for bond in (item for item in pattern.iter() if _tag(item) == "Bond"):
        endpoints = (
            component_ids[bond.get("site1", "")],
            component_ids[bond.get("site2", "")],
        )
        bonds.append(tuple(sorted(endpoints)))
    return tuple(molecules), tuple(sorted(bonds))


def _rule_signature(rule: ET.Element) -> tuple:
    reactants = _find(rule, "ListOfReactantPatterns")
    products = _find(rule, "ListOfProductPatterns")
    return (
        tuple(
            sorted(
                _pattern_signature(pattern)
                for pattern in reactants
                if _tag(pattern) == "ReactantPattern"
            )
        ),
        tuple(
            sorted(
                _pattern_signature(pattern)
                for pattern in products
                if _tag(pattern) == "ProductPattern"
            )
        ),
    )


def _reaction_rules(path: Path) -> list[ET.Element]:
    root = ET.parse(path).getroot()
    return [item for item in root.iter() if _tag(item) == "ReactionRule"]


def _rate_value(rule: ET.Element, parameters: dict[str, float]) -> float:
    constants = [item for item in rule.iter() if _tag(item) == "RateConstant"]
    assert len(constants) == 1, f"expected one rate constant in {rule.get('name')}"
    return parameters[constants[0].get("value", "")]


def _parameters(path: Path) -> dict[str, float]:
    root = ET.parse(path).getroot()
    return {
        item.get("id", ""): float(item.get("value", "nan"))
        for item in root.iter()
        if _tag(item) == "Parameter" and item.get("value") is not None
    }


def _run_exports(bng_cpp: Path, tmp_path: Path) -> tuple[Path, Path]:
    bng2 = oracle_perl._bng2_path()
    require_oracle(bng2 is not None, "pinned BNG2 unavailable (set BNG2_PERL)")
    assert bng2 is not None
    perl = os.environ.get("PERL", "perl")
    native_dir = tmp_path / "native"
    oracle_dir = tmp_path / "bng2"
    native_dir.mkdir()
    oracle_dir.mkdir()
    native_model = native_dir / SOURCE.name
    oracle_model = oracle_dir / SOURCE.name
    native_model.write_bytes(SOURCE.read_bytes())
    oracle_model.write_bytes(SOURCE.read_bytes())

    native = subprocess.run(
        [str(bng_cpp), str(native_model)],
        cwd=native_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert native.returncode == 0, native.stderr or native.stdout
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    oracle = subprocess.run(
        [perl, str(bng2), "--outdir", str(oracle_dir), str(oracle_model)],
        cwd=oracle_dir,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert oracle.returncode == 0, oracle.stderr or oracle.stdout

    native_xml = native_dir / "hybrid_test_hpp.xml"
    oracle_xml = oracle_dir / "hybrid_test_hpp.xml"
    assert native_xml.is_file() and native_xml.stat().st_size, native.stderr
    assert oracle_xml.is_file() and oracle_xml.stat().st_size, oracle.stderr
    return oracle_xml, native_xml


def test_hybrid_children_preserve_bng2_transitions_rates_and_observable_symmetry(
    bng_cpp: Path, tmp_path: Path
):
    oracle_xml, native_xml = _run_exports(bng_cpp, tmp_path)
    oracle_parameters = _parameters(oracle_xml)
    native_parameters = _parameters(native_xml)
    oracle_rules = _reaction_rules(oracle_xml)
    native_rules = _reaction_rules(native_xml)

    oracle_children = {
        rule.get("name"): rule
        for rule in oracle_rules
        if rule.get("name") in EXPECTED_CHILDREN
    }
    assert set(oracle_children) == set(EXPECTED_CHILDREN)

    expected_by_transition = {}
    for name, (base_parameter, factor) in EXPECTED_CHILDREN.items():
        rule = oracle_children[name]
        signature = _rule_signature(rule)
        assert signature not in expected_by_transition
        expected_by_transition[signature] = (base_parameter, factor)
        # Establish the pinned BNG2 rate law itself before using it as a parity
        # oracle for the C++ exporter.
        assert _rate_value(rule, oracle_parameters) == pytest.approx(
            oracle_parameters[base_parameter] * factor, rel=1e-12
        )

    native_candidates = [
        rule
        for rule in native_rules
        if any(
            molecule.get("name") in {"L", "R"}
            for item in rule.iter()
            if _tag(item) == "ListOfProductPatterns"
            for molecule in item.iter()
            if _tag(molecule) == "Molecule"
        )
        and any(
            _tag(item) == "Bond" for item in _find(rule, "ListOfProductPatterns").iter()
        )
    ]
    assert len(native_candidates) == len(EXPECTED_CHILDREN)
    assert len({_rule_signature(rule) for rule in native_candidates}) == len(
        EXPECTED_CHILDREN
    )

    native_base_rates = {
        "kp1": native_parameters["kp1"],
        "kp2": native_parameters["kp2"],
    }
    observed = {}
    for rule in native_candidates:
        signature = _rule_signature(rule)
        assert (
            signature in expected_by_transition
        ), f"unexpected hybrid transition {rule.get('name')}"
        base_parameter, factor = expected_by_transition[signature]
        observed[signature] = (
            _rate_value(rule, native_parameters) / native_base_rates[base_parameter]
        )
        assert observed[signature] == pytest.approx(factor, rel=1e-12)
    assert set(observed) == set(expected_by_transition)

    for name, automorphisms in (("Rfree", 2), ("Lfree", 6)):
        oracle_pattern = _observable_pattern(oracle_xml, name)
        native_pattern = _observable_pattern(native_xml, name)
        assert int(oracle_pattern.get("automorphisms", "1")) == automorphisms
        assert int(native_pattern.get("automorphisms", "1")) == automorphisms
        assert _pattern_signature(oracle_pattern) == _pattern_signature(native_pattern)


def _observable_pattern(path: Path, name: str) -> ET.Element:
    root = ET.parse(path).getroot()
    observable = next(
        item
        for item in root.iter()
        if _tag(item) == "Observable" and item.get("name") == name
    )
    patterns = [item for item in observable.iter() if _tag(item) == "Pattern"]
    assert patterns
    return patterns[0]
