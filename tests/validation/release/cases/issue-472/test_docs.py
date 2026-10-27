"""Negative controls for the explicit issue #472 documentation assessor."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from docs_checks import (
    _decision_acceptance_errors,
    _inventory_errors,
    _link_acceptance_errors,
    _markdown_link_errors,
)  # noqa: E402


def test_release_docs_links_rejects_a_broken_local_link(tmp_path: Path):
    (tmp_path / "README.md").write_text("[missing](missing.md)\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    errors = _markdown_link_errors(tmp_path)
    assert any("broken local link missing.md" in error for error in errors)


def test_release_docs_decisions_rejects_conflicting_active_scope(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "DECISIONS.md").write_text(
        "Every user-facing capability. All inventory rows are release requirements. "
        "Native BNG3 solvers are the default. BNGsim is a supported optional backend. "
        "NFnext is the single next-generation engine. Equality means process equality.",
        encoding="utf-8",
    )
    (docs / "active.md").write_text("All decisions remain pending.\n", encoding="utf-8")
    errors = _decision_acceptance_errors(tmp_path)
    assert any("active.md conflicts with final decisions" in error for error in errors)


def _write_decisions_fixture(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "DECISIONS.md").write_text(
        "Every user-facing capability. All inventory rows are release requirements. "
        "Native BNG3 solvers are the default. BNGsim is a supported optional backend. "
        "NFnext is the single next-generation engine. Equality means process equality.",
        encoding="utf-8",
    )


def _write_inventory_fixture(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "CAPABILITY_UNION_INVENTORY.md").write_text(
        "| ID | Behavior | Upstream | BNG3 | Check | Oracle | Status | Issue |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| row.alpha | Alpha behavior | source:alpha | src/a.py | release-capability[row.alpha] | oracle | missing | #137 |\n",
        encoding="utf-8",
    )
    (root / "provenance").mkdir(parents=True, exist_ok=True)
    (root / "provenance/capability-matrix.yml").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "row.alpha",
                        "behavior": "Alpha behavior",
                        "upstream": "source:alpha",
                        "bng3": "src/a.py",
                        "check": "release-capability[row.alpha]",
                        "oracle": "oracle",
                        "status": "missing",
                        "issue": 137,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (docs / "PLAN.md").write_text("Issue #137 owns row.alpha.\n", encoding="utf-8")


def test_release_docs_links_rejects_a_bad_heading_link(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "[section](docs/guide.md#missing)\n", encoding="utf-8"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Present\n", encoding="utf-8")
    errors = _markdown_link_errors(tmp_path)
    assert any("missing heading #missing" in error for error in errors)


def test_release_docs_links_accepts_math_and_code_examples(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "The function is [S](t).\n\n```md\n[example](missing.md)\n```\n",
        encoding="utf-8",
    )
    assert _markdown_link_errors(tmp_path) == []


def test_release_docs_links_rejects_missing_required_navigation(tmp_path: Path):
    _write_inventory_fixture(tmp_path)
    docs = tmp_path / "docs"
    for filename in (
        "DECISIONS.md",
        "BNG3_CONVERGENCE_DONE_CHECKLIST.md",
        "index.md",
        "CURRENT_PROGRESS.md",
    ):
        (docs / filename).write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Capability inventory only.\n", encoding="utf-8"
    )
    errors = _link_acceptance_errors(tmp_path)
    assert any("README.md does not link DECISIONS.md" in error for error in errors)


def test_release_docs_links_rejects_inventory_id_mismatch(tmp_path: Path):
    _write_inventory_fixture(tmp_path)
    matrix = json.loads((tmp_path / "provenance/capability-matrix.yml").read_text())
    matrix["rows"][0]["id"] = "row.beta"
    (tmp_path / "provenance/capability-matrix.yml").write_text(json.dumps(matrix))
    errors = _inventory_errors(tmp_path)
    assert any("inventory/matrix row IDs differ" in error for error in errors)


def test_release_docs_links_rejects_inventory_check_mismatch(tmp_path: Path):
    _write_inventory_fixture(tmp_path)
    matrix = json.loads((tmp_path / "provenance/capability-matrix.yml").read_text())
    matrix["rows"][0]["check"] = "release-capability[row.beta]"
    (tmp_path / "provenance/capability-matrix.yml").write_text(json.dumps(matrix))
    errors = _inventory_errors(tmp_path)
    assert any("check does not match the matrix" in error for error in errors)


def test_release_docs_links_rejects_inventory_issue_mismatch(tmp_path: Path):
    _write_inventory_fixture(tmp_path)
    matrix = json.loads((tmp_path / "provenance/capability-matrix.yml").read_text())
    matrix["rows"][0]["issue"] = 138
    (tmp_path / "provenance/capability-matrix.yml").write_text(json.dumps(matrix))
    errors = _inventory_errors(tmp_path)
    assert any("issue does not match the matrix" in error for error in errors)


def test_release_docs_decisions_rejects_unlabeled_archive(tmp_path: Path):
    _write_decisions_fixture(tmp_path)
    archive = tmp_path / "docs/archive"
    archive.mkdir(parents=True)
    (archive / "old.md").write_text("# Old report\n", encoding="utf-8")
    errors = _decision_acceptance_errors(tmp_path)
    assert any(
        "old.md is archived without a history label" in error for error in errors
    )


@pytest.mark.parametrize(
    "statement",
    [
        "BNGsim is the default backend.",
        "NFnext is the production default.",
        "NFcore is not the production default.",
        "Release scope remains pending.",
        "BNGIR v0.1 is the public default.",
    ],
)
def test_release_docs_decisions_rejects_conflicting_decision_variants(
    tmp_path: Path, statement: str
):
    _write_decisions_fixture(tmp_path)
    (tmp_path / "docs/active.md").write_text(statement, encoding="utf-8")
    errors = _decision_acceptance_errors(tmp_path)
    assert any("active.md conflicts with final decisions" in error for error in errors)
