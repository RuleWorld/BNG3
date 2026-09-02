"""Source-derived regressions for legacy pattern modifiers in XML output."""

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


def _run_legacy_xml(model_text: str, output_name: str, tmp_path: Path) -> str:
    model = tmp_path / f"{output_name}.bngl"
    model.write_text(model_text, encoding="utf-8")
    result = subprocess.run(
        ["perl", str(BNG2), str(model)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    output = tmp_path / f"{output_name}.xml"
    assert output.is_file()
    return output.read_text(encoding="utf-8")


def test_legacy_xml_escapes_pattern_quantifier_relations(tmp_path):
    """The dca95a6a quantifier fixture must produce well-formed XML."""

    generated = _run_legacy_xml(
        """
begin model

begin molecule types
  R()
end molecule types

begin seed species
  R() 10
end seed species

begin observables
  Species R5 R<4
end observables

writeXML({prefix=>"issue_234_pattern_quantifier",overwrite=>1})

end model
""",
        "issue_234_pattern_quantifier",
        tmp_path,
    )

    assert 'relation="&lt;" quantity="4"' in generated
    assert 'relation="<" quantity="4"' not in generated


def test_legacy_xml_accepts_whitespace_and_no_whitespace_matchonce(tmp_path):
    """The dca95a6a modifier fixture must retain both MatchOnce attributes."""

    generated = _run_legacy_xml(
        """
begin model

begin molecule types
  A(b,b)
  B(a)
end molecule types

begin seed species
  A(b,b) 10
  B(a) 20
end seed species

begin observables
  Molecules A_space A(b!+) {MatchOnce}
  Molecules A_nospace A(b!+){MatchOnce}
end observables

begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) 1, 0.1
end reaction rules

writeXML({prefix=>"issue_312_matchonce",overwrite=>1})

end model
""",
        "issue_312_matchonce",
        tmp_path,
    )

    assert generated.count('matchOnce="1"') == 2

