"""Small, live independent probes. Known discrepancies are real failures, never xfails.

These fixtures supplement diagnostic coverage; they do not modify the frozen
release corpus or claim that a bounded network is a complete scientific model.
"""

from __future__ import annotations

import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from tests.validation import campaign, conformance, contracts, scientific_contracts
from tests.validation.simulation_contract import run_simulation
from tests.validation.strict import require_oracle

PROBES = Path(__file__).with_name("probes")


@pytest.fixture(scope="module")
def probe(tmp_path_factory, bng_cpp):
    script = Path(os.environ.get("BNG2_PERL", "/missing/BNG2.pl"))
    require_oracle(
        script.is_file(),
        "diagnostic probes require live BNG2_PERL; goldens are not substituted",
    )
    digest = os.environ.get("BNG2_NETWORK_SHA256")
    require_oracle(
        bool(digest),
        "diagnostic probes require BNG2_NETWORK_SHA256 for the independently built binary",
    )
    lock = json.loads((conformance.ROOT / "provenance/upstreams.lock.yml").read_text())
    reference = conformance._reference(
        script.resolve().parent.parent, "bionetgen", lock, bng_cpp
    )
    binary = script.parent / "bin/run_network"
    campaign.verify_digest(binary, digest)
    campaign.reject_shared_engine(bng_cpp, binary)
    reference.update(network_binary=str(binary.resolve()), network_binary_sha256=digest)
    directory = tmp_path_factory.mktemp("diagnostic-probes")
    args = Namespace(
        bng_cpp=bng_cpp,
        case_timeout=20,
        network_iterations=4,
        max_aggregate=8,
        simulation_end=1.0,
        simulation_steps=20,
    )
    env = {
        **os.environ,
        "PERL": reference["interpreter"],
        "BNGPATH": str(script.parent),
    }
    cache = {}

    def get(name):
        if name not in cache:
            source = PROBES / (name + ".bngl")
            rows = conformance._model(name, source, args, directory, reference, env)
            work = directory / "models" / name
            for route in ("bngl", "net-reload"):
                rows += run_simulation(
                    name,
                    work,
                    reference,
                    args,
                    env,
                    [
                        r
                        for r in rows
                        if not r.get("aggregate") and r.get("route") is None
                    ],
                    route=route,
                )
            (work / "probe-results.json").write_text(json.dumps(rows, indent=2) + "\n")
            cache[name] = (work, rows)
        return cache[name]

    return get


def require_contract(probe, name, check, route=None):
    work, rows = probe(name)
    found = [r for r in rows if r.get("check") == check and r.get("route") == route]
    if len(found) != 1:
        upstream = [
            r
            for r in rows
            if r["status"] in {"FAIL", "HARNESS_ERROR", "TIMEOUT"}
            and (route is None or r.get("route") == route)
        ]
        pytest.fail(
            f"{name} / {route} / {check}: not reached. Earliest failed prerequisite: "
            + json.dumps(upstream[:1], indent=2)
            + f"\nComplete evidence: {work}/probe-results.json"
        )
    row = found[0]
    assert (
        row["status"] == "PASS"
    ), f"{row['id']}: {row['status']}: {row.get('detail','')}\nEvidence: {work}/probe-results.json\nBlocked by: {row.get('blocked_by',[])}"
    return work, row


def scientific_inputs(probe, name, kind="cdat"):
    require_contract(probe, name, kind + ".time-grid", "bngl")
    work, _ = require_contract(probe, name, kind + ".columns", "bngl")
    return work


def test_set_then_add_is_visible_in_exported_seed_amount(probe):
    work, rows = probe("set_add_initial")
    net = contracts.strict_network(work / "reference/set_add_initial.net")
    assert (
        float(net.initial_amounts[1]) == 200
    ), "independent reference must establish 100+100=200 before judging BNG3"
    require_contract(probe, "set_add_initial", "initial-amounts")


def test_net_reload_preserves_all_declared_observable_columns(probe):
    require_contract(probe, "first_order", "gdat.columns", "net-reload")


def test_net_reload_accepts_an_empty_declared_observable_group(probe):
    require_contract(probe, "empty_observable", "cdat.artifact-validity", "net-reload")
    require_contract(probe, "empty_observable", "gdat.columns", "net-reload")


def test_net_reload_preserves_dynamic_rate_function_trajectory(probe):
    require_contract(probe, "dynamic_function", "cdat.values", "net-reload")


def test_cdat_identifies_constant_species_without_discarding_its_marker(probe):
    require_contract(probe, "constant_cdat", "cdat.columns", "bngl")


def test_cdat_identifies_compartments_when_graph_labels_are_shared(probe):
    require_contract(probe, "compartment_cdat", "cdat.artifact-validity", "bngl")
    require_contract(probe, "compartment_cdat", "cdat.columns", "bngl")


@pytest.mark.parametrize("kind", ["cdat", "gdat"])
def test_source_first_order_trajectory_matches_independent_reference(probe, kind):
    require_contract(probe, "first_order", kind + ".values", "bngl")


@pytest.mark.parametrize("side", ["reference", "subject"])
def test_first_order_trajectory_satisfies_independent_analytic_solution(probe, side):
    work = scientific_inputs(probe, "first_order")
    net = contracts.strict_network(work / side / "first_order.net")
    directory = work / "simulation-bngl" / side
    data, columns = contracts._trajectory(directory / "trajectory.cdat")
    mapping = contracts.species_columns(columns, net)
    a = next(i for i, graph in net.species_by_index.items() if graph == "A()")
    row = scientific_contracts.first_order_decay(
        data[:, 0], data[:, columns.index(mapping[a])], initial=10, rate=0.5
    )
    assert row["status"] == "PASS", f"{side}: A(t)=10*exp(-0.5*t): {row}"


@pytest.mark.parametrize("side", ["reference", "subject"])
def test_first_order_species_total_is_conserved_at_every_sample(probe, side):
    work = scientific_inputs(probe, "first_order")
    data, columns = contracts._trajectory(
        work / "simulation-bngl" / side / "trajectory.cdat"
    )
    row = scientific_contracts.conserved_total(data[:, 0], data[:, 1:], [1, 1], 13)
    assert row["status"] == "PASS", f"{side}: A+B=13 at every requested time: {row}"


@pytest.mark.parametrize("side", ["reference", "subject"])
def test_first_order_species_remain_nonnegative_at_every_sample(probe, side):
    work = scientific_inputs(probe, "first_order")
    data, columns = contracts._trajectory(
        work / "simulation-bngl" / side / "trajectory.cdat"
    )
    row = scientific_contracts.nonnegative(data[:, 0], data[:, 1:], columns[1:])
    assert row["status"] == "PASS", f"{side}: {row}"


@pytest.mark.parametrize("side", ["reference", "subject"])
def test_declared_observables_reconstruct_from_species_at_every_sample(probe, side):
    work = scientific_inputs(probe, "first_order", "gdat")
    scientific_inputs(probe, "first_order", "cdat")
    directory = work / "simulation-bngl" / side
    row = scientific_contracts.observable_projection(
        work / side / "first_order.net",
        directory / "trajectory.cdat",
        directory / "trajectory.gdat",
    )
    assert (
        row["status"] == "PASS"
    ), f"{side}: weighted NET groups must reconstruct gdat: {row}"


def test_identical_reactant_symmetry_has_one_half_statistical_factor(probe):
    from tests.validation.compare import _resolve_rate

    work, _ = require_contract(probe, "symmetric_dimer", "reaction-rates")
    for side in ("reference", "subject"):
        net = contracts.strict_network(work / side / "symmetric_dimer.net")
        assert net.n_species == 2 and net.n_reactions == 1
        reactants, products, rate = net._raw[0]
        assert len(reactants) == 2 and len(products) == 1
        assert (
            float(
                _resolve_rate(
                    rate,
                    net.rate_defs,
                    "value",
                    net.rate_functions,
                    net.rate_observables,
                )
            )
            == 0.05
        ), f"{side}: k=0.1 with identical-reactant symmetry must give k/2, not k/4 or k"


def test_dimer_observable_counts_molecules_and_species_with_distinct_weights(probe):
    work, _ = require_contract(probe, "symmetric_dimer", "observable-weights")
    for side in ("reference", "subject"):
        net = contracts.strict_network(work / side / "symmetric_dimer.net")
        groups = {name: entries for name, entries in net.groups.values()}
        assert sorted(groups["Total"].values()) == [1.0, 2.0]
        assert list(groups["Dimer"].values()) == [1.0]


def test_symmetric_dimer_species_trajectory_matches_independent_reference(probe):
    require_contract(probe, "symmetric_dimer", "cdat.values", "bngl")


@pytest.mark.parametrize("side", ["reference", "subject"])
def test_symmetric_dimer_conserves_molecular_units_at_every_sample(probe, side):
    work = scientific_inputs(probe, "symmetric_dimer")
    scientific_inputs(probe, "symmetric_dimer", "gdat")
    directory = work / "simulation-bngl" / side
    row = scientific_contracts.observable_projection(
        work / side / "symmetric_dimer.net",
        directory / "trajectory.cdat",
        directory / "trajectory.gdat",
    )
    assert row["status"] == "PASS", str(row)
    observed, columns = contracts._trajectory(directory / "trajectory.gdat")
    assert all(
        abs(value - 10) < 1e-8 for value in observed[:, columns.index("Total")]
    ), f"{side}: molecular units changed during dimerization"
