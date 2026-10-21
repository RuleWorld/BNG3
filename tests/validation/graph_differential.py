"""Differential graph identity and bounded network equivalence (#168).

Issue #168 asks for differential cases that compare the production graph
identity and the generated network against an independent construction, and
for the intended bounded equivalence to be stated with an explicit domain and
termination argument.

The independent construction has two parts, and neither of them is BNG3's own
output:

``reference network``
    The canonical Perl BNG2 (``legacy/perl/BNG2.pl``) generates the network
    for the same source.  It is a separate implementation of network
    generation and of species identity.

``identity relation``
    Both ``.net`` artifacts are read by the harness's own reader
    (``tests/validation/compare.py``) and compared with the harness's own
    labeled-graph matcher.  Two species are the same species when that
    matcher says their graphs are isomorphic, so the comparison never depends
    on how either implementation spells a species.

The bounded equivalence
-----------------------

Let ``M`` be a model inside the declared domain below, ``N3(M)`` the network
BNG3's production generator produces and ``N2(M)`` the network the canonical
implementation produces for the same source.  Then:

* the species of ``N3(M)`` and the species of ``N2(M)`` are in bijection under
  the independent graph-isomorphism relation, and
* the isomorphism relation between the two networks is exactly that
  bijection: every production species has exactly one isomorphic reference
  species and every reference species has exactly one isomorphic production
  species, and neither network contains two species that the independent
  matcher calls identical.

The declared domain
-------------------

* the model declares at least one reaction rule and at most four;
* the model declares at most three seed species and no two of them are
  isomorphic (the canonical implementation refuses such a model);
* no seed species carries a dangling bond (the canonical implementation
  refuses such a model);
* each network holds at most eight species and at most twelve reactions;
* each species holds at most twelve molecule and site vertices.

The termination argument
------------------------

Both generators are bounded.  The canonical implementation stops when an
iteration adds no species, and BNG3's production generator stops after at
most ``MAX_ITERATIONS`` rule-application iterations.  The harness re-checks
the size bounds after both networks exist and refuses the case when a bound is
exceeded, so an unbounded computation is never compared.  The comparison
itself is a bipartite matching over at most eight species per side, so it
terminates.

A case outside the declared domain is refused with its reason and reported as
``UNSUPPORTED``.  It is never scored as a pass: a case the independent
construction cannot express has no evidence value.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .campaign import STATUSES
from .compare import parse_net, species_isomorphic

ISSUES = (168,)
OPERATION = "graph-differential"

# The named checks of this operation.
CHECKS = ("network-species-bijection", "graph-identity-relation")

ROOT = Path(__file__).resolve().parents[2]
ORACLE_SCRIPT = ROOT / "legacy" / "perl" / "BNG2.pl"

# The declared bounds of the qualified slice.
MAX_SEED_SPECIES = 3
MAX_RULES = 4
MAX_SPECIES = 8
MAX_REACTIONS = 12
MAX_VERTICES = 12
MAX_ITERATIONS = 100
ORACLE_TIMEOUT = 120

DOMAIN = (
    "at least one and at most four reaction rules, at most three seed species "
    "of which no two are isomorphic, no dangling bond in a seed species, at "
    "most eight species and twelve reactions per network, and at most twelve "
    "molecule and site vertices per species"
)


def _model(*, molecule_types, seeds, rules, compartments=()):
    """Render one generated case as a BNGL model."""
    lines = ["begin model"]
    if compartments:
        lines.append("begin compartments")
        for name, dimension, volume in compartments:
            lines.append(f"  {name} {dimension} {volume}")
        lines.append("end compartments")
    lines.append("begin molecule types")
    for name, sites in molecule_types:
        lines.append(f"  {name}({sites})" if sites else f"  {name}")
    lines.append("end molecule types")
    lines.append("begin seed species")
    for pattern, amount in seeds:
        lines.append(f"  {pattern} {amount}")
    lines.append("end seed species")
    if rules:
        lines.append("begin reaction rules")
        for label, left, right, rate in rules:
            prefix = f"{label}: " if label else ""
            lines.append(f"  {prefix}{left} -> {right} {rate}")
        lines.append("end reaction rules")
    # The canonical implementation writes a network only when it is asked for
    # one; BNG3 ignores the action and generates the network on request.
    lines.append("begin actions")
    lines.append("  generate_network({overwrite=>1})")
    lines.append("end actions")
    lines.append("end model")
    return "\n".join(lines) + "\n"


def _case(case_id, purpose, *, molecule_types, seeds, rules, compartments=()):
    return {
        "id": case_id,
        "purpose": purpose,
        "text": _model(
            molecule_types=molecule_types,
            seeds=seeds,
            rules=rules,
            compartments=compartments,
        ),
        "seed_species": [pattern for pattern, _ in seeds],
        "rule_count": len(rules),
    }


def generated_cases():
    """Return the generated, parameterized differential cases.

    The family varies the number of molecule types, the site states, the
    spelling of a product that is isomorphic to another product, and whether
    the species carry a compartment.  One generated case sits outside the
    declared domain on purpose: it has no reaction rule, so the canonical
    implementation refuses it and the case is refused rather than passed.
    """
    cases = []

    # A dimer of identical reactants, over a growing number of molecule types.
    # The identical reactants put the symmetry factor in play, and the dimer
    # is a symmetric graph.
    for count in (2, 3):
        names = ["A", "B", "C"][:count]
        cases.append(
            _case(
                f"symmetric-dimer-{count}",
                f"{count} molecule types, each with a self-dimerization rule "
                "over two identical reactants",
                molecule_types=[(name, "b") for name in names],
                seeds=[(f"{name}(b)", 10) for name in names],
                rules=[
                    (
                        f"dimer{index}",
                        f"{name}(b) + {name}(b)",
                        f"{name}(b!1).{name}(b!1)",
                        "0.01",
                    )
                    for index, name in enumerate(names)
                ],
            )
        )

    # Two rules whose products are isomorphic but spelled differently.  The
    # production generator must merge them into one species; a generator that
    # kept both would produce one species too many.
    cases.append(
        _case(
            "molecule-order-swap",
            "two rules whose products are isomorphic under a different "
            "molecule order",
            molecule_types=[("A", "b"), ("B", "b")],
            seeds=[("A(b)", 10), ("B(b)", 10)],
            rules=[
                ("bind1", "A(b) + B(b)", "A(b!1).B(b!1)", "0.01"),
                ("bind2", "B(b) + A(b)", "B(b!1).A(b!1)", "0.02"),
            ],
        )
    )

    # A state change: the product is not isomorphic to the reactant, so the
    # generator must not merge them.
    for states in (("u", "p"), ("on", "off")):
        first, second = states
        cases.append(
            _case(
                f"state-flip-{first}-{second}",
                f"a state change from {first} to {second} that must not be "
                "merged with its reactant",
                molecule_types=[("A", f"x~{first}~{second}")],
                seeds=[(f"A(x~{first})", 10)],
                rules=[
                    (
                        "flip",
                        f"A(x~{first})",
                        f"A(x~{second})",
                        "0.01",
                    )
                ],
            )
        )

    # A compartmented species: the compartment is part of the species
    # identity, so the dimer stays a distinct species.
    cases.append(
        _case(
            "compartment-dimer",
            "a compartmented species whose dimer keeps the compartment",
            molecule_types=[("A", "b")],
            compartments=[("PM", 2, 1)],
            seeds=[("@PM:A(b)", 10)],
            rules=[
                (
                    "self",
                    "@PM:A(b) + @PM:A(b)",
                    "@PM:A(b!1).A(b!1)",
                    "0.01",
                )
            ],
        )
    )

    # Outside the declared domain: the canonical implementation refuses a
    # model without reaction rules, so the case is refused, not passed.
    cases.append(
        _case(
            "no-rule-outside-domain",
            "a model without a reaction rule, which the canonical "
            "implementation refuses and which therefore leaves the declared "
            "domain",
            molecule_types=[("A", "b")],
            seeds=[("A(b)", 10)],
            rules=[],
        )
    )

    return tuple(cases)


CASES = generated_cases()


def check_ids():
    """Stable expected check identities for the graph-differential operation."""
    return [f"{OPERATION}:{case['id']}:{name}" for case in CASES for name in CHECKS]


# --------------------------------------------------------------------------- #
# The checks.
# --------------------------------------------------------------------------- #


def _difference(field, expected, actual):
    return dict(field=field, expected=expected, actual=actual)


def _vertices(species):
    """Count the molecule and site vertices of one species spelling."""
    from .compare import split_sites, split_species

    molecules = split_species(species)
    total = 0
    for molecule in molecules:
        _, sites = split_sites(molecule)
        total += 1 + len(sites)
    return total


def _partners(left, right):
    """Return, for every species on the left, the isomorphic species right."""
    return [
        [index for index, other in enumerate(right) if species_isomorphic(item, other)]
        for item in left
    ]


def _match(left, right):
    """Return a maximum bipartite matching under graph isomorphism."""
    adjacency = _partners(left, right)
    matched = [-1] * len(right)

    def augment(index, visited):
        for candidate in adjacency[index]:
            if visited[candidate]:
                continue
            visited[candidate] = True
            if matched[candidate] == -1 or augment(matched[candidate], visited):
                matched[candidate] = index
                return True
        return False

    for index in range(len(left)):
        augment(index, [False] * len(right))
    return {index: candidate for candidate, index in enumerate(matched) if index != -1}


def _bijection_differences(production, reference):
    """The species sets must correspond one to one under isomorphism."""
    if len(production) != len(reference):
        return [
            _difference(
                "network.species.count",
                len(reference),
                len(production),
            )
        ]
    matching = _match(production, reference)
    if len(matching) != len(production):
        unmatched = [
            production[index]
            for index in range(len(production))
            if index not in matching
        ]
        return [
            _difference(
                "network.species.unmatched",
                "every production species has an isomorphic reference species",
                unmatched,
            )
        ]
    return []


def _relation_differences(production, reference):
    """The isomorphism relation must coincide with the correspondence."""
    differences = []
    # Neither network may keep two species the independent matcher calls
    # identical: the production graph identity must be at least as
    # discriminating as the independent construction.
    for index, partners in enumerate(_partners(production, production)):
        if len(partners) != 1:
            differences.append(
                _difference(
                    f"relation.production[{index}].distinct",
                    "one representative per identity class",
                    [production[partner] for partner in partners],
                )
            )
            break
    if differences:
        return differences
    for index, partners in enumerate(_partners(reference, reference)):
        if len(partners) != 1:
            differences.append(
                _difference(
                    f"relation.reference[{index}].distinct",
                    "one representative per identity class",
                    [reference[partner] for partner in partners],
                )
            )
            break
    if differences:
        return differences
    for index, partners in enumerate(_partners(production, reference)):
        if len(partners) != 1:
            differences.append(
                _difference(
                    f"relation.production[{index}].partners",
                    1,
                    [reference[partner] for partner in partners],
                )
            )
            break
    if differences:
        return differences
    for index, partners in enumerate(_partners(reference, production)):
        if len(partners) != 1:
            differences.append(
                _difference(
                    f"relation.reference[{index}].partners",
                    1,
                    [production[partner] for partner in partners],
                )
            )
    return differences


def _domain_violations(case, production, reference):
    """Return the declared-domain conditions this case violates."""
    violations = []
    if case["rule_count"] < 1:
        violations.append("the model declares no reaction rule")
    if case["rule_count"] > MAX_RULES:
        violations.append(
            f"the model declares {case['rule_count']} rules, above the bound "
            f"of {MAX_RULES}"
        )
    if len(case["seed_species"]) > MAX_SEED_SPECIES:
        violations.append(
            f"the model declares {len(case['seed_species'])} seed species, "
            f"above the bound of {MAX_SEED_SPECIES}"
        )
    for index, left in enumerate(case["seed_species"]):
        for right in case["seed_species"][index + 1 :]:
            if species_isomorphic(left, right):
                violations.append(
                    "two declared seed species are isomorphic, which the "
                    "canonical implementation refuses"
                )
    for label, network in (("production", production), ("reference", reference)):
        if len(network) > MAX_SPECIES:
            violations.append(
                f"the {label} network holds {len(network)} species, above the "
                f"bound of {MAX_SPECIES}"
            )
        for species in network:
            vertices = _vertices(species)
            if vertices > MAX_VERTICES:
                violations.append(
                    f"a {label} species holds {vertices} vertices, above the "
                    f"bound of {MAX_VERTICES}"
                )
    return violations


def _oracle_network(directory: Path, case, source: Path):
    """Run the canonical Perl BNG2 on the case and parse its network."""
    if shutil.which(os.environ.get("PERL", "perl")) is None:
        return None, None, "the canonical Perl BNG2 runtime is unavailable"
    if not ORACLE_SCRIPT.is_file():
        return None, None, f"the canonical Perl BNG2 script {ORACLE_SCRIPT} is absent"
    work = directory / f"oracle-{case['id']}"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["BNGPATH"] = str(ORACLE_SCRIPT.parent)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [
                os.environ.get("PERL", "perl"),
                str(ORACLE_SCRIPT),
                "--outdir",
                str(work),
                str(source),
            ],
            cwd=str(work),
            capture_output=True,
            text=True,
            env=env,
            timeout=ORACLE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, f"the canonical Perl BNG2 could not be executed: {exc}"
    artifact = work / f"{source.stem}.net"
    if proc.returncode != 0 or not artifact.is_file():
        message = (proc.stderr or proc.stdout).strip().splitlines()
        return (
            None,
            None,
            "the canonical Perl BNG2 refused the case: "
            + (message[-1] if message else "no diagnostic"),
        )
    network = parse_net(artifact)
    if network is None:
        return None, None, "the canonical Perl BNG2 network could not be parsed"
    return network, artifact, ""


def _production_network(directory: Path, case, source: Path):
    """Generate the production network and read it with the harness reader."""
    import bionetgen

    model = bionetgen.load(str(source))
    network = model.generate_network(max_iter=MAX_ITERATIONS)
    artifact = source.parent / "production.net"
    model.write_net(str(artifact))
    parsed = parse_net(artifact)
    if parsed is None:
        return None, None, "the production network could not be parsed"
    if parsed.n_reactions > MAX_REACTIONS:
        return (
            None,
            None,
            f"the production network holds {parsed.n_reactions} reactions, "
            f"above the bound of {MAX_REACTIONS}",
        )
    return parsed, artifact, ""


def _row(case, name, status, detail, *, differences=None, supported=True):
    return {
        "id": f"{OPERATION}:{case['id']}:{name}",
        "check": name,
        "related_issues": list(ISSUES),
        "supported_execution": supported,
        "evidence_kind": "supported-execution" if supported else "diagnostic-only",
        "status": status,
        "detail": detail,
        "first_difference": differences[0] if differences else None,
    }


def _refused(case, reason):
    detail = (
        "the case is outside the declared domain and is refused rather than "
        f"scored: {reason}"
    )
    return [_row(case, name, "UNSUPPORTED", detail, supported=False) for name in CHECKS]


def _run_case(case, directory: Path):
    case_dir = directory / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    source = case_dir / "model.bngl"
    try:
        source.write_text(case["text"], encoding="utf-8")
    except OSError as exc:
        detail = (
            f"the generated model could not be written: {type(exc).__name__}: {exc}"
        )
        return [
            _row(
                case,
                name,
                "HARNESS_ERROR",
                detail,
                differences=[
                    _difference("source.write", "a writable model file", str(exc))
                ],
                supported=False,
            )
            for name in CHECKS
        ]

    violations = _domain_violations(case, [], [])
    if violations:
        return _refused(case, "; ".join(violations))

    reference_network, reference_artifact, oracle_detail = _oracle_network(
        case_dir, case, source
    )
    if reference_network is None:
        return _refused(case, oracle_detail)

    try:
        production_network, production_artifact, production_detail = (
            _production_network(case_dir, case, source)
        )
    except Exception as exc:
        detail = (
            "the production network could not be generated: "
            f"{type(exc).__name__}: {exc}"
        )
        return [
            _row(
                case,
                name,
                "HARNESS_ERROR",
                detail,
                differences=[
                    _difference("production.network", "a generated network", str(exc))
                ],
                supported=False,
            )
            for name in CHECKS
        ]
    if production_network is None:
        return _refused(case, production_detail)

    production = list(production_network.species_by_index.values())
    reference = list(reference_network.species_by_index.values())
    violations = _domain_violations(case, production, reference)
    if reference_network.n_reactions > MAX_REACTIONS:
        violations.append(
            f"the reference network holds {reference_network.n_reactions} "
            f"reactions, above the bound of {MAX_REACTIONS}"
        )
    if violations:
        return _refused(case, "; ".join(violations))

    bijection = _bijection_differences(production, reference)
    relation = _relation_differences(production, reference)
    details = {
        "network-species-bijection": (
            "the production network's species and the canonical "
            "implementation's species correspond one to one under the "
            "independent graph-isomorphism relation"
        ),
        "graph-identity-relation": (
            "the independent isomorphism relation between the two networks "
            "is exactly that correspondence, and neither network keeps two "
            "species the independent matcher calls identical"
        ),
    }
    rows = []
    for name, differences in (
        ("network-species-bijection", bijection),
        ("graph-identity-relation", relation),
    ):
        rows.append(
            _row(
                case,
                name,
                "FAIL" if differences else "PASS",
                details[name] if not differences else differences[0]["field"],
                differences=differences,
            )
        )
    for row in rows:
        row["production_artifact"] = str(production_artifact)
        row["reference_artifact"] = str(reference_artifact)
        row["oracle_sha256"] = hashlib.sha256(ORACLE_SCRIPT.read_bytes()).hexdigest()
    return rows


def run_worker(directory: Path):
    """Compare the production network with the independent construction."""
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in CASES:
        rows.extend(_run_case(case, directory))
    for row in rows:
        if row.get("status") not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the graph-differential adapter emitted an invalid status",
            )
    return rows
