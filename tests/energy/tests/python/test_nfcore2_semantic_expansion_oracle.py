import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/energy/fixtures/semantic/nfcore2_semantic_expansion.json"
PROVENANCE = ROOT / "provenance/semantic-expansion-2026-09-08.json"
STATUS = ROOT / "docs/architecture_handoffs/SEMANTIC_EXPANSION_STATUS_2026-09-08.md"


def load_cases():
    return json.loads(FIXTURE.read_text()), json.loads(PROVENANCE.read_text())


def connected(edges, source, target):
    graph = {}
    for left, right in edges:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    pending, seen = [source], {source}
    while pending:
        current = pending.pop(0)
        if current == target:
            return True
        for neighbor in graph.get(current, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return False


def test_semantic_expansion_inventory_names_all_six_families():
    cases, provenance = load_cases()
    contracts = {item["id"] for item in provenance["contracts"]}
    assert contracts == set(cases)
    assert all(item["tests"] for item in provenance["contracts"])


def test_population_transform_oracle():
    case, _ = load_cases()
    value = case["population-transforms"]["initial"]
    for delta in case["population-transforms"]["deltas"]:
        value += delta
    assert value == case["population-transforms"]["expected"]


def test_connected_to_graph_oracle():
    case, _ = load_cases()
    graph = case["root-graph-connectedTo"]
    assert connected(graph["edges"], graph["source"], graph["target"]) is graph["expected"]
    assert connected(graph["edges"], graph["source"], 99) is False


def test_synthesis_oracle():
    case, _ = load_cases()
    data = case["synthesis"]
    assert data["initial_particles"] + data["created_particles"] == data["expected_particles"]


def test_compartment_move_oracle():
    case, _ = load_cases()
    data = case["compartments-moves"]
    assert data["initial"] == data["required"]
    assert data["destination"] == data["expected"]


def test_local_and_dor_rate_oracle():
    case, _ = load_cases()
    local = case["local-function-dor"]["local"]
    dor = case["local-function-dor"]["dor"]
    local_rate = local["base"] * (local["offset"] + local["slope"] * local["state"])
    dor_rate = dor["base"] * dor["weight"] * dor["left"] * dor["right"]
    assert local_rate == local["expected"]
    assert dor_rate == dor["expected"]


def test_whole_species_deletion_oracle():
    case, _ = load_cases()
    data = case["whole-species-deletion"]
    component = {node for node in data["initial_nodes"] if connected(data["edges"], data["root"], node)}
    assert sorted(set(data["initial_nodes"]) - component) == data["expected_remaining"]


def test_expanded_goal_keeps_broader_ceilings_explicit_and_fail_closed():
    _, provenance = load_cases()
    expected = {
        "arbitrary internal graph expressions",
        "general local-function/DOR evaluation",
        "compartment hierarchy/species-carrying moves",
        "conditional deletion",
        "independent full NFsim/BNG2 parity",
    }
    remaining = set(provenance["remaining_fallbacks"])
    assert expected <= remaining
    status = STATUS.read_text()
    for ceiling in expected:
        assert ceiling in status
    assert "No NFsim, NFnext, Rasi, or uORP" in status
    assert "parity claim" in status
