"""Fault injections for independently meaningful network/output contracts."""

from pathlib import Path

import pytest

from tests.validation.contracts import network_contracts, trajectory_contracts

NET = """begin parameters
1 k 2
end parameters
begin species
1 A(x!1).B(y!1) 10
2 C() 0
end species
begin reactions
1 1 2 k
end reactions
begin groups
1 total 1,2
end groups
"""


def networks(tmp_path, text=NET):
    ref, test = tmp_path / "ref.net", tmp_path / "test.net"
    ref.write_text(NET)
    test.write_text(text)
    return ref, test


def checks(rows):
    return {r["check"]: r for r in rows}


@pytest.mark.parametrize(
    "old,new,check",
    [
        ("A(x!1).B(y!1)", "A(x!1).B(y~P!1)", "species-identity"),
        (" 10\n", " 20\n", "initial-amounts"),
        ("1 1 2 k", "1 1,1 2 k", "reaction-stoichiometry"),
        ("1 1 2 k", "1 1 2 k\n2 1 2 k", "reaction-multiplicity"),
        ("1 k 2", "1 k 3", "reaction-rates"),
        ("total 1,2", "total 2*1,2", "observable-weights"),
        ("total 1,2", "phantom 1,2", "observable-names"),
    ],
)
def test_each_network_mutation_names_its_failed_contract(tmp_path, old, new, check):
    rows = checks(network_contracts(*networks(tmp_path, NET.replace(old, new))))
    assert rows[check]["status"] == "FAIL"
    assert rows[check]["detail"]


def test_bond_renumbering_and_species_order_preserve_all_contracts(tmp_path):
    text = (
        NET.replace("1 A(x!1).B(y!1) 10", "7 B(y!99).A(x!99) 10")
        .replace("2 C() 0", "3 C() 0")
        .replace("1 1 2 k", "1 7 3 k")
        .replace("total 1,2", "total 7,3")
    )
    assert all(
        r["status"] == "PASS" for r in network_contracts(*networks(tmp_path, text))
    )


@pytest.mark.parametrize(
    "old,new",
    [
        ("1 1 2 k", "1 1 2 k\n2 ??? 2 99"),
        ("A(x!1).B(y!1)", "A(x!1).B(y!1)."),
        ("A(x!1).B(y!1)", "A(x!1).B(y)"),
        ("2 C() 0", "2 C() 0\n3 C() 0"),
        ("1 1 2 k", "1 1 99 k"),
        ("total 1,2", "total nan*1,2"),
        ("end reactions", "end species"),
    ],
)
def test_malformed_network_cannot_compare_successfully(tmp_path, old, new):
    rows = network_contracts(*networks(tmp_path, NET.replace(old, new)))
    assert rows[0]["check"] == "artifact-validity"
    assert rows[0]["status"] == "HARNESS_ERROR"


def trajectory(tmp_path, suffix, ref_text, test_text, nets=None, expected_times=None):
    ref, test = tmp_path / f"ref.{suffix}", tmp_path / f"test.{suffix}"
    ref.write_text(ref_text)
    test.write_text(test_text)
    return checks(
        trajectory_contracts(
            ref, test, kind=suffix, networks=nets, expected_times=expected_times
        )
    )


@pytest.mark.parametrize(
    "times",
    ["0 1\n1 1\n", "0 1\n2 1\n", "0 1\n1 1\n2 1\n3 1\n", "0 1\n1 1\n1 1\n2 1\n"],
)
def test_missing_extra_or_duplicate_samples_fail_full_time_grid(tmp_path, times):
    rows = trajectory(
        tmp_path, "gdat", "# time A\n0 1\n1 1\n2 1\n", "# time A\n" + times
    )
    assert rows["gdat.time-grid"]["status"] == "FAIL"
    assert rows["gdat.values"]["status"] == "NOT_TESTED"


def test_both_truncated_trajectories_fail_the_requested_schedule(tmp_path):
    text = "# time A\n0 1\n1 1\n"
    rows = trajectory(tmp_path, "gdat", text, text, expected_times=[0, 1, 2])
    assert rows["gdat.time-grid"]["status"] == "FAIL"


def test_observable_mutation_records_first_time_and_values(tmp_path):
    rows = trajectory(
        tmp_path, "gdat", "# time A\n0 10\n1 9\n2 8\n", "# time A\n0 10\n1 7\n2 6\n"
    )
    row = rows["gdat.values"]
    assert row["status"] == "FAIL"
    assert row["first_difference"] == {
        "column": "A",
        "time": 1.0,
        "reference": 9.0,
        "subject": 7.0,
        "absolute_error": 2.0,
    }


def test_exact_observable_schema_rejects_missing_and_phantom_names(tmp_path):
    rows = trajectory(
        tmp_path, "gdat", "# time A\n0 1\n1 1\n", "# time phantom\n0 1\n1 1\n"
    )
    assert rows["gdat.columns"]["status"] == "FAIL"


def test_cdat_species_columns_use_network_graph_identity(tmp_path):
    nets = networks(
        tmp_path,
        NET.replace("1 A(x!1).B(y!1) 10", "7 B(y!4).A(x!4) 10")
        .replace("2 C() 0", "3 C() 0")
        .replace("1 1 2 k", "1 7 3 k")
        .replace("total 1,2", "total 7,3"),
    )
    rows = trajectory(
        tmp_path,
        "cdat",
        "# time S1 S2\n0 10 0\n1 9 1\n",
        "# time S3 S7\n0 0 10\n1 1 9\n",
        nets,
    )
    assert all(r["status"] == "PASS" for r in rows.values())
    assert rows["cdat.columns"]["species_mapping"] == {"1": 7, "2": 3}


def test_cdat_same_numeric_headers_do_not_hide_swapped_species(tmp_path):
    nets = networks(tmp_path)
    rows = trajectory(
        tmp_path,
        "cdat",
        "# time S1 S2\n0 10 0\n1 9 1\n",
        "# time S1 S2\n0 0 10\n1 1 9\n",
        nets,
    )
    assert rows["cdat.values"]["status"] == "FAIL"


@pytest.mark.parametrize(
    "text",
    [
        "# time A\n0 nan\n1 1\n",
        "# time A A\n0 1 1\n1 1 1\n",
        "# A\n0 1\n1 1\n",
        "# time A\n0 1\n1\n",
    ],
)
def test_invalid_output_never_becomes_numeric_pass(tmp_path, text):
    rows = trajectory(tmp_path, "gdat", "# time A\n0 1\n1 1\n", text)
    assert rows["gdat.artifact-validity"]["status"] == "HARNESS_ERROR"


def test_cdat_accepts_graph_labels_emitted_by_native_writer(tmp_path):
    nets = networks(tmp_path)
    rows = trajectory(
        tmp_path,
        "cdat",
        "# time S1 S2\n0 10 0\n1 9 1\n",
        "# time C() B(y!9).A(x!9)\n0 0 10\n1 1 9\n",
        nets,
    )
    assert all(r["status"] == "PASS" for r in rows.values())


def test_numeric_rate_precision_is_explicit_bounded_and_keeps_multiplicity(tmp_path):
    ref, subject = networks(tmp_path)
    ref.write_text(NET.replace("1 k 2", "1 k 0.16666667"))
    subject.write_text(NET.replace("1 k 2", "1 k 0.16666666666666666"))
    assert checks(network_contracts(ref, subject))["reaction-rates"]["status"] == "FAIL"
    assert (
        checks(network_contracts(ref, subject, numeric_rate_rtol=5e-8))[
            "reaction-rates"
        ]["status"]
        == "PASS"
    )
    subject.write_text(NET.replace("1 k 2", "1 k 0.1667"))
    assert (
        checks(network_contracts(ref, subject, numeric_rate_rtol=5e-8))[
            "reaction-rates"
        ]["status"]
        == "FAIL"
    )
    subject.write_text(
        NET.replace("1 k 2", "1 k 0.16666666666666666").replace(
            "1 1 2 k", "1 1 2 k\n2 1 2 k"
        )
    )
    assert (
        checks(network_contracts(ref, subject, numeric_rate_rtol=5e-8))[
            "reaction-multiplicity"
        ]["status"]
        == "FAIL"
    )


def test_numeric_rate_precision_preserves_small_rates_and_zero(tmp_path):
    ref, subject = networks(tmp_path)
    ref.write_text(NET.replace("1 k 2", "1 k 1e-20"))
    subject.write_text(NET.replace("1 k 2", "1 k 0"))
    assert (
        checks(network_contracts(ref, subject, numeric_rate_rtol=5e-8))[
            "reaction-rates"
        ]["status"]
        == "FAIL"
    )
