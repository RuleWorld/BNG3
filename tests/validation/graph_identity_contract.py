"""Generated identity-contract qualification linked to issue #142.

One independent identity contract decides every surface:

``tests.validation.compare.species_isomorphic`` is the independent matcher.  It
decides a relation that is parameterized by a *layer* of the shared identity
contract (``cpp/core/IdentityContract.hpp``):

``structure``
    labeled-graph isomorphism; compartments are ignored.
``structure+compartment``
    structure, plus the compartment of every molecule under the isomorphism.  A
    molecule without an explicit compartment takes the species-level
    compartment, which is the compartment NFsim resolves for it.
``species``
    structure, plus the species-level compartment, plus the per-molecule
    compartments.

Two native surfaces are compared against that contract:

``network-canonical-label``
    the network encoding (``BNGcore::PatternGraph`` plus its nauty canonical
    label), which decides the ``structure`` layer.
``nfsim-canonical-label``
    the NFsim encoding (``NFcore::Complex`` plus its own nauty canonical
    label), which decides the ``structure+compartment`` layer.

The network species identity decides the ``species`` layer.  Every surface
states the layer it decides, so a surface that decides a different layer is
visible instead of silent.

A canonical label is never accepted as proof of identity: the partition a
label induces is compared with the partition the independent matcher computes,
so two different graphs that share a label are a mismatch and not a merge.

The generated families spell a species compartment as the ``@C:`` prefix and a
molecule compartment as the ``A(...)@C`` suffix.  The native parser reads the
molecule-prefix spelling ``A@C(...)`` differently, so the families do not use
it: a family that did would report a mismatch against the independent
contract rather than pass silently.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

from .compare import (
    _split_molecule_compartment,
    _split_species_compartment,
    parse_net,
    species_isomorphic,
    split_species,
)

ISSUE = 142

LAYER_STRUCTURE = "structure"
LAYER_COMPARTMENT = "structure+compartment"
LAYER_SPECIES = "species"

# The layer each surface decides.  The native product reports the same names;
# a difference between the two is a visible mismatch, not a silent pass.
SURFACE_LAYERS = {
    "network-canonical-label": LAYER_STRUCTURE,
    "nfsim-canonical-label": LAYER_COMPARTMENT,
    "network-species-identity": LAYER_SPECIES,
}

# The rows every generated case produces.
CHECKS = (
    "network-canonical-label",
    "nfsim-canonical-label",
    "network-species-identity",
    "shared-identity-contract",
)


def _ring(size: int, *, reverse: bool = False, relabel: bool = False) -> str:
    """One labeled cycle of identical two-site molecules.

    The permuted spelling renumbers the bonds, reverses the traversal order and
    swaps the site order, so it differs from the plain spelling in node
    labelling and traversal order only.
    """
    order = list(range(size))
    if reverse:
        order.reverse()
    molecules = []
    for node in order:
        previous = (node - 1) % size + 1
        following = node % size + 1
        bonds = {previous: previous, following: following}
        if relabel:
            bonds = {bond: 7 + 5 * bond for bond in bonds}
        sites = [f"a!{bonds[previous]}", f"b!{bonds[following]}"]
        if relabel:
            sites.reverse()
        molecules.append("A(" + ",".join(sites) + ")")
    return ".".join(molecules)


def _path(size: int) -> str:
    """One chain of identical two-site molecules; not a cycle."""
    molecules = []
    for node in range(size):
        previous = f"a!{node}" if node > 0 else "a"
        following = f"b!{node + 1}" if node < size - 1 else "b"
        molecules.append("A(" + previous + "," + following + ")")
    return ".".join(molecules)


def _partial_matchings(site_count: int) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Enumerate partial matchings of sites on different molecules."""
    def visit(remaining: tuple[int, ...]):
        if not remaining:
            yield ()
            return
        first, *tail = remaining
        yield from visit(tuple(tail))
        first_molecule = first // 2
        for offset, partner in enumerate(tail):
            if partner // 2 == first_molecule:
                continue
            rest = tuple(tail[:offset] + tail[offset + 1 :])
            for matching in visit(rest):
                yield ((first, partner),) + matching

    return tuple(visit(tuple(range(site_count))))


def _small_equivalent_site_graphs() -> tuple[str, ...]:
    """All state-colored graphs through two molecules with two equivalent sites.

    Each molecule has two equivalent ``l`` sites.  The generator enumerates
    every site-state assignment and every valid partial matching between
    molecules, including disconnected, one-bond and parallel-bond graphs.
    """
    species = []
    for molecule_count in (1, 2):
        site_count = 2 * molecule_count
        for matching in _partial_matchings(site_count):
            for states in product(("u", "p"), repeat=site_count):
                bond_ids = {
                    site: index + 1
                    for index, pair in enumerate(matching)
                    for site in pair
                }
                molecules = []
                for molecule in range(molecule_count):
                    sites = []
                    for site in range(2 * molecule, 2 * molecule + 2):
                        component = f"l~{states[site]}"
                        if site in bond_ids:
                            component += f"!{bond_ids[site]}"
                        sites.append(component)
                    molecules.append("R(" + ",".join(sites) + ")")
                species.append(".".join(molecules))
    return tuple(species)


def generated_cases() -> tuple[dict, ...]:
    """Return the generated identity cases and their negative controls."""
    cases = [
        {
            "id": f"symmetric-ring-{size}",
            "purpose": (
                f"symmetric {size}-ring under bond renumbering, reversed "
                "traversal and swapped site order, against a chain"
            ),
            "molecule_types": "A(a,b)",
            "compartments": "",
            "species": (
                _ring(size),
                _ring(size, reverse=True, relabel=True),
                _path(size),
            ),
        }
        for size in (3, 4, 5)
    ]
    cases.extend(
        (
            {
                "id": "molecule-compartment-distinction",
                "purpose": "per-molecule compartments stay part of the identity",
                "molecule_types": "A(x)\nB(y)",
                "compartments": "PM 2 1\nCP 3 1 PM\nNU 3 1 PM",
                "species": (
                    "@PM:A(x!1)@CP.B(y!1)@PM",
                    "@PM:A(x!9)@NU.B(y!9)@PM",
                ),
            },
            {
                "id": "species-compartment-distinction",
                "purpose": "the species-level compartment stays part of the identity",
                "molecule_types": "A(x)\nB(y)",
                "compartments": "PM 2 1\nNU 3 1 PM",
                "species": (
                    "@PM:A(x!1).B(y!1)",
                    "@NU:A(x!9).B(y!9)",
                ),
            },
            {
                "id": "state-distinction",
                "purpose": "a site state stays part of the identity",
                "molecule_types": "A(x~u~p)\nB(y)",
                "compartments": "",
                "species": (
                    "A(x~u!1).B(y!1)",
                    "A(x~p!9).B(y!9)",
                ),
            },
            {
                "id": "topology-distinction",
                "purpose": "the bond topology stays part of the identity",
                "molecule_types": "A(x,y)\nB(x)\nC(x)",
                "compartments": "",
                "species": (
                    "A(x!1,y!2).B(x!1).C(x!2)",
                    "A(x!1,y!2).B(x!2).C(x!1)",
                ),
            },
            {
                "id": "equivalent-site-permutation",
                "purpose": (
                    "equivalent sites keep their identity under site permutations, "
                    "while bond multiplicity stays distinct"
                ),
                "molecule_types": "R(l,l)",
                "compartments": "",
                "species": (
                    "R(l!1,l!2).R(l!1,l!2)",
                    "R(l!8,l!7).R(l!8,l!7)",
                    "R(l!3,l).R(l!3,l)",
                ),
            },
            {
                "id": "exhaustive-small-equivalent-sites",
                "purpose": (
                    "exhaust all state-colored partial bond matchings through "
                    "two molecules with two equivalent sites each"
                ),
                "molecule_types": "R(l~u~p,l~u~p)",
                "compartments": "",
                "species": _small_equivalent_site_graphs(),
            },
        )
    )
    return tuple(cases)


CASES = generated_cases()


def contract_spelling(text: str) -> str:
    """Rewrite a native species spelling into the independent matcher's spelling.

    The native parser reads a species-level compartment as a ``@C:`` prefix and
    a molecule compartment as ``A@C(...)``; the independent matcher reads a
    species-level compartment as a ``@C::`` prefix and a molecule compartment as
    a ``A(...)@C`` suffix.  Only the spelling changes: the compartments, the
    sites and the bonds stay the same.
    """
    compartment = ""
    body = text
    if text.startswith("@"):
        marker = text.find(":")
        if marker > 1:
            compartment = text[1:marker]
            body = text[marker + 1 :]
    molecules = []
    for molecule in split_species(body):
        molecule = molecule.strip()
        name, separator, sites = molecule.partition("(")
        if separator and "@" in name:
            name, _, molecule_compartment = name.partition("@")
            molecules.append(name + "(" + sites + ")@" + molecule_compartment)
        else:
            molecules.append(molecule)
    rendered = ".".join(molecules)
    if compartment:
        rendered = "@" + compartment + "::" + rendered
    return rendered


def _contract_parts(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(species compartment, [(molecule, compartment)])`` of a spelling."""
    compartment, body = _split_species_compartment(text)
    molecules = []
    for molecule in split_species(body):
        molecule, molecule_compartment = _split_molecule_compartment(molecule.strip())
        molecules.append((molecule.strip(), molecule_compartment))
    return compartment, molecules


def relation_text(text: str, relation: str) -> str:
    """Return the spelling of a species under one layer of the contract.

    The structure layer drops every compartment.  The compartment layer drops
    the species-level compartment and materializes each molecule's effective
    compartment, which is the compartment NFsim resolves for that molecule.  The
    species layer keeps the spelling unchanged.
    """
    if relation == LAYER_SPECIES:
        return text
    compartment, molecules = _contract_parts(text)
    if relation == LAYER_STRUCTURE:
        return ".".join(molecule for molecule, _ in molecules)
    if relation == LAYER_COMPARTMENT:
        rendered = []
        for molecule, molecule_compartment in molecules:
            effective = molecule_compartment or compartment
            rendered.append(molecule + ("@" + effective if effective else ""))
        return ".".join(rendered)
    raise ValueError("unknown identity relation: " + relation)


def contract_partition(texts: tuple[str, ...], relation: str) -> set[frozenset[int]]:
    """Partition species with the independent matcher under one layer."""
    transformed = [relation_text(text, relation) for text in texts]
    groups: list[list[tuple[int, str]]] = []
    for index, text in enumerate(transformed):
        for group in groups:
            if any(species_isomorphic(text, other) for _, other in group):
                group.append((index, text))
                break
        else:
            groups.append([(index, text)])
    return {frozenset(index for index, _ in group) for group in groups}


def partition_from_labels(labels: list[str]) -> set[frozenset[int]]:
    """Partition species by the label a surface assigned to each of them."""
    groups: dict[str, set[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, set()).add(index)
    return {frozenset(group) for group in groups.values()}


def _refines(inner: set[frozenset[int]], outer: set[frozenset[int]]) -> bool:
    """True when every inner class is contained in one outer class."""
    for group in inner:
        if not any(group <= candidate for candidate in outer):
            return False
    return True


def model_text(case: dict) -> str:
    """Return the generated BNGL model of one case."""
    compartments = case["compartments"]
    compartment_block = (
        f"begin compartments\n{compartments}\nend compartments\n"
        if compartments
        else ""
    )
    seeds = "\n".join(f"{species} 1" for species in case["species"])
    return (
        "begin model\n"
        + compartment_block
        + f"begin molecule types\n{case['molecule_types']}\nend molecule types\n"
        + f"begin seed species\n{seeds}\nend seed species\n"
        + "end model\n"
    )


def _row(case: dict, check: str, status: str, detail: str, **extra) -> dict:
    row = {
        "id": f"graph-identity-contract:{case['id']}:{check}",
        "check": check,
        "detail": detail,
        "related_issues": [ISSUE],
        "evidence_kind": "supported-execution",
        "identity_relations": dict(SURFACE_LAYERS),
    }
    row.update(extra)
    row["status"] = status
    return row


def _run_case(case: dict, directory: Path) -> list[dict]:
    import bionetgen
    from bionetgen import _bionetgen_cpp as cpp

    case_dir = directory / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    source = case_dir / "model.bngl"
    net_path = case_dir / "model.net"
    contract_texts = tuple(contract_spelling(text) for text in case["species"])

    try:
        source.write_text(model_text(case), encoding="utf-8")
    except OSError as exc:
        return [
            _row(
                case,
                check,
                "HARNESS_ERROR",
                f"could not write generated input: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "generated-input-write",
                    "exception": type(exc).__name__,
                },
            )
            for check in CHECKS
        ]

    try:
        model = bionetgen.load(str(source))
    except Exception as exc:
        return [
            _row(
                case,
                check,
                "INVALID_INPUT",
                "generated BNGL case was rejected before the identity "
                f"surfaces ran: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "generated-input-parse",
                    "exception": type(exc).__name__,
                },
            )
            for check in CHECKS
        ]

    try:
        observations = cpp._validation_species_identity_labels(model._model)
    except Exception as exc:
        return [
            _row(
                case,
                check,
                "HARNESS_ERROR",
                "the native identity surfaces refused to report their labels: "
                f"{type(exc).__name__}: {exc}",
                first_difference={
                    "field": "native-identity-observation",
                    "exception": type(exc).__name__,
                },
            )
            for check in CHECKS
        ]

    entries = list(observations["species"])
    if len(entries) != len(case["species"]):
        return [
            _row(
                case,
                check,
                "HARNESS_ERROR",
                "the native identity surfaces reported "
                f"{len(entries)} species for {len(case['species'])} seeds",
                first_difference={
                    "field": "native-identity-observation-count",
                    "expected": len(case["species"]),
                    "observed": len(entries),
                },
            )
            for check in CHECKS
        ]

    declared = dict(observations["layers"])

    # The network species identity surface: the species the native network
    # generator keeps apart.  The mapping from a seed to its network species is
    # established with the independent matcher, never by comparing labels.
    network_row = None
    network_problem = None
    network_partition = None
    try:
        network = model.generate_network()
        model.write_net(str(net_path))
        parsed = parse_net(net_path)
        if parsed is None:
            raise ValueError(
                "the native writer emitted a NET document the independent "
                "reader could not parse"
            )
        network_species = list(parsed.species_by_index.values())
        assignments = []
        for text in contract_texts:
            matches = [
                species
                for species in network_species
                if species_isomorphic(text, species)
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"seed '{text}' matched {len(matches)} network species"
                )
            assignments.append(matches[0])
    except Exception as exc:
        network_problem = {
            "field": "network-species-identity",
            "exception": type(exc).__name__,
        }
    else:
        expected = contract_partition(contract_texts, LAYER_SPECIES)
        observed = partition_from_labels(assignments)
        network_partition = observed
        passed = expected == observed
        network_row = _row(
            case,
            "network-species-identity",
            "PASS" if passed else "FAIL",
            f"the native network keeps {len(observed)} species apart; the "
            f"independent {LAYER_SPECIES} contract keeps {len(expected)} apart",
            expected_classes=sorted(len(group) for group in expected),
            observed_classes=sorted(len(group) for group in observed),
            first_difference=(
                None
                if passed
                else {
                    "field": "network-species-identity",
                    "expected": sorted(sorted(group) for group in expected),
                    "observed": sorted(sorted(group) for group in observed),
                }
            ),
        )

    network_labels = [entry["network_label"] for entry in entries]
    nfsim_labels = [entry["nfsim_label"] for entry in entries]
    rows: list[dict] = []
    for surface, labels, relation in (
        ("network-canonical-label", network_labels, LAYER_STRUCTURE),
        ("nfsim-canonical-label", nfsim_labels, LAYER_COMPARTMENT),
    ):
        expected = contract_partition(contract_texts, relation)
        observed = partition_from_labels(labels)
        passed = expected == observed
        rows.append(
            _row(
                case,
                surface,
                "PASS" if passed else "FAIL",
                f"the {surface} surface decides the {relation} layer; the "
                f"independent {relation} contract and the surface induce the "
                f"same {len(expected)} classes",
                identity_relation=relation,
                expected_classes=sorted(len(group) for group in expected),
                observed_classes=sorted(len(group) for group in observed),
                first_difference=(
                    None
                    if passed
                    else {
                        "field": surface,
                        "expected": sorted(sorted(group) for group in expected),
                        "observed": sorted(sorted(group) for group in observed),
                    }
                ),
            )
        )
    if network_row is not None:
        rows.append(network_row)
    else:
        rows.append(
            _row(
                case,
                "network-species-identity",
                "HARNESS_ERROR",
                "the native network species identity could not be observed: "
                f"{network_problem['exception']}",
                first_difference=network_problem,
            )
        )

    # The shared contract: every surface decides one layer of one identity
    # contract, the layers nest, and the native product declares the layer it
    # decides.
    structure = contract_partition(contract_texts, LAYER_STRUCTURE)
    compartment = contract_partition(contract_texts, LAYER_COMPARTMENT)
    species = contract_partition(contract_texts, LAYER_SPECIES)
    observed_structure = partition_from_labels(network_labels)
    observed_compartment = partition_from_labels(nfsim_labels)
    problems = []
    if declared != SURFACE_LAYERS:
        problems.append(
            {
                "field": "declared-identity-relation",
                "expected": SURFACE_LAYERS,
                "observed": declared,
            }
        )
    if not _refines(compartment, structure):
        problems.append(
            {
                "field": "contract-layers",
                "detail": "compartment does not refine structure",
            }
        )
    if not _refines(species, compartment):
        problems.append(
            {
                "field": "contract-layers",
                "detail": "species does not refine compartment",
            }
        )
    if not _refines(observed_compartment, observed_structure):
        problems.append(
            {
                "field": "surface-layers",
                "detail": "the nfsim label does not refine the network label",
            }
        )
    if network_partition is not None and not _refines(
        network_partition, observed_compartment
    ):
        problems.append(
            {
                "field": "surface-layers",
                "detail": "the network species identity does not refine the "
                "nfsim label",
            }
        )
    rows.append(
        _row(
            case,
            "shared-identity-contract",
            "PASS" if not problems else "FAIL",
            "the network label, the NFsim label and the network species "
            "identity decide the structure, structure+compartment and species "
            "layers of one identity contract",
            first_difference=problems[0] if problems else None,
        )
    )
    return rows


def run_worker(directory: Path) -> list[dict]:
    """Run the generated identity cases against the native surfaces."""
    rows: list[dict] = []
    directory.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        rows.extend(_run_case(case, directory))
    return rows
