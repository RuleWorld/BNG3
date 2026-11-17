"""Pinned PyBioNetGen restores the caller's BNGPATH after a CLI run."""

import os

import pytest
from _extdep import require_extension

from bionetgen.core.tools.cli import BNGCLI

cpp = require_extension()

MODEL = """begin model
begin molecule types
A()
end molecule types
begin seed species
A() 1
end seed species
end model
"""


@pytest.mark.parametrize("original", [None, "caller-owned-path"])
@pytest.mark.parametrize("valid", [False, True], ids=["native-error", "success"])
def test_native_bngcli_restores_caller_bngpath(tmp_path, monkeypatch, original, valid):
    if original is None:
        monkeypatch.delenv("BNGPATH", raising=False)
    else:
        monkeypatch.setenv("BNGPATH", original)
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "BNG2.pl").write_text("# unused native-route fixture\n")
    model = tmp_path / "model.bngl"
    model.write_text(MODEL if valid else "begin model\ninvalid syntax\nend model\n")
    cli = BNGCLI(str(model), str(tmp_path / "output"), str(reference), suppress=True)
    assert os.environ["BNGPATH"] == str(reference)
    if valid:
        cli.run()
        assert cli.result.process_return == 0
    else:
        with pytest.raises(cpp.ParseError):
            cli.run()
    restored = os.environ.get("BNGPATH")
    assert restored == original
