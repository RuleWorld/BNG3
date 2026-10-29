"""Focused provenance-helper controls for the Issue 161 runner."""

from __future__ import annotations

from pathlib import Path
import subprocess

from run_case import _git_identity


def test_git_identity_accepts_bng2_file_path_and_reports_checkout_dirty_state(
    tmp_path: Path,
):
    checkout = tmp_path / "oracle"
    script = checkout / "bng2" / "BNG2.pl"
    script.parent.mkdir(parents=True)
    script.write_text("# pinned oracle\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "init", "--quiet"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(checkout), "add", "bng2/BNG2.pl"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "--quiet", "-m", "oracle"],
        check=True,
    )

    clean = _git_identity(script)
    assert clean["root"] == str(checkout)
    assert clean["revision"]
    assert clean["dirty"] is False

    script.write_text("# modified oracle\n", encoding="utf-8")
    dirty = _git_identity(script)
    assert dirty["root"] == str(checkout)
    assert dirty["revision"] == clean["revision"]
    assert dirty["dirty"] is True
