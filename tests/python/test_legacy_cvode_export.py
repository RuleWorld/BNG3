"""Source-derived regression for legacy CVODE operator export."""

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


def test_legacy_cvode_export_translates_bngl_logical_operators(tmp_path):
    """The dca95a6a fixture must emit C operators, not BNGL spellings."""

    model = tmp_path / "issue_295_operator_export.bngl"
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

begin reaction rules
  A() -> 0 k*((1~=0)+(~k))
end reaction rules

generate_network({overwrite=>1})
writeMexfile({prefix=>"issue_295_operator_export",overwrite=>1})

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

    assert result.returncode == 0, result.stdout + result.stderr
    generated_path = tmp_path / "issue_295_operator_export_cvode.c"
    assert generated_path.is_file()
    generated = generated_path.read_text(encoding="utf-8")
    assert "1.0!=0.0" in generated
    assert "(!NV_Ith_S" in generated
    assert "1.0~=0.0" not in generated
