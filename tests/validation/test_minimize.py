from tests.validation import minimize


def test_report_source_must_match_a_clean_checkout(tmp_path):
    import subprocess
    import pytest

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "tracked").write_text("pinned\n")
    subprocess.run(["git", "-C", str(repo), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "pin source"], check=True)
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    report = {
        "source": {"revision": revision, "dirty": False},
        "input_changes_during_run": [],
    }

    assert minimize.verify_report_source(report, repo) == revision
    for source, changes in (
        ({"revision": revision, "dirty": True}, []),
        ({"revision": "f" * 40, "dirty": False}, []),
        ({"revision": revision, "dirty": False}, ["models/case.bngl"]),
    ):
        with pytest.raises(ValueError, match="source|input changes"):
            minimize.verify_report_source(
                {"source": source, "input_changes_during_run": changes}, repo
            )
    (repo / "untracked").write_text("changed\n")
    with pytest.raises(ValueError, match="checkout is dirty"):
        minimize.verify_report_source(report, repo)


def test_original_input_must_match_subject_receipt_and_hashes_are_retained(tmp_path):
    import hashlib
    import json
    import pytest

    report_dir = tmp_path / "report"
    source = report_dir / "models" / "case" / "input" / "case.bngl"
    subject = report_dir / "models" / "case" / "subject"
    source.parent.mkdir(parents=True)
    subject.mkdir(parents=True)
    original = b"begin model\nend model\n"
    source.write_bytes(original)
    executed = subject / "case.bngl"
    executed.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    (subject / "command.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "command": ["/build/bng_cpp", "/recorded/case.bngl"],
                "artifacts": [{"path": "/recorded/case.bngl", "sha256": digest}],
            }
        )
    )
    row = {
        "id": "case:network",
        "receipts": [
            "/home/runner/models/case/reference/command.json",
            "/home/runner/models/case/subject/command.json",
        ],
    }

    verified = minimize.verify_recorded_input(
        row, report_dir, source, subject_binary="/build/bng_cpp"
    )
    assert verified == digest
    with pytest.raises(ValueError, match="different binary"):
        minimize.verify_recorded_input(
            row, report_dir, source, subject_binary="/other/bng_cpp"
        )
    candidate = tmp_path / "reproducer.bngl"
    candidate.write_bytes(original + b"# reduced\n")
    record = minimize.minimization_hashes(source, candidate)
    assert record == {
        "original_model_sha256": digest,
        "candidate_model_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }
    source.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="recorded subject input"):
        minimize.verify_recorded_input(row, report_dir, source)


def test_original_input_without_receipt_digest_is_unverifiable(tmp_path):
    import json
    import pytest

    root = tmp_path / "report"
    model = root / "models" / "case" / "input" / "case.bngl"
    receipt = root / "models" / "case" / "subject" / "command.json"
    model.parent.mkdir(parents=True)
    receipt.parent.mkdir(parents=True)
    model.write_text("begin model\nend model\n")
    receipt.write_text(
        json.dumps(
            {"status": "PASS", "command": ["bng_cpp", "case.bngl"], "artifacts": []}
        )
    )
    with pytest.raises(ValueError, match="no recorded model digest"):
        minimize.verify_recorded_input(
            {"id": "case:network", "receipts": ["models/case/subject/command.json"]},
            root,
            model,
        )


def test_minimizer_uses_named_failing_contract_receipts():
    aggregate = {
        "id": "case:network",
        "first_observed_divergence": "case:network:species",
    }
    leaf = {
        "id": "case:network:species",
        "model": "case",
        "status": "FAIL",
        "receipts": ["reference/command.json", "subject/command.json"],
    }
    report = {"results": [aggregate, leaf]}
    assert minimize.input_evidence_row(report, aggregate, "case") is leaf


def test_delta_debugging_preserves_predicate_and_budget():
    attempts = []

    def reproduces(items):
        attempts.append(items)
        return 3 in items and 7 in items

    kept = minimize.ddmin(list(range(10)), reproduces, max_attempts=30)
    assert kept == [3, 7]
    assert len(attempts) <= 30


def test_unreproduced_failure_cannot_be_minimized():
    import pytest

    with pytest.raises(ValueError, match="does not reproduce"):
        minimize.ddmin([1, 2], lambda items: False, max_attempts=10)


def test_reduction_requires_fresh_final_confirmation_and_reserves_attempt():
    seen = []

    def intermittent(items):
        seen.append(list(items))
        return len(seen) < 3

    result = minimize.reduce_verified([1, 2], intermittent, max_attempts=3)
    assert len(seen) == 3
    assert result["verified"] is False
    assert result["attempts"] == 3


def test_reducer_distinguishes_different_species_with_same_count_mismatch():
    from tests.validation.compare import NetDiff

    one = NetDiff(False, 1, 2, 0, 0, set(), {"A()"}, [], [])
    other = NetDiff(False, 1, 2, 0, 0, set(), {"B()"}, [], [])
    assert minimize._signature(one) != minimize._signature(other)
