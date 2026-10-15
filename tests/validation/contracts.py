"""Granular artifact contracts; reuse the independent graph/rate comparator.

These are observations of serialized networks and bounded deterministic output,
not proofs of general kinetic equivalence or global canonicalization.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import numpy as np

from . import compare


def _row(check, ok, detail="", *, blocked_by=None, **evidence):
    return dict(
        check=check,
        status="NOT_TESTED" if blocked_by else ("PASS" if ok else "FAIL"),
        detail=detail,
        **({"blocked_by": blocked_by} if blocked_by else {}),
        **evidence,
    )


def strict_network(path):
    """Reject artifacts the permissive historical NET reader cannot score safely."""
    path = Path(path)
    section = None
    seen, indices, references = set(), {}, []
    empty_groups = {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        if text.startswith("begin "):
            name = text[6:].strip()
            if section is not None or name in seen:
                raise ValueError(f"{path.name}:{line_no}: repeated/nested block {name}")
            section = name
            seen.add(name)
            continue
        if text.startswith("end "):
            if text[4:].strip() != section:
                raise ValueError(f"{path.name}:{line_no}: mismatched block end")
            section = None
            continue
        if section not in {"species", "reactions", "groups"}:
            continue
        parts = text.split()
        if not parts[0].isdigit() or int(parts[0]) < 1:
            raise ValueError(f"{path.name}:{line_no}: invalid {section} index")
        index = int(parts[0])
        keys = indices.setdefault(section, set())
        if index in keys:
            raise ValueError(
                f"{path.name}:{line_no}: duplicate {section} index {index}"
            )
        keys.add(index)
        if len(parts) < (
            4 if section == "reactions" else 2 if section == "groups" else 3
        ):
            raise ValueError(f"{path.name}:{line_no}: incomplete {section} row")
        if section == "species":
            graph = parts[1]
            if (
                graph.endswith(".")
                or ".." in graph
                or compare._parse_species_graph(graph) is None
            ):
                raise ValueError(
                    f"{path.name}:{line_no}: invalid species graph {graph}"
                )
            bonds = Counter(re.findall(r"!(\d+)", graph))
            if any(n != 2 for n in bonds.values()) or re.search(r"![+?]", graph):
                raise ValueError(
                    f"{path.name}:{line_no}: nonconcrete or dangling species bonds"
                )
        elif section == "reactions":
            for side in parts[1:3]:
                if not re.fullmatch(r"\d+(?:,\d+)*", side):
                    raise ValueError(
                        f"{path.name}:{line_no}: invalid reaction participants"
                    )
                references += [int(i) for i in side.split(",") if i != "0"]
        else:
            if len(parts) == 2:
                empty_groups[index] = (parts[1], {})
            for item in "".join(parts[2:]).split(","):
                if not item:
                    continue
                weight, idx = item.split("*", 1) if "*" in item else ("1", item)
                if not np.isfinite(float(weight)) or not idx.isdigit():
                    raise ValueError(
                        f"{path.name}:{line_no}: invalid observable weight/index"
                    )
                references.append(int(idx))
    if section is not None or not {"species", "reactions"} <= seen:
        raise ValueError(f"{path.name}: missing/unterminated network blocks")
    if set(references) - indices.get("species", set()):
        raise ValueError(
            f"{path.name}: dangling species references {sorted(set(references) - indices.get('species', set()))}"
        )
    net = compare.parse_net(path)
    if net is None:
        raise ValueError(f"{path.name}: no parseable network")
    net.groups.update(empty_groups)
    if len({name for name, _ in net.groups.values()}) != len(net.groups):
        raise ValueError(f"{path.name}: duplicate observable names")
    buckets = {}
    for index, graph in net.species_by_index.items():
        key = compare._species_prefilter_key(graph, (), False)
        bucket = buckets.setdefault(key, [])
        if any(compare.species_isomorphic(graph, other) for other in bucket):
            raise ValueError(
                f"{path.name}: duplicate isomorphic species; mapping ambiguous at {index}"
            )
        bucket.append(graph)
    for expression in list(net.initial_amounts.values()) + [r[2] for r in net._raw]:
        if re.search(r"\b(?:nan|inf|infinity)\b", expression, re.I):
            raise ValueError(f"{path.name}: nonfinite amount/rate")
    return net


def network_contracts(reference, subject):
    try:
        ref, test = strict_network(reference), strict_network(subject)
    except (ValueError, OSError) as exc:
        return [
            dict(check="artifact-validity", status="HARNESS_ERROR", detail=str(exc))
        ]
    mapping = compare._species_index_mapping(ref, test)
    identity = len(mapping) == ref.n_species == test.n_species
    ri = {
        i: ("species", mapping[i]) if i in mapping else ("ref", i)
        for i in ref.species_by_index
    }
    ti = {i: ("species", i) for i in test.species_by_index}
    left, lp = compare._reaction_view(ref, ri, compare_rates=False)
    right, rp = compare._reaction_view(test, ti, compare_rates=False)
    topology = set(left) == set(right)
    multiplicity = left == right
    diff = compare.compare_net(ref, test, compare_initial_amounts=True)
    names_ref = {
        name: entries for name, entries in compare._group_view(ref, ri).values()
    }
    names_test = {
        name: entries for name, entries in compare._group_view(test, ti).values()
    }
    names_equal = names_ref.keys() == names_test.keys()
    blocked = None if identity else "species-identity"
    rows = [
        _row("artifact-validity", True),
        _row(
            "species-count",
            ref.n_species == test.n_species,
            f"reference={ref.n_species}, subject={test.n_species}",
        ),
        _row(
            "species-identity",
            identity,
            f"missing={sorted(diff.species_only_ref)}, extra={sorted(diff.species_only_test)}",
            species_mapping={str(k): v for k, v in sorted(mapping.items())},
        ),
        _row(
            "initial-amounts",
            not diff.initial_amounts_changed,
            f"changed={sorted(diff.initial_amounts_changed)}",
            blocked_by=blocked,
        ),
        _row(
            "reaction-count",
            ref.n_reactions == test.n_reactions,
            f"reference={ref.n_reactions}, subject={test.n_reactions}",
        ),
        _row(
            "reaction-stoichiometry",
            topology,
            f"missing={list((left-right).elements())[:5]}, extra={list((right-left).elements())[:5]}",
            blocked_by=blocked,
        ),
        _row(
            "reaction-multiplicity",
            multiplicity,
            f"missing={sum((left-right).values())}, extra={sum((right-left).values())}",
            blocked_by=blocked,
        ),
        _row(
            "reaction-rates",
            not diff.reactions_only_ref and not diff.reactions_only_test,
            diff.summary(),
            blocked_by=blocked or (None if multiplicity else "reaction-multiplicity"),
        ),
        _row(
            "observable-names",
            names_equal,
            f"missing={sorted(names_ref.keys()-names_test.keys())}, extra={sorted(names_test.keys()-names_ref.keys())}",
        ),
        _row(
            "observable-weights",
            names_ref == names_test,
            f"changed={[name for name in names_ref.keys() & names_test.keys() if names_ref[name] != names_test[name]]}",
            blocked_by=blocked or (None if names_equal else "observable-names"),
        ),
    ]
    return rows


def _trajectory(path):
    data, columns = compare.parse_gdat(path)
    if data is None or data.ndim != 2 or data.shape[1] != len(columns) or len(data) < 2:
        raise ValueError("missing, ragged or insufficient trajectory")
    if (
        columns[0] != "time"
        or len(columns) != len(set(columns))
        or not np.all(np.isfinite(data))
    ):
        raise ValueError(
            "trajectory requires unique time-first columns and finite values"
        )
    return data, columns


def species_columns(columns, network):
    """Map serialized cdat columns to generated-network indices unambiguously."""
    found = {}
    for name in columns[1:]:
        match = re.fullmatch(r"(?:S|s)?(\d+)", name)
        candidates = (
            [int(match[1])]
            if match
            else [
                i
                for i, graph in network.species_by_index.items()
                if compare.species_isomorphic(graph, name)
            ]
        )
        if len(candidates) != 1 or candidates[0] in found:
            raise ValueError("ambiguous cdat species column " + name)
        found[candidates[0]] = name
    if set(found) != set(network.species_by_index):
        raise ValueError("cdat columns do not cover every generated species")
    return found


def trajectory_contracts(
    reference,
    subject,
    *,
    kind,
    networks=None,
    expected_times=None,
    rtol=1e-6,
    atol=1e-9,
):
    """Require the complete requested grid, then exact named/graph-mapped columns.

    Numeric acceptance is abs(delta) <= atol + rtol*abs(reference). Neither
    endpoint-only checks nor time/name intersections can qualify this contract.
    """
    if kind not in {"gdat", "cdat"}:
        raise ValueError("trajectory kind must be gdat or cdat")
    if not np.isfinite(rtol) or not np.isfinite(atol) or min(rtol, atol) < 0:
        raise ValueError("invalid numeric tolerances")
    try:
        ref, rc = _trajectory(reference)
        test, tc = _trajectory(subject)
    except (ValueError, OSError) as exc:
        return [
            dict(
                check=kind + ".artifact-validity",
                status="HARNESS_ERROR",
                detail=str(exc),
            )
        ]
    rows = [_row(kind + ".artifact-validity", True)]
    grid = ref.shape[0] == test.shape[0] and np.allclose(
        ref[:, 0], test[:, 0], rtol=0, atol=1e-9
    )
    grid = grid and np.all(np.diff(ref[:, 0]) > 0) and np.all(np.diff(test[:, 0]) > 0)
    if expected_times is not None:
        times = np.asarray(expected_times)
        grid = (
            grid
            and len(ref) == len(times)
            and np.allclose(ref[:, 0], times, rtol=0, atol=1e-9)
        )
    rows.append(
        _row(
            kind + ".time-grid",
            bool(grid),
            f"reference_rows={len(ref)}, subject_rows={len(test)}, requested_rows={len(expected_times) if expected_times is not None else 'reference grid'}",
        )
    )
    mapping = {}
    if kind == "cdat":
        try:
            if networks is None:
                raise ValueError("cdat requires both generated networks")
            rn, tn = (strict_network(p) for p in networks)
            mapping = compare._species_index_mapping(rn, tn)
            if len(mapping) != rn.n_species or len(mapping) != tn.n_species:
                raise ValueError("cdat requires complete species graph bijection")

            rnames, tnames = species_columns(rc, rn), species_columns(tc, tn)
            paired = [(rnames[i], tnames[j]) for i, j in sorted(mapping.items())]
        except (ValueError, OSError) as exc:
            rows.append(_row(kind + ".columns", False, str(exc)))
            rows.append(_row(kind + ".values", False, blocked_by=kind + ".columns"))
            return rows
    else:
        paired = [(name, name) for name in rc[1:] if name in tc[1:]]
    names_ok = len(paired) == len(rc) - 1 == len(tc) - 1 and bool(paired)
    rows.append(
        _row(
            kind + ".columns",
            names_ok,
            f"reference={rc[1:]}, subject={tc[1:]}",
            **(
                {"species_mapping": {str(i): j for i, j in sorted(mapping.items())}}
                if kind == "cdat"
                else {}
            ),
        )
    )
    blocked = (
        None if grid and names_ok else kind + (".time-grid" if not grid else ".columns")
    )
    if blocked:
        rows.append(_row(kind + ".values", False, blocked_by=blocked))
        return rows
    rv = ref[:, [rc.index(a) for a, b in paired]]
    tv = test[:, [tc.index(b) for a, b in paired]]
    error = np.abs(tv - rv)
    accepted = error <= atol + rtol * np.abs(rv)
    evidence = {"rtol": rtol, "atol": atol, "max_absolute_error": float(np.max(error))}
    if not accepted.all():
        i, j = np.argwhere(~accepted)[0]
        evidence["first_difference"] = {
            "column": paired[j][0],
            "time": float(ref[i, 0]),
            "reference": float(rv[i, j]),
            "subject": float(tv[i, j]),
            "absolute_error": float(error[i, j]),
        }
    rows.append(
        _row(
            kind + ".values",
            bool(accepted.all()),
            str(
                evidence.get(
                    "first_difference", "all samples within declared tolerances"
                )
            ),
            **evidence,
        )
    )
    return rows
