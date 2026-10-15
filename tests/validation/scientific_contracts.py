"""Independent analytic/algebraic checks for explicitly declared model invariants."""

from __future__ import annotations

import numpy as np

from . import contracts


def _check(check, times, actual, expected, columns, *, rtol=1e-6, atol=1e-9):
    times, actual, expected = (
        np.asarray(x, dtype=float) for x in (times, actual, expected)
    )
    if actual.ndim == 1:
        actual = actual[:, None]
    if expected.ndim == 1:
        expected = expected[:, None]
    valid = (
        times.ndim == 1
        and len(times) >= 2
        and np.all(np.diff(times) > 0)
        and actual.shape == expected.shape == (len(times), len(columns))
    )
    if not valid or not all(np.all(np.isfinite(x)) for x in (times, actual, expected)):
        return dict(
            check=check,
            status="HARNESS_ERROR",
            detail="nonfinite or inconsistent invariant inputs",
        )
    accepted = np.abs(actual - expected) <= atol + rtol * np.abs(expected)
    row = dict(
        check=check,
        status="PASS" if accepted.all() else "FAIL",
        detail="all samples satisfy the declared invariant",
        rtol=rtol,
        atol=atol,
    )
    if not accepted.all():
        i, j = np.argwhere(~accepted)[0]
        row["first_difference"] = dict(
            column=columns[j],
            time=float(times[i]),
            reference=float(expected[i, j]),
            subject=float(actual[i, j]),
            absolute_error=float(abs(expected[i, j] - actual[i, j])),
        )
        row["detail"] = str(row["first_difference"])
    return row


def first_order_decay(times, values, *, initial, rate):
    return _check(
        "analytic.first-order-decay",
        times,
        values,
        initial * np.exp(-rate * np.asarray(times)),
        ["A"],
    )


def conserved_total(times, species, weights, total):
    species = np.asarray(species)
    return _check(
        "invariant.conserved-total",
        times,
        species @ np.asarray(weights),
        np.full(len(times), total),
        ["weighted-total"],
        rtol=0,
        atol=1e-8,
    )


def nonnegative(times, species, columns):
    species = np.asarray(species)
    return _check(
        "invariant.nonnegative",
        times,
        species,
        np.maximum(species, 0),
        columns,
        rtol=0,
        atol=1e-9,
    )


def observable_projection(network, cdat, gdat):
    try:
        net = contracts.strict_network(network)
        species, sc = contracts._trajectory(cdat)
        observed, oc = contracts._trajectory(gdat)
        mapping = contracts.species_columns(sc, net)
        if len(species) != len(observed) or not np.allclose(
            species[:, 0], observed[:, 0], rtol=0, atol=1e-9
        ):
            raise ValueError("cdat/gdat time grids differ")
        names, expected = [], []
        for name, entries in net.groups.values():
            if name not in oc:
                raise ValueError("declared observable missing from gdat: " + name)
            names.append(name)
            expected.append(
                sum(
                    (
                        weight * species[:, sc.index(mapping[index])]
                        for index, weight in entries.items()
                    ),
                    np.zeros(len(species)),
                )
            )
        if not names:
            return dict(
                check="gdat.observable-projection",
                status="NOT_TESTED",
                applicability="no-observables",
                detail="no declared NET observable groups",
            )
        return _check(
            "gdat.observable-projection",
            species[:, 0],
            observed[:, [oc.index(name) for name in names]],
            np.column_stack(expected),
            names,
        )
    except (ValueError, OSError) as exc:
        return dict(
            check="gdat.observable-projection", status="HARNESS_ERROR", detail=str(exc)
        )
