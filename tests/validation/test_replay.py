"""A process exit is never accepted as a reproduced semantic contract."""

import json
import sys
from pathlib import Path

import pytest

from tests.validation import replay


def fixture(tmp_path, *, outcome="FAIL", wrong_check=False):
    script = tmp_path / "validator.py"
    script.write_text("""import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text())
output = pathlib.Path(sys.argv[sys.argv.index('--report-dir')+1])
output.mkdir(parents=True)
report['results'][0]['status'] = sys.argv[2]
if sys.argv[3] == 'wrong': report['results'][0]['id'] = 'different-check'
(output/'report.json').write_text(json.dumps(report))
raise SystemExit(1)
""")
    seed = tmp_path / "seed.json"
    document = {
        "source": {"revision": "a" * 40, "dirty": False},
        "configuration": {"cases": [{"id": "decay", "k": 0.1}], "seed": 7},
        "inputs": {},
        "references": {},
        "subject": {},
        "results": [
            {"id": "decay:rhs", "stage": "rhs", "status": "FAIL", "detail": "mismatch"}
        ],
    }
    seed.write_text(json.dumps(document))
    document["results"][0]["command"] = [
        sys.executable,
        str(script),
        str(seed),
        outcome,
        "wrong" if wrong_check else "right",
        "--report-dir",
        str(tmp_path / "old"),
    ]
    return document


def test_semantic_report_replay_accepts_named_check_despite_nonzero_process(tmp_path):
    document = fixture(tmp_path)
    result = replay.execute_case(
        document, document["results"][0], tmp_path / "replay", timeout=5
    )
    assert result["status"] == "OBSERVED"
    assert result["receipt"]["status"] == "FAIL"
    assert result["report"]["results"][0]["id"] == "decay:rhs"
    assert result["report"]["results"][0]["status"] == "FAIL"
    assert result["report"]["replay_evidence"]["report_sha256"]


def test_successful_named_check_is_retained_as_nondeterministic_evidence(tmp_path):
    document = fixture(tmp_path, outcome="PASS")
    result = replay.execute_case(
        document, document["results"][0], tmp_path / "replay", timeout=5
    )
    assert result["report"]["results"][0]["status"] == "PASS"


def test_missing_named_check_and_unsupported_command_never_count_as_reproduction(
    tmp_path,
):
    document = fixture(tmp_path, wrong_check=True)
    result = replay.execute_case(
        document, document["results"][0], tmp_path / "replay", timeout=5
    )
    assert result["status"] == "UNVERIFIED"
    assert result["report"] is None
    assert "named check" in result["detail"]
    document["results"][0]["command"] = [sys.executable, "-c", "raise SystemExit(1)"]
    result = replay.execute_case(
        document, document["results"][0], tmp_path / "unsupported", timeout=5
    )
    assert result["status"] == "UNSUPPORTED_REPLAY"
    assert not (tmp_path / "unsupported").exists()


def test_replay_rejects_changed_configuration_and_inputs(tmp_path):
    source = fixture(tmp_path)
    changed = json.loads((tmp_path / "seed.json").read_text())
    changed["configuration"]["seed"] = 8
    (tmp_path / "seed.json").write_text(json.dumps(changed))
    result = replay.execute_case(
        source, source["results"][0], tmp_path / "replay", timeout=5
    )
    assert result["status"] == "UNVERIFIED"
    assert "configuration" in result["detail"]


def test_selected_case_configuration_must_be_identical():
    base = {
        "configuration": {
            "cases": [{"id": "a", "k": 1}, {"id": "b", "k": 2}],
            "seed": 7,
        }
    }
    subset = {"configuration": {"cases": [{"id": "b", "k": 2}], "seed": 7}}
    replay.verify_configuration(base, subset)
    subset["configuration"]["cases"][0]["k"] = 3
    with pytest.raises(ValueError, match="case"):
        replay.verify_configuration(base, subset)


def test_replay_wall_budget_is_enforced_for_nonterminating_process(tmp_path):
    document = fixture(tmp_path)
    script = tmp_path / "validator.py"
    script.write_text("import time; time.sleep(60)")
    result = replay.execute_case(
        document, document["results"][0], tmp_path / "timeout", timeout=0.05
    )
    assert result["status"] == "UNVERIFIED"
    assert result["receipt"]["status"] == "TIMEOUT"
    assert result["receipt"]["elapsed_seconds"] < 3
