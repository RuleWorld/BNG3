"""Source-derived regression for legacy console error routing."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BNG2 = REPO / "legacy" / "perl" / "BNG2.pl"

pytestmark = pytest.mark.skipif(
    shutil.which("perl") is None or not BNG2.is_file(),
    reason="bundled Perl BNG2.pl is unavailable",
)


def test_legacy_console_writes_action_errors_to_stderr(tmp_path):
    """The dca95a6a console fixture must not label errors as warnings."""

    result = subprocess.run(
        ["perl", str(BNG2), "--console"],
        cwd=tmp_path,
        input="action simulate()\ndone\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ERROR:" not in result.stdout
    assert "ERROR: Attempt to execute action without loading model" in result.stderr
    assert (
        "WARNING: Attempt to execute action without loading model" not in result.stdout
    )
