"""Generated native network identity controls linked to issue #142.

The independent Python graph matcher supplies expected seed partitions; each
CI worker separately asks the installed BNG3 network generator to deduplicate
the same seeds. NFsim identity routes are outside this slice.
"""

from __future__ import annotations

from pathlib import Path

from .compare import parse_net, species_isomorphic

ISSUE = 142


def _ring_seed(size: int, *, permuted: bool) -> str:
    """Make one labeled cycle, alpha-renaming bonds and reordering syntax."""
    bond_ids = range(1, size + 1)
    if not permuted:
        order = list(range(size))
        labels = {bond: bond for bond in bond_ids}
        swap_sites = False
    else:
        order = list(reversed(range(size)))
        labels = {bond: 37 + 11 * bond for bond in bond_ids}
        swap_sites = True
    molecules = []
    for node in order:
        previous = (node - 1) % size + 1
        following = node % size + 1
        sites = (f"a!{labels[previous]}", f"b!{labels[following]}")
        if swap_sites:
            sites = tuple(reversed(sites))
        molecules.append("A(" + ",".join(sites) + ")")
    return ".".join(molecules)


def generated_cases() -> tuple[dict, ...]:
    """Return small symmetric families and semantic negative controls."""
    cases = [
        {
            "id": f"symmetric-ring-{size}",
            "molecule_types": "A(a,b)",
            "seeds": (
                _ring_seed(size, permuted=False),
                _ring_seed(size, permuted=True),
            ),
            "oracle_seeds": (
                _ring_seed(size, permuted=False),
                _ring_seed(size, permuted=True),
            ),
            "expected_species": 1,
            "purpose": (
                f"symmetric {size}-ring under molecule/site/bond-label permutations"
            ),
        }
        for size in (3, 4, 5)
    ]
    cases.extend(
        (
            {
                "id": "state-distinction",
                "molecule_types": "A(x~u~p)\nB(y)",
                "seeds": ("A(x~u!1).B(y!1)", "B(y!9).A(x~p!9)"),
                "oracle_seeds": ("A(x~u!1).B(y!1)", "B(y!9).A(x~p!9)"),
                "expected_species": 2,
                "purpose": "site state remains part of graph identity",
            },
            {
                "id": "species-compartment-distinction",
                "molecule_types": "A(x)\nB(y)",
                "compartments": "PM 2 1\nCP 3 1 PM",
                "seeds": (
                    "@PM:A(x!1).B(y!1)",
                    "@CP:B(y!9).A(x!9)",
                ),
                "oracle_seeds": (
                    "@PM::A(x!1).B(y!1)",
                    "@CP::B(y!9).A(x!9)",
                ),
                "expected_species": 2,
                "purpose": "species compartment remains part of graph identity",
            },
            {
                "id": "molecule-compartment-distinction",
                "molecule_types": "A(x)\nB(y)",
                "compartments": "PM 2 1\nCP 3 1 PM",
                "seeds": (
                    "@PM:A@CP(x!1).B@PM(y!1)",
                    "@PM:B@CP(y!9).A@PM(x!9)",
                ),
                "oracle_seeds": (
                    "@PM::A(x!1)@CP.B(y!1)@PM",
                    "@PM::B(y!9)@CP.A(x!9)@PM",
                ),
                "expected_species": 2,
                "purpose": "per-molecule compartments remain part of graph identity",
            },
        )
    )
    return tuple(cases)


CASES = generated_cases()


def oracle_partition(seeds: tuple[str, ...]) -> list[str]:
    """Group generated NET spellings only when the independent oracle agrees."""
    representatives: list[str] = []
    for seed in seeds:
        if not any(species_isomorphic(seed, item) for item in representatives):
            representatives.append(seed)
    return representatives


def model_text(case: dict) -> str:
    compartments = case.get("compartments")
    compartment_block = (
        f"begin compartments\n{compartments}\nend compartments\n"
        if compartments
        else ""
    )
    seeds = "\n".join(f"{seed} 1" for seed in case["seeds"])
    return (
        "begin model\n"
        + compartment_block
        + f"begin molecule types\n{case['molecule_types']}\nend molecule types\n"
        + f"begin seed species\n{seeds}\nend seed species\n"
        + "end model\n"
    )


def _matches(expected: list[str], observed: list[str]) -> bool:
    return (
        len(expected) == len(observed)
        and all(
            any(species_isomorphic(actual, wanted) for wanted in expected)
            for actual in observed
        )
        and all(
            any(species_isomorphic(wanted, actual) for actual in observed)
            for wanted in expected
        )
    )


def run_worker(directory: Path) -> list[dict]:
    """Run native production network generation and compare with graph oracle."""
    import bionetgen

    rows = []
    directory.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        case_dir = directory / case["id"]
        case_dir.mkdir()
        source = case_dir / "model.bngl"
        net_path = case_dir / "model.net"
        expected = oracle_partition(case["oracle_seeds"])
        row = {
            "id": f"graph-identity:{case['id']}",
            "check": case["id"],
            "detail": case["purpose"],
            "related_issues": [ISSUE],
            "evidence_kind": "independent-graph-oracle-vs-native-network",
            "expected_species": len(expected),
        }
        try:
            source.write_text(model_text(case), encoding="utf-8")
        except OSError as exc:
            row.update(
                status="HARNESS_ERROR",
                detail=f"could not write generated input: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "generated-input-write",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue
        try:
            model = bionetgen.load(str(source))
        except Exception as exc:
            row.update(
                status="INVALID_INPUT",
                detail=f"generated BNGL case was rejected before network generation: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "generated-input-parse",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue
        try:
            network = model.generate_network()
            model.write_net(str(net_path))
        except OSError as exc:
            row.update(
                status="HARNESS_ERROR",
                detail=f"could not retain generated native network evidence: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "native-network-artifact-write",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue
        except Exception as exc:
            row.update(
                status="FAIL",
                detail=f"{case['purpose']}; native network generation raised {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "native-network-generation",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue

        try:
            parsed = parse_net(net_path)
            observed_count = int(network.num_species)
        except Exception as exc:
            row.update(
                status="HARNESS_ERROR",
                detail=f"could not inspect generated native network evidence: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "network-evidence-inspection",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue
        if parsed is None:
            row.update(
                status="HARNESS_ERROR",
                detail="native writer emitted a NET document the independent reader could not parse",
                first_difference={"field": "net-artifact", "path": str(net_path)},
            )
            rows.append(row)
            continue

        try:
            observed = list(parsed.species_by_index.values())
            matched = _matches(expected, observed)
            passed = (
                len(expected) == case["expected_species"]
                and observed_count == case["expected_species"]
                and len(observed) == case["expected_species"]
                and matched
            )
        except Exception as exc:
            row.update(
                status="HARNESS_ERROR",
                detail=f"could not compare generated graph evidence: {type(exc).__name__}: {exc}",
                first_difference={
                    "field": "graph-evidence-comparison",
                    "exception": type(exc).__name__,
                },
            )
            rows.append(row)
            continue
        row.update(
            status="PASS" if passed else "FAIL",
            observed_species=observed_count,
            network_species=observed,
            artifact=str(net_path),
        )
        if not passed:
            row["first_difference"] = {
                "field": "network-species-identity",
                "expected": expected,
                "observed": observed,
            }
        rows.append(row)
    return rows
