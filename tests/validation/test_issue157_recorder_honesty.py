"""Negative controls for the Issue 157 recorder's row-specific evidence contract.

The historical #741 recorder inferred six named claims from a whole-directory
pytest exit code, with no per-row execution identity and no execution of the
16-seed randomized-event oracle campaign. These controls pin the honest
behaviour for missing, skipped, duplicate and stale evidence.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "record_issue157_release", str(ROOT / "scripts/ci/record_issue157_release.py")
)
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)

REV = "98b310afdda85b9628d7c9cdcbb48b139da15ee3"


def _run_stub(*args, **kwargs):
    class _C:
        pass

    c = _C()
    c.returncode = 0
    cmd = args[0] if args else []
    c.stdout = REV + "\n" if "rev-parse" in cmd else ""
    if "pytest" in cmd:
        junit = next(
            (a.split("=", 1)[1] for a in cmd if a.startswith("--junitxml=")), None
        )
        if junit:
            nodes = {
                n.split("::")[-1]
                for nodes in recorder.CHECK_TESTS.values()
                if nodes
                for n in nodes
            }
            nodes |= {
                "test_source_fixture_is_valid_sbml_and_matches_its_analytic_event_schedule",
                "test_source_contract_rejects_semantic_mutations",
                "test_source_derived_roundoff_bound_is_finite_and_small",
            }
            body = "".join(
                f'<testcase classname="m" name="{n}"/>' for n in sorted(nodes)
            )
            Path(junit).write_text(
                f'<testsuite tests="{len(nodes)}">{body}</testsuite>'
            )
    return c


def _stochastic(tmp_path, **overrides):
    run = {
        "check_id": "release-event-stochastic",
        "status": "passed",
        "source_sha256": recorder.SOURCE_SHA256,
        "predeclared_design": {"seeds": list(range(1, 17))},
        "completed_seeds": list(range(1, 17)),
        "summary": {"seeds_passed": 16, "seeds_total": 16},
        "identity": {"product_revision": REV},
    }
    run.update(overrides)
    p = tmp_path / "run.json"
    p.write_text(json.dumps(run))
    return p


def test_stochastic_run_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.subprocess, "run", _run_stub)
    try:
        recorder.build_release_record(REV, True, None)
    except ValueError as exc:
        assert "stochastic-run" in str(exc)
    else:
        raise AssertionError("stochastic claim accepted without oracle campaign")


def test_stochastic_run_must_execute_all_16_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.subprocess, "run", _run_stub)
    run = _stochastic(tmp_path, completed_seeds=list(range(1, 9)))
    try:
        recorder.build_release_record(REV, True, run)
    except ValueError as exc:
        assert "16" in str(exc)
    else:
        raise AssertionError("partial seed campaign accepted")


def test_stochastic_run_revision_must_match(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.subprocess, "run", _run_stub)
    run = _stochastic(tmp_path, identity={"product_revision": "0" * 40})
    try:
        recorder.build_release_record(REV, True, run)
    except ValueError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("stale product revision accepted")


def test_exact_five_checks_and_no_duplicates():
    ids = list(recorder.EXPECTED_CHECKS)
    assert len(ids) == 6
    assert len(set(ids)) == 6
    assert set(ids) == set(recorder.CHECK_DETAILS) == set(recorder.CHECK_TESTS)


def test_required_test_set_is_explicit_and_nonempty():
    covered = {n for nodes in recorder.CHECK_TESTS.values() if nodes for n in nodes}
    assert len(covered) >= 8
    assert all("::test_" in n for n in covered)
