"""Mutations must fail the particular biochemical/numerical invariant they break."""

import numpy as np
import pytest

from tests.validation.scientific_contracts import (
    first_order_decay,
    conserved_total,
    nonnegative,
    observable_projection,
)
from tests.validation.test_contracts import networks


def test_analytic_decay_rejects_wrong_rate_even_when_total_is_conserved():
    t = np.array([0.0, 0.5, 1.0])
    a = 10 * np.exp(-0.8 * t)
    b = 13 - a
    assert conserved_total(t, np.column_stack([a, b]), [1, 1], 13)["status"] == "PASS"
    row = first_order_decay(t, a, initial=10, rate=0.5)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["time"] == 0.5


def test_conservation_reports_first_species_total_drift():
    row = conserved_total(
        np.array([0.0, 1.0]), np.array([[10.0, 3.0], [9.0, 3.0]]), [1, 1], 13
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["time"] == 1.0
    assert row["first_difference"]["subject"] == 12.0


def test_positivity_detects_one_negative_species_without_averaging_it_away():
    row = nonnegative(
        np.array([0.0, 1.0]), np.array([[10.0, 0.0], [11.0, -0.01]]), ["A", "B"]
    )
    assert row["status"] == "FAIL"
    assert row["first_difference"]["column"] == "B"
    assert row["first_difference"]["subject"] == -0.01


def test_observable_reconstruction_detects_consistent_but_wrong_gdat(tmp_path):
    net, _ = networks(tmp_path)
    cdat = tmp_path / "x.cdat"
    gdat = tmp_path / "x.gdat"
    cdat.write_text("# time S1 S2\n0 10 0\n1 9 1\n")
    gdat.write_text("# time total\n0 10\n1 9\n")
    row = observable_projection(net, cdat, gdat)
    assert row["status"] == "FAIL"
    assert row["first_difference"]["reference"] == 10.0
    assert row["first_difference"]["subject"] == 9.0


def test_observable_reconstruction_accepts_graph_and_numeric_cdat_headers(tmp_path):
    net, _ = networks(tmp_path)
    cdat = tmp_path / "x.cdat"
    gdat = tmp_path / "x.gdat"
    cdat.write_text("# time C() B(y!9).A(x!9)\n0 0 10\n1 1 9\n")
    gdat.write_text("# time total\n0 10\n1 10\n")
    assert observable_projection(net, cdat, gdat)["status"] == "PASS"


@pytest.mark.parametrize(
    "fn,args",
    [
        (first_order_decay, (np.array([0.0, 1.0]), np.array([10.0, float("nan")]))),
        (
            nonnegative,
            (np.array([0.0, 1.0]), np.array([[10.0], [float("nan")]]), ["A"]),
        ),
        (
            conserved_total,
            (np.array([0.0, 1.0]), np.array([[10.0], [float("nan")]]), [1], 10),
        ),
    ],
)
def test_nonfinite_samples_never_pass_scientific_contract(fn, args):
    kwargs = {"initial": 10, "rate": 0.5} if fn is first_order_decay else {}
    assert fn(*args, **kwargs)["status"] == "HARNESS_ERROR"


@pytest.mark.parametrize("kind", ["cdat", "gdat"])
def test_live_scientific_controls_require_the_entire_requested_schedule(tmp_path, kind):
    from tests.validation.test_diagnostic_probes import scientific_inputs

    rows = [
        {
            "id": "x:" + kind + ".columns",
            "check": kind + ".columns",
            "route": "bngl",
            "status": "PASS",
        },
        {
            "id": "x:" + kind + ".time-grid",
            "check": kind + ".time-grid",
            "route": "bngl",
            "status": "FAIL",
            "detail": "reference and subject both truncated",
        },
    ]
    with pytest.raises(AssertionError, match="time-grid"):
        scientific_inputs(lambda _: (tmp_path, rows), "x", kind)
