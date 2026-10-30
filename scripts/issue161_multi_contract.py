"""Independent source-authored semantic contracts for Issue 161 fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from scripts.issue161_multi_expected import SOURCE_SEMANTICS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_manifest_for(source: Path) -> dict | None:
    digest = _sha256(source)
    return next(
        (
            manifest
            for manifest in SOURCE_SEMANTICS.values()
            if manifest["sha256"] == digest
        ),
        None,
    )


def sbml_validity(path: Path) -> dict:
    """Return libSBML consistency errors for source-contract eligibility."""
    import libsbml

    document = libsbml.readSBMLFromFile(str(path))
    if document is None:
        return {
            "status": "invalid",
            "severity_error_count": 1,
            "diagnostics": ["libSBML could not read the document"],
        }
    document.checkConsistency()
    diagnostics = []
    for index in range(document.getNumErrors()):
        error = document.getError(index)
        if error.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            diagnostics.append(
                {
                    "id": error.getErrorId(),
                    "line": error.getLine(),
                    "message": error.getMessage().strip().splitlines()[0],
                }
            )
    return {
        "status": "valid" if not diagnostics else "invalid",
        "severity_error_count": len(diagnostics),
        "diagnostics": diagnostics,
    }


def source_contract_eligible(
    reference_validity: dict,
    candidate_validity: dict,
    semantic_contract: dict,
    mutation_controls: dict,
) -> bool:
    """Allow a source contract to replace only an invalid reference document."""
    return bool(mutation_controls) and (
        reference_validity["status"] == "invalid"
        and candidate_validity["status"] == "valid"
        and semantic_contract["status"] == "pass"
        and all(control["status"] == "pass" for control in mutation_controls.values())
    )


MULTI_SEMANTIC_SECTIONS = (
    "listOfCompartments",
    "listOfParameters",
    "listOfSpeciesTypes",
    "listOfSpecies",
    "listOfReactions",
)


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
            from scripts.cross_validate import diff_structural_xml

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
    manifest = _source_manifest_for(source)
    if manifest is None:
        return {"status": "error", "error": "source contract or BNGL hash mismatch"}

    root = ET.parse(xml_path).getroot()

    def elements(tag: str) -> list[ET.Element]:
        return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == tag]

    def attribute(node: ET.Element, name: str) -> str | None:
        return _local_attribute(node, name)

    problems = []
    if (
        attribute(root, "level") != "3"
        or attribute(root, "version") != "1"
        or attribute(root, "required") != "true"
    ):
        problems.append("SBML Level 3 / Multi required package flags differ")
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
    missing_types = set(manifest["molecules"]) - set(base_types)
    if missing_types:
        problems.append(f"missing molecule species types: {sorted(missing_types)}")
        return {
            "status": "fail",
            "source_sha256": manifest["sha256"],
            "checks": ["molecule sites"],
            "problems": problems,
        }
    binding_site_types = {
        attribute(node, "id"): node for node in elements("bindingSiteSpeciesType")
    }
    actual_features = {}
    feature_occurrences = {}
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
                feature_occurrences[(molecule, site_name, site_ordinals[site_name])] = [
                    attribute(feature, "occur")
                    for feature in binding_type.iter()
                    if feature.tag.rsplit("}", 1)[-1] == "speciesFeatureType"
                ]
    if actual_features != manifest.get("features", {}):
        problems.append(f"site feature values differ: {actual_features}")
    if any(values != ["1"] for values in feature_occurrences.values()):
        problems.append(f"site feature occurrences differ: {feature_occurrences}")

    species = {attribute(node, "name"): node for node in elements("species")}
    if set(species) != manifest["species"]:
        problems.append(f"species patterns differ: {sorted(species)}")
    expected_amounts = {
        name: manifest["seeds"].get(name, 0.0) for name in manifest["species"]
    }
    for name, amount in expected_amounts.items():
        node = species.get(name)
        if node is None or attribute(node, "initialAmount") is None:
            problems.append(f"missing initial amount for {name}")
        elif float(attribute(node, "initialAmount")) != amount:
            problems.append(f"initial amount differs for {name}")

    compartments = elements("compartment")
    if (
        len(compartments) != 1
        or attribute(compartments[0], "size") != "1"
        or attribute(compartments[0], "spatialDimensions") != "3"
    ):
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
    complex_type_ids = {
        attribute(node, "id")
        for node in elements("speciesType")
        if attribute(node, "name") not in manifest["molecules"]
    }
    for pattern, species_node in species.items():
        type_id = attribute(species_node, "speciesType")
        if "." in pattern:
            expected_type = type_id in complex_type_ids
        else:
            expected_type = type_by_id.get(type_id) == pattern.split("(", 1)[0]
        if not expected_type:
            problems.append(f"species type assignment differs for {pattern}")
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
        bindings = []
        unresolved_bindings = []
        for outward in species_node.iter():
            if outward.tag.rsplit("}", 1)[-1] != "outwardBindingSite":
                continue
            identity = site_identity(attribute(outward, "component"))
            if identity is not None:
                bindings.append((*identity, attribute(outward, "bindingStatus")))
            else:
                unresolved_bindings.append(attribute(outward, "component"))
        if Counter(bindings) != Counter(manifest["bindings"][pattern]):
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
        if Counter(complex_instances.values()) != Counter({"R": 1, "L": 1}):
            problems.append(
                f"complex molecule composition differs: {complex_instances}"
            )
            if any(
                molecule not in base_types for molecule in complex_instances.values()
            ):
                continue
        indexes = {
            attribute(node, "id"): node
            for node in complex_type.iter()
            if node.tag.rsplit("}", 1)[-1] == "speciesTypeComponentIndex"
        }
        for instance_id, molecule in complex_instances.items():
            expected_components = Counter()
            expected_ordinals = {}
            for node in base_types[molecule].iter():
                if node.tag.rsplit("}", 1)[-1] != "speciesTypeInstance":
                    continue
                site_name = attribute(node, "name")
                expected_ordinals[site_name] = expected_ordinals.get(site_name, 0) + 1
                expected_components[(site_name, expected_ordinals[site_name])] += 1
            actual_components = Counter()
            for index in indexes.values():
                if attribute(index, "identifyingParent") != instance_id:
                    continue
                component_id = attribute(index, "component")
                component = base_components.get(component_id)
                if component is None:
                    actual_components[("invalid", 0)] += 1
                    continue
                site_name = component[0]
                matching_sites = [
                    node
                    for node in base_types[molecule].iter()
                    if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
                    and attribute(node, "name") == site_name
                ]
                ordinal = next(
                    (
                        position
                        for position, node in enumerate(matching_sites, 1)
                        if attribute(node, "id") == component_id
                    ),
                    0,
                )
                actual_components[(site_name, ordinal)] += 1
            if actual_components != expected_components:
                problems.append(
                    f"complex component inventory differs for {instance_id}: "
                    f"{actual_components}"
                )
        observed_bonds = set()
        bond_count = 0
        for bond in complex_type.iter():
            if bond.tag.rsplit("}", 1)[-1] != "inSpeciesTypeBond":
                continue
            bond_count += 1
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
        if observed_bonds != expected_bond or bond_count != 1:
            problems.append(
                f"bond graph differs: endpoints={observed_bonds}, count={bond_count}"
            )

    observed_states = []
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
            if attribute(feature, "occur") != "1":
                problems.append(f"site feature occurrence differs for {species_name}")
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
                observed_states.append(
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
    if Counter(observed_states) != Counter(expected_states):
        problems.append(f"site states differ: {observed_states}")

    parameters = {
        attribute(node, "id"): attribute(node, "value")
        for node in elements("parameter")
    }
    normalized_parameters = {
        key: str(float(value)) if _is_number(value) else value
        for key, value in parameters.items()
    }
    expected_parameters = {
        key: str(float(value)) if _is_number(value) else value
        for key, value in manifest["parameters"].items()
    }
    if normalized_parameters != expected_parameters:
        problems.append(f"rate parameters differ: {parameters}")
    parameter_constants = {
        attribute(node, "id"): attribute(node, "constant")
        for node in elements("parameter")
    }
    if parameter_constants != manifest["parameter_constants"]:
        problems.append(f"parameter mutability differs: {parameter_constants}")
    actual_reactions = []
    species_names_by_id = {
        attribute(node, "id"): attribute(node, "name") for node in species.values()
    }

    def normalized_tokens(tokens):
        return tuple(
            sorted(
                str(float(token)) if _is_number(token) else token for token in tokens
            )
        )

    for reaction in elements("reaction"):
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
            participants = []
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
                        participants.append(attribute(participant, "name"))
            participant_names[direction] = participants
        apply_node = next(
            (
                node
                for node in reaction.iter()
                if node.tag.rsplit("}", 1)[-1] == "apply"
            ),
            None,
        )
        operator = (
            list(apply_node)[0].tag.rsplit("}", 1)[-1]
            if apply_node is not None and list(apply_node)
            else None
        )
        apply_count = sum(
            node.tag.rsplit("}", 1)[-1] == "apply" for node in reaction.iter()
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
        rate_terms = [
            species_names_by_id.get(text.strip(), text.strip())
            for node in reaction.iter()
            if node.tag.rsplit("}", 1)[-1] in {"ci", "cn"}
            and (text := (node.text or "").strip())
        ]
        actual_reactions.append(
            (
                tuple(sorted(participant_names["listOfReactants"])),
                tuple(sorted(participant_names["listOfProducts"])),
                tuple(sorted(pairs)),
                operator,
                apply_count,
                attribute(reaction, "reversible"),
                normalized_tokens(rate_terms),
            )
        )
    expected_maps = tuple(sorted([("L", "L"), ("R", "R")]))
    expected_reactions = [
        (
            tuple(sorted(reactants)),
            tuple(sorted(products)),
            expected_maps,
            manifest["rate_operator"],
            1,
            manifest["reaction_reversible"],
            normalized_tokens(rate_terms),
        )
        for (reactants, products), rate_terms in zip(
            manifest["stoichiometry"], manifest["kinetics"], strict=True
        )
    ]
    if len(actual_reactions) != manifest["reaction_count"]:
        problems.append(f"reaction count differs: {len(actual_reactions)}")
    if Counter(actual_reactions) != Counter(expected_reactions):
        problems.append(f"reaction signatures differ: {actual_reactions}")

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
    """Require rejection of semantic mutations to the authored SBML structure."""
    manifest = _source_manifest_for(source)
    if manifest is None:
        return {"source_hash": {"status": "fail"}}
    controls = {}
    with tempfile.TemporaryDirectory(
        prefix="bng3-issue-161-contract-mutations-"
    ) as raw:
        directory = Path(raw)
        mutation_names = (
            "missing_molecule_type",
            "missing_complex_type",
            "missing_bond",
            "wrong_bond_endpoint",
            "wrong_state",
            "wrong_component_map_target",
            "wrong_initial_quantity",
            "wrong_compartment_volume",
            "wrong_rate_parameter",
            "wrong_rate_operator",
        )
        for name in mutation_names:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            parent_by_child = {
                child: parent for parent in root.iter() for child in list(parent)
            }
            if name == "missing_molecule_type":
                target = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "speciesType"
                        and _local_attribute(node, "name") in manifest["molecules"]
                    ),
                    None,
                )
                if target is not None:
                    parent_by_child[target].remove(target)
            elif name == "missing_complex_type":
                target = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "speciesType"
                        and _local_attribute(node, "name") not in manifest["molecules"]
                    ),
                    None,
                )
                if target is not None:
                    parent_by_child[target].remove(target)
            elif name in {"missing_bond", "wrong_bond_endpoint"}:
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
            elif name == "wrong_state":
                values = [
                    node
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "speciesFeatureValue"
                ]
                if values:
                    possible = {
                        _local_attribute(node, "id")
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "possibleSpeciesFeatureValue"
                    }
                    current = _local_attribute(values[0], "value")
                    alternative = next(
                        (value for value in possible if value != current), None
                    )
                    if alternative is not None:
                        _set_local_attribute(values[0], "value", alternative)
                else:
                    species = next(
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "species"
                    )
                    feature_list = ET.SubElement(species, "listOfSpeciesFeatures")
                    feature = ET.SubElement(
                        feature_list,
                        "speciesFeature",
                        {
                            "component": "unexpected-component",
                            "speciesFeatureType": "unexpected-feature",
                        },
                    )
                    values = ET.SubElement(feature, "listOfSpeciesFeatureValues")
                    ET.SubElement(
                        values, "speciesFeatureValue", {"value": "unexpected-state"}
                    )
            elif name == "wrong_component_map_target":
                mappings = [
                    node
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "speciesTypeComponentMapInProduct"
                ]
                if mappings:
                    current = _local_attribute(mappings[0], "productComponent")
                    alternatives = [
                        _local_attribute(node, "productComponent")
                        for node in mappings[1:]
                    ]
                    if not alternatives:
                        alternatives = [
                            _local_attribute(node, "id")
                            for node in root.iter()
                            if node.tag.rsplit("}", 1)[-1] == "speciesTypeInstance"
                        ]
                    alternative = next(
                        (value for value in alternatives if value != current), None
                    )
                    if alternative is not None:
                        _set_local_attribute(
                            mappings[0], "productComponent", alternative
                        )
            elif name == "wrong_initial_quantity":
                species = next(
                    node
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "species"
                )
                attribute_name = next(
                    (
                        key.rsplit("}", 1)[-1]
                        for key in species.attrib
                        if key.rsplit("}", 1)[-1]
                        in {"initialAmount", "initialConcentration"}
                    ),
                    None,
                )
                if attribute_name:
                    current = _local_attribute(species, attribute_name)
                    _set_local_attribute(
                        species, attribute_name, str(float(current) + 1)
                    )
            elif name == "wrong_compartment_volume":
                compartment = next(
                    node
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "compartment"
                )
                current = _local_attribute(compartment, "size")
                _set_local_attribute(compartment, "size", str(float(current) + 1))
            elif name == "wrong_rate_parameter":
                parameter = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "parameter"
                        and _local_attribute(node, "value") is not None
                    ),
                    None,
                )
                constants = [
                    node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "cn"
                ]
                if parameter is not None:
                    current = _local_attribute(parameter, "value")
                    _set_local_attribute(parameter, "value", str(float(current) + 1))
                elif constants:
                    current = (constants[0].text or "0").strip()
                    constants[0].text = str(float(current) + 1)
            elif name == "wrong_rate_operator":
                operator = next(
                    (
                        node
                        for node in root.iter()
                        if node.tag.rsplit("}", 1)[-1] == "times"
                    ),
                    None,
                )
                if operator is not None:
                    operator.tag = operator.tag.replace("times", "plus")
            mutated = directory / f"{name}.xml"
            tree.write(mutated, encoding="utf-8", xml_declaration=True)
            result = _source_semantic_contract(source, mutated)
            controls[name] = {
                "status": ("pass" if result["status"] in {"fail", "error"} else "fail"),
                "contract_status_after_mutation": result["status"],
                "problems": result.get("problems", []),
            }
        changed_source = directory / "changed-source.bngl"
        changed_source.write_text(
            source.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        hash_result = _source_semantic_contract(changed_source, xml_path)
        controls["changed_source_hash"] = {
            "status": "pass" if hash_result["status"] == "error" else "fail",
            "contract_status_after_mutation": hash_result["status"],
        }
    return controls


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
