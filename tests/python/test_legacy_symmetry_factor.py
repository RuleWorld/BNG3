"""Source-derived regression for legacy reaction-rule symmetry factors."""

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


def test_legacy_symmetry_factor_preserves_reactant_pattern_boundaries(tmp_path):
    """The dca95a6a fixture must not over-correct identical reactant patterns."""

    model = tmp_path / "issue_090_implicit_bonds.bngl"
    model.write_text(
        """
begin seed species
  S(a!0,b!1,c!2).A(b,s!0).B(a,s!1).C(c,s!2)  2
end seed species

begin reaction rules
  A(b).B(a).C(c) + A(b).B(a).C(c) -> A(b!0).B(a!1).C(c!2).A(b!1).B(a!0).C(c!2)  1
end reaction rules

generate_network({overwrite=>1})
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["perl", str(BNG2), "--outdir", str(tmp_path), str(model)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    network_path = tmp_path / "issue_090_implicit_bonds.net"
    assert network_path.is_file()
    network = network_path.read_text(encoding="utf-8")
    assert "0.5*_rateLaw1" in network
    assert "0.25*_rateLaw1" not in network
