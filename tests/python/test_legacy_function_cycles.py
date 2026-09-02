"""Source-derived regression for legacy named-function dependency cycles."""

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


def test_legacy_named_function_cycle_has_bounded_diagnostic(tmp_path):
    """The dca95a6a source fixture must fail as a cycle, not recurse forever."""

    model = tmp_path / "issue_217_circular_functions.bngl"
    model.write_text(
        """
begin model

begin parameters
  k 1
end parameters

begin molecule types
  A()
end molecule types

begin seed species
  A() 1
end seed species

begin functions
  g f()
  f g()
end functions

begin reaction rules
  0 -> A() f
end reaction rules

generate_network()

end model
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["perl", str(BNG2), str(model)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Function dependency cycle" in combined
    assert "Deep recursion" not in combined
