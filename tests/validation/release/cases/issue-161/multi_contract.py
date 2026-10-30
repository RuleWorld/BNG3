"""Independent source-authored semantic contracts for Issue 161 fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from scripts.cross_validate import diff_structural_xml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


MULTI_SEMANTIC_SECTIONS = (
    "listOfCompartments",
    "listOfParameters",
    "listOfSpeciesTypes",
    "listOfSpecies",
    "listOfReactions",
)
SOURCE_SEMANTICS = {
    "test_write_sbml_multi.bngl": {
        "sha256": "226d9719593f806eb766c1641b9815675e6b98590a6a6f264719b7c7f7c3e13b",
        "molecules": {"R": ["l", "l"], "L": ["r", "r", "r"]},
        "seeds": {"R(l,l)": 300.0, "L(r,r,r)": 1200.0},
        "species": {
            "R(l,l)",
            "L(r,r,r)",
            "R(l)",
            "R(l!1).L(r!1,r,r)",
            "L(r,r,r!+)",
            "R(l!1).L(r!1,r,r!+)",
        },
        "bindings": {
            "R(l,l)": {("R", "l", 1, "unbound"), ("R", "l", 2, "unbound")},
            "L(r,r,r)": {
                ("L", "r", 1, "unbound"),
                ("L", "r", 2, "unbound"),
                ("L", "r", 3, "unbound"),
            },
            "R(l)": {("R", "l", 1, "unbound"), ("R", "l", 2, "either")},
            "R(l!1).L(r!1,r,r)": {
                ("R", "l", 2, "either"),
                ("L", "r", 2, "unbound"),
                ("L", "r", 3, "unbound"),
            },
            "L(r,r,r!+)": {
                ("L", "r", 1, "unbound"),
                ("L", "r", 2, "unbound"),
                ("L", "r", 3, "bound"),
            },
            "R(l!1).L(r!1,r,r!+)": {
                ("R", "l", 2, "either"),
                ("L", "r", 2, "unbound"),
                ("L", "r", 3, "bound"),
            },
        },
        "reactions": {"RR1", "RR1r", "RR2", "RR2r"},
        "stoichiometry": {
            "RR1": ({"R(l)", "L(r,r,r)"}, {"R(l!1).L(r!1,r,r)"}),
            "RR1r": ({"R(l!1).L(r!1,r,r)"}, {"R(l)", "L(r,r,r)"}),
            "RR2": ({"R(l)", "L(r,r,r!+)"}, {"R(l!1).L(r!1,r,r!+)"}),
            "RR2r": (
                {"R(l!1).L(r!1,r,r!+)"},
                {"R(l)", "L(r,r,r!+)"},
            ),
        },
        "rate_operator": "times",
        "parameters": {"kon": "0.001", "koff": "0.1"},
        "states": {},
        "kinetics": {
            "RR1": {"kon", "RR1_R1", "S2"},
            "RR1r": {"koff", "RR1_P1"},
            "RR2": {"kon", "RR1_R1", "RR2_R2"},
            "RR2r": {"koff", "RR2_P1"},
        },
    },
    "state_bearing_binding_refusal.bngl": {
        "sha256": "57b53ca1d4aa9708aa8722a363142ec05188ccb982cd4d253bb71bcd59ba9627",
        "molecules": {"R": ["l"], "L": ["r"]},
        "features": {("R", "l", 1): {"u", "p"}},
        "seeds": {"R(l~u)": 100.0, "L(r)": 100.0},
        "species": {
            "R(l~u)",
            "L(r)",
            "R(l~u!1).L(r!1)",
        },
        "bindings": {
            "R(l~u)": {("R", "l", 1, "unbound")},
            "L(r)": {("L", "r", 1, "unbound")},
            "R(l~u!1).L(r!1)": set(),
        },
        "reactions": {"RR1", "RR1r"},
        "stoichiometry": {
            "RR1": ({"R(l~u)", "L(r)"}, {"R(l~u!1).L(r!1)"}),
            "RR1r": ({"R(l~u!1).L(r!1)"}, {"R(l~u)", "L(r)"}),
        },
        "rate_operator": "times",
        "parameters": {},
        "states": {
            ("R(l~u)", "R", "l", "u"),
            ("R(l~u!1).L(r!1)", "R", "l", "u"),
        },
        "kinetics": {
            "RR1": {"0.01", "S1", "S2"},
            "RR1r": {"0.1", "RR1_P1"},
        },
    },
}


def _local_attribute(element: ET.Element, name: str) -> str | None:
    return next(
        (
            value
            for key, value in element.attrib.items()
            if key.rsplit("}", 1)[-1] == name
        ),
        None,
    )


def _set_local_attribute(element: ET.Element, name: str, value: str) -> None:
    for key in list(element.attrib):
        if key.rsplit("}", 1)[-1] == name:
            element.set(key, value)
            return
    element.set(name, value)


def _xml_mutation_controls(xml_path: Path) -> dict:
    """Prove the structural comparator detects each supported semantic mutation."""

    def elements(tree: ET.ElementTree, tag: str) -> list[ET.Element]:
        return [
            element
            for element in tree.getroot().iter()
            if element.tag.rsplit("}", 1)[-1] == tag
        ]

    def mutate(tree: ET.ElementTree, name: str) -> bool:
        if name == "bond":
            nodes = elements(tree, "inSpeciesTypeBond")
            values = [
                _local_attribute(node, "id")
                for node in elements(tree, "speciesTypeComponentIndex")
            ]
            if not nodes:
                return False
            current = _local_attribute(nodes[0], "bindingSite2")
            alternative = next((value for value in values if value != current), None)
            if alternative is None:
                return False
            _set_local_attribute(nodes[0], "bindingSite2", alternative)
            return True
        if name == "state":
            nodes = elements(tree, "speciesFeatureValue")
            values = {
                _local_attribute(node, "id")
                for node in elements(tree, "possibleSpeciesFeatureValue")
            }
            if not nodes:
                return False
            current = _local_attribute(nodes[0], "value")
            alternative = next((value for value in values if value != current), None)
            if alternative is None:
                return False
            _set_local_attribute(nodes[0], "value", alternative)
            return True
        if name == "component_map_target":
            nodes = elements(tree, "speciesTypeComponentMapInProduct")
            if not nodes:
                return False
            current = _local_attribute(nodes[0], "productComponent")
            alternative = next(
                (
                    _local_attribute(node, "productComponent")
                    for node in nodes[1:]
                    if _local_attribute(node, "productComponent") != current
                ),
                None,
            )
            if alternative is None:
                instances = [
                    _local_attribute(node, "id")
                    for node in elements(tree, "speciesTypeInstance")
                ]
                alternative = next(
                    (value for value in instances if value != current), None
                )
            if alternative is None:
                return False
            _set_local_attribute(nodes[0], "productComponent", alternative)
            return True
        if name == "initial_quantity":
            nodes = elements(tree, "species")
            if not nodes:
                return False
            attribute = next(
                (
                    key
                    for key in nodes[0].attrib
                    if key.rsplit("}", 1)[-1]
                    in {"initialAmount", "initialConcentration"}
                ),
                None,
            )
            if attribute is None:
                return False
            _set_local_attribute(
                nodes[0],
                attribute.rsplit("}", 1)[-1],
                repr(float(nodes[0].attrib[attribute]) + 1),
            )
            return True
        if name == "compartment_volume":
            nodes = elements(tree, "compartment")
            if not nodes or _local_attribute(nodes[0], "size") is None:
                return False
            current = _local_attribute(nodes[0], "size")
            _set_local_attribute(nodes[0], "size", repr(float(current) + 1))
            return True
        if name == "reaction_rate":
            nodes = elements(tree, "parameter")
            if nodes and _local_attribute(nodes[0], "value") is not None:
                current = _local_attribute(nodes[0], "value")
                _set_local_attribute(nodes[0], "value", repr(float(current) * 2 + 0.01))
                return True
            # The state-bearing control uses literal kinetic-law values rather
            # than named parameters, so mutate its MathML numeric rate directly.
            constants = elements(tree, "cn")
            if not constants or not (constants[0].text or "").strip():
                return False
            constants[0].text = repr(float(constants[0].text.strip()) * 2 + 0.01)
            return True
        raise ValueError(f"unknown Issue 161 mutation control {name}")

    controls = {}
    with tempfile.TemporaryDirectory(prefix="bng3-issue-161-mutations-") as raw:
        root = Path(raw)
        for name in (
            "bond",
            "state",
            "component_map_target",
            "initial_quantity",
            "compartment_volume",
            "reaction_rate",
        ):
            modified = ET.parse(xml_path)
            if not mutate(modified, name):
                controls[name] = {"status": "not-applicable"}
                continue
            path = root / f"{name}.xml"
            modified.write(path, encoding="utf-8", xml_declaration=True)
            difference = diff_structural_xml(
                xml_path, path, sections=MULTI_SEMANTIC_SECTIONS
            )
            controls[name] = {
                "status": "pass" if not difference.equal else "fail",
                "difference_summary": difference.summary(),
            }
    return controls


def _source_semantic_contract(source: Path, xml_path: Path) -> dict:
    """Check SBML against a fixture-scoped contract derived from its BNGL."""
    manifest = SOURCE_SEMANTICS.get(source.name)
    if manifest is None or _sha256(source) != manifest["sha256"]:
        return {"status": "error", "error": "source contract or BNGL hash mismatch"}

    root = ET.parse(xml_path).getroot()

    def elements(tag: str) -> list[ET.Element]:
        return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == tag]

    def attribute(node: ET.Element, name: str) -> str | None:
        return _local_attribute(node, name)

    problems = []
    base_types = {
        attribute(node, "name"): node
        for node in elements("speciesType")
        if attribute(node, "name") in manifest["molecules"]
    }
    actual_molecules = {
        name: [
            attribute(node, "name")
            for node in base_types[name].iter()
            if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
        ]
        for name in base_types
    }
    if actual_molecules != manifest["molecules"]:
        problems.append(f"molecule sites differ: {actual_molecules}")
    binding_site_types = {
        attribute(node, "id"): node for node in elements("bindingSiteSpeciesType")
    }
    actual_features = {}
    for molecule, base_type in base_types.items():
        site_ordinals = {}
        for component in base_type.iter():
            if component.tag.rsplit("}", 1)[-1] != "speciesTypeInstance":
                continue
            site_name = attribute(component, "name")
            site_ordinals[site_name] = site_ordinals.get(site_name, 0) + 1
            binding_type = binding_site_types.get(attribute(component, "speciesType"))
            values = (
                {
                    attribute(value, "name")
                    for value in binding_type.iter()
                    if value.tag.rsplit("}", 1)[-1] == "possibleSpeciesFeatureValue"
                }
                if binding_type is not None
                else set()
            )
            if values:
                actual_features[(molecule, site_name, site_ordinals[site_name])] = (
                    values
                )
    if actual_features != manifest.get("features", {}):
        problems.append(f"site feature values differ: {actual_features}")

    species = {attribute(node, "name"): node for node in elements("species")}
    if set(species) != manifest["species"]:
        problems.append(f"species patterns differ: {sorted(species)}")
    for name, amount in manifest["seeds"].items():
        node = species.get(name)
        if node is None or attribute(node, "initialAmount") is None:
            problems.append(f"missing initial amount for {name}")
        elif float(attribute(node, "initialAmount")) != amount:
            problems.append(f"initial amount differs for {name}")

    compartments = elements("compartment")
    if len(compartments) != 1 or attribute(compartments[0], "size") != "1":
        problems.append("expected one unit-volume compartment")
    elif any(
        attribute(node, "compartment") != attribute(compartments[0], "id")
        or attribute(node, "hasOnlySubstanceUnits") != "true"
        for node in species.values()
    ):
        problems.append("species amount units or compartment differ")

    type_by_id = {
        attribute(node, "id"): attribute(node, "name")
        for node in elements("speciesType")
        if attribute(node, "id")
    }
    instance_by_id = {
        attribute(node, "id"): type_by_id.get(attribute(node, "speciesType"))
        for node in elements("speciesTypeInstance")
        if attribute(node, "id")
    }
    instances_by_id = {
        attribute(node, "id"): node for node in elements("speciesTypeInstance")
    }
    base_components = {
        attribute(node, "id"): (attribute(node, "name"), attribute(node, "speciesType"))
        for name in manifest["molecules"]
        for node in base_types[name].iter()
        if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
    }
    base_component_molecules = {
        attribute(node, "id"): name
        for name in manifest["molecules"]
        for node in base_types[name].iter()
        if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
    }
    component_indexes = {
        attribute(node, "id"): node for node in elements("speciesTypeComponentIndex")
    }

    def site_identity(component_id: str | None) -> tuple[str, str, int] | None:
        index = component_indexes.get(component_id)
        if index is None:
            molecule = base_component_molecules.get(component_id)
            base_component_id = component_id
        else:
            parent = instances_by_id.get(attribute(index, "identifyingParent"))
            molecule = (
                type_by_id.get(attribute(parent, "speciesType"))
                if parent is not None
                else None
            )
            base_component_id = attribute(index, "component")
        component = base_components.get(base_component_id)
        if molecule is None or component is None:
            return None
        site_name = component[0]
        candidates = [
            node
            for node in base_types[molecule].iter()
            if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
            and attribute(node, "name") == site_name
        ]
        ordinal = next(
            (
                position
                for position, node in enumerate(candidates, 1)
                if attribute(node, "id") == base_component_id
            ),
            0,
        )
        return (molecule, site_name, ordinal) if ordinal else None

    for pattern, species_node in species.items():
        bindings = set()
        unresolved_bindings = []
        for outward in species_node.iter():
            if outward.tag.rsplit("}", 1)[-1] != "outwardBindingSite":
                continue
            identity = site_identity(attribute(outward, "component"))
            if identity is not None:
                bindings.add((*identity, attribute(outward, "bindingStatus")))
            else:
                unresolved_bindings.append(attribute(outward, "component"))
        if bindings != manifest["bindings"][pattern]:
            problems.append(
                f"binding sites differ for {pattern}: {bindings}; unresolved={unresolved_bindings}"
            )

    expected_bond = {("R", "l", 1), ("L", "r", 1)}
    complex_types = [
        node
        for node in elements("speciesType")
        if attribute(node, "name") not in manifest["molecules"]
    ]
    expected_complex_count = len(
        {pattern for pattern in manifest["species"] if "." in pattern}
    )
    if len(complex_types) != expected_complex_count:
        problems.append(f"complex type count differs: {len(complex_types)}")
    for complex_type in complex_types:
        complex_instances = {
            attribute(node, "id"): type_by_id.get(attribute(node, "speciesType"))
            for node in complex_type.iter()
            if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
        }
        indexes = {
            attribute(node, "id"): node
            for node in complex_type.iter()
            if node.tag.rsplit("}", 1)[-1] == "speciesTypeComponentIndex"
        }
        observed_bonds = set()
        for bond in complex_type.iter():
            if bond.tag.rsplit("}", 1)[-1] != "inSpeciesTypeBond":
                continue
            for side in ("bindingSite1", "bindingSite2"):
                index = indexes.get(attribute(bond, side))
                if index is None:
                    observed_bonds.add(("invalid", "invalid", -1))
                    continue
                parent = attribute(index, "identifyingParent")
                molecule = complex_instances.get(parent)
                base_component = base_components.get(attribute(index, "component"))
                if base_component is None:
                    observed_bonds.add(("invalid", "invalid", -1))
                    continue
                site_name, _binding_type = base_component
                base_node = base_types[molecule]
                # Same-named sites are ordered by their authored component IDs.
                authored_id = attribute(index, "component")
                site_instances = [
                    node
                    for node in base_node.iter()
                    if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
                    and attribute(node, "name") == site_name
                ]
                site_number = next(
                    (
                        position
                        for position, node in enumerate(site_instances, 1)
                        if attribute(node, "id") == authored_id
                    ),
                    0,
                )
                observed_bonds.add((molecule, site_name, site_number))
        if observed_bonds != expected_bond:
            problems.append(f"bond graph differs: {observed_bonds}")

    observed_states = set()
    feature_types = {
        attribute(node, "id"): attribute(node, "name")
        for node in elements("speciesFeatureType")
    }
    feature_values = {
        attribute(node, "id"): attribute(node, "name")
        for node in elements("possibleSpeciesFeatureValue")
    }
    for species_name, species_node in species.items():
        for feature in species_node.iter():
            if feature.tag.rsplit("}", 1)[-1] != "speciesFeature":
                continue
            component = attribute(feature, "component")
            molecule = None
            component_node = instances_by_id.get(component)
            if component_node is None:
                component_index = next(
                    (
                        node
                        for node in elements("speciesTypeComponentIndex")
                        if attribute(node, "id") == component
                    ),
                    None,
                )
                if component_index is not None:
                    component_node = instances_by_id.get(
                        attribute(component_index, "identifyingParent")
                    )
            if component_node is not None:
                molecule = type_by_id.get(attribute(component_node, "speciesType"))
                molecule = molecule or base_component_molecules.get(component)
            for value in feature.iter():
                if value.tag.rsplit("}", 1)[-1] != "speciesFeatureValue":
                    continue
                observed_states.add(
                    (
                        species_name,
                        molecule,
                        feature_types.get(attribute(feature, "speciesFeatureType")),
                        feature_values.get(attribute(value, "value")),
                    )
                )
    expected_states = {
        (species_name, molecule, site, value)
        for species_name, molecule, site, value in manifest["states"]
    }
    if observed_states != expected_states:
        problems.append(f"site states differ: {observed_states}")

    parameters = {
        attribute(node, "id"): attribute(node, "value")
        for node in elements("parameter")
    }
    if parameters != manifest["parameters"]:
        problems.append(f"rate parameters differ: {parameters}")
    actual_maps = {}
    actual_stoichiometry = {}
    actual_operators = {}
    for reaction in elements("reaction"):
        reaction_id = attribute(reaction, "id")
        pairs = []
        participant_names = {}
        for direction in ("listOfReactants", "listOfProducts"):
            participant_list = next(
                (
                    node
                    for node in reaction.iter()
                    if node.tag.rsplit("}", 1)[-1] == direction
                ),
                None,
            )
            participants = set()
            if participant_list is not None:
                for ref in participant_list.iter():
                    if ref.tag.rsplit("}", 1)[-1] != "speciesReference":
                        continue
                    referenced_id = attribute(ref, "species")
                    participant = next(
                        (
                            node
                            for node in species.values()
                            if attribute(node, "id") == referenced_id
                        ),
                        None,
                    )
                    if participant is not None:
                        participants.add(attribute(participant, "name"))
            participant_names[direction] = participants
        actual_stoichiometry[reaction_id] = (
            participant_names["listOfReactants"],
            participant_names["listOfProducts"],
        )
        apply_node = next(
            (
                node
                for node in reaction.iter()
                if node.tag.rsplit("}", 1)[-1] == "apply"
            ),
            None,
        )
        actual_operators[reaction_id] = (
            list(apply_node)[0].tag.rsplit("}", 1)[-1]
            if apply_node is not None and list(apply_node)
            else None
        )
        for mapping in reaction.iter():
            if mapping.tag.rsplit("}", 1)[-1] != "speciesTypeComponentMapInProduct":
                continue
            source_component = attribute(mapping, "reactantComponent")
            source_type = type_by_id.get(source_component) or instance_by_id.get(
                source_component
            )
            target_id = attribute(mapping, "productComponent")
            target_type = type_by_id.get(target_id) or instance_by_id.get(target_id)
            pairs.append((source_type, target_type))
        actual_maps[reaction_id] = pairs
    if set(actual_maps) != manifest["reactions"]:
        problems.append(f"reaction ids differ: {sorted(actual_maps)}")
    if actual_stoichiometry != manifest["stoichiometry"]:
        problems.append(f"reaction participants differ: {actual_stoichiometry}")
    if any(
        operator != manifest["rate_operator"] for operator in actual_operators.values()
    ):
        problems.append(f"reaction rate operators differ: {actual_operators}")
    if any(sorted(pairs) != [("L", "L"), ("R", "R")] for pairs in actual_maps.values()):
        problems.append(f"reaction component maps differ: {actual_maps}")

    actual_kinetics = {}
    for reaction in elements("reaction"):
        actual_kinetics[attribute(reaction, "id")] = {
            text.strip()
            for node in reaction.iter()
            if node.tag.rsplit("}", 1)[-1] in {"ci", "cn"}
            and (text := (node.text or "").strip())
        }
    normalized_kinetics = {
        reaction_id: {
            str(float(token)) if _is_number(token) else token for token in tokens
        }
        for reaction_id, tokens in actual_kinetics.items()
    }
    normalized_expected = {
        reaction_id: {
            str(float(token)) if _is_number(token) else token for token in tokens
        }
        for reaction_id, tokens in manifest["kinetics"].items()
    }
    if normalized_kinetics != normalized_expected:
        problems.append(f"reaction rate laws differ: {normalized_kinetics}")

    return {
        "status": "pass" if not problems else "fail",
        "source_sha256": manifest["sha256"],
        "checks": [
            "molecule sites",
            "species patterns",
            "seed amounts",
            "volume",
            "bond graphs",
            "site states",
            "component maps",
            "rate parameters",
            "reaction rate laws",
        ],
        "problems": problems,
    }


def _source_contract_mutation_controls(source: Path, xml_path: Path) -> dict:
    """Require the source contract to reject deleted or rewired Multi structure."""
    controls = {}
    with tempfile.TemporaryDirectory(
        prefix="bng3-issue-161-contract-mutations-"
    ) as raw:
        directory = Path(raw)
        for name in ("missing_complex_type", "missing_bond", "wrong_bond_endpoint"):
            tree = ET.parse(xml_path)
            root = tree.getroot()
            parent_by_child = {
                child: parent for parent in root.iter() for child in list(parent)
            }
            if name == "missing_complex_type":
                target = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "speciesType"
                        and _local_attribute(node, "name")
                        not in SOURCE_SEMANTICS[source.name]["molecules"]
                    ),
                    None,
                )
                if target is not None:
                    parent_by_child[target].remove(target)
            else:
                bond = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "inSpeciesTypeBond"
                    ),
                    None,
                )
                if bond is not None and name == "missing_bond":
                    parent_by_child[bond].remove(bond)
                elif bond is not None:
                    current = _local_attribute(bond, "bindingSite2")
                    alternatives = [
                        _local_attribute(node, "id")
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "speciesTypeComponentIndex"
                    ]
                    alternative = next(
                        (value for value in alternatives if value != current), None
                    )
                    if alternative is not None:
                        _set_local_attribute(bond, "bindingSite2", alternative)
            mutated = directory / f"{name}.xml"
            tree.write(mutated, encoding="utf-8", xml_declaration=True)
            result = _source_semantic_contract(source, mutated)
            controls[name] = {
                "status": "pass" if result["status"] == "fail" else "fail",
                "contract_status_after_mutation": result["status"],
                "problems": result.get("problems", []),
            }
    return controls


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
